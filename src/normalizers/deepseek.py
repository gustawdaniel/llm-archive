import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class DeepSeekNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a dict from DeepSeek JSON export (with 'chat_session' and 'chat_messages')
        - a dict from DeepSeek Web API containing 'chat_session_id', 'messages' or 'data': {'biz_data': {'chat_messages': [...]}}
        """
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)

        chat_session = raw_data.get("chat_session") or {}
        conv_id = (
            chat_session.get("id")
            or raw_data.get("chat_session_id")
            or raw_data.get("id")
            or (metadata or {}).get("conversation_id", "unknown-deepseek")
        )
        title = chat_session.get("title") or raw_data.get("title") or "Rozmowa DeepSeek"

        # Messages list can be at top level or nested under biz_data
        biz = raw_data.get("data", {}).get("biz_data", {}) if "data" in raw_data else raw_data
        raw_messages = raw_data.get("chat_messages") or biz.get("chat_messages") or biz.get("messages") or []

        def parse_ts(ts: Any) -> datetime:
            if isinstance(ts, (int, float)):
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

        started_at = parse_ts(chat_session.get("inserted_at")) if chat_session.get("inserted_at") else None
        updated_at = parse_ts(chat_session.get("updated_at")) if chat_session.get("updated_at") else None
        messages: List[NormalizedMessage] = []
        detected_model: Optional[str] = chat_session.get("model_type")
        has_thinking = False

        for idx, m in enumerate(raw_messages):
            raw_role = (m.get("role") or "assistant").lower()
            role = "user" if raw_role in ("user", "human") else "assistant"
            parent_id = str(m["parent_id"]) if m.get("parent_id") is not None else None

            if m.get("thinking_enabled"):
                has_thinking = True

            dt = parse_ts(m.get("inserted_at") or m.get("created_at"))
            if started_at is None:
                started_at = dt
            updated_at = dt

            if not detected_model and m.get("model"):
                detected_model = m.get("model")

            token_usage = {}
            if m.get("accumulated_token_usage"):
                try:
                    token_usage["total_tokens"] = int(m["accumulated_token_usage"])
                except Exception:
                    pass

            content_parts: List[str] = []
            think_parts: List[str] = []
            sources: List[Dict[str, Any]] = []
            tool_calls: List[ToolCallRecord] = []

            # 1. DeepSeek Web API fragments extraction
            fragments = m.get("fragments")
            if isinstance(fragments, list) and fragments:
                for f in fragments:
                    if not isinstance(f, dict):
                        continue
                    ftype = (f.get("type") or "").upper()
                    fcontent = f.get("content") or f.get("text") or ""
                    if not isinstance(fcontent, str):
                        fcontent = str(fcontent) if fcontent is not None else ""

                    if ftype == "THINK":
                        if fcontent.strip():
                            think_parts.append(fcontent.strip())
                    elif ftype == "REQUEST":
                        if fcontent.strip():
                            content_parts.append(fcontent.strip())
                    elif ftype == "RESPONSE":
                        if fcontent.strip():
                            content_parts.append(fcontent.strip())
                    elif ftype == "TOOL_SEARCH":
                        queries = [
                            q.get("query")
                            for q in f.get("queries", [])
                            if isinstance(q, dict) and q.get("query")
                        ]
                        results = f.get("results") or []
                        tool_calls.append(
                            ToolCallRecord(
                                name="web_search",
                                input={"queries": queries},
                                output=fcontent or f"Found {len(results)} web pages"
                            )
                        )
                        for r in results:
                            if isinstance(r, dict) and r.get("url"):
                                sources.append({
                                    "title": r.get("title") or r.get("site_name") or r.get("url"),
                                    "url": r.get("url"),
                                    "snippet": r.get("snippet") or ""
                                })
                    elif ftype == "TOOL_OPEN":
                        r = f.get("result") or {}
                        if isinstance(r, dict) and r.get("url"):
                            sources.append({
                                "title": r.get("title") or r.get("site_name") or r.get("url"),
                                "url": r.get("url"),
                                "snippet": r.get("snippet") or ""
                            })
                    else:
                        if fcontent.strip():
                            content_parts.append(fcontent.strip())

            # 2. Fallback for top-level content
            if not content_parts:
                raw_content = m.get("content") or m.get("text") or m.get("message") or ""
                if isinstance(raw_content, list):
                    content = "\n".join(
                        c.get("text", "") if isinstance(c, dict) else str(c) for c in raw_content
                    )
                elif isinstance(raw_content, dict):
                    content = raw_content.get("text") or raw_content.get("content") or ""
                else:
                    content = str(raw_content)
                if content.strip():
                    content_parts.append(content.strip())

            # 3. Fallback for reasoning
            if not think_parts:
                thinking = m.get("thinking_content") or m.get("reasoning_content")
                if thinking:
                    think_parts.append(str(thinking).strip())

            # 4. Fallback for search results
            if m.get("search_results"):
                for s in m["search_results"]:
                    if isinstance(s, dict) and s.get("url"):
                        sources.append({
                            "title": s.get("title") or s.get("url"),
                            "url": s.get("url"),
                            "snippet": s.get("snippet") or s.get("desc") or ""
                        })

            # Deduplicate sources by URL
            seen_urls = set()
            deduped_sources = []
            for s in sources:
                u = s.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    deduped_sources.append(s)

            final_content = "\n\n".join(content_parts).strip()
            final_reasoning = "\n\n".join(think_parts).strip() if think_parts else None

            messages.append(NormalizedMessage(
                step_index=idx,
                external_id=str(m.get("message_id") or f"{conv_id}_{idx}"),
                parent_id=parent_id,
                role=role,
                content=final_content,
                reasoning_content=final_reasoning,
                sources=deduped_sources,
                tool_calls=tool_calls,
                token_usage=token_usage,
                created_at=dt
            ))

        if not detected_model:
            detected_model = "deepseek-r1" if has_thinking else "deepseek-chat"

        return NormalizedConversation(
            platform="deepseek",
            external_id=conv_id,
            title=title,
            model=detected_model,
            device=(metadata or {}).get("device"),
            started_at=started_at or datetime.now(timezone.utc),
            updated_at=updated_at or datetime.now(timezone.utc),
            raw_metadata={"session_id": conv_id, "agent": chat_session.get("agent")},
            messages=messages
        )

