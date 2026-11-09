import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models import NormalizedConversation
from src.normalizers.claude_code import ClaudeCodeNormalizer

logger = logging.getLogger("daemon.parser.claude_code")


class ClaudeCodeParser:
    """Parser for local Claude Code JSONL projects and history."""

    def __init__(self):
        self.normalizer = ClaudeCodeNormalizer()

    def parse_file(self, file_path: Path, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        return self.normalizer.parse(file_path, metadata=metadata)

    def parse_history(self, history_file: Path) -> List[Dict[str, Any]]:
        """Parses ~/.claude/history.jsonl entries."""
        if not history_file.is_file():
            return []
        entries = []
        with open(history_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
        return entries
