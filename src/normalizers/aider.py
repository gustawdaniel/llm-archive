import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class AiderNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a string containing markdown of an aider session or whole history file
        - a Path to .aider.chat.history.md
        - a dict with {"content": "...", "session_id": "..."}
        """
        meta = metadata or {}
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict) and "role" in raw_data[0]:
            msgs = [NormalizedMessage.model_validate(item) for item in raw_data]
            sess_id = meta.get("session_id") or meta.get("conversation_id") or "unknown-aider"
            return NormalizedConversation(
                platform="aider",
                external_id=sess_id,
                title=meta.get("title") or f"Sesja Aider {sess_id[:8]}",
                project_path=meta.get("project_path"),
                git_branch=meta.get("git_branch"),
                device=meta.get("device"),
                model=meta.get("model") or "deepseek/deepseek-chat",
                started_at=msgs[0].created_at if msgs and msgs[0].created_at else datetime.now(timezone.utc),
                updated_at=msgs[-1].created_at if msgs and msgs[-1].created_at else datetime.now(timezone.utc),
                raw_metadata=meta,
                messages=msgs
            )

        content: str = ""
        file_path: Optional[Path] = None
        target_session_id = meta.get("session_id") or meta.get("conversation_id")
        project_path = meta.get("project_path")

        # Support reading directly from a JSON file or JSON string
        is_file_candidate = isinstance(raw_data, Path) or (
            isinstance(raw_data, str) and "\n" not in raw_data and len(raw_data) < 4096 and Path(raw_data).is_file()
        )
        if is_file_candidate:
            file_path = Path(raw_data)
            if not project_path:
                project_path = str(file_path.parent)
            content = file_path.read_text(encoding="utf-8", errors="replace")
        elif isinstance(raw_data, dict):
            content = raw_data.get("content", "")
            target_session_id = target_session_id or raw_data.get("session_id")
            project_path = project_path or raw_data.get("project_path")
        elif isinstance(raw_data, str):
            content = raw_data
        else:
            raise ValueError(f"Unsupported raw_data type for Aider: {type(raw_data)}")

        # Check if content is structured JSON
        stripped_content = content.strip()
        if (file_path and file_path.suffix == ".json") or (stripped_content.startswith("{") and stripped_content.endswith("}")):
            try:
                import json
                data = json.loads(stripped_content)
                if isinstance(data, dict) and "messages" in data:
                    msgs = [NormalizedMessage.model_validate(m) for m in data["messages"]]
                    sess_id = data.get("external_id") or target_session_id or meta.get("session_id") or "unknown-aider"
                    first_user = next((m.content for m in msgs if m.role == "user"), None)
                    conv_title = data.get("title") or meta.get("title") or (first_user[:80] if first_user else f"Sesja Aider {sess_id[:8]}")

                    token_summary = data.get("token_summary")
                    raw_meta = dict(data.get("raw_metadata") or meta)
                    if token_summary and "token_summary" not in raw_meta:
                        raw_meta["token_summary"] = token_summary
                    if "total_cost" in data and "total_cost" not in raw_meta:
                        raw_meta["total_cost"] = data["total_cost"]

                    last_asst = next((m for m in reversed(msgs) if m.role == "assistant"), None)
                    if last_asst and token_summary and not last_asst.token_usage:
                        last_asst.token_usage = token_summary.copy()

                    return NormalizedConversation(
                        platform="aider",
                        external_id=sess_id,
                        title=conv_title,
                        project_path=data.get("project_path") or project_path,
                        git_branch=data.get("git_branch") or meta.get("git_branch"),
                        device=data.get("device") or meta.get("device"),
                        model=data.get("model") or meta.get("model") or "deepseek/deepseek-chat",
                        started_at=datetime.fromisoformat(data["started_at"]) if "started_at" in data else (msgs[0].created_at if msgs else datetime.now(timezone.utc)),
                        updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else (msgs[-1].created_at if msgs else datetime.now(timezone.utc)),
                        raw_metadata=raw_meta,
                        messages=msgs
                    )
            except Exception as e:
                # If JSON parsing fails, fall back to markdown parsing
                pass

        if not content.strip():
            raise ValueError("Empty content for Aider session")

        # Split into sessions if multiple exist
        sessions = re.split(r'(?m)^# aider chat started at ', content)
        selected_session: Optional[str] = None
        started_at_str: Optional[str] = None

        if len(sessions) <= 1:
            selected_session = content
        else:
            # Match target session or select the last one
            for s in sessions:
                if not s.strip():
                    continue
                header_time = s.strip().split("\n")[0].strip()
                s_id = f"aider_{header_time.replace(' ', '_').replace(':', '')}"
                if target_session_id and target_session_id in (s_id, header_time):
                    selected_session = s
                    started_at_str = header_time
                    break
            if not selected_session:
                # Pick the latest session that actually has user messages
                for s in reversed(sessions):
                    if s.strip() and "####" in s:
                        selected_session = s
                        started_at_str = s.strip().split("\n")[0].strip()
                        break
            if not selected_session:
                # Fallback to the latest non-empty block
                for s in reversed(sessions):
                    if s.strip():
                        selected_session = s
                        started_at_str = s.strip().split("\n")[0].strip()
                        break

        if not selected_session:
            raise ValueError("No valid session block found in Aider history")

        # Parse start time
        started_at: datetime
        if started_at_str:
            try:
                started_at = datetime.strptime(started_at_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception:
                started_at = datetime.now(timezone.utc)
        elif file_path and file_path.is_file():
            started_at = datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc)
        else:
            started_at = datetime.now(timezone.utc)

        session_id = target_session_id or f"aider_{started_at.strftime('%Y%m%d_%H%M%S')}"

        # Extract model
        model = "deepseek/deepseek-chat"
        model_match = re.search(r'> Model:\s*([^\s,]+)', selected_session)
        if model_match:
            model = model_match.group(1).strip()

        # Parse messages
        # Prompts are separated by #### <prompt>
        parts = re.split(r'(?m)^####\s+', selected_session)
        # parts[0] is preamble before first user prompt
        messages: List[NormalizedMessage] = []
        step_idx = 0

        total_in_tok = 0
        total_out_tok = 0
        total_session_cost = 0.0

        for turn in parts[1:]:
            if not turn.strip():
                continue

            lines = turn.split("\n")
            user_prompt = lines[0].strip()
            rest = "\n".join(lines[1:]).strip()

            # Add user message
            messages.append(NormalizedMessage(
                step_index=step_idx,
                external_id=f"{session_id}_{step_idx}",
                role="user",
                content=user_prompt,
                created_at=started_at
            ))
            step_idx += 1

            if not rest:
                continue

            # Assistant response parsing
            # Look for token metrics line:
            # > Tokens: 2.8k sent, 1.8k received. Cost: $0.0016 message, $0.0023 session.
            tok_match = re.search(
                r'> Tokens:\s*([\d\.]+[km]?)\s*sent,\s*([\d\.]+[km]?)\s*received\.\s*Cost:\s*\$([\d\.]+)\s*message,\s*\$([\d\.]+)\s*session\.',
                rest
            )
            msg_usage: Dict[str, Any] = {}
            if tok_match:
                in_str, out_str, msg_cost_str, sess_cost_str = tok_match.groups()
                in_tokens = self._parse_tokens_str(in_str)
                out_tokens = self._parse_tokens_str(out_str)
                total_in_tok += in_tokens
                total_out_tok += out_tokens
                try:
                    total_session_cost = float(sess_cost_str)
                except ValueError:
                    pass

                msg_usage = {
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                    "total_tokens": in_tokens + out_tokens
                }

            # Check for edits or commands in rest
            tool_calls: List[ToolCallRecord] = []
            
            # Check for file edits <<<<<<< SEARCH ... >>>>>>> REPLACE
            if "<<<<<<< SEARCH" in rest:
                # Find filename preceding SEARCH
                edit_match = re.search(r'([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)\s*```[a-z]*\s*<<<<<<< SEARCH', rest)
                edit_file = edit_match.group(1) if edit_match else "file"
                tool_calls.append(ToolCallRecord(
                    name="edit_file",
                    input={"path": edit_file},
                    output="Applied edit to " + edit_file
                ))

            # Check for shell runs
            shell_runs = re.findall(r'> Running (.*?)(?:\n|$)', rest)
            for cmd in shell_runs:
                tool_calls.append(ToolCallRecord(
                    name="run_command",
                    input={"command": cmd.strip()},
                    output=None
                ))

            messages.append(NormalizedMessage(
                step_index=step_idx,
                external_id=f"{session_id}_{step_idx}",
                role="assistant",
                content=rest,
                tool_calls=tool_calls,
                token_usage=msg_usage,
                created_at=started_at
            ))
            step_idx += 1

        if not messages:
            raise ValueError(f"No messages parsed for Aider session {session_id}")

        first_user_msg = next((m.content for m in messages if m.role == "user"), None)
        title = first_user_msg[:80] if first_user_msg else f"Sesja Aider {session_id[:8]}"

        token_summary = {
            "input_tokens": total_in_tok,
            "output_tokens": total_out_tok,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": total_in_tok + total_out_tok
        }

        return NormalizedConversation(
            platform="aider",
            external_id=session_id,
            title=title,
            project_path=project_path,
            git_branch=meta.get("git_branch"),
            model=model,
            started_at=started_at,
            updated_at=started_at,
            raw_metadata={
                "session_id": session_id,
                "project_path": project_path,
                "model": model,
                "total_cost": total_session_cost,
                "token_summary": token_summary
            },
            messages=messages
        )

    def _parse_tokens_str(self, val: str) -> int:
        val = val.lower().strip()
        try:
            if val.endswith("k"):
                return int(float(val[:-1]) * 1000)
            elif val.endswith("m"):
                return int(float(val[:-1]) * 1_000_000)
            return int(float(val))
        except Exception:
            return 0
