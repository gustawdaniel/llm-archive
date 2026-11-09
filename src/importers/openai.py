import logging
from pathlib import Path
from typing import List
from ..models import NormalizedConversation
from ..normalizers import ChatGPTNormalizer
from .base import BaseArchiveImporter

logger = logging.getLogger("importer.openai")


class OpenAIArchiveImporter(BaseArchiveImporter):
    def parse_archive(self, file_path: Path) -> List[NormalizedConversation]:
        data = self.read_file_or_zip(file_path, "conversations.json")
        if not data:
            raise ValueError(f"Could not find 'conversations.json' in {file_path}")

        if not isinstance(data, list):
            data = [data]

        normalizer = ChatGPTNormalizer()
        conversations: List[NormalizedConversation] = []

        for item in data:
            try:
                conv = self.to_common_model(item)
                if conv and conv.messages:
                    conversations.append(conv)
            except Exception as e:
                conv_id = item.get("id") or "unknown"
                logger.warning(f"Failed to parse OpenAI conversation {conv_id}: {e}")

        return conversations

    def to_common_model(self, raw: dict) -> NormalizedConversation:
        normalizer = ChatGPTNormalizer()
        return normalizer.parse(raw)

