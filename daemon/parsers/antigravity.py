import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models import NormalizedConversation
from src.normalizers.antigravity import AntigravityNormalizer

logger = logging.getLogger("daemon.parser.antigravity")


class AntigravityParser:
    """Parser for Antigravity transcript*.jsonl logs and session artifacts."""

    def __init__(self):
        self.normalizer = AntigravityNormalizer()

    def parse_file(self, file_path: Path, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        return self.normalizer.parse(file_path, metadata=metadata)

    def scan_transcripts(self, antigravity_home: Path) -> List[Path]:
        """Finds all transcript.jsonl files in the antigravity brain directory."""
        if not antigravity_home.is_dir():
            return []
        transcripts = []
        for p in antigravity_home.glob("brain/*/.system_generated/logs/transcript*.jsonl"):
            if p.is_file():
                transcripts.append(p)
        return sorted(transcripts, key=lambda f: f.stat().st_mtime, reverse=True)
