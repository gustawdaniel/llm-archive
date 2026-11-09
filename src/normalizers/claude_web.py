import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class ClaudeWebNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a dict from Claude Web API: /api/organizations/{org}/chat_conversations/{id}?tree=True
        - an item from conversations.json export: {uuid, name, created_at, updated_at, chat_messages: [...]}
        """
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)
        elif isinstance(raw_data, list):
            raw_data = {"chat_messages": raw_data}

        conv_id = raw_data.get("uuid") or raw_data.get("id") or (metadata or {}).get("conversation_id", "unknown-claude")
        title = raw_data.get("name") or raw_data.get("title") or (metadata or {}).get("title", "Rozmowa Claude")
        created_at_raw = raw_data.get("created_at")
        updated_at_raw = raw_data.get("updated_at")

        def parse_dt(val: Any) -> datetime:
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                except Exception:
                    pass
            return datetime.now(timezone.utc)

        started_at = parse_dt(created_at_raw)
        updated_at = parse_dt(updated_at_raw)

        raw_messages = raw_data.get("chat_messages") or raw_data.get("messages") or []
        messages: List[NormalizedMessage] = []

        for idx, m in enumerate(raw_messages):
            sender = m.get("sender") or m.get("role") or "assistant"
            role = "user" if sender in ("human", "user") else "assistant"
            
            # Content could be text or blocks
            text = m.get("text") or ""
            content_blocks = m.get("content") or []
            tool_calls = []
            reasoning = None

            if isinstance(content_blocks, list):
                block_texts = []
                for b in content_blocks:
                    if isinstance(b, dict):
                        b_type = b.get("type")
                        if b_type == "text":
                            block_texts.append(b.get("text", ""))
                        elif b_type == "tool_use":
                            tool_calls.append(ToolCallRecord(
                                name=b.get("name", "tool"),
                                input=b.get("input", {})
                            ))
                        elif b_type == "thinking":
                            reasoning = b.get("thinking")
                if block_texts and not text:
                    text = "\n".join(block_texts)

            # Check attachments
            attachments = m.get("attachments") or []
            if attachments:
                att_desc = "\n".join([f"> [Załącznik: {a.get('file_name', 'plik')}]" for a in attachments])
                text = f"{text}\n\n{att_desc}" if text else att_desc

            m_dt = parse_dt(m.get("created_at"))
            messages.append(NormalizedMessage(
                step_index=idx,
                external_id=m.get("uuid") or f"{conv_id}_{idx}",
                role=role,
                content=text.strip(),
                reasoning_content=reasoning,
                tool_calls=tool_calls,
                created_at=m_dt
            ))

        return NormalizedConversation(
            platform="claude_web",
            external_id=conv_id,
            title=title,
            model=raw_data.get("model") or "claude-3-7-sonnet",
            device=(metadata or {}).get("device"),
            started_at=started_at,
            updated_at=updated_at,
            raw_metadata={"model": raw_data.get("model")},
            messages=messages
        )

