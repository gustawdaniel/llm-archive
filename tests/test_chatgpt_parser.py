import pytest
from src.normalizers.chatgpt import ChatGPTNormalizer


def test_chatgpt_mapping_normalizer():
    normalizer = ChatGPTNormalizer()
    raw_chatgpt_conv = {
        "id": "chatgpt-guid-1234",
        "title": "Konfiguracja PostgreSQL HNSW",
        "create_time": 1711000000.0,
        "update_time": 1711000500.0,
        "mapping": {
            "node_1": {
                "id": "node_1",
                "parent": None,
                "message": {
                    "id": "msg_1",
                    "author": {"role": "user"},
                    "create_time": 1711000010.0,
                    "content": {"parts": ["Jak stworzyć indeks HNSW w pgvector?"]},
                    "metadata": {}
                }
            },
            "node_2": {
                "id": "node_2",
                "parent": "node_1",
                "message": {
                    "id": "msg_2",
                    "author": {"role": "assistant"},
                    "create_time": 1711000020.0,
                    "content": {"parts": ["Użyj polecenia: CREATE INDEX ON items USING hnsw (embedding vector_cosine_ops);"]},
                    "metadata": {"model_slug": "gpt-4o"}
                }
            }
        }
    }

    conv = normalizer.parse(raw_chatgpt_conv)

    assert conv.platform == "chatgpt"
    assert conv.external_id == "chatgpt-guid-1234"
    assert conv.title == "Konfiguracja PostgreSQL HNSW"
    assert conv.model == "gpt-4o"
    assert len(conv.messages) == 2
    assert conv.messages[0].role == "user"
    assert "pgvector" in conv.messages[0].content
    assert conv.messages[1].role == "assistant"
    assert "CREATE INDEX" in conv.messages[1].content
