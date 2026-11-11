import asyncio
import tempfile
from pathlib import Path
import pytest
from daemon.forwarder import SQLiteWALBuffer, HTTPForwarder


def test_sqlite_wal_buffer():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_buffer.db"
        buffer = SQLiteWALBuffer(db_path)

        # 1. Buffer session
        buffer.buffer_session(
            platform="claude_code",
            external_id="session-xyz-123",
            session_data={"title": "Test Session", "messages": []},
            file_path="/tmp/fake.jsonl",
            file_offset=1024
        )

        # 2. Query pending
        pending = buffer.get_pending()
        assert len(pending) == 1
        assert pending[0]["platform"] == "claude_code"
        assert pending[0]["external_id"] == "session-xyz-123"

        # 3. Mark synced
        buffer.mark_synced(pending[0]["id"])
        pending_after = buffer.get_pending()
        assert len(pending_after) == 0

        # 4. Upserting modified session resets synced to 0
        buffer.buffer_session(
            platform="claude_code",
            external_id="session-xyz-123",
            session_data={"title": "Updated Session", "messages": [{"role": "user"}]},
            file_path="/tmp/fake.jsonl",
            file_offset=2048,
            file_mtime=123456.78
        )
        pending_updated = buffer.get_pending()
        assert len(pending_updated) == 1
        assert "Updated Session" in pending_updated[0]["session_data"]

        # 5. Mark synced again, then re-buffer with IDENTICAL session_data:
        # Synced status must be preserved (0 pending, not reset to 0)
        buffer.mark_synced(pending_updated[0]["id"])
        assert len(buffer.get_pending()) == 0

        buffer.buffer_session(
            platform="claude_code",
            external_id="session-xyz-123",
            session_data={"title": "Updated Session", "messages": [{"role": "user"}]},
            file_path="/tmp/fake.jsonl",
            file_offset=2048,
            file_mtime=123456.78
        )
        assert len(buffer.get_pending()) == 0  # Still 0, preserved!

        # 6. Re-buffer with CHANGED session_data but IDENTICAL file_offset (e.g. SQLite database or in-place edit):
        # Must reset synced to 0!
        buffer.buffer_session(
            platform="claude_code",
            external_id="session-xyz-123",
            session_data={"title": "Updated Session", "messages": [{"role": "user"}, {"role": "assistant"}]},
            file_path="/tmp/fake.jsonl",
            file_offset=2048,
            file_mtime=123456.78
        )
        assert len(buffer.get_pending()) == 1

        # 7. Verify get_known_files maps file_path -> (mtime, offset)
        known = buffer.get_known_files()
        assert "/tmp/fake.jsonl" in known
        assert known["/tmp/fake.jsonl"] == (123456.78, 2048)


@pytest.mark.asyncio
async def test_http_forwarder_offline_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_buffer.db"
        buffer = SQLiteWALBuffer(db_path)
        buffer.buffer_session(
            platform="antigravity",
            external_id="test-offline-session",
            session_data={"platform": "antigravity", "payload": []}
        )

        # Point forwarder to a non-existent port
        fwd = HTTPForwarder(buffer, ingest_url="http://127.0.0.1:59999/api/v1/ingest")
        synced = await fwd.forward_once()
        assert synced == 0

        # Item should still be pending with retry_count incremented
        pending = buffer.get_pending(ignore_backoff=True)
        assert len(pending) == 1
        assert pending[0]["retry_count"] == 1


@pytest.mark.asyncio
async def test_http_forwarder_success():
    from unittest.mock import AsyncMock, patch, MagicMock

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_buffer.db"
        buffer = SQLiteWALBuffer(db_path)
        buffer.buffer_session(
            platform="claude_code",
            external_id="test-success-session",
            session_data={"platform": "claude_code", "raw_data": []}
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            fwd = HTTPForwarder(buffer, ingest_url="http://mock-ingest/api/v1/ingest")
            synced = await fwd.forward_once()
            assert synced == 1

        # Buffer should have 0 pending sessions
        assert len(buffer.get_pending()) == 0



def test_canonical_title_roundtrip():
    """Bufor pamięta tytuł nadany przez AutoTitler, żeby urządzenie nie wymyślało
    własnego sluga w nazwie pliku (to właśnie mnożyło kopie rozmów)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        buffer = SQLiteWALBuffer(Path(tmpdir) / "buf.db")

        assert buffer.get_canonical("conv-1") is None

        buffer.set_canonical("conv-1", "Porządki w ClickUp", "antigravity/2026-11-08_porzadki-w-clickup_abcd1234-mac.md", "sha-1")
        stored = buffer.get_canonical("conv-1")
        assert stored["title"] == "Porządki w ClickUp"
        assert stored["rel_path"].endswith("-mac.md")
        assert stored["content_sha256"] == "sha-1"

        # Nowy tytuł nadpisuje ścieżkę, ale nie gubi hasha poprzedniej treści,
        # dopóki nie zapiszemy nowej (COALESCE).
        buffer.set_canonical("conv-1", "Inny tytuł", "antigravity/2026-11-08_inny-tytul_abcd1234-mac.md")
        stored = buffer.get_canonical("conv-1")
        assert stored["title"] == "Inny tytuł"
        assert stored["content_sha256"] == "sha-1"


def test_forwarder_remembers_canonical_title_from_response():
    import json as _json

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    with tempfile.TemporaryDirectory() as tmpdir:
        buffer = SQLiteWALBuffer(Path(tmpdir) / "buf.db")
        forwarder = HTTPForwarder(buffer, ingest_url="http://example.invalid/api/v1/ingest")

        forwarder._remember_canonical(
            "conv-2",
            FakeResponse({"title": "Migracja CLI", "relative_path": "antigravity/2026-11-08_migracja-cli_abcd1234-apps.md"}),
        )
        stored = buffer.get_canonical("conv-2")
        assert stored["title"] == "Migracja CLI"
        assert stored["rel_path"].endswith("-apps.md")

        # Odpowiedź bez tytułu nie może wyczyścić zapamiętanej wartości.
        forwarder._remember_canonical("conv-2", FakeResponse({"status": "success"}))
        assert buffer.get_canonical("conv-2")["title"] == "Migracja CLI"
