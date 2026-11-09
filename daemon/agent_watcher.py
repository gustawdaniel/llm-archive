import asyncio
from datetime import datetime
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

# Add parent directory to sys.path so daemon can import src packages
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.normalizers import (
    AntigravityNormalizer,
    ClaudeCodeNormalizer,
    ClineNormalizer,
    OpenCodeNormalizer,
    AiderNormalizer,
    OMPNormalizer,
    ZedNormalizer,
    HermesNormalizer,
    CodexNormalizer,
    MarkdownGenerator
)
from src.normalizers.mirror import MirrorNormalizer
from daemon.forwarder import SQLiteWALBuffer, HTTPForwarder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("agent-watcher")


class AgentWatcherDaemon:
    def __init__(
        self,
        buffer_db_path: Optional[Path] = None,
        ingest_url: Optional[str] = None,
        scan_interval: int = 15
    ):
        self.buffer = SQLiteWALBuffer(buffer_db_path)
        self.forwarder = HTTPForwarder(
            self.buffer,
            ingest_url=ingest_url or os.environ.get("INGEST_URL", f"http://localhost:{settings.API_PORT}/api/v1/ingest"),
            poll_interval=10
        )
        self.scan_interval = scan_interval
        # Track timestamp of last parsing per file to debounce rapidly-updating transcripts
        self.last_parsed_time: Dict[str, float] = {}
        self.min_reparse_interval: float = 60.0


        self.antigravity_norm = AntigravityNormalizer()
        self.claude_norm = ClaudeCodeNormalizer()
        self.cline_norm = ClineNormalizer()
        self.opencode_norm = OpenCodeNormalizer()
        self.aider_norm = AiderNormalizer()
        self.omp_norm = OMPNormalizer()
        self.zed_norm = ZedNormalizer()
        self.hermes_norm = HermesNormalizer()
        self.codex_norm = CodexNormalizer()
        self.mirror_norm = MirrorNormalizer()

        # Track (filepath, mtime, size) to avoid redundant re-parsing.
        # Seeded from SQLite buffer so restarts don't re-parse already-synced files.
        self.seen_files: Dict[str, tuple] = self.buffer.get_known_files()

    def discover_files(self) -> List[Path]:
        files = []

        # 1. Claude Code project sessions
        claude_projects = settings.CLAUDE_HOME / "projects"
        if claude_projects.is_dir():
            for p in claude_projects.glob("*/*.jsonl"):
                if p.is_file() and p.stat().st_size > 0:
                    files.append(p)

        # 2. Antigravity transcripts (prefer transcript.jsonl, fallback to transcript_full.jsonl)
        #    Scan every Antigravity flavour (IDE, CLI, ...), not just one home.
        agy_homes = getattr(settings, "ANTIGRAVITY_HOMES", None) or [settings.ANTIGRAVITY_HOME]
        for agy_home in agy_homes:
            agy_brain = agy_home / "brain"
            if not agy_brain.is_dir():
                continue
            for session_dir in agy_brain.iterdir():
                if not session_dir.is_dir():
                    continue
                logs_dir = session_dir / ".system_generated" / "logs"
                if not logs_dir.is_dir():
                    continue
                standard_log = logs_dir / "transcript.jsonl"
                full_log = logs_dir / "transcript_full.jsonl"
                target_log = standard_log if (standard_log.is_file() and standard_log.stat().st_size > 0) else full_log
                if target_log.is_file() and target_log.stat().st_size > 0:
                    files.append(target_log)

        # 3. Cline sessions (modern ~/.cline/data/sessions/ and legacy tasks/)
        cline_sessions_dir = Path.home() / ".cline" / "data" / "sessions"
        if cline_sessions_dir.is_dir():
            for sdir in cline_sessions_dir.iterdir():
                if not sdir.is_dir():
                    continue
                for mf in sdir.glob("*.messages.json"):
                    if mf.is_file() and mf.stat().st_size > 0:
                        files.append(mf)

        cline_homes = getattr(settings, "CLINE_HOMES", []) or [settings.CLINE_HOME]
        for c_home in cline_homes:
            tasks_dir = c_home / "tasks" if (c_home / "tasks").is_dir() else c_home
            if tasks_dir.is_dir() and tasks_dir.name == "tasks":
                for task_dir in tasks_dir.iterdir():
                    if not task_dir.is_dir():
                        continue
                    ui_msg = task_dir / "ui_messages.json"
                    api_hist = task_dir / "api_conversation_history.json"
                    target = ui_msg if (ui_msg.is_file() and ui_msg.stat().st_size > 0) else api_hist
                    if target.is_file() and target.stat().st_size > 0:
                        files.append(target)

        # 4. OpenCode database (~/.local/share/opencode/opencode.db)
        opencode_db = getattr(settings, "OPENCODE_DB", Path.home() / ".local" / "share" / "opencode" / "opencode.db")
        if opencode_db.is_file() and opencode_db.stat().st_size > 0:
            files.append(opencode_db)

        # 5. Aider histories & XDG conversations (~/.local/share/aider/conversations/*)
        aider_conv_dir = Path.home() / ".local" / "share" / "aider" / "conversations"
        if aider_conv_dir.is_dir():
            for cf in aider_conv_dir.glob("*.json"):
                if cf.is_file() and cf.stat().st_size > 0:
                    files.append(cf)
            for cf in aider_conv_dir.glob("*.md"):
                if cf.is_file() and cf.stat().st_size > 0:
                    files.append(cf)

        aider_global = Path.home() / ".aider.chat.history.md"
        if aider_global.is_file() and aider_global.stat().st_size > 0 and aider_global not in files:
            files.append(aider_global)

        # Scan potential aider directories in exp (shallow, max 2 levels - NEVER deep recursive glob across ~/pro or ~/exp)
        exp_dir = Path.home() / "exp"
        if exp_dir.is_dir():
            for af in exp_dir.glob("*/aider/.aider.chat.history.md"):
                if af.is_file() and af.stat().st_size > 0 and af not in files:
                    files.append(af)

        # 6. OMP sessions (~/.omp/agent/sessions/*/*.jsonl)
        omp_sessions_dir = Path.home() / ".omp" / "agent" / "sessions"
        if omp_sessions_dir.is_dir():
            for sdir in omp_sessions_dir.iterdir():
                if not sdir.is_dir():
                    continue
                for jf in sdir.glob("*.jsonl"):
                    if jf.is_file() and jf.stat().st_size > 0:
                        files.append(jf)

        # 7. Zed threads database (~/.local/share/zed/threads/threads.db)
        zed_db = getattr(settings, "ZED_DB", Path.home() / ".local" / "share" / "zed" / "threads" / "threads.db")
        if zed_db.is_file() and zed_db.stat().st_size > 0:
            files.append(zed_db)

        # 8. Hermes state database (~/.hermes/state.db)
        hermes_db = getattr(settings, "HERMES_DB", Path.home() / ".hermes" / "state.db")
        if hermes_db.is_file() and hermes_db.stat().st_size > 0:
            files.append(hermes_db)

        # 8b. Mirror (Beam / Reflection) state database (~/.mirror/state.db)
        mirror_db = getattr(settings, "MIRROR_DB", Path.home() / ".mirror" / "state.db")
        if mirror_db.is_file() and mirror_db.stat().st_size > 0:
            files.append(mirror_db)

        # 9. Codex sessions (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl)
        codex_sessions = settings.CODEX_HOME / "sessions"
        if codex_sessions.is_dir():
            for cf in codex_sessions.glob("*/*/*/rollout-*.jsonl"):
                if cf.is_file() and cf.stat().st_size > 0:
                    files.append(cf)

        return files

    def _buffer_and_export_conv(self, conv, platform: str, file_key: str, mtime: float, size: int):
        if not conv or not conv.messages:
            return

        # 1. Generate local Markdown file immediately (Obsidian sync guarantee)
        md_content, rel_path = MarkdownGenerator.generate(conv)
        target_md_file = settings.MARKDOWN_EXPORT_DIR / rel_path
        target_md_file.parent.mkdir(parents=True, exist_ok=True)
        target_md_file.write_text(md_content, encoding="utf-8")

        # 2. Buffer in SQLite WAL for HTTP forwarding
        ingest_payload = {
            "platform": platform,
            "external_id": conv.external_id,
            "payload": [m.model_dump(mode="json") for m in conv.messages],
            "metadata": {
                "conversation_id": conv.external_id,
                "title": conv.title,
                "project_path": conv.project_path,
                "git_branch": conv.git_branch,
                "device": settings.DEVICE_NAME,
                "model": conv.model,
                **(conv.raw_metadata or {})
            }
        }
        self.buffer.buffer_session(
            platform=platform,
            external_id=conv.external_id,
            session_data=ingest_payload,
            file_path=file_key,
            file_offset=size,
            file_mtime=mtime
        )
        self.seen_files[file_key] = (mtime, size)
        self.last_parsed_time[file_key] = datetime.now().timestamp()
        logger.info(f"Processed and buffered {platform}:{conv.external_id} ({len(conv.messages)} msgs)")

    def process_file_local(self, file_path: Path):
        stat = file_path.stat()
        file_key = str(file_path)
        last_stat = self.seen_files.get(file_key)

        # Special handling for OpenCode SQLite DB: multiple sessions inside one file
        if file_key.endswith("opencode.db"):
            if last_stat and last_stat[0] == stat.st_mtime and last_stat[1] == stat.st_size:
                return
            try:
                conn = sqlite3.connect(str(file_path))
                cur = conn.cursor()
                cur.execute("SELECT id, time_updated FROM session")
                rows = cur.fetchall()
                conn.close()
                for sid, t_up in rows:
                    sub_key = f"{file_key}#{sid}"
                    last_sub = self.seen_files.get(sub_key)
                    if last_sub and last_sub[0] == float(t_up):
                        continue
                    try:
                        conv = self.opencode_norm.parse(file_path, {"session_id": sid})
                        self._buffer_and_export_conv(conv, "opencode", sub_key, float(t_up), 0)
                    except Exception as ex:
                        logger.warning(f"Error parsing OpenCode session {sid}: {ex}")
                self.seen_files[file_key] = (stat.st_mtime, stat.st_size)
            except Exception as e:
                logger.warning(f"Error reading OpenCode database: {e}")
            return

        # Special handling for Zed threads DB: multiple threads inside threads.db
        if file_key.endswith("threads.db") and "zed" in file_key:
            if last_stat and last_stat[0] == stat.st_mtime and last_stat[1] == stat.st_size:
                return
            try:
                conn = sqlite3.connect(f"file:{file_path}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute("SELECT id, updated_at FROM threads")
                rows = cur.fetchall()
                conn.close()
                for tid, updated_at_str in rows:
                    sub_key = f"{file_key}#{tid}"
                    last_sub = self.seen_files.get(sub_key)
                    # Convert to epoch timestamp float
                    t_val = 0.0
                    if updated_at_str:
                        try:
                            clean_ts = updated_at_str.replace("Z", "+00:00")
                            if "." in clean_ts:
                                p = clean_ts.split(".")
                                sub = p[1].split("+")
                                frac = sub[0][:6]
                                tz = ("+" + sub[1]) if len(sub) > 1 else ""
                                clean_ts = f"{p[0]}.{frac}{tz}"
                            t_val = datetime.fromisoformat(clean_ts).timestamp()
                        except Exception:
                            t_val = stat.st_mtime

                    if last_sub and last_sub[0] == t_val:
                        continue
                    try:
                        conv = self.zed_norm.parse(file_path, {"thread_id": tid})
                        self._buffer_and_export_conv(conv, "zed", sub_key, t_val, 0)
                    except Exception as ex:
                        logger.warning(f"Error parsing Zed thread {tid}: {ex}")
                self.seen_files[file_key] = (stat.st_mtime, stat.st_size)
            except Exception as e:
                logger.warning(f"Error reading Zed database: {e}")
            return

        # Special handling for Hermes state DB: multiple sessions inside state.db
        if file_key.endswith("state.db") and ".hermes" in file_key:
            if last_stat and last_stat[0] == stat.st_mtime and last_stat[1] == stat.st_size:
                return
            try:
                conn = sqlite3.connect(f"file:{file_path}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute("SELECT id, started_at, COALESCE(ended_at, started_at) FROM sessions")
                rows = cur.fetchall()
                conn.close()
                for sid, t_start, t_end in rows:
                    sub_key = f"{file_key}#{sid}"
                    last_sub = self.seen_files.get(sub_key)
                    t_val = float(t_end or t_start or 0.0)
                    if last_sub and last_sub[0] == t_val:
                        continue
                    try:
                        conv = self.hermes_norm.parse(file_path, {"session_id": sid})
                        self._buffer_and_export_conv(conv, "hermes", sub_key, t_val, 0)
                    except Exception as ex:
                        logger.warning(f"Error parsing Hermes session {sid}: {ex}")
                self.seen_files[file_key] = (stat.st_mtime, stat.st_size)
            except Exception as e:
                logger.warning(f"Error reading Hermes database: {e}")
            return

        # Special handling for Mirror (Beam/Reflection) state DB: multiple
        # sessions in react_session, each with protobuf turns in react_entry.
        if file_key.endswith("state.db") and ".mirror" in file_key:
            if last_stat and last_stat[0] == stat.st_mtime and last_stat[1] == stat.st_size:
                return
            try:
                conn = sqlite3.connect(f"file:{file_path}?mode=ro", uri=True)
                cur = conn.cursor()
                # max(entry id) per session is a monotonic "grew since last seen"
                # signal, since react_session itself carries no timestamp.
                cur.execute("SELECT session_id, MAX(id) FROM react_entry GROUP BY session_id")
                rows = cur.fetchall()
                conn.close()
                for sid, max_entry_id in rows:
                    sub_key = f"{file_key}#{sid}"
                    last_sub = self.seen_files.get(sub_key)
                    t_val = float(max_entry_id or 0)
                    if last_sub and last_sub[0] == t_val:
                        continue
                    try:
                        conv = self.mirror_norm.parse(file_path, {"session_id": sid})
                        if conv.messages:
                            self._buffer_and_export_conv(conv, "mirror", sub_key, t_val, 0)
                    except Exception as ex:
                        logger.warning(f"Error parsing Mirror session {sid}: {ex}")
                self.seen_files[file_key] = (stat.st_mtime, stat.st_size)
            except Exception as e:
                logger.warning(f"Error reading Mirror database: {e}")
            return

        if last_stat and last_stat[0] == stat.st_mtime and last_stat[1] == stat.st_size:
            return  # No changes

        # Debounce rapidly updating files (e.g. streaming LLM logs / tool calls)
        now = datetime.now().timestamp()
        last_parsed = self.last_parsed_time.get(file_key, 0.0)
        if last_stat and (now - last_parsed) < self.min_reparse_interval and stat.st_size != last_stat[1]:
            return  # Settle period: wait until min_reparse_interval has elapsed or size stabilizes

        is_cline = "saoudrizwan.claude-dev" in file_key or "cline" in file_key.lower()
        is_antigravity = "antigravity" in file_key and ".system_generated" in file_key
        is_aider = ".aider.chat.history.md" in file_key or "/aider/conversations/" in file_key or "/.local/share/aider/" in file_key
        is_omp = ".omp/agent/sessions" in file_key or "/.omp/" in file_key
        is_codex = file_path.name.startswith("rollout-") and "/sessions/" in file_key

        if is_cline:
            platform = "cline"
        elif is_antigravity:
            platform = "antigravity"
        elif is_aider:
            platform = "aider"
        elif is_omp:
            platform = "omp"
        elif is_codex:
            platform = "codex"
        else:
            platform = "claude_code"

        if is_aider:
            if file_path.suffix == ".json":
                try:
                    conv = self.aider_norm.parse(file_path)
                    self._buffer_and_export_conv(conv, "aider", file_key, stat.st_mtime, stat.st_size)
                    self.seen_files[file_key] = (stat.st_mtime, stat.st_size)
                except Exception as ex:
                    logger.warning(f"Error parsing Aider JSON session {file_key}: {ex}")
                return

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                sessions = [s for s in content.split("# aider chat started at ") if s.strip() and "####" in s]
                for s in sessions:
                    header_time = s.strip().split("\n")[0].strip()
                    sid = f"aider_{header_time.replace(' ', '_').replace(':', '')}"
                    sub_key = f"{file_key}#{sid}"
                    last_sub = self.seen_files.get(sub_key)
                    if last_sub and last_sub[0] == stat.st_mtime and last_sub[1] == stat.st_size:
                        continue
                    try:
                        session_raw = f"# aider chat started at {s}"
                        conv = self.aider_norm.parse(session_raw, {"session_id": sid, "project_path": str(file_path.parent)})
                        self._buffer_and_export_conv(conv, "aider", sub_key, stat.st_mtime, stat.st_size)
                    except Exception as ex:
                        logger.warning(f"Error parsing Aider session {sid}: {ex}")
                self.seen_files[file_key] = (stat.st_mtime, stat.st_size)
            except Exception as e:
                logger.warning(f"Error reading Aider history {file_path}: {e}")
            return

        try:
            if is_cline:
                conv = self.cline_norm.parse(file_path)
            elif is_antigravity:
                conv = self.antigravity_norm.parse(file_path)
            elif is_omp:
                conv = self.omp_norm.parse(file_path)
            elif is_codex:
                conv = self.codex_norm.parse(file_path)
            else:
                conv = self.claude_norm.parse(file_path)

            self._buffer_and_export_conv(conv, platform, file_key, stat.st_mtime, stat.st_size)

        except Exception as e:
            logger.warning(f"Error processing {file_path.name}: {e}")

    async def run(self):
        logger.info("AgentWatcherDaemon started.")
        # Start forwarder in background
        forwarder_task = asyncio.create_task(self.forwarder.run_loop())

        try:
            while True:
                files = self.discover_files()
                for f in files:
                    self.process_file_local(f)
                await asyncio.sleep(self.scan_interval)
        finally:
            forwarder_task.cancel()


if __name__ == "__main__":
    daemon = AgentWatcherDaemon()
    asyncio.run(daemon.run())
