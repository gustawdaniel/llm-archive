import io
import json
import logging
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from ..models import NormalizedConversation, NormalizedMessage
from .base import BaseArchiveImporter

logger = logging.getLogger("importer.takeout")


class GoogleTakeoutImporter(BaseArchiveImporter):
    def parse_archive(self, file_path: Path) -> List[NormalizedConversation]:
        conversations: List[NormalizedConversation] = []

        if file_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(file_path, "r") as z:
                for name in z.namelist():
                    if name.endswith(".json") and "gemini" in name.lower():
                        with z.open(name) as f:
                            data = json.load(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
                            convs = self._parse_json(data)
                            conversations.extend(convs)
                    elif name.endswith(".html") and ("activity" in name.lower() or "gemini" in name.lower()):
                        with z.open(name) as f:
                            html_text = io.TextIOWrapper(f, encoding="utf-8", errors="replace").read()
                            convs = self._parse_html_activity(html_text)
                            conversations.extend(convs)
        else:
            if file_path.suffix.lower() == ".json":
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                    conversations.extend(self._parse_json(data))
            elif file_path.suffix.lower() == ".html":
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    html_text = f.read()
                    conversations.extend(self._parse_html_activity(html_text))

        return conversations

    def _parse_json(self, data: any) -> List[NormalizedConversation]:
        convs = []
        if isinstance(data, dict) and "conversations" in data:
            items = data["conversations"]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]

        for idx, item in enumerate(items):
            conv_id = item.get("conversation_id") or item.get("id") or f"takeout-gemini-{idx}"
            title = item.get("title") or "Google Gemini Activity"
            raw_turns = item.get("turns") or item.get("messages") or []

            messages = []
            for t_idx, turn in enumerate(raw_turns):
                role = "user" if turn.get("role") in ("user", "human") or turn.get("author") == "USER" else "assistant"
                content = turn.get("content") or turn.get("text") or ""
                messages.append(NormalizedMessage(
                    step_index=t_idx,
                    external_id=f"{conv_id}_{t_idx}",
                    role=role,
                    content=content,
                    created_at=datetime.now(timezone.utc)
                ))

            if messages:
                convs.append(NormalizedConversation(
                    platform="gemini",
                    external_id=conv_id,
                    title=title,
                    model="gemini-takeout",
                    started_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    messages=messages
                ))
        return convs

    def _parse_html_activity(self, html_text: str) -> List[NormalizedConversation]:
        """Extract prompt and response blocks from Google Takeout My Activity HTML."""
        convs = []
        # Match activity blocks
        blocks = re.split(r'<div class="outer-cell[^>]*>', html_text)
        for idx, b in enumerate(blocks):
            if not b.strip() or "Gemini" not in b:
                continue

            # Extract user prompt
            prompt_match = re.search(r'Prompted\s*(.*?)(?:<br>|</div>)', b, re.DOTALL | re.IGNORECASE)
            content = prompt_match.group(1).strip() if prompt_match else ""
            clean_content = re.sub(r'<[^>]+>', '', content).strip()

            if clean_content:
                conv_id = f"takeout-gemini-act-{idx}"
                msg = NormalizedMessage(
                    step_index=0,
                    external_id=f"{conv_id}_0",
                    role="user",
                    content=clean_content,
                    created_at=datetime.now(timezone.utc)
                )
                convs.append(NormalizedConversation(
                    platform="gemini",
                    external_id=conv_id,
                    title=clean_content[:60],
                    model="gemini-takeout",
                    started_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    messages=[msg]
                ))

        return convs

    def to_common_model(self, raw: dict) -> NormalizedConversation:
        convs = self._parse_json(raw)
        if convs:
            return convs[0]
        conv_id = raw.get("id") or "gemini-raw"
        return NormalizedConversation(
            platform="gemini",
            external_id=conv_id,
            title=raw.get("title", "Google Gemini Takeout"),
            model="gemini-takeout",
            started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            messages=[]
        )

