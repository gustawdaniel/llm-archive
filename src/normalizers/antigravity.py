import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


def _read_varint(b: bytes, i: int) -> Tuple[int, int]:
    shift = val = 0
    while True:
        x = b[i]
        i += 1
        val |= (x & 0x7F) << shift
        if not (x & 0x80):
            return val, i
        shift += 7


def _walk_protobuf(b: bytes, path: str, out: List[Tuple[str, int]]) -> None:
    """Collect (field_path, varint_value) pairs from a protobuf message, recursing
    into length-delimited sub-messages where they parse cleanly."""
    i, n = 0, len(b)
    while i < n:
        try:
            key, i = _read_varint(b, i)
        except Exception:
            return
        f, wt = key >> 3, key & 7
        p = f"{path}.{f}"
        if wt == 0:
            v, i = _read_varint(b, i)
            out.append((p, v))
        elif wt == 2:
            ln, i = _read_varint(b, i)
            chunk = b[i:i + ln]
            i += ln
            try:
                sub: List[Tuple[str, int]] = []
                _walk_protobuf(chunk, p, sub)
                if sub:
                    out.extend(sub)
            except Exception:
                pass
        elif wt == 1:
            i += 8
        elif wt == 5:
            i += 4
        else:
            return


class AntigravityNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a list of dicts (parsed jsonl lines)
        - a string containing newline-delimited JSON
        - a Path to a transcript.jsonl file
        """
        lines = []
        conversation_id = (metadata or {}).get("conversation_id", "unknown-antigravity")
        project_path = (metadata or {}).get("project_path")

        file_path: Optional[Path] = None
        if isinstance(raw_data, (str, Path)) and (isinstance(raw_data, Path) or "\n" not in raw_data and Path(raw_data).is_file()):
            file_path = Path(raw_data)
            # Try to infer conversation_id from parent directory: .../brain/<conv_id>/.system_generated/logs/transcript.jsonl
            parts = file_path.parts
            if ".system_generated" in parts:
                idx = parts.index(".system_generated")
                if idx > 0:
                    conversation_id = parts[idx - 1]
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(json.loads(line))
        elif isinstance(raw_data, str):
            for line in raw_data.strip().split("\n"):
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
        elif isinstance(raw_data, list):
            lines = raw_data
        else:
            raise ValueError(f"Unsupported raw_data type for Antigravity: {type(raw_data)}")

        if file_path and file_path.is_file():
            default_dt = datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc)
        else:
            default_dt = datetime.now(timezone.utc)

        if not lines:
            now = default_dt
            return NormalizedConversation(
                platform="antigravity",
                external_id=conversation_id,
                title="Pusta sesja Antigravity",
                started_at=now,
                updated_at=now,
                messages=[]
            )

        if isinstance(lines[0], dict) and "role" in lines[0] and ("content" in lines[0] or "tool_calls" in lines[0]):
            msgs = [NormalizedMessage.model_validate(item) for item in lines]
            return NormalizedConversation(
                platform="antigravity",
                external_id=conversation_id,
                title=(metadata or {}).get("title") or f"Sesja Antigravity {conversation_id[:8]}",
                project_path=project_path or (metadata or {}).get("project_path"),
                git_branch=(metadata or {}).get("git_branch"),
                device=(metadata or {}).get("device"),
                started_at=msgs[0].created_at if msgs else datetime.now(timezone.utc),
                updated_at=msgs[-1].created_at if msgs else datetime.now(timezone.utc),
                raw_metadata=metadata or {},
                messages=msgs
            )

        messages: List[NormalizedMessage] = []
        first_prompt_title: Optional[str] = None
        started_at: Optional[datetime] = None
        updated_at: Optional[datetime] = None
        step_counter = 0

        current_assistant_reasoning: List[str] = []
        current_assistant_tools: List[ToolCallRecord] = []
        current_assistant_content_parts: List[str] = []
        current_assistant_dt: Optional[datetime] = None
        # Real per-turn usage, summed across every model call (PLANNER_RESPONSE)
        # that Antigravity logged between two user inputs. Antigravity's agent
        # loop fires several model calls per turn, each re-sending context, so
        # summing them is what the turn actually cost.
        current_assistant_usage: Dict[str, int] = {}
        current_assistant_has_real_usage = False

        def flush_assistant(fallback_dt: datetime):
            nonlocal step_counter, current_assistant_reasoning, current_assistant_tools
            nonlocal current_assistant_content_parts, current_assistant_dt
            nonlocal current_assistant_usage, current_assistant_has_real_usage
            content_str = "\n\n".join(current_assistant_content_parts).strip()
            reasoning_str = "\n\n".join(current_assistant_reasoning).strip() or None

            if content_str or current_assistant_tools or reasoning_str:
                if current_assistant_has_real_usage:
                    # Antigravity logs real usage per model call; trust it.
                    in_tok = current_assistant_usage.get("input_tokens", 0)
                    out_tok = current_assistant_usage.get("output_tokens", 0)
                    c_read = current_assistant_usage.get("cache_read_tokens", 0)
                    c_write = current_assistant_usage.get("cache_write_tokens", 0)
                    token_usage = {
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "cache_read_tokens": c_read,
                        "cache_write_tokens": c_write,
                        "total_tokens": in_tok + out_tok + c_read + c_write,
                        "is_estimated": 0,
                    }
                else:
                    # No usage in the log (older transcripts): fall back to a
                    # char-count estimate of output only, flagged as estimated.
                    total_chars = len(content_str) + len(reasoning_str or "")
                    approx_out = max(1, total_chars // 4)
                    token_usage = {
                        "output_tokens": approx_out,
                        "total_tokens": approx_out,
                        "is_estimated": 1,
                    }
                messages.append(NormalizedMessage(
                    step_index=step_counter,
                    external_id=f"{conversation_id}_{step_counter}",
                    role="assistant",
                    content=content_str,
                    reasoning_content=reasoning_str,
                    tool_calls=list(current_assistant_tools),
                    token_usage=token_usage,
                    created_at=current_assistant_dt or fallback_dt
                ))
                step_counter += 1
                current_assistant_reasoning = []
                current_assistant_tools = []
                current_assistant_content_parts = []
                current_assistant_dt = None
                current_assistant_usage = {}
                current_assistant_has_real_usage = False

        for step in lines:
            source = step.get("source", "UNKNOWN")
            step_type = step.get("type", "UNKNOWN")
            raw_content = step.get("content") or ""
            created_at_str = step.get("created_at")

            # Parse timestamp (deterministic fallback using file mtime or default_dt)
            if created_at_str:
                try:
                    dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                except Exception:
                    dt = default_dt
            else:
                dt = default_dt

            if started_at is None:
                started_at = dt
            updated_at = dt

            if step_type == "USER_INPUT" or source == "USER_EXPLICIT":
                flush_assistant(dt)
                clean_content = self._clean_user_content(raw_content)
                if not first_prompt_title and clean_content:
                    first_line = clean_content.split("\n")[0].strip()
                    first_prompt_title = first_line[:100] if first_line else "Sesja Antigravity"

                if not project_path:
                    m = re.search(r"/(?:Users|home)/[^/\s]+(?:/[^/\s]+)+", raw_content)
                    if m:
                        project_path = m.group(0)

                messages.append(NormalizedMessage(
                    step_index=step_counter,
                    external_id=f"{conversation_id}_{step_counter}",
                    role="user",
                    content=clean_content,
                    created_at=dt
                ))
                step_counter += 1

            elif source == "MODEL" and step_type == "PLANNER_RESPONSE":
                if not current_assistant_dt:
                    current_assistant_dt = dt
                if step.get("thinking"):
                    current_assistant_reasoning.append(step["thinking"])
                if step.get("content"):
                    current_assistant_content_parts.append(step["content"])

                # Antigravity records real token usage on each model call. Sum
                # it into the current turn; map its key names to our schema.
                for src_key, dst_key in (
                    ("input_tokens", "input_tokens"),
                    ("output_tokens", "output_tokens"),
                    ("cache_read_tokens", "cache_read_tokens"),
                    ("cache_write_tokens", "cache_write_tokens"),
                ):
                    val = step.get(src_key)
                    if isinstance(val, (int, float)):
                        current_assistant_usage[dst_key] = (
                            current_assistant_usage.get(dst_key, 0) + int(val)
                        )
                        current_assistant_has_real_usage = True

                raw_tools = step.get("tool_calls") or []
                for t in raw_tools:
                    current_assistant_tools.append(ToolCallRecord(
                        name=t.get("name", "unknown_tool"),
                        input=t.get("args") or {},
                        output=None
                    ))

            elif current_assistant_tools and current_assistant_tools[-1].output is None:
                # Correlate tool output with the most recently launched tool call
                if raw_content:
                    current_assistant_tools[-1].output = raw_content

        flush_assistant(updated_at or datetime.now(timezone.utc))

        # Older transcripts (pre ~Oct 2026) carry no token usage. The per-session
        # sqlite db does, under step_payload field 5.9 {2:input,3:output,5:cache_read}
        # (verified byte-for-byte identical to the transcript for sessions that
        # have both). If the transcript yielded no real usage, recover the
        # session total from the db so historical sessions are not undercounted.
        has_real = any(
            (m.token_usage or {}).get("total_tokens") and not m.token_usage.get("is_estimated")
            for m in messages
        )
        if not has_real:
            recovered = self._recover_session_usage(conversation_id)
            if recovered:
                r_in, r_out, r_cache = recovered
                for m in messages:
                    if (m.token_usage or {}).get("is_estimated"):
                        m.token_usage = {}
                last_asst = next((m for m in reversed(messages) if m.role == "assistant"), None)
                if last_asst is not None:
                    last_asst.token_usage = {
                        "input_tokens": r_in,
                        "output_tokens": r_out,
                        "cache_read_tokens": r_cache,
                        "cache_write_tokens": 0,
                        "total_tokens": r_in + r_out + r_cache,
                        "is_estimated": 0,
                    }

        extracted_model = self._extract_antigravity_model(conversation_id)
        resolved_model = extracted_model or (metadata or {}).get("model") or "Gemini 3.8 Flash (High)"

        return NormalizedConversation(
            platform="antigravity",
            external_id=conversation_id,
            title=first_prompt_title or f"Sesja Antigravity {conversation_id[:8]}",
            project_path=project_path,
            model=resolved_model,
            started_at=started_at or datetime.now(timezone.utc),
            updated_at=updated_at or datetime.now(timezone.utc),
            raw_metadata={"total_steps": len(lines)},
            messages=messages
        )

    def _find_session_db(self, conversation_id: str) -> Optional[Path]:
        if not conversation_id or conversation_id == "unknown-antigravity":
            return None
        base = Path.home() / ".gemini"
        for flavour in ("antigravity-ide", "antigravity-cli", "antigravity"):
            db_path = base / flavour / "conversations" / f"{conversation_id}.db"
            if db_path.is_file():
                return db_path
        return None

    def _recover_session_usage(self, conversation_id: str) -> Optional[Tuple[int, int, int]]:
        """Sum real (input, output, cache_read) token usage from a session's
        per-session sqlite db (step_payload protobuf field 5.9). Returns None if
        the db or usage is absent."""
        db_path = self._find_session_db(conversation_id)
        if not db_path:
            return None
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
            try:
                rows = conn.execute(
                    "SELECT step_payload FROM steps WHERE step_payload IS NOT NULL"
                ).fetchall()
            finally:
                conn.close()
        except Exception:
            return None

        total_in = total_out = total_cache = 0
        for (payload,) in rows:
            if not isinstance(payload, (bytes, bytearray)):
                continue
            fields: List[Tuple[str, int]] = []
            _walk_protobuf(payload, "s", fields)
            d = dict(fields)  # one usage block per step; last-wins is fine
            if "s.5.9.2" in d:
                total_in += d.get("s.5.9.2", 0)
                total_out += d.get("s.5.9.3", 0)
                total_cache += d.get("s.5.9.5", 0)
        if total_in or total_out or total_cache:
            return total_in, total_out, total_cache
        return None

    def _extract_antigravity_model(self, conversation_id: str) -> Optional[str]:
        if not conversation_id or conversation_id == "unknown-antigravity":
            return None
        db_path = Path.home() / ".gemini" / "antigravity-ide" / "conversations" / f"{conversation_id}.db"
        if not db_path.is_file():
            return None
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            row = cur.execute("SELECT data FROM gen_metadata WHERE idx = 0").fetchone()
            conn.close()
            if not row or not row[0]:
                return None
            data = row[0]
            # Protobuf field 21 (tag 0xAA 0x01) has human-readable display name like 'Gemini 3.8 Flash (High)'
            for m in re.finditer(rb'\xaa\x01(.)', data):
                pos = m.end()
                l = m.group(1)[0]
                val = data[pos:pos+l].decode("utf-8", errors="ignore").strip()
                if "Gemini" in val or "Claude" in val:
                    return val
            # Protobuf field 19 (tag 0x9A 0x01) has model identifier like 'gemini-3.8-flash'
            for m in re.finditer(rb'\x9a\x01(.)', data):
                pos = m.end()
                l = m.group(1)[0]
                val = data[pos:pos+l].decode("utf-8", errors="ignore").strip()
                if val.startswith("gemini-") or val.startswith("claude-"):
                    return val
        except Exception:
            pass
        return None

    def _clean_user_content(self, text: str) -> str:
        """Strip internal system wrapper tags like <USER_REQUEST>, <ADDITIONAL_METADATA>."""
        m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", text, re.DOTALL)
        if m:
            text = m.group(1)
        else:
            text = re.sub(r"<USER_REQUEST>", "", text)
            text = re.sub(r"</USER_REQUEST>", "", text)

        text = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", text, flags=re.DOTALL)
        text = re.sub(r"<conversation_summaries>.*?</conversation_summaries>", "", text, flags=re.DOTALL)
        # Also clean empty lines from the beginning
        lines = [l for l in text.strip().split("\n") if l.strip()]
        return "\n".join(lines).strip()

