import asyncio
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("llm-forwarder")

DEFAULT_DB_PATH = Path(os.path.expanduser("~/.local/share/brain-llm/local_buffer.db"))
DEFAULT_INGEST_URL = os.environ.get("INGEST_URL", "http://localhost:8080/api/v1/ingest?async_embed=true")

# Exponential backoff so a persistently-failing item doesn't hammer a dead
# endpoint every poll cycle forever, but never gives up either - it just gets
# more patient. retry_count=1 -> 15s, 2 -> 30s, 3 -> 60s, ... capped at 10min.
BACKOFF_BASE_SECONDS = 15
BACKOFF_MAX_SECONDS = 600


def _next_retry_delay(retry_count: int) -> float:
    if retry_count <= 0:
        return 0.0
    return min(BACKOFF_BASE_SECONDS * (2 ** (retry_count - 1)), BACKOFF_MAX_SECONDS)


class SQLiteWALBuffer:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    session_data TEXT NOT NULL,
                    file_path TEXT,
                    file_offset INTEGER DEFAULT 0,
                    synced INTEGER DEFAULT 0,
                    retry_count INTEGER DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    synced_at TEXT,
                    last_attempt_at TEXT,
                    UNIQUE(platform, external_id)
                );
            """)
            conn.commit()
            # Older buffer DBs predate last_attempt_at - add it if missing.
            cols = [r[1] for r in conn.execute("PRAGMA table_info(pending_sessions);").fetchall()]
            if "last_attempt_at" not in cols:
                conn.execute("ALTER TABLE pending_sessions ADD COLUMN last_attempt_at TEXT;")
                conn.commit()
            if "file_mtime" not in cols:
                conn.execute("ALTER TABLE pending_sessions ADD COLUMN file_mtime REAL;")
                conn.commit()

    def get_known_files(self) -> Dict[str, tuple]:
        """Returns map of {file_path: (file_mtime, file_offset)} for files in buffer."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("""
                SELECT file_path, file_mtime, file_offset
                FROM pending_sessions
                WHERE file_path IS NOT NULL;
            """).fetchall()
            return {r[0]: (r[1], r[2]) for r in rows if r[0]}

    def buffer_session(
        self,
        platform: str,
        external_id: str,
        session_data: dict,
        file_path: Optional[str] = None,
        file_offset: int = 0,
        file_mtime: Optional[float] = None
    ):
        """Insert or update a session in the local WAL buffer.
        
        If the session already exists and its session_data is unchanged, its synced
        status is preserved (does NOT reset to 0). It only resets synced to 0 when
        the content has actually changed, avoiding redundant re-embeddings across daemon restarts.
        """
        payload_json = json.dumps(session_data, ensure_ascii=False, sort_keys=True)
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO pending_sessions (platform, external_id, session_data, file_path, file_offset, file_mtime, synced, retry_count)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                ON CONFLICT(platform, external_id) DO UPDATE SET
                    session_data = excluded.session_data,
                    file_path = excluded.file_path,
                    file_offset = excluded.file_offset,
                    file_mtime = excluded.file_mtime,
                    synced = CASE
                        WHEN pending_sessions.session_data = excluded.session_data THEN pending_sessions.synced
                        ELSE 0
                    END,
                    retry_count = CASE
                        WHEN pending_sessions.session_data = excluded.session_data THEN pending_sessions.retry_count
                        ELSE 0
                    END;
            """, (platform, external_id, payload_json, file_path, file_offset, file_mtime))
            conn.commit()

    def get_pending(self, limit: int = 20, ignore_backoff: bool = False) -> List[dict]:
        # Backoff is computed in Python (not SQL) so the delay formula lives
        # in one place - see _next_retry_delay.
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            rows = cursor.execute("""
                SELECT id, platform, external_id, session_data, file_path, retry_count, last_attempt_at
                FROM pending_sessions
                WHERE synced = 0
                ORDER BY id ASC
                LIMIT ?;
            """, (limit * 4,)).fetchall()

        now = datetime.now()
        due: List[dict] = []
        for r in rows:
            d = dict(r)
            if not ignore_backoff:
                delay = _next_retry_delay(d["retry_count"])
                if delay and d["last_attempt_at"]:
                    try:
                        last = datetime.strptime(d["last_attempt_at"], "%Y-%m-%d %H:%M:%S")
                        if now - last < timedelta(seconds=delay):
                            continue  # still backing off
                    except ValueError:
                        pass
            due.append(d)
            if len(due) >= limit:
                break
        return due

    def mark_synced(self, session_id: int):
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE pending_sessions
                SET synced = 1, synced_at = datetime('now', 'localtime'), last_error = NULL
                WHERE id = ?;
            """, (session_id,))
            conn.commit()

    def mark_failed(self, session_id: int, error_msg: str):
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE pending_sessions
                SET retry_count = retry_count + 1, last_error = ?, last_attempt_at = datetime('now', 'localtime')
                WHERE id = ?;
            """, (error_msg, session_id))
            conn.commit()


class HTTPForwarder:
    def __init__(self, buffer: SQLiteWALBuffer, ingest_url: str = DEFAULT_INGEST_URL, poll_interval: int = 10):
        self.buffer = buffer
        if "async_embed" not in ingest_url:
            separator = "&" if "?" in ingest_url else "?"
            ingest_url = f"{ingest_url}{separator}async_embed=true"
        self.ingest_url = ingest_url
        self.poll_interval = poll_interval

    async def forward_once(self) -> int:
        pending = self.buffer.get_pending(limit=20)
        if not pending:
            return 0

        synced_count = 0
        # Large conversations (deep tool-output chunks) take well over the
        # old 15s timeout to embed server-side; give ingest room to finish
        # instead of retrying forever and never syncing.
        async with httpx.AsyncClient(timeout=180.0) as client:
            for item in pending:
                payload = json.loads(item["session_data"])
                try:
                    resp = await client.post(self.ingest_url, json=payload)
                    if resp.status_code == 200:
                        self.buffer.mark_synced(item["id"])
                        synced_count += 1
                        logger.info(f"Successfully synced session {item['platform']}:{item['external_id']}")
                    else:
                        error_text = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        self.buffer.mark_failed(item["id"], error_text)
                        logger.warning(f"Failed to sync {item['external_id']}: {error_text}")
                except Exception as e:
                    error_text = repr(e) or e.__class__.__name__
                    self.buffer.mark_failed(item["id"], error_text)
                    logger.warning(f"Network error forwarding {item['external_id']}: {error_text}")

        return synced_count

    async def run_loop(self):
        logger.info(f"HTTPForwarder started. Ingest URL: {self.ingest_url}")
        while True:
            try:
                await self.forward_once()
            except Exception as e:
                logger.error(f"Error in forwarder loop: {e}", exc_info=True)
            await asyncio.sleep(self.poll_interval)


if __name__ == "__main__":
    buf = SQLiteWALBuffer()
    fwd = HTTPForwarder(buf)
    asyncio.run(fwd.run_loop())
