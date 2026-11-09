import pytest
from datetime import datetime, timezone
from src.models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from src.normalizers.markdown_generator import MarkdownGenerator


def test_markdown_generator():
    dt = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    conv = NormalizedConversation(
        platform="antigravity",
        external_id="conv-abc",
        title="Optymalizacja Bazy Danych",
        model="gemini-2.5-pro",
        project_path="/home/user/project",
        started_at=dt,
        updated_at=dt,
        messages=[
            NormalizedMessage(
                step_index=0,
                role="user",
                content="Jakie indeksy dodać do PostgreSQL?",
                created_at=dt
            ),
            NormalizedMessage(
                step_index=1,
                role="assistant",
                content="Sprawdzę obecne zapytania.",
                tool_calls=[
                    ToolCallRecord(
                        name="run_command",
                        input={"command": "psql -c '\\d'"},
                        output="Table: users\nTable: logs"
                    )
                ],
                created_at=dt
            )
        ]
    )

    md, rel_path = MarkdownGenerator.generate(conv)

    # Verify YAML Frontmatter
    assert md.startswith("---\n")
    assert "platform: antigravity" in md
    assert "title: Optymalizacja Bazy Danych" in md
    assert "model: gemini-2.5-pro" in md
    assert "tags:" in md
    assert "brain" in md

    # Verify Markdown Headers & Details
    assert "# Optymalizacja Bazy Danych" in md
    assert "## 👤 User" in md
    assert "Jakie indeksy dodać do PostgreSQL?" in md
    assert "## 🤖 Assistant" in md
    assert "<details>" in md
    assert "🛠️ <b>Tool Call</b>: <code>run_command</code>" in md
    assert "Table: users" in md
    assert "</details>" in md

    # Verify Relative Path
    assert rel_path.startswith("antigravity/2026-09-21_optymalizacja-bazy-danych_conv-abc.md")


def test_unified_normalizer_service():
    from src.service.normalizer import UnifiedNormalizer

    raw_data = [
        {"uuid": "m1", "sender": "human", "text": "Cześć Claude", "created_at": "2026-09-20T10:00:00Z"},
        {"uuid": "m2", "sender": "assistant", "text": "Cześć! W czym mogę pomóc?", "created_at": "2026-09-20T10:00:05Z"}
    ]
    meta = {"conversation_id": "test-unified-123", "title": "Test Unified Claude"}

    conv, md, path = UnifiedNormalizer.normalize_to_markdown(raw_data, platform="claude_web", metadata=meta)
    assert conv.platform == "claude_web"
    assert conv.external_id == "test-unified-123"
    assert "platform: claude_web" in md
    assert "Cześć Claude" in md
    assert path.startswith("claude_web/")

