import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class OpenCodeNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a dict containing serialized {"session": {...}, "messages": [...]}
        - a dict containing {"db_path": "...", "session_id": "..."}
        - a session_id string (with db_path looked up at default location)
        - a Path to opencode.db (extracts latest session or session specified in metadata)
        """
        meta = metadata or {}
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict) and "role" in raw_data[0]:
            msgs = [NormalizedMessage.model_validate(item) for item in raw_data]
            sess_id = meta.get("session_id") or meta.get("conversation_id") or "unknown-opencode"
            return NormalizedConversation(
                platform="opencode",
                external_id=sess_id,
                title=meta.get("title") or f"Sesja OpenCode {sess_id[:8]}",
                project_path=meta.get("project_path"),
                git_branch=meta.get("git_branch"),
                device=meta.get("device"),
                model=meta.get("model") or "deepseek-v4-pro",
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
            # Query from SQLite database
            db_path: Path
            session_id: Optional[str] = meta.get("session_id") or meta.get("conversation_id")

            if isinstance(raw_data, (str, Path)) and str(raw_data).endswith(".db"):
                db_path = Path(raw_data)
            elif isinstance(raw_data, dict) and "db_path" in raw_data:
                db_path = Path(raw_data["db_path"])
                session_id = session_id or raw_data.get("session_id")
            elif isinstance(raw_data, str) and raw_data.startswith("ses_"):
                session_id = raw_data
                db_path = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
            else:
                db_path = Path.home() / ".local" / "share" / "opencode" / "opencode.db"

            if not db_path.is_file():
                raise FileNotFoundError(f"OpenCode database not found at {db_path}")

            session_dict, messages_list = self._load_from_sqlite(db_path, session_id)

        if not session_dict:
            raise ValueError("No session found in OpenCode data")

        session_id = session_dict.get("id", "unknown-opencode")
        title = session_dict.get("title") or f"Sesja OpenCode {session_id[:8]}"
        project_path = session_dict.get("directory") or meta.get("project_path")

        # Parse model
        raw_model = session_dict.get("model")
        model_name = "deepseek-v4-pro"
        if isinstance(raw_model, str):
            try:
                parsed_model = json.loads(raw_model)
                if isinstance(parsed_model, dict):
                    model_name = parsed_model.get("id") or parsed_model.get("modelID") or model_name
                else:
                    model_name = str(parsed_model)
            except Exception:
                model_name = raw_model
        elif isinstance(raw_model, dict):
            model_name = raw_model.get("id") or raw_model.get("modelID") or model_name

        # Timestamps
        t_created = session_dict.get("time_created")
        t_updated = session_dict.get("time_updated")
        started_at = datetime.fromtimestamp(t_created / 1000.0, timezone.utc) if t_created else datetime.now(timezone.utc)
        updated_at = datetime.fromtimestamp(t_updated / 1000.0, timezone.utc) if t_updated else started_at

        # Session token summary & cost
        tokens_in = session_dict.get("tokens_input", 0)
        tokens_out = session_dict.get("tokens_output", 0)
        cache_read = session_dict.get("tokens_cache_read", 0)
        cache_write = session_dict.get("tokens_cache_write", 0)
        total_tokens = tokens_in + tokens_out
        total_cost = session_dict.get("cost", 0.0)

        norm_messages: List[NormalizedMessage] = []
        step_idx = 0

        for msg in messages_list:
            data = msg.get("data")
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    data = {}
            elif not isinstance(data, dict):
                data = {}

            role = data.get("role") or msg.get("role") or "assistant"
            # Normalize role
            if role in ("user", "human"):
                role = "user"
            else:
                role = "assistant"

            # Extract parts (text, reasoning, tools)
            parts = msg.get("parts", [])
            text_chunks: List[str] = []
            reasoning_chunks: List[str] = []
            tool_calls: List[ToolCallRecord] = []

            msg_usage: Dict[str, Any] = {}
            data_tokens = data.get("tokens")
            if isinstance(data_tokens, dict):
                msg_in = data_tokens.get("input", 0)
                msg_out = data_tokens.get("output", 0)
                cache_dict = data_tokens.get("cache") or {}
                msg_cr = cache_dict.get("read", 0) if isinstance(cache_dict, dict) else 0
                msg_cw = cache_dict.get("write", 0) if isinstance(cache_dict, dict) else 0
                msg_usage = {
                    "input_tokens": int(msg_in),
                    "output_tokens": int(msg_out),
                    "cache_read_tokens": int(msg_cr),
                    "cache_write_tokens": int(msg_cw),
                    "total_tokens": int(msg_in + msg_out)
                }

            for p in parts:
                pdata = p.get("data")
                if isinstance(pdata, str):
                    try:
                        pdata = json.loads(pdata)
                    except Exception:
                        pdata = {}
                elif not isinstance(pdata, dict):
                    pdata = p

                ptype = pdata.get("type")
                if ptype == "text":
                    txt = pdata.get("text", "")
                    if txt:
                        text_chunks.append(txt)
                elif ptype == "reasoning":
                    r_txt = pdata.get("text") or pdata.get("reasoning", "")
                    if r_txt:
                        reasoning_chunks.append(r_txt)
                elif ptype == "tool":
                    tool_name = pdata.get("tool", "unknown_tool")
                    tool_state = pdata.get("state") or {}
                    tool_input = tool_state.get("input") if isinstance(tool_state, dict) else {}
                    tool_output = tool_state.get("output") if isinstance(tool_state, dict) else None
                    is_err = tool_state.get("status") == "error" if isinstance(tool_state, dict) else False
                    tool_calls.append(ToolCallRecord(
                        name=tool_name,
                        input=tool_input,
                        output=str(tool_output) if tool_output is not None else None,
                        is_error=is_err
                    ))
                elif ptype == "step-finish":
                    tokens_info = pdata.get("tokens")
                    if isinstance(tokens_info, dict) and not msg_usage:
                        msg_usage = {
                            "input_tokens": int(tokens_info.get("input", 0)),
                            "output_tokens": int(tokens_info.get("output", 0)),
                            "cache_read_tokens": int((tokens_info.get("cache") or {}).get("read", 0)),
                            "cache_write_tokens": int((tokens_info.get("cache") or {}).get("write", 0)),
                            "total_tokens": int(tokens_info.get("total", 0))
                        }

            content = "\n\n".join(text_chunks).strip()
            reasoning = "\n\n".join(reasoning_chunks).strip() if reasoning_chunks else None

            # Timestamp for message
            m_time = msg.get("time_created") or (data.get("time") or {}).get("created")
            msg_dt = datetime.fromtimestamp(m_time / 1000.0, timezone.utc) if m_time else started_at

            if not content and not tool_calls and not reasoning:
                continue

            norm_messages.append(NormalizedMessage(
                step_index=step_idx,
                external_id=str(msg.get("id", f"{session_id}_{step_idx}")),
                role=role,
                content=content,
                reasoning_content=reasoning,
                tool_calls=tool_calls,
                token_usage=msg_usage,
                created_at=msg_dt
            ))
            step_idx += 1

        token_summary = {
            "input_tokens": int(tokens_in),
            "output_tokens": int(tokens_out),
            "cache_read_tokens": int(cache_read),
            "cache_write_tokens": int(cache_write),
            "total_tokens": int(total_tokens)
        }

        return NormalizedConversation(
            platform="opencode",
            external_id=session_id,
            title=title,
            project_path=project_path,
            git_branch=meta.get("git_branch"),
            model=model_name,
            started_at=started_at,
            updated_at=updated_at,
            raw_metadata={
                "session_id": session_id,
                "project_path": project_path,
                "model": model_name,
                "total_cost": total_cost,
                "token_summary": token_summary
            },
            messages=norm_messages
        )

    def _load_from_sqlite(self, db_path: Path, session_id: Optional[str]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if session_id:
            cur.execute("SELECT * FROM session WHERE id = ?", (session_id,))
        else:
            cur.execute("SELECT * FROM session ORDER BY time_updated DESC LIMIT 1")

        row = cur.fetchone()
        if not row:
            conn.close()
            return {}, []

        session_dict = dict(row)
        sid = session_dict["id"]

        # Fetch messages
        cur.execute("SELECT * FROM message WHERE session_id = ? ORDER BY time_created ASC", (sid,))
        msg_rows = [dict(r) for r in cur.fetchall()]

        # Fetch parts per message
        cur.execute("SELECT * FROM part WHERE session_id = ? ORDER BY time_created ASC", (sid,))
        part_rows = cur.fetchall()

        parts_by_msg: Dict[str, List[Dict[str, Any]]] = {}
        for p in part_rows:
            p_dict = dict(p)
            mid = p_dict["message_id"]
            if mid not in parts_by_msg:
                parts_by_msg[mid] = []
            parts_by_msg[mid].append(p_dict)

        for m in msg_rows:
            m["parts"] = parts_by_msg.get(m["id"], [])

        conn.close()
        return session_dict, msg_rows
