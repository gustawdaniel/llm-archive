import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class HermesNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a dict containing serialized {"session": {...}, "messages": [...]}
        - a Path to state.db (extracts session specified in metadata, or latest session)
        - a session_id string (looks up in ~/.hermes/state.db)
        """
        meta = metadata or {}
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict) and "role" in raw_data[0]:
            msgs = [NormalizedMessage.model_validate(item) for item in raw_data]
            sess_id = meta.get("session_id") or meta.get("conversation_id") or "unknown-hermes"
            return NormalizedConversation(
                platform="hermes",
                external_id=sess_id,
                title=meta.get("title") or f"Sesja Hermes {sess_id[:8]}",
                project_path=meta.get("project_path"),
                git_branch=meta.get("git_branch"),
                device=meta.get("device"),
                model=meta.get("model") or "gpt-4o",
                started_at=msgs[0].created_at if msgs and msgs[0].created_at else datetime.now(timezone.utc),
                updated_at=msgs[-1].created_at if msgs and msgs[-1].created_at else datetime.now(timezone.utc),
                raw_metadata=meta,
                messages=msgs
            )

        session_dict: Optional[Dict[str, Any]] = None
        messages_list: List[Dict[str, Any]] = []

        if isinstance(raw_data, dict) and "session" in raw_data and "messages" in raw_data:
            session_dict = raw_data["session"]
            messages_list = raw_data["messages"]
        else:
            db_path: Path
            session_id: Optional[str] = meta.get("session_id") or meta.get("conversation_id")

            if isinstance(raw_data, (str, Path)) and str(raw_data).endswith("state.db"):
                db_path = Path(raw_data)
            elif isinstance(raw_data, dict) and "db_path" in raw_data:
                db_path = Path(raw_data["db_path"])
                session_id = session_id or raw_data.get("session_id")
            elif isinstance(raw_data, str) and ("_" in raw_data or len(raw_data) >= 8):
                session_id = raw_data
                db_path = Path.home() / ".hermes" / "state.db"
            else:
                db_path = Path.home() / ".hermes" / "state.db"

            if not db_path.is_file():
                raise FileNotFoundError(f"Hermes database not found at {db_path}")

            session_dict, messages_list = self._load_from_sqlite(db_path, session_id)

        if not session_dict:
            raise ValueError("No session found in Hermes data")

        session_id = session_dict.get("id") or meta.get("session_id") or "unknown-hermes"
        title = session_dict.get("title") or f"Sesja Hermes {session_id[:8]}"
        project_path = session_dict.get("cwd") or meta.get("project_path")
        git_branch = session_dict.get("git_branch") or meta.get("git_branch")
        model_name = session_dict.get("model") or meta.get("model") or "gpt-4o"

        # Timestamps
        started_epoch = session_dict.get("started_at")
        ended_epoch = session_dict.get("ended_at")

        started_at = (
            datetime.fromtimestamp(float(started_epoch), timezone.utc)
            if started_epoch is not None
            else datetime.now(timezone.utc)
        )
        updated_at = (
            datetime.fromtimestamp(float(ended_epoch), timezone.utc)
            if ended_epoch is not None
            else started_at
        )

        # Tokens & Cost
        tokens_in = session_dict.get("input_tokens") or 0
        tokens_out = session_dict.get("output_tokens") or 0
        cache_read = session_dict.get("cache_read_tokens") or 0
        cache_write = session_dict.get("cache_write_tokens") or 0
        reasoning_tokens = session_dict.get("reasoning_tokens") or 0
        cost_usd = session_dict.get("actual_cost_usd") or session_dict.get("estimated_cost_usd") or 0.0

        # Build tool results map if tool messages exist
        tool_results_by_id: Dict[str, Dict[str, Any]] = {}
        for m in messages_list:
            if m.get("role") == "tool" and m.get("tool_call_id"):
                tool_results_by_id[m["tool_call_id"]] = m

        norm_messages: List[NormalizedMessage] = []
        step_idx = 0

        for m in messages_list:
            role = m.get("role", "user")
            # Tool messages are attached to the assistant's ToolCallRecord
            if role == "tool":
                continue

            step_idx += 1
            raw_content = m.get("content") or ""
            reasoning_content = m.get("reasoning_content") or m.get("reasoning")
            ts_epoch = m.get("timestamp")
            msg_time = (
                datetime.fromtimestamp(float(ts_epoch), timezone.utc)
                if ts_epoch is not None
                else started_at
            )

            tool_calls: List[ToolCallRecord] = []
            raw_tool_calls = m.get("tool_calls")
            if raw_tool_calls:
                parsed_calls = []
                if isinstance(raw_tool_calls, str):
                    try:
                        parsed_calls = json.loads(raw_tool_calls)
                    except Exception:
                        parsed_calls = []
                elif isinstance(raw_tool_calls, list):
                    parsed_calls = raw_tool_calls

                for tc in parsed_calls:
                    if not isinstance(tc, dict):
                        continue
                    tc_id = tc.get("id") or ""
                    fn = tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}
                    t_name = fn.get("name") or tc.get("name") or "tool"
                    t_args = fn.get("arguments") or tc.get("input") or {}
                    if isinstance(t_args, str):
                        try:
                            t_args = json.loads(t_args)
                        except Exception:
                            t_args = {"raw": t_args}

                    tool_output = None
                    is_err = False
                    if tc_id and tc_id in tool_results_by_id:
                        tr_msg = tool_results_by_id[tc_id]
                        tool_output = tr_msg.get("content")
                        if tr_msg.get("is_error"):
                            is_err = True

                    tool_calls.append(
                        ToolCallRecord(
                            name=t_name,
                            input=t_args if isinstance(t_args, dict) else {"arg": t_args},
                            output=str(tool_output) if tool_output is not None else None,
                            is_error=is_err
                        )
                    )

            norm_messages.append(
                NormalizedMessage(
                    step_index=step_idx,
                    external_id=str(m.get("id")) if m.get("id") is not None else None,
                    role="assistant" if role == "assistant" else ("system" if role == "system" else "user"),
                    content=raw_content,
                    reasoning_content=reasoning_content,
                    tool_calls=tool_calls,
                    token_usage={},
                    created_at=msg_time,
                )
            )

        if not norm_messages:
            norm_messages.append(
                NormalizedMessage(
                    step_index=1,
                    role="assistant",
                    content="Pusta sesja Hermes.",
                    token_usage={},
                    created_at=started_at
                )
            )

        if norm_messages and norm_messages[-1].created_at > updated_at:
            updated_at = norm_messages[-1].created_at

        # Compute conversation-wide token_summary
        token_summary = None
        if tokens_in or tokens_out or cache_read or cache_write:
            token_summary = {
                "input_tokens": int(tokens_in),
                "output_tokens": int(tokens_out),
                "cache_read_tokens": int(cache_read),
                "cache_write_tokens": int(cache_write),
                "reasoning_tokens": int(reasoning_tokens),
                "total_tokens": int(tokens_in + tokens_out + cache_read + cache_write),
            }

        # Put session token usage on the final assistant message so that the message chip displays it accurately
        last_asst = next((m for m in reversed(norm_messages) if m.role == "assistant"), None)
        if last_asst and token_summary:
            last_asst.token_usage = token_summary.copy()

        raw_meta = {
            "session_id": session_id,
            "cost_usd": cost_usd,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "reasoning_tokens": reasoning_tokens,
            **(meta or {})
        }
        if token_summary:
            raw_meta["token_summary"] = token_summary

        return NormalizedConversation(
            platform="hermes",
            external_id=str(session_id),
            title=title,
            project_path=project_path,
            git_branch=git_branch,
            device=meta.get("device"),
            model=model_name,
            started_at=started_at,
            updated_at=updated_at,
            raw_metadata=raw_meta,
            messages=norm_messages
        )

    def _load_from_sqlite(self, db_path: Path, session_id: Optional[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            if session_id:
                cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            else:
                cur.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1")
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
