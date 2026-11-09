import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer

DEFAULT_MIRROR_DB = Path.home() / ".mirror" / "state.db"


# --- Minimal protobuf wire reader -------------------------------------------
# Mirror stores each conversation turn as a protobuf-encoded blob in
# react_entry.payload. There is no published .proto, so we read the wire format
# directly. Field map (reverse-engineered from live data):
#   1  seq              varint
#   2  entry_id         string
#   3  timestamp        msg { 1: unix_seconds, 2: nanos }
#   4  entry            msg, one of:
#        2 user          msg { 1: text }
#        3 assistant      msg { 1: text(final), 2: tool_call*, 3: reasoning }
#              tool_call  msg { 1: call_id, 2: "function", 3: { 1: name, 2: args_json } }
#        4 tool_result    msg { 1: call_id, 2: output, 3: tool_name }
#        5 usage          msg { 1: prompt_total, 2: output, 3: cache_read }
#   8  model            msg { 1: name, 2: provider, 4: tier }
#   13 tool_status      msg (lifecycle marker, ignored)
#   14 turn_id          string
def _read_varint(b: bytes, i: int) -> Tuple[int, int]:
    shift = 0
    val = 0
    while True:
        x = b[i]
        i += 1
        val |= (x & 0x7F) << shift
        if not (x & 0x80):
            return val, i
        shift += 7


def _parse(b: bytes) -> Dict[int, List[Any]]:
    """Parse one protobuf message into {field_no: [value, ...]}.

    Length-delimited values are returned as raw bytes; use _msg()/_text() to
    interpret them as a submessage or a UTF-8 string.
    """
    out: Dict[int, List[Any]] = {}
    i, n = 0, len(b)
    while i < n:
        try:
            key, i = _read_varint(b, i)
        except IndexError:
            break
        fno, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _read_varint(b, i)
        elif wt == 2:
            ln, i = _read_varint(b, i)
            v = b[i:i + ln]
            i += ln
        elif wt == 1:
            v = b[i:i + 8]
            i += 8
        elif wt == 5:
            v = b[i:i + 4]
            i += 4
        else:
            break
        out.setdefault(fno, []).append(v)
    return out


def _first(d: Dict[int, List[Any]], fno: int) -> Optional[Any]:
    vals = d.get(fno)
    return vals[0] if vals else None


def _msg(d: Dict[int, List[Any]], fno: int) -> Optional[Dict[int, List[Any]]]:
    raw = _first(d, fno)
    if isinstance(raw, (bytes, bytearray)):
        try:
            return _parse(raw)
        except Exception:
            return None
    return None


def _text(d: Dict[int, List[Any]], fno: int) -> Optional[str]:
    raw = _first(d, fno)
    if isinstance(raw, (bytes, bytearray)):
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return None
    return None


def _int(d: Dict[int, List[Any]], fno: int) -> int:
    raw = _first(d, fno)
    return int(raw) if isinstance(raw, int) else 0


