import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from src.service.auto_titler import sample_user_messages, slugify_title, AutoTitler


def test_slugify_title():
    assert slugify_title("Naprawa miniatur video MKV w Finderze") == "naprawa-miniatur-video-mkv-w-finderze"
    assert slugify_title("Zadania ClickUp: statusy & dokumentacja!") == "zadania-clickup-statusy-dokumentacja"
    assert slugify_title("   --- Test ---   ") == "test"
    assert slugify_title("") == "conversation"


def test_sample_user_messages_short():
    msgs = ["Pierwsza wiadomość", "Druga wiadomość", "Trzecia wiadomość"]
    samples = sample_user_messages(msgs, max_samples=10, max_chars_per_msg=200)
    assert len(samples) == 3
    assert "[Krok 1/3]: Pierwsza wiadomość" in samples[0]


def test_sample_user_messages_long_spanning():
    # 50 messages: should take head, middle, tail
    msgs = [f"Wiadomość krok {i}" for i in range(50)]
    samples = sample_user_messages(msgs, max_samples=12, max_chars_per_msg=200)
    assert len(samples) == 12
    # Verify first and last are included
    assert "[Krok 1/50]" in samples[0]
    assert "[Krok 2/50]" in samples[1]
    assert "[Krok 3/50]" in samples[2]
    assert "[Krok 50/50]" in samples[-1]


def test_sample_user_messages_truncation():
    giant_msg = "A" * 2000
    samples = sample_user_messages([giant_msg], max_samples=5, max_chars_per_msg=300)
    assert len(samples) == 1
    assert len(samples[0]) < 350
    assert "[przycięto]" in samples[0]


@pytest.mark.asyncio
async def test_auto_titler_generate_title_mocked():
    mock_db = MagicMock()
    mock_db.pool = MagicMock()

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"content": "Mam problem z synchronizacją bazy na serwerze"},
        {"content": "Popraw konfigurację Caddy i Tailscale"}
    ]

    mock_db.pool.acquire.return_value.__aenter__.return_value = mock_conn

    titler = AutoTitler(db=mock_db)

    with patch.object(titler, "_query_ollama", new_callable=AsyncMock) as mock_ollama:
        mock_ollama.return_value = "Konfiguracja Caddy i Tailscale"
        title = await titler.generate_title(conv_id=uuid4(), project_path="/home/user/project")
        assert title == "Konfiguracja Caddy i Tailscale"


@pytest.mark.asyncio
async def test_auto_titler_retitle_batch():
    mock_db = MagicMock()
    mock_db.pool = MagicMock()

    mock_conn = AsyncMock()
    fake_conv = {
        "id": uuid4(),
        "platform": "claude_code",
        "external_id": "test-uuid-1234",
        "title": "kurwa",
        "project_path": "/home/user/project",
        "started_at": datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)
    }
    mock_conn.fetch.return_value = [fake_conv]
    mock_conn.fetchrow.return_value = None  # no existing doc row for simplicity
    mock_conn.execute.return_value = "UPDATE 1"

    mock_db.pool.acquire.return_value.__aenter__.return_value = mock_conn

    titler = AutoTitler(db=mock_db)
    with patch.object(titler, "generate_title", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "Odzyskanie kontekstu sesji Claude"
        count = await titler.retitle_batch(batch_size=5, force=True)
        assert count == 1
