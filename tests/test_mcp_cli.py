import pytest
from unittest.mock import AsyncMock, patch
from typer.testing import CliRunner
from src.service.mcp_server import BrainArchiveMCPServer
from src.cli.main import app
from src.models import SearchResult
from datetime import datetime

runner = CliRunner()

@pytest.mark.asyncio
async def test_mcp_server_lifecycle():
    server = BrainArchiveMCPServer()
    
    # 1. Initialize
    init_res = await server.handle_request({"id": 1, "method": "initialize", "params": {}})
    assert init_res["result"]["serverInfo"]["name"] == "brain-llm-archive"
    
    # 2. Ping
    ping_res = await server.handle_request({"id": 2, "method": "ping", "params": {}})
    assert ping_res["result"] == {}
    
    # 3. Tools list
    tools_res = await server.handle_request({"id": 3, "method": "tools/list", "params": {}})
    tool_names = [t["name"] for t in tools_res["result"]["tools"]]
    assert "search_llm_history" in tool_names
    assert "get_llm_conversation" in tool_names


@pytest.mark.asyncio
async def test_mcp_server_search_tool():
    server = BrainArchiveMCPServer()
    server.db = AsyncMock()
    server.embedder = AsyncMock()
    server.embedder.embed_texts.return_value = [[0.1] * 1024]
    
    fake_result = SearchResult(
        conversation_id="conv-123",
        title="Test Conversation",
        platform="antigravity",
        started_at=datetime(2026, 9, 21, 12, 0),
        relative_path="antigravity/conv-123.md",
        header_path="## Implementation",
        chunk_text="This is an indexed chunk about PostgreSQL pgvector.",
        score=0.95
    )
    server.db.hybrid_search.return_value = [fake_result]
    
    req = {
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "search_llm_history",
            "arguments": {
                "query": "pgvector",
                "platform": "antigravity",
                "limit": 3
            }
        }
    }
    
    res = await server.handle_request(req)
    assert "result" in res
    content = res["result"]["content"][0]["text"]
    assert "Test Conversation" in content
    assert "ANTIGRAVITY" in content
    assert "PostgreSQL pgvector" in content


@pytest.mark.asyncio
async def test_mcp_server_get_conversation_tool():
    server = BrainArchiveMCPServer()
    server.db = AsyncMock()
    server.db.get_conversation_full.return_value = {
        "id": "conv-123",
        "title": "Test Title",
        "platform": "claude_code",
        "content_markdown": "# Test Title\n\nFull conversation content here."
    }
    
    req = {
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "get_llm_conversation",
            "arguments": {
                "conversation_id": "conv-123"
            }
        }
    }
    
    res = await server.handle_request(req)
    assert "result" in res
    content = res["result"]["content"][0]["text"]
    assert "# Test Title" in content
    assert "Full conversation content here." in content


@pytest.mark.asyncio
async def test_mcp_server_get_stats_tool():
    server = BrainArchiveMCPServer()
    server.db = AsyncMock()
    server.db.get_stats.return_value = [
        {
            "platform": "antigravity",
            "conversations": 33,
            "messages": 23351,
            "chunks": 34626,
            "last_sync": datetime(2026, 9, 23, 19, 13)
        }
    ]

    req = {
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "get_llm_stats",
            "arguments": {}
        }
    }

    res = await server.handle_request(req)
    assert "result" in res
    content = res["result"]["content"][0]["text"]
    assert "antigravity" in content
    assert "23,351" in content
    assert "34,626" in content


@pytest.mark.asyncio
async def test_mcp_server_search_with_after():
    server = BrainArchiveMCPServer()
    server.db = AsyncMock()
    server.embedder = AsyncMock()
    server.embedder.embed_texts.return_value = [[0.1] * 1024]
    server.db.hybrid_search.return_value = []

    req = {
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "search_llm_history",
            "arguments": {
                "query": "caddy",
                "after": "2026-09-01",
                "platform": ["antigravity", "claude_code"],
                "limit": 5
            }
        }
    }

    res = await server.handle_request(req)
    assert "result" in res
    # Verify search was called with parsed filters
    call_args = server.db.hybrid_search.call_args[0]
    search_query = call_args[0]
    assert search_query.query == "caddy"
    assert search_query.filters.after == "2026-09-01"
    assert search_query.filters.platform == ["antigravity", "claude_code"]