class MirrorNormalizer(BaseNormalizer):
    """Normalizer for Mirror (Beam / Reflection) agent sessions stored in
    ~/.mirror/state.db (react_session + react_entry protobuf payloads)."""

    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        meta = metadata or {}

        # Already-normalized payload (server re-ingest path): revalidate and return.
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict) and "role" in raw_data[0]:
            msgs = [NormalizedMessage.model_validate(item) for item in raw_data]
            sid = meta.get("session_id") or meta.get("conversation_id") or "unknown-mirror"
            return NormalizedConversation(
                platform="mirror",
                external_id=sid,
                title=meta.get("title") or f"Sesja Mirror {sid[:8]}",
                project_path=meta.get("project_path"),
                git_branch=meta.get("git_branch"),
                device=meta.get("device"),
                model=meta.get("model") or "Beam",
                started_at=msgs[0].created_at if msgs and msgs[0].created_at else datetime.now(timezone.utc),
                updated_at=msgs[-1].created_at if msgs and msgs[-1].created_at else datetime.now(timezone.utc),
                raw_metadata=meta,
                messages=msgs,
            )

        # Resolve db path + session id.
        session_id: Optional[str] = meta.get("session_id") or meta.get("conversation_id")
        if isinstance(raw_data, dict) and "db_path" in raw_data:
            db_path = Path(raw_data["db_path"])
            session_id = session_id or raw_data.get("session_id")
        elif isinstance(raw_data, (str, Path)) and str(raw_data).endswith("state.db"):
            db_path = Path(raw_data)
        elif isinstance(raw_data, str):
            session_id = session_id or raw_data
            db_path = DEFAULT_MIRROR_DB
        else:
            db_path = DEFAULT_MIRROR_DB

        if not db_path.is_file():
            raise FileNotFoundError(f"Mirror database not found at {db_path}")
        if not session_id:
            raise ValueError("Mirror: session_id is required to parse a conversation")

        workspace, entries = self._load_from_sqlite(db_path, session_id)
        return self._build(session_id, workspace, entries, meta)

    def _load_from_sqlite(self, db_path: Path, session_id: str) -> Tuple[Optional[str], List[bytes]]:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            row = cur.execute("SELECT workspace FROM react_session WHERE id = ?", (session_id,)).fetchone()
            workspace = row[0] if row else None
            rows = cur.execute(
                "SELECT payload FROM react_entry WHERE session_id = ? ORDER BY sequence",
                (session_id,),
            ).fetchall()
            return workspace, [r[0] for r in rows]
        finally:
            conn.close()

    def _build(self, session_id: str, workspace: Optional[str],
               payloads: List[bytes], meta: Dict[str, Any]) -> NormalizedConversation:
        messages: List[NormalizedMessage] = []
        tool_call_index: Dict[str, Tuple[int, int]] = {}  # call_id -> (msg idx, tool_call idx)
        step = 0
        first_dt: Optional[datetime] = None
        last_dt: Optional[datetime] = None
        model_name: Optional[str] = None
        provider: Optional[str] = None
        title: Optional[str] = None

        for payload in payloads:
            if not isinstance(payload, (bytes, bytearray)):
                continue
            top = _parse(payload)

            ts = _msg(top, 3)
            dt = (
                datetime.fromtimestamp(_int(ts, 1), timezone.utc)
                if ts and _int(ts, 1) > 0
                else (last_dt or datetime.now(timezone.utc))
            )
            if first_dt is None:
                first_dt = dt
            last_dt = dt

            model_msg = _msg(top, 8)
            if model_msg:
                model_name = _text(model_msg, 1) or model_name
                provider = _text(model_msg, 2) or provider

            entry = _msg(top, 4)
            if not entry:
                continue  # status / lifecycle marker

            # User message (4.2)
            user = _msg(entry, 2)
            if user is not None:
                content = (_text(user, 1) or "").strip()
                if title is None and content:
                    title = content.split("\n", 1)[0].strip()[:100]
                messages.append(NormalizedMessage(
                    step_index=step, external_id=f"{session_id}_{step}",
                    role="user", content=content, created_at=dt,
                ))
                step += 1
                continue

            # Assistant message (4.3) with optional usage (4.5)
            asst = _msg(entry, 3)
            if asst is not None:
                content = (_text(asst, 1) or "").strip()
                reasoning = (_text(asst, 3) or "").strip() or None
                tool_calls: List[ToolCallRecord] = []
                for tc_raw in entry[3] if isinstance(entry.get(3), list) else []:
                    tc = _parse(tc_raw) if isinstance(tc_raw, (bytes, bytearray)) else None
                    if not tc:
                        continue
                    for call_raw in tc.get(2, []):
                        call = _parse(call_raw) if isinstance(call_raw, (bytes, bytearray)) else None
                        if not call:
                            continue
                        call_id = _text(call, 1)
                        fn = _msg(call, 3)
                        name = (_text(fn, 1) if fn else None) or "unknown_tool"
                        args_json = (_text(fn, 2) if fn else None) or ""
                        try:
                            args = json.loads(args_json) if args_json else {}
                        except Exception:
                            args = {"raw": args_json}
                        tool_calls.append(ToolCallRecord(name=name, input=args, output=None))
                        if call_id:
                            tool_call_index[call_id] = (len(messages), len(tool_calls) - 1)

                token_usage: Dict[str, int] = {}
                usage = _msg(entry, 5)
                if usage is not None:
                    prompt_total = _int(usage, 1)
                    out_tok = _int(usage, 2)
                    cache_read = _int(usage, 3)
                    # field 1 is the full prompt (cached + new); keep input_tokens
                    # as the non-cached part so total = in+out+cache_read matches
                    # the claude_code accounting and does not double-count cache.
                    input_tokens = max(0, prompt_total - cache_read)
                    token_usage = {
                        "input_tokens": input_tokens,
                        "output_tokens": out_tok,
                        "cache_read_tokens": cache_read,
                        "cache_write_tokens": 0,
                        "total_tokens": input_tokens + out_tok + cache_read,
                    }

                messages.append(NormalizedMessage(
                    step_index=step, external_id=f"{session_id}_{step}",
                    role="assistant", content=content, reasoning_content=reasoning,
                    tool_calls=tool_calls, token_usage=token_usage, created_at=dt,
                ))
                step += 1
                continue

            # Tool result (4.4): attach output to the originating tool call.
            result = _msg(entry, 4)
            if result is not None:
                call_id = _text(result, 1)
                output = _text(result, 2)
                if call_id and call_id in tool_call_index:
                    m_idx, tc_idx = tool_call_index[call_id]
                    tc = messages[m_idx].tool_calls[tc_idx]
                    tc.output = output
                    if output and output.lower().startswith("tool error"):
                        tc.is_error = True

        now = datetime.now(timezone.utc)
        return NormalizedConversation(
            platform="mirror",
            external_id=session_id,
            title=title or f"Sesja Mirror {session_id[:8]}",
            project_path=workspace or meta.get("project_path"),
            git_branch=meta.get("git_branch"),
            device=meta.get("device"),
            model=model_name or meta.get("model") or "Beam",
            started_at=first_dt or now,
            updated_at=last_dt or now,
            raw_metadata={
                "provider": provider,
                "total_entries": len(payloads),
                **({"model": model_name} if model_name else {}),
            },
            messages=messages,
        )
