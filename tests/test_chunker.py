import pytest
from datetime import datetime, timezone
from src.models import NormalizedConversation, NormalizedMessage
from src.chunker import SemanticChunker


def test_semantic_chunker():
    dt = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    conv = NormalizedConversation(
        platform="claude_code",
        external_id="session-xyz",
        title="Naprawa błędu w Remotion",
        started_at=dt,
        updated_at=dt,
        messages=[
            NormalizedMessage(
                step_index=0,
                role="user",
                content="Jak wyrenderować animację w Remotion?",
                created_at=dt
            ),
            NormalizedMessage(
                step_index=1,
                role="assistant",
                content="Użyj npx remotion render src/index.ts Out.mp4.",
                created_at=dt
            )
        ]
    )

    chunker = SemanticChunker(max_chunk_chars=500)
    chunks = chunker.chunk_conversation(conv)

    assert len(chunks) >= 2
    # Chunk 0: Overview
    assert "Overview" in chunks[0].header_path
    assert "Naprawa błędu w Remotion" in chunks[0].text_content

    # Chunk 1: Grouped user & assistant turn
    assert "Step 0" in chunks[1].header_path
    assert "Jak wyrenderować animację" in chunks[1].text_content
    assert "npx remotion render" in chunks[1].text_content
