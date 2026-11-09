import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage
from .base import BaseNormalizer


class GeminiNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        Supports Gemini Web exports, API turn structures, or single conversation dicts.
        """
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)

        conv_id = (
            raw_data.get("conversation_id")
            or raw_data.get("id")
            or (metadata or {}).get("conversation_id", "unknown-gemini")
        )
        title = raw_data.get("title") or "Rozmowa Gemini"
        model = raw_data.get("model") or "gemini-2.5-pro"

        raw_messages = (
            raw_data.get("messages")
            or raw_data.get("turns")
            or raw_data.get("contents")
            or []
        )

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

        # Parse timestamps and sort messages chronologically if timestamps are available
        parsed_entries = []
        for idx, m in enumerate(raw_messages):
            dt = parse_ts(m.get("created_at") or m.get("timestamp"))
            author = m.get("author") or m.get("role") or "assistant"
            role = "user" if str(author).lower() in ("user", "human") else "assistant"
            parsed_entries.append((dt, 0 if role == "user" else 1, idx, m, role))

        # If timestamps are present and not in ascending order, sort chronologically
        if len(parsed_entries) > 1:
            parsed_entries.sort(key=lambda e: (e[0], e[1], e[2]))

        started_at = None
        updated_at = None
        messages: List[NormalizedMessage] = []

        for new_idx, (dt, _, orig_idx, m, role) in enumerate(parsed_entries):
            parts = m.get("parts") or m.get("content") or m.get("text") or ""
            if isinstance(parts, list):
                text_parts = []
                for p in parts:
                    if isinstance(p, dict):
                        text_parts.append(p.get("text") or "")
                    elif isinstance(p, str):
                        text_parts.append(p)
                content = "\n\n".join(text_parts)
            else:
                content = str(parts)

            if started_at is None or dt < started_at:
                started_at = dt
            if updated_at is None or dt > updated_at:
                updated_at = dt

            messages.append(NormalizedMessage(
                step_index=new_idx,
                external_id=str(m.get("id") or f"{conv_id}_{new_idx}"),
                role=role,
                content=content.strip(),
                created_at=dt
            ))

        return NormalizedConversation(
            platform="gemini",
            external_id=conv_id,
            title=title,
            model=model,
            device=(metadata or {}).get("device"),
            started_at=started_at or datetime.now(timezone.utc),
            updated_at=updated_at or datetime.now(timezone.utc),
            raw_metadata={"session_id": conv_id},
            messages=messages
        )

    IGNORED_EVENT_PREFIXES = (
        "Wyczyszczono poprzednie opinie",
        "Wybrana preferowana wersja odpowiedzi",
        "Użyto funkcji Asystenta",
        "Użyto Aplikacje z",
        "Utworzono artefakt Gemini Canvas",
        "Cleared previous feedback",
        "Used Assistant",
        "Used the Assistant feature",
        "Created Gemini Canvas",
        "Used Gemini Apps",
        "Selected preferred response",
    )

    @classmethod
    def aggregate_takeout_events(cls, events: List[Dict[str, Any]]) -> List[NormalizedConversation]:
        """
        Groups raw Google Takeout My Activity events by conversation URL and converts HTML responses to Markdown.
        Filters out internal telemetry and UI actions (e.g. feedback resets, Assistant invocations, Canvas creations).
        """
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for e in events:
            raw_title = (e.get("title") or "").replace("\xa0", " ").strip()
            if any(raw_title.startswith(p) for p in cls.IGNORED_EVENT_PREFIXES):
                continue

            url = None
            for d in e.get("details", []):
                if d.get("url") and "gemini.google.com/app/" in d["url"]:
                    url = d["url"]
                    break

            # Skip events that lack an active Gemini conversation URL
            if not url:
                continue

            # Must either be a recognized query or have an assistant HTML response
            is_query = bool(re.match(r"^(?:Wysłano zapytanie|Prompted|Asked):\s*", raw_title, re.IGNORECASE))
            has_response = bool(e.get("safeHtmlItem"))
            if not is_query and not has_response:
                continue

            groups[url].append(e)

        conversations: List[NormalizedConversation] = []

        for conv_key, ev_list in groups.items():
            # Sort events chronologically (Google Takeout is newest-first)
            ev_list.sort(key=lambda x: x.get("time") or "")

            ext_id = conv_key.split("/")[-1] if "gemini.google.com" in conv_key else conv_key.replace("activity_", "")
            title: Optional[str] = None
            started_at: Optional[datetime] = None
            updated_at: Optional[datetime] = None
            messages: List[NormalizedMessage] = []
            step_counter = 0

            for ev in ev_list:
                raw_time = ev.get("time")
                try:
                    dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00")) if raw_time else datetime.now(timezone.utc)
                except Exception:
                    dt = datetime.now(timezone.utc)

                if started_at is None:
                    started_at = dt
                updated_at = dt

                # User query extraction
                raw_title = ev.get("title") or ""
                query_text = re.sub(r"^(?:Wysłano zapytanie|Prompted|Asked):\s*", "", raw_title, flags=re.IGNORECASE).strip()
                if not title and query_text:
                    first_line = query_text.split("\n")[0].strip()
                    title = first_line[:100]

                # Attachments from subtitles or attachedFiles
                attachments: List[Dict[str, Any]] = []
                for sub in ev.get("subtitles", []):
                    if sub.get("url"):
                        attachments.append({
                            "name": sub.get("name") or "audio.wav",
                            "filename": sub.get("url"),
                            "type": "audio" if sub.get("url", "").endswith(".wav") else "file"
                        })
                for att in ev.get("attachedFiles", []):
                    if isinstance(att, str):
                        attachments.append({
                            "name": att,
                            "filename": att,
                            "type": "audio" if att.endswith(".wav") else ("image" if att.endswith((".jpg", ".png")) else "file")
                        })

                # 1. User message
                if query_text or attachments:
                    messages.append(NormalizedMessage(
                        step_index=step_counter,
                        external_id=f"{ext_id}_u_{step_counter}",
                        role="user",
                        content=query_text or "Zapytanie głosowe / plik",
                        attachments=attachments,
                        created_at=dt
                    ))
                    step_counter += 1

                # 2. Assistant response from safeHtmlItem
                safe_html = ev.get("safeHtmlItem", [])
                html_snippets = [item.get("html", "") for item in safe_html if isinstance(item, dict) and item.get("html")]
                combined_html = "\n".join(html_snippets)
                markdown_text = cls._html_to_markdown(combined_html)

                if markdown_text.strip():
                    messages.append(NormalizedMessage(
                        step_index=step_counter,
                        external_id=f"{ext_id}_a_{step_counter}",
                        role="assistant",
                        content=markdown_text.strip(),
                        created_at=dt
                    ))
                    step_counter += 1

            if messages:
                conversations.append(NormalizedConversation(
                    platform="gemini",
                    external_id=ext_id,
                    title=title or f"Gemini {ext_id[:8]}",
                    model="gemini-takeout",
                    started_at=started_at or datetime.now(timezone.utc),
                    updated_at=updated_at or datetime.now(timezone.utc),
                    raw_metadata={"events_count": len(ev_list), "url": conv_key},
                    messages=messages
                ))

        return conversations

    @staticmethod
    def _html_to_markdown(html_content: str) -> str:
        """Lightweight, resilient HTML to Markdown converter."""
        if not html_content:
            return ""

        text = html.unescape(html_content)
        # Block tags
        text = re.sub(r"<(?:p|div)[^>]*>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</(?:p|div)>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<hr\s*/?>", "\n\n---\n\n", text, flags=re.IGNORECASE)

        # Headers
        text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", text, flags=re.IGNORECASE | re.DOTALL)

        # Inline styles
        text = re.sub(r"<(?:strong|b)[^>]*>(.*?)</(?:strong|b)>", r"**\1**", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<(?:em|i)[^>]*>(.*?)</(?:em|i)>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.IGNORECASE | re.DOTALL)

        # Lists
        text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n* \1", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"</?[uo]l[^>]*>", "\n", text, flags=re.IGNORECASE)

        # Links
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.IGNORECASE | re.DOTALL)

        # Strip remaining tags
        text = re.sub(r"<[^>]+>", "", text)
        # Collapse excessive newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

