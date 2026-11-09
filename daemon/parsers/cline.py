import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models import NormalizedConversation
from src.normalizers.cline import ClineNormalizer

logger = logging.getLogger("daemon.parser.cline")


class ClineParser:
    """Parser for local Cline task sessions in VS Code globalStorage."""

    def __init__(self):
        self.normalizer = ClineNormalizer()

    def parse_file(self, file_path: Path, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        return self.normalizer.parse(file_path, metadata=metadata)

    def scan_tasks(self, cline_home: Path) -> List[Path]:
        """Finds all task files (*.messages.json or ui_messages.json) in Cline directories."""
        if not cline_home.is_dir():
            return []

        task_files = []
        # 1. Modern SDK sessions in sessions/
        sessions_dir = cline_home / "sessions" if (cline_home / "sessions").is_dir() else (cline_home / "data" / "sessions" if (cline_home / "data" / "sessions").is_dir() else None)
        if sessions_dir and sessions_dir.is_dir():
            for sdir in sessions_dir.iterdir():
                if not sdir.is_dir():
                    continue
                for mf in sdir.glob("*.messages.json"):
                    if mf.is_file() and mf.stat().st_size > 0:
                        task_files.append(mf)

        # 2. Legacy tasks in tasks/
        tasks_dir = cline_home / "tasks" if (cline_home / "tasks").is_dir() else (cline_home if cline_home.name == "tasks" else None)
        if tasks_dir and tasks_dir.is_dir():
            for task_subdir in tasks_dir.iterdir():
                if not task_subdir.is_dir():
                    continue
                ui_msg = task_subdir / "ui_messages.json"
                api_hist = task_subdir / "api_conversation_history.json"
                target = ui_msg if (ui_msg.is_file() and ui_msg.stat().st_size > 0) else api_hist
                if target.is_file() and target.stat().st_size > 0:
                    task_files.append(target)

        return sorted(task_files, key=lambda f: f.stat().st_mtime, reverse=True)
