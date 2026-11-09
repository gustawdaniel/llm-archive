import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class ClaudeCodeNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a list of dicts (parsed jsonl lines from ~/.claude/projects/.../*.jsonl)
        - a string containing newline-delimited JSON
        - a Path to a session jsonl file
        """
        lines = []
        session_id = (metadata or {}).get("session_id") or (metadata or {}).get("conversation_id")
        project_path = (metadata or {}).get("project_path")
        git_branch = (metadata or {}).get("git_branch")

        if isinstance(raw_data, (str, Path)) and (isinstance(raw_data, Path) or "\n" not in raw_data and Path(raw_data).is_file()):
            file_path = Path(raw_data)
            if not session_id:
                session_id = file_path.stem
            parent_name = file_path.parent.name
            if not project_path and (parent_name.startswith("-Users-") or parent_name.startswith("-home-")):
                # Check if cwd is inside the file first, fallback to slug
                raw_slug = parent_name.lstrip("-")
                # Try finding real directory by replacing leading parts
                parts = raw_slug.split("-")
                for i in range(1, len(parts)):
                    candidate = Path("/" + "/".join(parts[:i]) + "/" + "-".join(parts[i:]))
                    if candidate.is_dir():
                        project_path = str(candidate)
                        break
                if not project_path:
                    project_path = "/" + raw_slug.replace("-", "/")

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
            raise ValueError(f"Unsupported raw_data type for Claude Code: {type(raw_data)}")

        session_id = session_id or "unknown-claude-code"

        if lines and isinstance(lines[0], dict) and "role" in lines[0] and ("content" in lines[0] or "tool_calls" in lines[0]):
            msgs = [NormalizedMessage.model_validate(item) for item in lines]
            return NormalizedConversation(
                platform="claude_code",
                external_id=session_id,
                title=(metadata or {}).get("title") or f"Sesja Claude Code {session_id[:8]}",
                project_path=project_path or (metadata or {}).get("project_path"),
                git_branch=git_branch or (metadata or {}).get("git_branch"),
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
        model: Optional[str] = None
        step_counter = 0

        # Mapping tool_use_id -> tool_call for attaching results
        active_tools: Dict[str, ToolCallRecord] = {}

        for entry in lines:
            if not project_path and entry.get("cwd"):
                project_path = entry["cwd"]
            if not git_branch and entry.get("gitBranch"):
                git_branch = entry["gitBranch"]
            if (not session_id or session_id == "unknown-claude-code") and entry.get("sessionId"):
                session_id = entry["sessionId"]

            msg_obj = entry.get("message") or {}
            entry_model = msg_obj.get("model") or entry.get("model")
            if entry_model and not model:
                model = entry_model

            entry_type = entry.get("type")
            msg_obj = entry.get("message") or {}
            timestamp_raw = entry.get("timestamp") or (entry.get("snapshot") or {}).get("timestamp")

            dt = None
            if timestamp_raw:
                try:
                    if isinstance(timestamp_raw, (int, float)):
                        dt = datetime.fromtimestamp(timestamp_raw / 1000.0, timezone.utc)
                    elif isinstance(timestamp_raw, str):
                        dt = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
                except Exception:
                    pass

            if dt is None:
                dt = updated_at or datetime.now(timezone.utc)

            if started_at is None and dt is not None and (entry_type in ("user", "assistant") or msg_obj.get("role")):
                started_at = dt
            if dt is not None and (entry_type in ("user", "assistant") or msg_obj.get("role")):
                updated_at = dt


            if entry_type == "user" or msg_obj.get("role") == "user":
                content_payload = msg_obj.get("content", "")
                text_parts = []
                tool_results = []

                if isinstance(content_payload, str):
                    text_parts.append(content_payload)
                elif isinstance(content_payload, list):
                    for item in content_payload:
                        if isinstance(item, str):
                            text_parts.append(item)
                        elif isinstance(item, dict):
                            if item.get("type") == "text":
                                text_parts.append(item.get("text", ""))
                            elif item.get("type") == "tool_result":
                                t_id = item.get("tool_use_id")
                                t_content = item.get("content", "")
                                tool_results.append((t_id, t_content))

                content_str = "\n".join(text_parts).strip()

                # If this is a pure tool result step, attach output to previous tool
                if tool_results and not content_str:
                    for t_id, t_content in tool_results:
                        if t_id in active_tools:
                            active_tools[t_id].output = str(t_content)
                    continue

                if not first_prompt_title and content_str:
                    lines_cand = [ln.strip() for ln in content_str.split("\n") if ln.strip() and not ln.strip().startswith("<pasted_content") and not ln.strip().startswith("</pasted_content")]
                    if lines_cand:
                        first_prompt_title = lines_cand[0][:100]
                    else:
                        first_line = content_str.split("\n")[0].strip()
                        first_prompt_title = first_line[:100] if first_line else None

                messages.append(NormalizedMessage(
                    step_index=step_counter,
                    external_id=entry.get("promptId") or f"{session_id}_{step_counter}",
                    role="user",
                    content=content_str,
                    created_at=dt
                ))
                step_counter += 1

            elif entry_type == "assistant" or msg_obj.get("role") == "assistant":
                msg_id = msg_obj.get("id")
                content_payload = msg_obj.get("content", "")
                text_parts = []
                reasoning_parts = []
                tool_calls: List[ToolCallRecord] = []

                if isinstance(content_payload, str):
                    text_parts.append(content_payload)
                elif isinstance(content_payload, list):
                    for item in content_payload:
                        if isinstance(item, str):
                            text_parts.append(item)
                        elif isinstance(item, dict):
                            itype = item.get("type")
                            if itype == "text":
                                text_parts.append(item.get("text", ""))
                            elif itype == "thinking":
                                th = item.get("thinking", "")
                                if th:
                                    reasoning_parts.append(th)
                            elif itype == "tool_use":
                                t_record = ToolCallRecord(
                                    name=item.get("name", "tool"),
                                    input=item.get("input", {}),
                                    output=None
                                )
                                tool_calls.append(t_record)
                                if item.get("id"):
                                    active_tools[item["id"]] = t_record

                u = msg_obj.get("usage") or entry.get("usage") or {}
                token_usage: Dict[str, int] = {}
                if u:
                    in_tok = u.get("input_tokens", 0)
                    out_tok = u.get("output_tokens", 0)
                    c_read = u.get("cache_read_input_tokens", 0)
                    c_write = u.get("cache_creation_input_tokens", 0)
                    thinking = (u.get("output_tokens_details") or {}).get("thinking_tokens", 0)
                    token_usage = {
                        "input_tokens": int(in_tok),
                        "output_tokens": int(out_tok),
                        "cache_read_tokens": int(c_read),
                        "cache_write_tokens": int(c_write),
                        "thinking_tokens": int(thinking),
                        "total_tokens": int(in_tok + out_tok + c_read + c_write)
                    }

                text_content = "\n".join(text_parts).strip()
                reasoning_content = "\n".join(reasoning_parts).strip() or None

                can_merge = False
                if messages and messages[-1].role == "assistant":
                    if msg_id and messages[-1].external_id == msg_id:
                        can_merge = True

                if can_merge:
                    last = messages[-1]
                    if text_content:
                        last.content = (last.content + "\n" + text_content).strip() if last.content else text_content
                    if reasoning_content:
                        last.reasoning_content = (last.reasoning_content + "\n" + reasoning_content).strip() if last.reasoning_content else reasoning_content
                    if tool_calls:
                        last.tool_calls.extend(tool_calls)
                    if token_usage:
                        if not last.token_usage:
                            last.token_usage = token_usage
                        else:
                            for k, v in token_usage.items():
                                last.token_usage[k] = max(last.token_usage.get(k, 0), v)
                            last.token_usage["total_tokens"] = (
                                last.token_usage.get("input_tokens", 0) +
                                last.token_usage.get("output_tokens", 0) +
                                last.token_usage.get("cache_read_tokens", 0) +
                                last.token_usage.get("cache_write_tokens", 0)
                            )
                else:
                    messages.append(NormalizedMessage(
                        step_index=step_counter,
                        external_id=msg_id or f"{session_id}_{step_counter}",
                        role="assistant",
                        content=text_content,
                        reasoning_content=reasoning_content,
                        tool_calls=tool_calls,
                        token_usage=token_usage,
                        created_at=dt
                    ))
                    step_counter += 1

        # Drop any assistant message that has no text, no reasoning, and no tool calls
        messages = [
            m for m in messages
            if not (m.role == "assistant" and not m.content.strip() and not (m.reasoning_content or "").strip() and not m.tool_calls)
        ]
        for idx, m in enumerate(messages):
            m.step_index = idx

        if not messages:
            return None

        # Compute conversation-wide token_summary
        total_in = sum((m.token_usage or {}).get("input_tokens", 0) for m in messages)
        total_out = sum((m.token_usage or {}).get("output_tokens", 0) for m in messages)
        total_cr = sum((m.token_usage or {}).get("cache_read_tokens", 0) for m in messages)
        total_cw = sum((m.token_usage or {}).get("cache_write_tokens", 0) for m in messages)
        total_th = sum((m.token_usage or {}).get("thinking_tokens", 0) for m in messages)

        token_summary = None
        if total_in > 0 or total_out > 0 or total_cr > 0 or total_cw > 0:
            token_summary = {
                "input_tokens": int(total_in),
                "output_tokens": int(total_out),
                "cache_read_tokens": int(total_cr),
                "cache_write_tokens": int(total_cw),
                "thinking_tokens": int(total_th),
                "total_tokens": int(total_in + total_out + total_cr + total_cw)
            }

        raw_meta = metadata.copy() if metadata else {}
        raw_meta["session_id"] = session_id
        if project_path:
            raw_meta["project"] = project_path
        if token_summary:
            raw_meta["token_summary"] = token_summary

        return NormalizedConversation(
            platform="claude_code",
            external_id=session_id,
            title=(metadata or {}).get("title") or first_prompt_title or f"Sesja Claude Code {session_id[:8]}",
            project_path=project_path or (metadata or {}).get("project_path"),
            git_branch=git_branch or (metadata or {}).get("git_branch"),
            model=model,
            started_at=started_at or datetime.now(timezone.utc),
            updated_at=updated_at or datetime.now(timezone.utc),
            raw_metadata=raw_meta,
            messages=messages
        )
