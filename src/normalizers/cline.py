import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer

logger = logging.getLogger(__name__)


class ClineNormalizer(BaseNormalizer):
    """
    Normalizer for Cline (VS Code extension saoudrizwan.claude-dev).
    Supports:
    - Modern Cline v4+ SDK sessions: ~/.cline/data/sessions/<id>/<id>.messages.json & <id>.json
    - Legacy VS Code globalStorage tasks: tasks/<id>/ui_messages.json & api_conversation_history.json
    """

    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        task_id = (metadata or {}).get("task_id") or (metadata or {}).get("session_id") or (metadata or {}).get("conversation_id")
        project_path = (metadata or {}).get("project_path")
        git_branch = (metadata or {}).get("git_branch")
        model = (metadata or {}).get("model")
        device = (metadata or {}).get("device")
        meta_title = (metadata or {}).get("title")
        task_dir: Optional[Path] = None

        raw_list: List[Dict[str, Any]] = []
        is_ui_messages = False

        if isinstance(raw_data, (str, Path)) and (isinstance(raw_data, Path) or ("\n" not in str(raw_data) and Path(str(raw_data)).exists())):
            path = Path(str(raw_data))
            if path.is_dir():
                task_dir = path
                if not task_id:
                    task_id = path.name
                
                # Check for modern Cline SDK session format: *.messages.json
                sdk_msg_files = list(path.glob("*.messages.json"))
                if sdk_msg_files and sdk_msg_files[0].stat().st_size > 0:
                    raw_data_file = sdk_msg_files[0]
                else:
                    ui_file = path / "ui_messages.json"
                    api_file = path / "api_conversation_history.json"
                    if ui_file.is_file() and ui_file.stat().st_size > 0:
                        raw_data_file = ui_file
                        is_ui_messages = True
                    elif api_file.is_file() and api_file.stat().st_size > 0:
                        raw_data_file = api_file
                    else:
                        raw_data_file = ui_file
            else:
                raw_data_file = path
                task_dir = path.parent
                if not task_id:
                    task_id = path.parent.name
                if "ui_messages" in path.name:
                    is_ui_messages = True

            # Check companion metadata files: <session_id>.json or task_metadata.json
            if task_dir and task_dir.is_dir():
                companion_candidates = [
                    task_dir / f"{task_dir.name}.json",
                    task_dir / "task_metadata.json"
                ]
                for companion in companion_candidates:
                    if companion.is_file():
                        try:
                            with open(companion, "r", encoding="utf-8", errors="replace") as f:
                                comp_json = json.load(f)
                                if not task_id:
                                    task_id = comp_json.get("session_id") or comp_json.get("id")
                                if not project_path:
                                    project_path = comp_json.get("cwd") or comp_json.get("workspace_root") or comp_json.get("workspace")
                                if not model:
                                    model = comp_json.get("model") or (comp_json.get("metadata") or {}).get("modelId")
                                    if not model and isinstance(comp_json.get("model_usage"), list) and comp_json["model_usage"]:
                                        model = comp_json["model_usage"][0].get("model")
                                if not metadata:
                                    metadata = {}
                                meta_obj = comp_json.get("metadata") or {}
                                session_usage = meta_obj.get("usage") or comp_json.get("usage") or meta_obj.get("aggregateUsage")
                                if session_usage:
                                    metadata["usage"] = session_usage
                                if "totalCost" in meta_obj:
                                    metadata["total_cost"] = meta_obj.get("totalCost")
                                elif "totalCost" in comp_json:
                                    metadata["total_cost"] = comp_json.get("totalCost")
                        except Exception as e:
                            logger.debug(f"Could not load companion metadata: {e}")

            if raw_data_file.is_file():
                try:
                    with open(raw_data_file, "r", encoding="utf-8", errors="replace") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            # Modern SDK format: {"version": 1, "sessionId": "...", "messages": [...]}
                            if not task_id and loaded.get("sessionId"):
                                task_id = loaded.get("sessionId")
                            if "messages" in loaded and isinstance(loaded["messages"], list):
                                raw_list = loaded["messages"]
                        elif isinstance(loaded, list):
                            raw_list = loaded
                except Exception as e:
                    logger.warning(f"Failed to load JSON from {raw_data_file}: {e}")

        elif isinstance(raw_data, str):
            try:
                loaded = json.loads(raw_data.strip())
                if isinstance(loaded, dict) and "messages" in loaded and isinstance(loaded["messages"], list):
                    raw_list = loaded["messages"]
                    if not task_id and loaded.get("sessionId"):
                        task_id = loaded.get("sessionId")
                elif isinstance(loaded, list):
                    raw_list = loaded
            except Exception as e:
                logger.warning(f"Failed to parse JSON string for Cline: {e}")

        elif isinstance(raw_data, list):
            raw_list = raw_data

        task_id = task_id or "unknown-cline-task"

        # If already normalized NormalizedMessage list passed
        if raw_list and isinstance(raw_list[0], dict) and "role" in raw_list[0] and ("content" in raw_list[0] or "tool_calls" in raw_list[0]) and "step_index" in raw_list[0]:
            msgs = [NormalizedMessage.model_validate(item) for item in raw_list]
            return NormalizedConversation(
                platform="cline",
                external_id=task_id,
                title=meta_title or f"Zadanie Cline {task_id[:8]}",
                project_path=project_path,
                git_branch=git_branch,
                device=device,
                model=model,
                started_at=msgs[0].created_at if msgs else datetime.now(timezone.utc),
                updated_at=msgs[-1].created_at if msgs else datetime.now(timezone.utc),
                raw_metadata=metadata or {},
                messages=msgs
            )

        if is_ui_messages or (raw_list and any("say" in x or "ask" in x for x in raw_list)):
            return self._parse_ui_messages(raw_list, task_id, project_path, git_branch, model, device, metadata, meta_title)
        else:
            return self._parse_api_history(raw_list, task_id, project_path, git_branch, model, device, metadata, meta_title)

    def _parse_ui_messages(
        self,
        items: List[Dict[str, Any]],
        task_id: str,
        project_path: Optional[str],
        git_branch: Optional[str],
        model: Optional[str],
        device: Optional[str],
        metadata: Optional[Dict[str, Any]],
        meta_title: Optional[str]
    ) -> NormalizedConversation:
        messages: List[NormalizedMessage] = []
        first_prompt_title: Optional[str] = None
        started_at: Optional[datetime] = None
        updated_at: Optional[datetime] = None
        step_counter = 0

        current_assistant_reasoning: List[str] = []
        current_assistant_content_parts: List[str] = []
        current_assistant_tools: List[ToolCallRecord] = []
        current_assistant_token_usage: Dict[str, int] = {}
        current_assistant_dt: Optional[datetime] = None

        default_dt = datetime.now(timezone.utc)

        def flush_assistant(fallback_dt: datetime):
            nonlocal step_counter, current_assistant_reasoning, current_assistant_tools
            nonlocal current_assistant_content_parts, current_assistant_token_usage, current_assistant_dt
            content_str = "\n\n".join(current_assistant_content_parts).strip()
            reasoning_str = "\n\n".join(current_assistant_reasoning).strip() or None

            if content_str or current_assistant_tools or reasoning_str:
                messages.append(NormalizedMessage(
                    step_index=step_counter,
                    external_id=f"{task_id}_{step_counter}",
                    role="assistant",
                    content=content_str,
                    reasoning_content=reasoning_str,
                    tool_calls=list(current_assistant_tools),
                    token_usage=dict(current_assistant_token_usage),
                    created_at=current_assistant_dt or fallback_dt
                ))
                step_counter += 1
                current_assistant_reasoning = []
                current_assistant_content_parts = []
                current_assistant_tools = []
                current_assistant_token_usage = {}
                current_assistant_dt = None

        for item in items:
            ts = item.get("ts")
            dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc) if ts else default_dt
            if started_at is None:
                started_at = dt
            updated_at = dt

            item_type = item.get("type")
            say_type = item.get("say")
            ask_type = item.get("ask")
            raw_text = str(item.get("text") or "")

            # 1. User Initiated Task or Feedback
            if (item_type == "say" and say_type in ("task", "user_feedback", "user_feedback_diff")) or (item_type == "ask" and ask_type in ("resume_task", "resume_completed_task")):
                flush_assistant(dt)
                clean_text = self._clean_prompt_text(raw_text)
                if not first_prompt_title and clean_text:
                    first_line = clean_text.split("\n")[0].strip()
                    first_prompt_title = first_line[:100]

                if not project_path:
                    m = re.search(r"/(?:Users|home)/[^/\s]+(?:/[^/\s]+)+", clean_text)
                    if m:
                        project_path = m.group(0)

                messages.append(NormalizedMessage(
                    step_index=step_counter,
                    external_id=f"{task_id}_{step_counter}",
                    role="user",
                    content=clean_text,
                    created_at=dt
                ))
                step_counter += 1
                continue

            # 2. Assistant Reasoning (Thought Process)
            if item_type == "say" and say_type == "reasoning":
                if current_assistant_dt is None:
                    current_assistant_dt = dt
                if raw_text.strip():
                    current_assistant_reasoning.append(raw_text.strip())
                continue

            # 3. Assistant Output Text or Completion
            if (item_type == "say" and say_type in ("text", "completion_result", "task_completed")) or (item_type == "ask" and ask_type in ("followup", "completion_result")):
                if current_assistant_dt is None:
                    current_assistant_dt = dt
                if raw_text.strip():
                    current_assistant_content_parts.append(raw_text.strip())
                continue

            # 4. Tool Execution Request
            if (item_type == "say" and say_type == "tool") or (item_type == "ask" and ask_type == "tool"):
                if current_assistant_dt is None:
                    current_assistant_dt = dt
                tool_data = {}
                try:
                    tool_data = json.loads(raw_text) if raw_text.startswith("{") else {"raw": raw_text}
                except Exception:
                    tool_data = {"raw": raw_text}
                tool_name = tool_data.get("tool") or tool_data.get("name") or "tool"
                if not project_path and isinstance(tool_data, dict):
                    fpath = tool_data.get("path") or tool_data.get("filePath")
                    if fpath and ("/" in fpath or "\\" in fpath):
                        p = Path(fpath)
                        project_path = str(p.parent if p.suffix or p.is_file() else p)
                current_assistant_tools.append(ToolCallRecord(
                    name=tool_name,
                    input=tool_data
                ))
                continue

            # 5. Shell Command Request
            if item_type == "ask" and ask_type == "command":
                if current_assistant_dt is None:
                    current_assistant_dt = dt
                current_assistant_tools.append(ToolCallRecord(
                    name="execute_command",
                    input={"command": raw_text}
                ))
                continue

            # 6. Shell Command Output
            if item_type == "say" and say_type == "command_output":
                if current_assistant_tools:
                    current_assistant_tools[-1].output = raw_text
                else:
                    if current_assistant_dt is None:
                        current_assistant_dt = dt
                    current_assistant_tools.append(ToolCallRecord(
                        name="command_output",
                        input={},
                        output=raw_text
                    ))
                continue

            # 7. Browser or MCP Tools
            if item_type in ("say", "ask") and any(k in (say_type or ask_type or "") for k in ("browser", "mcp")):
                sub_name = say_type or ask_type or "tool"
                if "result" in sub_name or "response" in sub_name:
                    if current_assistant_tools:
                        current_assistant_tools[-1].output = raw_text
                else:
                    if current_assistant_dt is None:
                        current_assistant_dt = dt
                    current_assistant_tools.append(ToolCallRecord(
                        name=sub_name,
                        input={"input": raw_text}
                    ))
                continue

            # 8. Token / Model Metadata from api_req_started / api_req_finished
            if item_type == "say" and say_type in ("api_req_started", "api_req_finished"):
                try:
                    meta_parsed = json.loads(raw_text) if raw_text.startswith("{") else {}
                    if not model and meta_parsed.get("model"):
                        model = meta_parsed["model"]
                    tokens_in = meta_parsed.get("tokensIn")
                    tokens_out = meta_parsed.get("tokensOut")
                    if tokens_in is not None or tokens_out is not None:
                        in_tok = int(tokens_in or 0)
                        out_tok = int(tokens_out or 0)
                        c_read = int(meta_parsed.get("cacheReads", 0))
                        c_write = int(meta_parsed.get("cacheWrites", 0))
                        current_assistant_token_usage = {
                            "input_tokens": in_tok,
                            "output_tokens": out_tok,
                            "cache_read_tokens": c_read,
                            "cache_write_tokens": c_write,
                            "total_tokens": in_tok + out_tok
                        }
                except Exception:
                    pass
                continue

        flush_assistant(updated_at or default_dt)

        title = meta_title or first_prompt_title or f"Zadanie Cline {task_id[:8]}"

        return NormalizedConversation(
            platform="cline",
            external_id=task_id,
            title=title,
            project_path=project_path,
            git_branch=git_branch,
            device=device,
            model=model,
            started_at=started_at or default_dt,
            updated_at=updated_at or default_dt,
            raw_metadata=metadata or {},
            messages=messages
        )

    def _parse_api_history(
        self,
        items: List[Dict[str, Any]],
        task_id: str,
        project_path: Optional[str],
        git_branch: Optional[str],
        model: Optional[str],
        device: Optional[str],
        metadata: Optional[Dict[str, Any]],
        meta_title: Optional[str]
    ) -> NormalizedConversation:
        messages: List[NormalizedMessage] = []
        first_prompt_title: Optional[str] = None
        started_at: Optional[datetime] = None
        updated_at: Optional[datetime] = None
        step_counter = 0

        default_dt = datetime.now(timezone.utc)
        active_tools: Dict[str, ToolCallRecord] = {}

        for item in items:
            role = item.get("role", "user")
            content_blocks = item.get("content", [])
            ts = item.get("ts")
            dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc) if ts else default_dt

            if started_at is None:
                started_at = dt
            updated_at = dt

            if not model and item.get("modelInfo"):
                model = item["modelInfo"].get("id") or item["modelInfo"].get("model")

            text_parts: List[str] = []
            reasoning_parts: List[str] = []
            tool_calls: List[ToolCallRecord] = []

            if isinstance(content_blocks, str):
                text_parts.append(content_blocks)
            elif isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        t = block.get("text", "")
                        if t:
                            text_parts.append(t)
                    elif btype in ("thinking", "reasoning"):
                        th = block.get("thinking") or block.get("text") or ""
                        if th:
                            reasoning_parts.append(th)
                    elif btype == "tool_use":
                        tc = ToolCallRecord(
                            name=block.get("name", "unknown_tool"),
                            input=block.get("input") or {}
                        )
                        tool_calls.append(tc)
                        if block.get("id"):
                            active_tools[block["id"]] = tc
                        if not project_path and isinstance(block.get("input"), dict):
                            fpath = block["input"].get("path") or block["input"].get("filePath")
                            if fpath and ("/" in fpath or "\\" in fpath):
                                p = Path(fpath)
                                project_path = str(p.parent if p.suffix or p.is_file() else p)
                    elif btype == "tool_result":
                        tid = block.get("tool_use_id")
                        tout = block.get("content") or ""
                        if isinstance(tout, list):
                            tout = "\n".join(b.get("text", "") for b in tout if isinstance(b, dict))
                        if tid and tid in active_tools:
                            active_tools[tid].output = str(tout)
                        else:
                            text_parts.append(f"[Tool Result]: {tout}")

            # Ignore pure tool_result messages that were attached to preceding assistant tool calls
            if role == "user" and not text_parts and any(b.get("type") == "tool_result" for b in (content_blocks if isinstance(content_blocks, list) else [])):
                continue

            full_content = "\n\n".join(text_parts).strip()
            clean_content = self._clean_prompt_text(full_content)

            if role == "user" and not first_prompt_title and clean_content:
                first_line = clean_content.split("\n")[0].strip()
                first_prompt_title = first_line[:100]

            if not project_path and clean_content:
                m = re.search(r"/(?:Users|home)/[^/\s]+(?:/[^/\s]+)+", clean_content)
                if m:
                    project_path = m.group(0)

            reasoning_content = "\n\n".join(reasoning_parts).strip() or None

            metrics = item.get("metrics") or item.get("usage") or {}
            token_usage: Dict[str, int] = {}
            if metrics:
                in_tok = metrics.get("inputTokens") or metrics.get("input_tokens") or 0
                out_tok = metrics.get("outputTokens") or metrics.get("output_tokens") or 0
                c_read = metrics.get("cacheReadTokens") or metrics.get("cache_read_tokens") or metrics.get("cache_read_input_tokens") or 0
                c_write = metrics.get("cacheWriteTokens") or metrics.get("cache_write_tokens") or metrics.get("cache_creation_input_tokens") or 0
                token_usage = {
                    "input_tokens": int(in_tok),
                    "output_tokens": int(out_tok),
                    "cache_read_tokens": int(c_read),
                    "cache_write_tokens": int(c_write),
                    "total_tokens": int(in_tok + out_tok)
                }

            messages.append(NormalizedMessage(
                step_index=step_counter,
                external_id=f"{task_id}_{step_counter}",
                role=role,
                content=clean_content,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls,
                token_usage=token_usage,
                created_at=dt
            ))
            step_counter += 1

        title = meta_title or first_prompt_title or f"Zadanie Cline {task_id[:8]}"

        return NormalizedConversation(
            platform="cline",
            external_id=task_id,
            title=title,
            project_path=project_path,
            git_branch=git_branch,
            device=device,
            model=model,
            started_at=started_at or default_dt,
            updated_at=updated_at or default_dt,
            raw_metadata=metadata or {},
            messages=messages
        )

    def _clean_prompt_text(self, text: str) -> str:
        if not text:
            return ""
        # Strip <task> ... </task> tags
        cleaned = re.sub(r"^\s*<task>\s*", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*</task>\s*$", "", cleaned, flags=re.IGNORECASE)
        # Strip <user_input mode="..."> ... </user_input> tags
        cleaned = re.sub(r"^\s*<user_input[^>]*>\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*</user_input>\s*$", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()
