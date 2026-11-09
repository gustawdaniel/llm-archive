import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage
from .base import BaseNormalizer


class PerplexityNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        Supports a single conversation dict from Perplexity export.
        """
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)

        conv_id = (
            raw_data.get("context_uuid")
            or raw_data.get("id")
            or (metadata or {}).get("conversation_id", "unknown-perplexity")
        )
        title = raw_data.get("context_title") or raw_data.get("title") or "Rozmowa Perplexity"

        def parse_ts(ts: Any) -> datetime:
            if isinstance(ts, str):
                try:
                    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    pass
            elif isinstance(ts, (int, float)):
                try:
                    return datetime.fromtimestamp(ts if ts < 1e11 else ts / 1000.0, timezone.utc)
                except Exception:
                    pass
            return datetime.now(timezone.utc)

        started_at = parse_ts(raw_data.get("created_at"))
        updated_at = parse_ts(raw_data.get("updated_at")) or started_at

        entries = raw_data.get("entries") or []
        messages: List[NormalizedMessage] = []
        step_counter = 0

        for entry in entries:
            entry_uuid = entry.get("entry_uuid") or f"{conv_id}_{step_counter}"
            entry_dt = parse_ts(entry.get("created_at")) or updated_at

            query = entry.get("query") or ""
            answer = entry.get("answer") or ""

            # 1. User message
            if query.strip():
                messages.append(NormalizedMessage(
                    step_index=step_counter,
                    external_id=f"{entry_uuid}_u",
                    role="user",
                    content=query.strip(),
                    created_at=entry_dt
                ))
                step_counter += 1

            # 2. Assistant message
            if answer.strip():
                messages.append(NormalizedMessage(
                    step_index=step_counter,
                    external_id=f"{entry_uuid}_a",
                    role="assistant",
                    content=answer.strip(),
                    created_at=entry_dt
                ))
                step_counter += 1

        return NormalizedConversation(
            platform="perplexity",
            external_id=conv_id,
            title=title,
            model=raw_data.get("mode") or "perplexity-copilot",
            device=(metadata or {}).get("device"),
            started_at=started_at,
            updated_at=updated_at,
            raw_metadata={"mode": raw_data.get("mode"), "entries_count": len(entries)},
            messages=messages
        )

