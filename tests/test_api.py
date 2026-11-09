import pytest
from starlette.testclient import TestClient
from src.service.api import app

from unittest.mock import AsyncMock, patch

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_db_pool():
    with patch("src.service.api.db.pool", True), \
         patch("src.service.api.db.upsert_conversation", new_callable=AsyncMock, return_value="mock-db-id"):
        yield


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "device" in data


def test_ingest_chatgpt_payload():
    payload = {
        "platform": "chatgpt",
        "external_id": "test-chatgpt-123",
        "raw_data": {
            "id": "test-chatgpt-123",
            "title": "API Test Conversation",
            "create_time": 1774000000.0,
            "update_time": 1774000010.0,
            "mapping": {
                "root": {
                    "id": "root",
                    "parent": None,
                    "children": ["msg-1"]
                },
                "msg-1": {
                    "id": "msg-1",
                    "parent": "root",
                    "children": ["msg-2"],
                    "message": {
                        "id": "msg-1",
                        "author": {"role": "user"},
                        "create_time": 1774000000.0,
                        "content": {"content_type": "text", "parts": ["Hello via API test!"]}
                    }
                },
                "msg-2": {
                    "id": "msg-2",
                    "parent": "msg-1",
                    "children": [],
                    "message": {
                        "id": "msg-2",
                        "author": {"role": "assistant"},
                        "create_time": 1774000005.0,
                        "content": {"content_type": "text", "parts": ["Hello, I received your API request."]}
                    }
                }
            }
        },
        "metadata": {
            "device": "test-workstation"
        }
    }
    response = client.post("/api/v1/ingest", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["platform"] == "chatgpt"
    assert res_data["total_messages"] == 2
    assert "relative_path" in res_data


def test_ingest_claude_code_payload():
    payload = {
        "platform": "claude_code",
        "external_id": "test-claude-code-session",
        "raw_data": [
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": "Fix this bug"}]},
                "uuid": "u-1",
                "timestamp": "2026-09-20T12:00:00Z"
            },
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Bug is fixed."}]},
                "uuid": "u-2",
                "timestamp": "2026-09-20T12:00:05Z"
            }
        ],
        "metadata": {
            "device": "test-workstation",
            "project_path": "/home/user/project"
        }
    }
    response = client.post("/api/v1/ingest", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["platform"] == "claude_code"
    assert res_data["total_messages"] == 2



def test_api_stats_and_conversation_detail():
    from unittest.mock import AsyncMock, patch
    with patch("src.service.api.db.get_stats", new_callable=AsyncMock) as mock_stats, \
         patch("src.service.api.db.get_conversation_full", new_callable=AsyncMock) as mock_conv, \
         patch("src.service.api.db.pool", True):
        
        mock_stats.return_value = {
            "total_conversations": 42,
            "total_messages": 300,
            "total_chunks": 1200,
            "platforms": [{"platform": "chatgpt", "conversations": 42, "messages": 300, "chunks": 1200}]
        }
        mock_conv.return_value = {
            "id": "test-conv-123",
            "title": "Sample Conversation",
            "platform": "chatgpt",
            "content_markdown": "# Sample Conversation\n\nContent..."
        }

        res_stats = client.get("/api/v1/stats")
        assert res_stats.status_code == 200
        assert res_stats.json()["total_conversations"] == 42

        res_conv = client.get("/api/v1/conversations/test-conv-123")
        assert res_conv.status_code == 200
        assert res_conv.json()["title"] == "Sample Conversation"


def test_search_endpoint_with_filters():
    from unittest.mock import AsyncMock, patch
    from datetime import datetime, timezone
    from src.models import SearchResult

    mock_result = SearchResult(
        conversation_id="conv-1",
        platform="claude_code",
        title="Test Search Result",
        project_path="/home/user/project",
        header_path="# Issue Fix",
        chunk_text="Resolved thumbnail bug in Hyprland",
        score=0.032,
        started_at=datetime.now(timezone.utc),
        relative_path="claude_code/test.md"
    )

    with patch("src.service.search.SearchService.search", new_callable=AsyncMock) as mock_search, \
         patch("src.service.api.db.pool", True):
        mock_search.return_value = [mock_result]

        payload = {
            "query": "jak naprawić błąd thumbnails w Hyprlandzie",
            "filters": {
                "platform": ["antigravity", "claude_code"],
                "after": "2026-01-01T00:00:00Z",
                "project_path": "/home/user/project"
            },
            "limit": 20
        }
        res = client.post("/api/v1/search", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["query"] == "jak naprawić błąd thumbnails w Hyprlandzie"
        assert data["count"] == 1
        assert data["results"][0]["conversation_id"] == "conv-1"
        assert data["results"][0]["platform"] == "claude_code"


def test_mcp_http_endpoint():
    # Test initialize via HTTP
    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }
    res = client.post("/mcp", json=init_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["result"]["serverInfo"]["name"] == "brain-llm-archive"

    # Test tools/list via HTTP
    tools_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    res_tools = client.post("/mcp", json=tools_payload)
    assert res_tools.status_code == 200
    tool_names = [t["name"] for t in res_tools.json()["result"]["tools"]]
    assert "search_llm_history" in tool_names
    assert "get_llm_conversation" in tool_names
    assert "get_llm_stats" in tool_names


def test_sync_status_endpoint():
    from unittest.mock import AsyncMock, patch
    with patch("src.service.api.db.get_sync_status", new_callable=AsyncMock) as mock_sync, \
         patch("src.service.api.db.pool", True):
        mock_sync.return_value = {
            "c_123": {
                "id": "uuid-123",
                "title": "Test Chat",
                "updated_at": "2026-09-24T18:00:00Z",
                "message_count": 8
            }
        }
        res = client.get("/api/v1/sync/status?platform=gemini&limit=10")
        assert res.status_code == 200
        data = res.json()
        assert data["platform"] == "gemini"
        assert data["count"] == 1
        assert "c_123" in data["conversations"]
        assert data["conversations"]["c_123"]["message_count"] == 8


def test_conversation_detail_trims_large_tool_outputs():
    screenshot = "[{'type': 'image', 'source': {'data': '" + "A" * 50000 + "'}}]"
    conv = {
        "id": "c1",
        "messages": [{"role": "assistant", "content": "", "tool_calls": [
            {"name": "Read", "output": screenshot},
            {"name": "Bash", "output": "ok"},
        ]}],
    }
    with patch("src.service.api.db.get_conversation_full", new_callable=AsyncMock) as mock_conv:
        mock_conv.side_effect = lambda _id: __import__("copy").deepcopy(conv)

        calls = client.get("/api/v1/conversations/c1").json()["messages"][0]["tool_calls"]
        assert "<base64 48 KB pominięte>" in calls[0]["output"]
        assert len(calls[0]["output"]) < 1000
        assert calls[1]["output"] == "ok"

        full = client.get("/api/v1/conversations/c1?full_tools=true").json()
        assert full["messages"][0]["tool_calls"][0]["output"] == screenshot
