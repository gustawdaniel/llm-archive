import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value if value < 1e11 else value / 1000.0, timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            clean = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    return None


class GooseNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a list of serialized NormalizedMessage dicts (e.g. from HTTP forwarder ingest)
        - a dict containing serialized {"session": {...}, "messages": [...]}
        - a Path or str to sessions.db (extracts session specified in metadata, or latest session)
        - a session_id string (looks up in ~/.local/share/goose/sessions/sessions.db)
        """
        meta = metadata or {}

        # 1. Re-hydration from HTTP forwarder payload (already-normalized messages)
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict) and "role" in raw_data[0]:
            msgs = [NormalizedMessage.model_validate(item) for item in raw_data]
            sess_id = str(meta.get("session_id") or meta.get("conversation_id") or "unknown-goose")
            return NormalizedConversation(
                platform="goose",
                external_id=sess_id,
                title=meta.get("title") or f"Sesja Goose {sess_id[:8]}",
                project_path=meta.get("project_path"),
                git_branch=meta.get("git_branch"),
                device=meta.get("device"),
                model=meta.get("model") or "deepseek-flash",
                started_at=msgs[0].created_at if msgs and msgs[0].created_at else datetime.now(timezone.utc),
                updated_at=msgs[-1].created_at if msgs and msgs[-1].created_at else datetime.now(timezone.utc),
                raw_metadata=meta,
                messages=msgs,
            )

        session_dict: Optional[Dict[str, Any]] = None
        messages_list: List[Dict[str, Any]] = []

        if isinstance(raw_data, dict) and "session" in raw_data and "messages" in raw_data:
            session_dict = raw_data["session"]
            messages_list = raw_data["messages"]
        else:
            db_path: Path
            session_id: Optional[str] = meta.get("session_id") or meta.get("conversation_id")

            if isinstance(raw_data, (str, Path)) and str(raw_data).endswith("sessions.db"):
                db_path = Path(raw_data)
            elif isinstance(raw_data, dict) and "db_path" in raw_data:
                db_path = Path(raw_data["db_path"])
                session_id = session_id or raw_data.get("session_id")
            elif isinstance(raw_data, str) and len(raw_data) > 0 and not raw_data.endswith(".db"):
                session_id = raw_data
                db_path = Path.home() / ".local" / "share" / "goose" / "sessions" / "sessions.db"
            else:
                db_path = Path.home() / ".local" / "share" / "goose" / "sessions" / "sessions.db"

            if not db_path.is_file():
                raise FileNotFoundError(f"Goose database not found at {db_path}")

            session_dict, messages_list = self._load_from_sqlite(db_path, session_id)

        if not session_dict:
            raise ValueError("No session found in Goose data")

        session_id = str(session_dict.get("id") or meta.get("session_id") or "unknown-goose")

        # Title resolution
        raw_name = (session_dict.get("name") or "").strip()
        raw_desc = (session_dict.get("description") or "").strip()
        if raw_name and raw_name != "CLI Session":
            title = raw_name
        elif raw_desc:
            title = raw_desc
        elif meta.get("title"):
            title = meta["title"]
        else:
            title = f"Sesja Goose {session_id[:8]}"

        project_path = session_dict.get("working_dir") or meta.get("project_path")
        git_branch = meta.get("git_branch")

        # Model resolution from model_config_json or provider_name
        model_name: Optional[str] = None
        model_cfg_raw = session_dict.get("model_config_json")
        if model_cfg_raw:
            try:
                cfg = json.loads(model_cfg_raw) if isinstance(model_cfg_raw, str) else model_cfg_raw
                if isinstance(cfg, dict):
                    model_name = cfg.get("model_name")
            except Exception:
                pass
        if not model_name:
            provider = session_dict.get("provider_name")
            model_name = provider if provider else (meta.get("model") or "deepseek-flash")

        # Timestamps
        started_at = _parse_ts(session_dict.get("created_at")) or datetime.now(timezone.utc)
        updated_at = _parse_ts(session_dict.get("updated_at")) or started_at

        # Tokens & Cost
        input_tokens = session_dict.get("input_tokens") or session_dict.get("accumulated_input_tokens") or 0
        output_tokens = session_dict.get("output_tokens") or session_dict.get("accumulated_output_tokens") or 0
        cache_read = session_dict.get("cache_read_tokens") or session_dict.get("accumulated_cache_read_tokens") or 0
        cache_write = session_dict.get("cache_write_tokens") or session_dict.get("accumulated_cache_write_tokens") or 0
        total_tokens = session_dict.get("total_tokens") or session_dict.get("accumulated_total_tokens") or (input_tokens + output_tokens + cache_read + cache_write)
        cost_usd = session_dict.get("accumulated_cost") or 0.0

        # Pass 1: Collect tool responses by toolRequest call id
        tool_responses_by_id: Dict[str, Tuple[str, bool]] = {}
        for m in messages_list:
            content_raw = m.get("content_json") or m.get("content") or []
            if isinstance(content_raw, str):
                try:
                    items = json.loads(content_raw)
                except Exception:
                    items = []
            elif isinstance(content_raw, list):
                items = content_raw
            else:
                items = []

            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("type") == "toolResponse":
                    call_id = it.get("id")
                    if not call_id:
                        continue
                    tr = it.get("toolResult", {})
                    val = tr.get("value", {}) if isinstance(tr, dict) else {}
                    is_err = False
                    if (isinstance(tr, dict) and (tr.get("status") == "error" or tr.get("isError"))) or (isinstance(val, dict) and val.get("isError")):
                        is_err = True

                    out_texts: List[str] = []
                    if isinstance(val, dict):
                        content = val.get("content")
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("text"):
                                    out_texts.append(c["text"])
                                elif isinstance(c, str):
                                    out_texts.append(c)
                        elif isinstance(content, str):
                            out_texts.append(content)

                        sc = val.get("structuredContent")
                        if isinstance(sc, dict):
                            stderr = sc.get("stderr")
                            if stderr:
                                out_texts.append(f"[stderr]\n{stderr}")
                            if sc.get("exit_code") and sc.get("exit_code") != 0:
                                is_err = True
                        elif val.get("stderr"):
                            out_texts.append(f"[stderr]\n{val['stderr']}")
                        if val.get("exit_code") and val.get("exit_code") != 0:
                            is_err = True
                    elif isinstance(val, str):
                        out_texts.append(val)

                    tool_responses_by_id[call_id] = ("\n".join(out_texts), is_err)

        # Pass 2: Process messages
        norm_messages: List[NormalizedMessage] = []
        step_idx = 0

        for m in messages_list:
            content_raw = m.get("content_json") or m.get("content") or []
            if isinstance(content_raw, str):
                try:
                    items = json.loads(content_raw)
                except Exception:
                    items = []
            elif isinstance(content_raw, list):
                items = content_raw
            else:
                items = []

            text_parts: List[str] = []
            thinking_parts: List[str] = []
            tool_calls: List[ToolCallRecord] = []

            for it in items:
                if not isinstance(it, dict):
                    continue
                itype = it.get("type")
                if itype == "text":
                    t = it.get("text", "")
                    # Filter out isolated turn-context injected by Goose
                    t_clean = re.sub(r"<turn-context>.*?</turn-context>", "", t, flags=re.DOTALL).strip()
                    if t_clean:
                        text_parts.append(t_clean)
                elif itype == "thinking":
                    th = it.get("thinking", "").strip()
                    if th:
                        thinking_parts.append(th)
                elif itype == "toolRequest":
                    tc_id = it.get("id") or ""
                    tc_call = it.get("toolCall", {}) if isinstance(it.get("toolCall"), dict) else {}
                    tc_val = tc_call.get("value", {}) if isinstance(tc_call, dict) else {}
                    t_name = tc_val.get("name") or "tool"
                    t_args = tc_val.get("arguments") or {}
                    if isinstance(t_args, str):
                        try:
                            t_args = json.loads(t_args)
                        except Exception:
                            t_args = {"raw": t_args}
                    t_out, is_err = tool_responses_by_id.get(tc_id, (None, False))
                    tool_calls.append(
                        ToolCallRecord(
                            name=t_name,
                            input=t_args if isinstance(t_args, dict) else {"arg": t_args},
                            output=t_out,
                            is_error=is_err,
                        )
                    )
                elif itype == "error":
                    err_msg = it.get("message", "")
                    if err_msg:
                        text_parts.append(f"[Error: {err_msg}]")

            raw_content = "\n\n".join(text_parts).strip()
            reasoning_content = "\n\n".join(thinking_parts).strip() or None

            # Skip messages with no text, no reasoning, and no tool calls (e.g. pure tool responses or turn-context)
            if not raw_content and not tool_calls and not reasoning_content:
                continue

            created_ts = m.get("created_timestamp")
            msg_time = (
                datetime.fromtimestamp(float(created_ts), timezone.utc)
                if created_ts
                else (_parse_ts(m.get("timestamp")) or started_at)
            )

            step_idx += 1
            norm_messages.append(
                NormalizedMessage(
                    step_index=step_idx,
                    external_id=str(m.get("id")) if m.get("id") is not None else None,
                    role="assistant" if m.get("role") == "assistant" else "user",
                    content=raw_content,
                    reasoning_content=reasoning_content,
                    tool_calls=tool_calls,
                    token_usage={},
                    created_at=msg_time,
                )
            )

        if norm_messages and norm_messages[-1].created_at > updated_at:
            updated_at = norm_messages[-1].created_at

        # Conversation token summary
        token_summary = None
        if total_tokens or input_tokens or output_tokens:
            token_summary = {
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "cache_read_tokens": int(cache_read),
                "cache_write_tokens": int(cache_write),
                "total_tokens": int(total_tokens),
            }

        last_asst = next((m for m in reversed(norm_messages) if m.role == "assistant"), None)
        if last_asst and token_summary:
            last_asst.token_usage = token_summary.copy()

        raw_meta = {
            "session_id": session_id,
            "provider_name": session_dict.get("provider_name"),
            "cost_usd": cost_usd,
            "total_tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            **(meta or {}),
        }
        if token_summary:
            raw_meta["token_summary"] = token_summary

        return NormalizedConversation(
            platform="goose",
            external_id=session_id,
            title=title,
            project_path=project_path,
            git_branch=git_branch,
            device=meta.get("device"),
            model=model_name,
            started_at=started_at,
            updated_at=updated_at,
            raw_metadata=raw_meta,
            messages=norm_messages,
        )

    def _load_from_sqlite(
        self, db_path: Path, session_id: Optional[str]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            if session_id:
                cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            else:
                cur.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                raise ValueError(f"No session matching id '{session_id}' found in {db_path}")

            session_dict = dict(row)
            actual_session_id = session_dict["id"]

            cur.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (actual_session_id,))
            messages_list = [dict(r) for r in cur.fetchall()]
            return session_dict, messages_list
        finally:
            conn.close()
