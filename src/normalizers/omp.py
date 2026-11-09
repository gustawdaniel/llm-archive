import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class OMPNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a list of dicts (parsed jsonl lines)
        - a string containing newline-delimited JSON
        - a Path to an OMP session jsonl file (~/.omp/agent/sessions/*/*.jsonl)
        """
        meta = metadata or {}
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict) and "role" in raw_data[0]:
            msgs = [NormalizedMessage.model_validate(item) for item in raw_data]
            sess_id = meta.get("session_id") or meta.get("conversation_id") or "unknown-omp"
            return NormalizedConversation(
                platform="omp",
                external_id=sess_id,
                title=meta.get("title") or f"Sesja OMP {sess_id[:8]}",
                project_path=meta.get("project_path"),
                git_branch=meta.get("git_branch"),
                device=meta.get("device"),
                model=meta.get("model") or "deepseek/deepseek-v4-flash",
                started_at=msgs[0].created_at if msgs and msgs[0].created_at else datetime.now(timezone.utc),
                updated_at=msgs[-1].created_at if msgs and msgs[-1].created_at else datetime.now(timezone.utc),
                raw_metadata=meta,
                messages=msgs
            )

        lines: List[Dict[str, Any]] = []
        file_path: Optional[Path] = None
        session_id = meta.get("session_id") or meta.get("conversation_id")
        project_path = meta.get("project_path")

        if isinstance(raw_data, (str, Path)) and (isinstance(raw_data, Path) or ("\n" not in str(raw_data) and Path(str(raw_data)).is_file())):
            file_path = Path(raw_data)
            stem = file_path.stem
            # filename format: 2026-09-25T15-43-35-209Z_01a0d93c-7d29-7781-a184-9551507b7df8
            if "_" in stem and not session_id:
                session_id = stem.split("_", 1)[1]
            elif not session_id:
                session_id = stem

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            lines.append(json.loads(line))
                        except Exception:
                            continue
        elif isinstance(raw_data, str):
            for line in raw_data.strip().split("\n"):
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except Exception:
                        continue
        elif isinstance(raw_data, list):
            lines = raw_data
        else:
            raise ValueError(f"Unsupported raw_data type for OMP: {type(raw_data)}")

        if not lines:
            raise ValueError("No valid JSON lines found for OMP session")

        title: Optional[str] = None
        model: Optional[str] = meta.get("model")
        cwd: Optional[str] = project_path
        started_at: Optional[datetime] = None
        updated_at: Optional[datetime] = None

        # Pass 1: extract header metadata
        for obj in lines:
            t = obj.get("type")
            if t == "title" and not title:
                title = obj.get("title")
            elif t == "title_change":
                title = obj.get("title") or title
            elif t == "session":
                if not session_id:
                    session_id = obj.get("id")
                cwd = obj.get("cwd") or cwd
                ts_str = obj.get("timestamp")
                if ts_str:
                    try:
                        started_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except Exception:
                        pass
            elif t == "model_change":
                m = obj.get("model")
                if m:
                    model = m

        if not session_id:
            session_id = "unknown-omp"
        if not project_path:
            project_path = cwd

        # Pass 2: build normalized messages
        norm_messages: List[NormalizedMessage] = []
        step_idx = 0

        # Maintain map of toolCallId -> ToolCallRecord for correlating tool results
        active_tools_map: Dict[str, ToolCallRecord] = {}

        total_in = 0
        total_out = 0
        total_cr = 0
        total_cw = 0
        total_cost = 0.0

        for obj in lines:
            t = obj.get("type")
            if t != "message":
                continue

            msg_obj = obj.get("message") or {}
            role = msg_obj.get("role")
            msg_ts = msg_obj.get("timestamp") or obj.get("timestamp")
            msg_dt = None
            if isinstance(msg_ts, (int, float)):
                # epoch ms
                msg_dt = datetime.fromtimestamp(msg_ts / 1000.0, timezone.utc)
            elif isinstance(msg_ts, str):
                try:
                    msg_dt = datetime.fromisoformat(msg_ts.replace("Z", "+00:00"))
                except Exception:
                    pass
            if not msg_dt:
                msg_dt = started_at or datetime.now(timezone.utc)
            updated_at = msg_dt

            if role == "user":
                raw_content = msg_obj.get("content", [])
                text_parts: List[str] = []
                if isinstance(raw_content, str):
                    text_parts.append(raw_content)
                elif isinstance(raw_content, list):
                    for part in raw_content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            text_parts.append(part)

                user_text = "\n".join(text_parts).strip()
                if not title and user_text:
                    title = user_text[:80]

                norm_messages.append(NormalizedMessage(
                    step_index=step_idx,
                    external_id=str(obj.get("id", f"{session_id}_{step_idx}")),
                    role="user",
                    content=user_text,
                    created_at=msg_dt
                ))
                step_idx += 1

            elif role == "assistant":
                m_model = msg_obj.get("model")
                if m_model and not model:
                    model = m_model

                raw_content = msg_obj.get("content", [])
                text_parts = []
                thinking_parts = []
                tool_calls: List[ToolCallRecord] = []

                if isinstance(raw_content, str):
                    text_parts.append(raw_content)
                elif isinstance(raw_content, list):
                    for part in raw_content:
                        if not isinstance(part, dict):
                            continue
                        ptype = part.get("type")
                        if ptype == "text":
                            txt = part.get("text", "")
                            if txt:
                                text_parts.append(txt)
                        elif ptype == "thinking":
                            thk = part.get("thinking", "")
                            if thk:
                                thinking_parts.append(thk)
                        elif ptype == "toolCall":
                            call_id = part.get("id") or f"call_{len(tool_calls)}"
                            name = part.get("name", "unknown_tool")
                            args = part.get("arguments") or {}
                            t_rec = ToolCallRecord(
                                name=name,
                                input=args,
                                output=None
                            )
                            tool_calls.append(t_rec)
                            active_tools_map[call_id] = t_rec

                # Usage & cost
                u = msg_obj.get("usage") or {}
                m_in = u.get("input", 0)
                m_out = u.get("output", 0)
                m_cr = u.get("cacheRead", 0)
                m_cw = u.get("cacheWrite", 0)
                m_tot = u.get("totalTokens", m_in + m_out)
                c_dict = u.get("cost") or {}
                m_cost = c_dict.get("total", 0.0) if isinstance(c_dict, dict) else 0.0

                total_in += m_in
                total_out += m_out
                total_cr += m_cr
                total_cw += m_cw
                total_cost += m_cost

                msg_usage = {}
                if m_in or m_out or m_cr:
                    msg_usage = {
                        "input_tokens": int(m_in),
                        "output_tokens": int(m_out),
                        "cache_read_tokens": int(m_cr),
                        "cache_write_tokens": int(m_cw),
                        "total_tokens": int(m_tot)
                    }

                norm_messages.append(NormalizedMessage(
                    step_index=step_idx,
                    external_id=str(obj.get("id", f"{session_id}_{step_idx}")),
                    role="assistant",
                    content="\n\n".join(text_parts).strip(),
                    reasoning_content="\n\n".join(thinking_parts).strip() if thinking_parts else None,
                    tool_calls=tool_calls,
                    token_usage=msg_usage,
                    created_at=msg_dt
                ))
                step_idx += 1

            elif role == "toolResult":
                call_id = msg_obj.get("toolCallId")
                t_content = msg_obj.get("content", [])
                out_strs = []
                if isinstance(t_content, list):
                    for c_item in t_content:
                        if isinstance(c_item, dict) and c_item.get("type") == "text":
                            out_strs.append(c_item.get("text", ""))
                        elif isinstance(c_item, str):
                            out_strs.append(c_item)
                elif isinstance(t_content, str):
                    out_strs.append(t_content)

                out_text = "\n".join(out_strs).strip()
                is_err = msg_obj.get("isError", False)

                if call_id and call_id in active_tools_map:
                    active_tools_map[call_id].output = out_text
                    active_tools_map[call_id].is_error = is_err

        if not norm_messages:
            raise ValueError(f"No messages parsed for OMP session {session_id}")

        token_summary = {
            "input_tokens": int(total_in),
            "output_tokens": int(total_out),
            "cache_read_tokens": int(total_cr),
            "cache_write_tokens": int(total_cw),
            "total_tokens": int(total_in + total_out)
        }

        return NormalizedConversation(
            platform="omp",
            external_id=session_id,
            title=title or f"Sesja OMP {session_id[:8]}",
            project_path=project_path,
            git_branch=meta.get("git_branch"),
            model=model or "deepseek/deepseek-v4-flash",
            started_at=started_at or datetime.now(timezone.utc),
            updated_at=updated_at or started_at or datetime.now(timezone.utc),
            raw_metadata={
                "session_id": session_id,
                "project_path": project_path,
                "model": model,
                "total_cost": total_cost,
                "token_summary": token_summary
            },
            messages=norm_messages
        )
