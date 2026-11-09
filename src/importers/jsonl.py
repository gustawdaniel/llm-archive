import json
import logging
from pathlib import Path
from typing import List, Optional
from ..models import NormalizedConversation
from ..normalizers import DeepSeekNormalizer, GrokNormalizer, GeminiNormalizer
from .base import BaseArchiveImporter

logger = logging.getLogger("importer.jsonl")


class GenericJSONLImporter(BaseArchiveImporter):
    def __init__(self, platform: str = "deepseek"):
        self.platform = platform

    def parse_archive(self, file_path: Path) -> List[NormalizedConversation]:
        conversations = []
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        normalizers = {
            "deepseek": DeepSeekNormalizer(),
            "grok": GrokNormalizer(),
            "gemini": GeminiNormalizer(),
        }
        norm = normalizers.get(self.platform.lower(), DeepSeekNormalizer())

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line_idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw_obj = json.loads(line)
                    conv = norm.parse(raw_obj, metadata={"line_idx": line_idx})
                    if conv and conv.messages:
                        conversations.append(conv)
                except Exception as e:
                    logger.warning(f"Error parsing line {line_idx} in {file_path.name}: {e}")

        return conversations