def test_cli_scan():
    result = runner.invoke(app, ["scan"])
    assert result.exit_code == 0
    assert "Odnalezione Lokalne Sesje Agentów" in result.stdout


def test_cli_help():
    for cmd in ["reindex", "export", "stats", "mcp", "search"]:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0
        assert "Usage" in result.stdout or "Pomoc" in result.stdout or "brain-llm" in result.stdout


def test_cli_search_json_and_markdown():
    fake_result = SearchResult(
        conversation_id="conv-456",
        title="Hyprland Config Fix",
        platform="antigravity",
        started_at=datetime(2026, 9, 21, 14, 0),
        relative_path="antigravity/conv-456.md",
        header_path="## Hyprland Config",
        chunk_text="Fixing thumbnail rendering issue",
        score=0.98
    )

    with patch("src.cli.main.Database") as MockDb, \
         patch("src.cli.main.Embedder") as MockEmb:
        db_instance = AsyncMock()
        db_instance.hybrid_search.return_value = [fake_result]
        MockDb.return_value = db_instance

        emb_instance = AsyncMock()
        emb_instance.embed_texts.return_value = [[0.1] * 1024]
        MockEmb.return_value = emb_instance

        # Test search with JSON format and --after
        res_json = runner.invoke(app, [
            "search", "Hyprland",
            "--platform", "antigravity",
            "--after", "2026-09-01",
            "--format", "json"
        ])
        assert res_json.exit_code == 0
        assert "Hyprland Config Fix" in res_json.stdout
        assert '"platform": "antigravity"' in res_json.stdout

        # Test search with Markdown format
        res_md = runner.invoke(app, [
            "search", "Hyprland",
            "--format", "markdown"
        ])
        assert res_md.exit_code == 0
        assert "## 1. Hyprland Config Fix" in res_md.stdout
        assert "Fixing thumbnail rendering issue" in res_md.stdout


def test_cli_export_jsonl_and_md(tmp_path):
    fake_conv = {
        "id": "conv-789",
        "title": "Rust Zero Copy",
        "platform": "claude_code",
        "started_at": "2026-09-01T10:00:00Z",
        "content_markdown": "# Rust Zero Copy\n\nOptimizing memory in Rust."
    }

    with patch("src.cli.main.Database") as MockDb:
        db_instance = AsyncMock()
        db_instance.list_conversations.return_value = [{"id": "conv-789"}]
        db_instance.get_conversation_full.return_value = fake_conv
        MockDb.return_value = db_instance

        # Test export JSONL to stdout
        res_jsonl = runner.invoke(app, [
            "export",
            "--format", "jsonl",
            "--platform", "claude_code",
            "--after", "2026-09-01"
        ])
        assert res_jsonl.exit_code == 0
        assert "Rust Zero Copy" in res_jsonl.stdout
        assert '"platform": "claude_code"' in res_jsonl.stdout

        # Test export Markdown to directory
        out_dir = tmp_path / "export_out"
        res_md = runner.invoke(app, [
            "export",
            "--format", "md",
            "--output", str(out_dir) + "/"
        ])
        assert res_md.exit_code == 0
        exported_file = out_dir / "claude_code" / "conv-789.md"
        assert exported_file.exists()
        assert "Optimizing memory in Rust" in exported_file.read_text()


def test_cli_stats():
    fake_stats = [
        {
            "platform": "chatgpt",
            "conversations": 1234,
            "messages": 45678,
            "chunks": 123456,
            "last_sync": datetime(2026, 9, 23, 20, 0)
        }
    ]

    with patch("src.cli.main.Database") as MockDb:
        db_instance = AsyncMock()
        db_instance.get_stats.return_value = fake_stats
        MockDb.return_value = db_instance

        res = runner.invoke(app, ["stats"])
        assert res.exit_code == 0
        assert "chatgpt" in res.stdout
        assert "1,234" in res.stdout
        assert "Statystyki Brain LLM Archive" in res.stdout

