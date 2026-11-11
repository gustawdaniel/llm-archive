import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class KimiCodeNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        Parse a Kimi Code CLI session.

        raw_data can be:
        - a Path/str to agents/main/wire.jsonl
        - a string with newline-delimited JSON
        - a list of event dicts
        """
        lines: List[dict] = []
        session_id = (metadata or {}).get("session_id") or (metadata or {}).get("conversation_id")
        project_path = (metadata or {}).get("project_path")
        model: Optional[str] = (metadata or {}).get("model")

        if isinstance(raw_data, (str, Path)) and (isinstance(raw_data, Path) or (not isinstance(raw_data, Path) and "\n" not in str(raw_data) and Path(raw_data).is_file())):
            file_path = Path(raw_data)
            if not session_id:
                # wire.jsonl lives at <session_dir>/agents/main/wire.jsonl
                session_dir = file_path.parent.parent.parent
                session_id = session_dir.name
            if not project_path:
                state_file = file_path.parent.parent.parent / "state.json"
                if state_file.is_file():
                    try:
                        st = json.loads(state_file.read_text(encoding="utf-8"))
                        project_path = st.get("cwd")
                    except Exception:
                        pass
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
            raise ValueError(f"Unsupported raw_data type for Kimi Code: {type(raw_data)}")

        session_id = session_id or "unknown-kimi-code"

        messages: List[NormalizedMessage] = []
        started_at: Optional[datetime] = None
        updated_at: Optional[datetime] = None
        step_counter = 0
        first_prompt_title: Optional[str] = None

        for ev in lines:
            if not isinstance(ev, dict):
                continue

            ev_type = ev.get("type")

            if ev_type == "profile.bind":
                if not model:
                    model = ev.get("modelAlias") or ev.get("model")

            if ev_type != "agent.message.appended":
                continue

            wrapper = ev.get("message", {})
            m = wrapper.get("message", {})
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue

            content_parts: List[str] = []
            reasoning_parts: List[str] = []
            for c in m.get("content", []) or []:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype == "text":
                    txt = c.get("text", "")
                    if isinstance(txt, str) and txt.strip():
                        content_parts.append(txt.strip())
                elif ctype == "think":
                    th = c.get("think", "")
                    if isinstance(th, str) and th.strip():
                        reasoning_parts.append(th.strip())

            content_str = "\n".join(content_parts).strip()
            reasoning_str = "\n".join(reasoning_parts).strip() or None

            # timestamp
            dt = None
            meta = wrapper.get("meta", {}) or {}
            created = meta.get("createdAt")
            if isinstance(created, str):
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except Exception:
                    pass
            if dt is None:
                time_ms = ev.get("time")
                if isinstance(time_ms, (int, float)):
                    try:
                        dt = datetime.fromtimestamp(time_ms / 1000.0, timezone.utc)
                    except Exception:
                        pass
            if dt is None:
                dt = updated_at or datetime.now(timezone.utc)

            if started_at is None:
                started_at = dt
            updated_at = dt

            if role == "user" and not first_prompt_title and content_str:
                first_line = content_str.split("\n")[0].strip()
                if first_line:
                    first_prompt_title = first_line[:100]

            messages.append(NormalizedMessage(
                step_index=step_counter,
                external_id=meta.get("userMessageId") or meta.get("promptId") or f"{session_id}_{step_counter}",
                role=role,
                content=content_str,
                reasoning_content=reasoning_str,
                created_at=dt,
            ))
            step_counter += 1

        title = (metadata or {}).get("title") or first_prompt_title or f"Sesja Kimi Code {str(session_id)[:8]}"

        if started_at is None:
            started_at = datetime.now(timezone.utc)
        if updated_at is None:
            updated_at = started_at

        return NormalizedConversation(
            platform="kimi_code",
            external_id=session_id,
            title=title,
            model=model,
            project_path=project_path,
            started_at=started_at,
            updated_at=updated_at,
            raw_metadata=metadata or {},
            messages=messages,
        )
