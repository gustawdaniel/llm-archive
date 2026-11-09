import logging
from pathlib import Path
from typing import List
from ..models import NormalizedConversation
from ..normalizers import ClaudeWebNormalizer
from .base import BaseArchiveImporter

logger = logging.getLogger("importer.claude")


class ClaudeArchiveImporter(BaseArchiveImporter):
    def parse_archive(self, file_path: Path) -> List[NormalizedConversation]:
        data = self.read_file_or_zip(file_path, "conversations.json")
        if not data:
            raise ValueError(f"Could not find 'conversations.json' in {file_path}")

        if not isinstance(data, list):
            data = [data]

        normalizer = ClaudeWebNormalizer()
        conversations: List[NormalizedConversation] = []

        for item in data:
            try:
                conv = self.to_common_model(item)
                if conv and conv.messages:
                    conversations.append(conv)
            except Exception as e:
                conv_id = item.get("uuid") or item.get("id") or "unknown"
                logger.warning(f"Failed to parse Claude conversation {conv_id}: {e}")

        return conversations

    def to_common_model(self, raw: dict) -> NormalizedConversation:
        normalizer = ClaudeWebNormalizer()
        return normalizer.parse(raw)

