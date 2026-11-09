import pytest
from unittest.mock import patch, AsyncMock
from src.embedder import Embedder

@pytest.mark.asyncio
async def test_embedder_prioritizes_first_healthy_worker():
    embedder = Embedder(
        ollama_urls=[
            "http://fake-rog:11435",
            "http://fake-mac:11436",
            "http://fake-brain-db:11434"
        ]
    )

    # When rog is online
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"version": "0.34.0"}
        mock_get.return_value = mock_resp

        active = await embedder.get_active_worker()
        assert active == "http://fake-rog:11435"
        assert embedder.get_worker_name(active) == "rog [RTX 4090 GPU]"

@pytest.mark.asyncio
async def test_embedder_falls_back_to_mac_when_rog_offline():
    embedder = Embedder(
        ollama_urls=[
            "http://fake-rog:11435",
            "http://fake-mac:11436",
            "http://fake-brain-db:11434"
        ]
    )

    async def fake_get(url):
        if "fake-rog" in url:
            raise ConnectionError("Rog is sleeping")
        resp = AsyncMock()
        resp.status_code = 200
        resp.json.return_value = {"version": "0.34.4"}
        return resp

    with patch("httpx.AsyncClient.get", side_effect=fake_get):
        active = await embedder.get_active_worker()
        assert active == "http://fake-mac:11436"
        assert embedder.get_worker_name(active) == "mac [Apple Silicon M1]"

@pytest.mark.asyncio
async def test_embedder_falls_back_to_brain_db_when_both_offline():
    embedder = Embedder(
        ollama_urls=[
            "http://fake-rog:11435",
            "http://fake-mac:11436",
            "http://fake-brain-db:11434"
        ]
    )

    async def fake_get(url):
        if "fake-brain-db" in url:
            resp = AsyncMock()
            resp.status_code = 200
            resp.json.return_value = {"version": "0.34.4"}
            return resp
        raise ConnectionError("Host offline")

    with patch("httpx.AsyncClient.get", side_effect=fake_get):
        active = await embedder.get_active_worker()
        assert active == "http://fake-brain-db:11434"
        assert embedder.get_worker_name(active) == "brain-db [ARM CPU fallback]"
