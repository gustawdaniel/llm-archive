import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage
from .base import BaseNormalizer


class GrokNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        Supports Grok / xAI export formats (containing 'conversation' and 'responses').
        """
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)

        conv_info = raw_data.get("conversation") or {}
        conv_id = (
            conv_info.get("id")
            or conv_info.get("conversationId")
            or raw_data.get("conversation_id")
            or raw_data.get("conversationId")
            or raw_data.get("id")
            or (metadata or {}).get("conversation_id", "unknown-grok")
        )
        title = conv_info.get("title") or raw_data.get("title") or "Rozmowa Grok"
        model = conv_info.get("model") or raw_data.get("model") or "grok-3"

        def parse_ts(ts: Any) -> datetime:
            if isinstance(ts, dict):
                date_val = ts.get("$date")
                if isinstance(date_val, dict) and "$numberLong" in date_val:
                    try:
                        ms = int(date_val["$numberLong"])
                        return datetime.fromtimestamp(ms / 1000.0, timezone.utc)
                    except Exception:
                        pass
                elif isinstance(date_val, (int, float)):
                    return datetime.fromtimestamp(date_val / 1000.0, timezone.utc)
            elif isinstance(ts, (int, float)):
                try:
                    return datetime.fromtimestamp(ts if ts < 1e11 else ts / 1000.0, timezone.utc)
                except Exception:
                    pass
            elif isinstance(ts, str):
                try:
                    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    pass
            return datetime.now(timezone.utc)

        started_at = parse_ts(
            conv_info.get("create_time") or conv_info.get("createTime") or raw_data.get("create_time") or raw_data.get("createTime")
        ) if (conv_info.get("create_time") or conv_info.get("createTime") or raw_data.get("create_time") or raw_data.get("createTime")) else None

        updated_at = parse_ts(
            conv_info.get("modify_time") or conv_info.get("modifyTime") or raw_data.get("modify_time") or raw_data.get("modifyTime")
        ) if (conv_info.get("modify_time") or conv_info.get("modifyTime") or raw_data.get("modify_time") or raw_data.get("modifyTime")) else None

        raw_responses = raw_data.get("responses") or raw_data.get("messages") or []

        # Map by response ID for active path traversal
        resp_map = {}
        for r in raw_responses:
            inner = r.get("response") if isinstance(r, dict) and "response" in r else r
            if isinstance(inner, dict):
                r_id = inner.get("_id") or inner.get("id") or inner.get("responseId")
                if r_id:
                    resp_map[r_id] = inner

        leaf_id = (
            conv_info.get("leaf_response_id")
            or conv_info.get("leafResponseId")
            or raw_data.get("leaf_response_id")
            or raw_data.get("leafResponseId")
        )
        active_responses = []
        if leaf_id and leaf_id in resp_map:
            curr = leaf_id
            visited = set()
            while curr and curr in resp_map and curr not in visited:
                visited.add(curr)
                node = resp_map[curr]
                active_responses.append(node)
                curr = node.get("parent_response_id") or node.get("parentResponseId")
            active_responses.reverse()
        else:
            active_responses = [
                r.get("response") if isinstance(r, dict) and "response" in r else r
                for r in raw_responses
                if isinstance(r, dict)
            ]

        messages: List[NormalizedMessage] = []
        step_counter = 0

        for m in active_responses:
            if not isinstance(m, dict):
                continue
            sender = m.get("sender") or m.get("role") or "assistant"
            role = "user" if str(sender).lower() in ("human", "user") else "assistant"

            content = m.get("message") or m.get("content") or m.get("text") or ""
            dt = parse_ts(m.get("create_time") or m.get("createTime") or m.get("timestamp"))

            if started_at is None:
                started_at = dt
            updated_at = dt

            if not content.strip() and m.get("metadata", {}).get("stream_errors"):
                errors = m["metadata"]["stream_errors"]
                content = f"[Błąd strumieniowania: {errors[0].get('message', 'Nieznany błąd')}]"

            if content.strip() or role == "user":
                if not title and role == "user" and content.strip():
                    first_line = content.strip().split("\n")[0].strip()
                    title = first_line[:100]

                messages.append(NormalizedMessage(
                    step_index=step_counter,
                    external_id=str(m.get("_id") or m.get("id") or m.get("responseId") or f"{conv_id}_{step_counter}"),
                    role=role,
                    content=content.strip(),
                    created_at=dt
                ))
                step_counter += 1

        return NormalizedConversation(
            platform="grok",
            external_id=conv_id,
            title=title or f"Grok {conv_id[:8]}",
            model=model,
            device=(metadata or {}).get("device"),
            started_at=started_at or datetime.now(timezone.utc),
            updated_at=updated_at or datetime.now(timezone.utc),
            raw_metadata={"session_id": conv_id, "leaf_response_id": leaf_id},
            messages=messages
        )
