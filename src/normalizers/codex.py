import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer

# Context Codex injects as "user" messages before the real prompt
INJECTED_PREFIXES = ("<environment_context>", "<user_instructions>", "<permissions", "<recommended_plugins>",
                     "# AGENTS.md instructions")


def _is_injected(payload: Dict[str, Any], text: str) -> bool:
    # Newer Codex tags every content item; only "user.text" is something the user typed
    kinds = (payload.get("internal_chat_message_metadata_passthrough") or {}).get("content_item_kinds")
    if kinds:
        return "user.text" not in kinds
    return text.startswith(INJECTED_PREFIXES)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _text_of(content: Any) -> str:
    """Text of a Codex content list ([{type: input_text|output_text|summary_text, text}]) or string."""
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                parts.append(c["text"])
            elif isinstance(c, str):
                parts.append(c)
    return "\n".join(p for p in parts if p).strip()


class CodexNormalizer(BaseNormalizer):
    """OpenAI Codex CLI sessions: ~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session id>.jsonl

    The conversation is rebuilt from `response_item` lines (messages, reasoning summaries, tool
    calls and their outputs). Token usage comes from `token_usage_record` lines, one per model
    response, in OpenAI semantics: input_tokens INCLUDES cached and cache-write tokens, and
    output_tokens INCLUDES reasoning tokens.
    """

    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        meta = metadata or {}

        # Already normalized messages (daemon → API)
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict) and "role" in raw_data[0]:
            msgs = [NormalizedMessage.model_validate(item) for item in raw_data]
            sess_id = meta.get("session_id") or meta.get("conversation_id") or "unknown-codex"
            return NormalizedConversation(
                platform="codex",
                external_id=sess_id,
                title=meta.get("title") or f"Sesja Codex {sess_id[:8]}",
                project_path=meta.get("project_path"),
                git_branch=meta.get("git_branch"),
                device=meta.get("device"),
                model=meta.get("model"),
                started_at=msgs[0].created_at if msgs else datetime.now(timezone.utc),
                updated_at=msgs[-1].created_at if msgs else datetime.now(timezone.utc),
                raw_metadata=meta,
                messages=msgs
            )

        lines: List[Dict[str, Any]] = []
        if isinstance(raw_data, Path) or (isinstance(raw_data, str) and "\n" not in raw_data and Path(raw_data).is_file()):
            text = Path(raw_data).read_text(encoding="utf-8", errors="replace")
        elif isinstance(raw_data, str):
            text = raw_data
        elif isinstance(raw_data, list):
            text = ""
            lines = [x for x in raw_data if isinstance(x, dict)]
        else:
            raise ValueError(f"Unsupported raw_data type for Codex: {type(raw_data)}")
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    lines.append(obj)
        if not lines:
            raise ValueError("No valid JSON lines found for Codex session")

        session_id = meta.get("session_id")
        project_path = meta.get("project_path")
        model = meta.get("model")
        cli_version = None
        started_at: Optional[datetime] = None
        updated_at: Optional[datetime] = None
        total_usage: Optional[Dict[str, Any]] = None

        messages: List[NormalizedMessage] = []
        current: Optional[NormalizedMessage] = None  # assistant message collecting reasoning + tool calls
        calls: Dict[str, ToolCallRecord] = {}
        title: Optional[str] = None

        has_usage_records = any(o.get("type") == "token_usage_record" for o in lines)

        def add_usage(usage: Dict[str, Any]) -> None:
            if current is None:
                return
            tu = current.token_usage
            for src, dst in (("input_tokens", "input_tokens"), ("cached_input_tokens", "cache_read_tokens"),
                             ("cache_write_input_tokens", "cache_write_tokens"), ("output_tokens", "output_tokens"),
                             ("reasoning_output_tokens", "thinking_tokens"), ("total_tokens", "total_tokens")):
                tu[dst] = tu.get(dst, 0) + int(usage.get(src) or 0)

        def new_assistant(ts: datetime) -> NormalizedMessage:
            msg = NormalizedMessage(step_index=len(messages), role="assistant", content="", created_at=ts)
            messages.append(msg)
            return msg

        for obj in lines:
            kind = obj.get("type")
            payload = obj.get("payload") or {}
            ts = _parse_ts(obj.get("timestamp")) or updated_at or datetime.now(timezone.utc)
            started_at = started_at or ts
            updated_at = ts

            if kind == "session_meta":
                session_id = session_id or payload.get("id") or payload.get("session_id")
                project_path = project_path or payload.get("cwd")
                cli_version = payload.get("cli_version")
                started_at = _parse_ts(payload.get("timestamp")) or started_at
            elif kind == "turn_context":
                model = payload.get("model") or model
            elif kind == "token_usage_record":
                add_usage(payload.get("usage") or {})
            elif kind == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                total_usage = info.get("total_token_usage") or total_usage
                if not has_usage_records:
                    add_usage(info.get("last_token_usage") or {})
            elif kind == "response_item":
                ptype = payload.get("type")
                if ptype == "message":
                    role = payload.get("role")
                    text = _text_of(payload.get("content"))
                    if role == "user":
                        if not text or _is_injected(payload, text):
                            continue
                        messages.append(NormalizedMessage(step_index=len(messages), external_id=payload.get("id"),
                                                          role="user", content=text, created_at=ts))
                        title = title or text.splitlines()[0][:80]
                        current = None
                    elif role == "assistant":
                        if current is None or current.content:
                            current = new_assistant(ts)
                        current.external_id = current.external_id or payload.get("id")
                        current.content = text
                    # "developer" messages are Codex's own system instructions: skipped
                elif ptype == "reasoning":
                    summary = _text_of(payload.get("summary"))
                    if summary:
                        if current is None or current.content:
                            current = new_assistant(ts)
                        current.reasoning_content = "\n\n".join(x for x in (current.reasoning_content, summary) if x)
                elif ptype in ("function_call", "custom_tool_call", "local_shell_call"):
                    if current is None or current.content:
                        current = new_assistant(ts)
                    raw_args = payload.get("arguments") if ptype == "function_call" else payload.get("input")
                    if ptype == "local_shell_call":
                        raw_args = (payload.get("action") or {})
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args = {"input": raw_args}
                    else:
                        args = raw_args or {}
                    if not isinstance(args, dict):
                        args = {"input": args}
                    call = ToolCallRecord(name=payload.get("name") or ptype, input=args)
                    current.tool_calls.append(call)
                    if payload.get("call_id"):
                        calls[payload["call_id"]] = call
                elif ptype in ("function_call_output", "custom_tool_call_output"):
                    call = calls.get(payload.get("call_id"))
                    if call is not None:
                        out = payload.get("output")
                        if isinstance(out, dict):
                            out = out.get("content") or json.dumps(out)
                        call.output = _text_of(out)

        messages = [m for m in messages if m.content.strip() or (m.reasoning_content or "").strip() or m.tool_calls]
        for idx, m in enumerate(messages):
            m.step_index = idx
        if not messages:
            raise ValueError(f"No messages parsed for Codex session {session_id}")
        session_id = session_id or "unknown-codex"

        token_summary = None
        if total_usage:
            token_summary = {
                "input_tokens": int(total_usage.get("input_tokens") or 0),
                "cache_read_tokens": int(total_usage.get("cached_input_tokens") or 0),
                "cache_write_tokens": int(total_usage.get("cache_write_input_tokens") or 0),
                "output_tokens": int(total_usage.get("output_tokens") or 0),
                "thinking_tokens": int(total_usage.get("reasoning_output_tokens") or 0),
                "total_tokens": int(total_usage.get("total_tokens") or 0),
            }

        raw_meta = dict(meta)
        raw_meta.update({"session_id": session_id, "project": project_path, "cli_version": cli_version})
        if token_summary:
            raw_meta["token_summary"] = token_summary

        return NormalizedConversation(
            platform="codex",
            external_id=session_id,
            title=title or f"Sesja Codex {session_id[:8]}",
            project_path=project_path,
            git_branch=meta.get("git_branch"),
            device=meta.get("device"),
            model=model,
            started_at=started_at or datetime.now(timezone.utc),
            updated_at=updated_at or started_at or datetime.now(timezone.utc),
            raw_metadata=raw_meta,
            messages=messages
        )
