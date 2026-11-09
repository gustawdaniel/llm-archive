import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.embedder import Embedder
from src.models import ChunkRecord, NormalizedConversation, NormalizedMessage
from datetime import datetime, timezone
from starlette.testclient import TestClient
from src.service.api import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_embedder_dummy_deterministic():
    embedder = Embedder(provider="dummy", dim=1024)
    v1 = await embedder.embed_texts(["Witaj świecie"])
    v2 = await embedder.embed_texts(["Witaj świecie"])
    v3 = await embedder.embed_texts(["Inny tekst"])

    assert len(v1) == 1
    assert len(v1[0]) == 1024
    assert v1 == v2
    assert v1 != v3


@pytest.mark.asyncio
async def test_embedder_batching():
    embedder = Embedder(provider="dummy", dim=128)
    texts = [f"Text line {i}" for i in range(125)]
    results = await embedder.embed_texts(texts, batch_size=50)

    assert len(results) == 125
    assert len(results[0]) == 128


@pytest.mark.asyncio
async def test_embedder_ollama_mock():
    embedder = Embedder(provider="ollama", ollama_model="bge-m3", dim=1024)
    embedder._ollama_online = True

    fake_embs = [[0.05] * 1024, [0.06] * 1024]
    with patch.object(embedder, "_embed_ollama", new_callable=AsyncMock) as mock_ollama:
        mock_ollama.return_value = fake_embs
        res = await embedder.embed_texts(["Tekst 1", "Tekst 2"])

        assert len(res) == 2
        assert res[0][0] == 0.05
        assert res[1][0] == 0.06
        mock_ollama.assert_called_once()


def test_api_reindex_and_async_ingest():
    fake_conv_payload = {
        "platform": "chatgpt",
        "external_id": "test-chatgpt-embed-1",
        "raw_data": {
            "title": "ChatGPT Embedding Test",
            "mapping": {
                "m1": {
                    "id": "m1",
                    "message": {
                        "id": "m1",
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": ["Test query"]},
                        "create_time": 1726000000.0
                    }
                }
            }
        },
        "metadata": {
            "device": "test-workstation"
        }
    }

    with patch("src.service.api.db.pool", True), \
         patch("src.service.api.db.upsert_conversation", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = "db-conv-uuid-1"

        # Ingest with async_embed=true
        res = client.post("/api/v1/ingest?async_embed=true", json=fake_conv_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["embeddings_status"] == "queued_background"

        # Reindex endpoint with async_mode=true
        res_reindex = client.post("/api/v1/reindex?async_mode=true", json={"platform": "chatgpt"})
        assert res_reindex.status_code == 200
        reindex_data = res_reindex.json()
        assert reindex_data["status"] == "reindexing_started"
        assert reindex_data["mode"] == "background"
