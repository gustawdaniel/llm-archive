import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import httpx

from ..config import settings
from ..normalizers import AntigravityNormalizer, ClaudeCodeNormalizer, CodexNormalizer, MarkdownGenerator
from ..chunker import SemanticChunker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("llm-daemon")


class LocalAgentWatcher:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        api_url: str = f"http://localhost:{settings.API_PORT}/api/v1/ingest",
        poll_interval: int = 5
    ):
        self.db_path = db_path or settings.OFFLINE_DB_PATH
        self.api_url = api_url
        self.poll_interval = poll_interval
        self._init_sqlite()

        self.antigravity_norm = AntigravityNormalizer()
        self.claude_norm = ClaudeCodeNormalizer()

    def _init_sqlite(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS watched_files (
                    filepath TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL,
                    synced INTEGER DEFAULT 0,
                    last_attempt TEXT
                );
            """)
            conn.commit()

    def scan_local_files(self) -> List[Path]:
        """Discover all transcript files from Claude Code, Antigravity and Codex."""
        discovered = []

        # 1. Claude Code
        claude_projects = settings.CLAUDE_HOME / "projects"
        if claude_projects.is_dir():
            for p in claude_projects.glob("*/*.jsonl"):
                if p.is_file() and p.stat().st_size > 0:
                    discovered.append(p)

        # 2. Antigravity
        agy_brain = settings.ANTIGRAVITY_HOME / "brain"
        if agy_brain.is_dir():
            # Watch transcript.jsonl files
            for p in agy_brain.glob("*/.system_generated/logs/transcript.jsonl"):
                if p.is_file() and p.stat().st_size > 0:
                    discovered.append(p)

        # 3. Codex
        codex_sessions = settings.CODEX_HOME / "sessions"
        if codex_sessions.is_dir():
            for p in codex_sessions.glob("*/*/*/rollout-*.jsonl"):
                if p.is_file() and p.stat().st_size > 0:
                    discovered.append(p)

        return discovered

    def get_pending_files(self) -> List[Path]:
        all_files = self.scan_local_files()
        pending = []

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for f in all_files:
                stat = f.stat()
                row = cursor.execute(
                    "SELECT mtime, size, synced FROM watched_files WHERE filepath = ?",
                    (str(f),)
                ).fetchone()

                if not row or row[0] < stat.st_mtime or row[1] < stat.st_size or row[2] == 0:
                    pending.append(f)

        return pending

    async def process_file(self, file_path: Path) -> bool:
        stat = file_path.stat()
        is_antigravity = "antigravity-ide" in str(file_path)
        is_codex = file_path.name.startswith("rollout-")
        platform = "antigravity" if is_antigravity else "codex" if is_codex else "claude_code"

        logger.info(f"Ingesting {platform} file: {file_path}")

        try:
            # 1. Parse locally
            if is_antigravity:
                conv = self.antigravity_norm.parse(file_path)
            elif is_codex:
                conv = CodexNormalizer().parse(file_path)
            else:
                conv = self.claude_norm.parse(file_path)

            # 2. Always write Markdown locally immediately (guarantees offline Obsidian sync)
            md_content, rel_path = MarkdownGenerator.generate(conv)
            md_file = settings.MARKDOWN_EXPORT_DIR / rel_path
            md_file.parent.mkdir(parents=True, exist_ok=True)
            md_file.write_text(md_content, encoding="utf-8")
            logger.info(f"Wrote markdown to: {md_file}")

            # 3. Post to central API over Tailscale/localhost
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.api_url,
                    json={
                        "platform": platform,
                        "payload": [m.model_dump(mode="json") for m in conv.messages],
                        "metadata": {
                            "conversation_id": conv.external_id,
                            "project_path": conv.project_path,
                            "device": settings.DEVICE_NAME
                        }
                    }
                )
                if resp.status_code == 200:
                    self._update_status(file_path, platform, stat.st_mtime, stat.st_size, synced=1)
                    return True
                else:
                    logger.warning(f"API returned status {resp.status_code} for {file_path.name}")
                    self._update_status(file_path, platform, stat.st_mtime, stat.st_size, synced=0)
                    return False

        except Exception as e:
            logger.warning(f"Failed to post {file_path.name} to API ({e}). Saved locally to Markdown.")
            self._update_status(file_path, platform, stat.st_mtime, stat.st_size, synced=0)
            return False

    def _update_status(self, file_path: Path, platform: str, mtime: float, size: int, synced: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO watched_files (filepath, platform, mtime, size, synced, last_attempt)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(filepath) DO UPDATE SET
                    mtime = excluded.mtime,
                    size = excluded.size,
                    synced = excluded.synced,
                    last_attempt = excluded.last_attempt;
                """,
                (str(file_path), platform, mtime, size, synced, datetime.now(timezone.utc).isoformat())
            )
            conn.commit()

    async def run_loop(self):
        logger.info(f"LocalAgentWatcher started. Watching Claude Code and Antigravity logs...")
        while True:
            try:
                pending = self.get_pending_files()
                if pending:
                    logger.info(f"Found {len(pending)} files pending sync.")
                    for f in pending:
                        await self.process_file(f)
            except Exception as e:
                logger.error(f"Error during scan loop: {e}", exc_info=True)

            await asyncio.sleep(self.poll_interval)


if __name__ == "__main__":
    watcher = LocalAgentWatcher()
    asyncio.run(watcher.run_loop())
