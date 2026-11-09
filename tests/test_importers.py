import json
import tempfile
import zipfile
from pathlib import Path
import pytest
from src.importers import (
    OpenAIArchiveImporter,
    ClaudeArchiveImporter,
    GoogleTakeoutImporter,
    GenericJSONLImporter,
    ArchiveReconciler,
)


def test_openai_importer_zip():
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "chatgpt-export.zip"
        sample_data = [
            {
                "id": "conv-openai-1",
                "title": "OpenAI GDPR Test",
                "create_time": 1774000000.0,
                "update_time": 1774000010.0,
                "mapping": {
                    "root": {"id": "root", "children": ["m-1"]},
                    "m-1": {
                        "id": "m-1",
                        "children": [],
                        "message": {
                            "id": "m-1",
                            "author": {"role": "user"},
                            "create_time": 1774000000.0,
                            "content": {"content_type": "text", "parts": ["Test export question"]}
                        }
                    }
                }
            }
        ]
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("conversations.json", json.dumps(sample_data))

        importer = OpenAIArchiveImporter()
        convs = importer.parse_archive(zip_path)
        assert len(convs) == 1
        assert convs[0].platform == "chatgpt"
        assert convs[0].external_id == "conv-openai-1"
        assert len(convs[0].messages) == 1

        # Test common Importer interface .parse() and .to_common_model()
        convs2 = importer.parse(zip_path)
        assert len(convs2) == 1
        single_conv = importer.to_common_model(sample_data[0])
        assert single_conv.external_id == "conv-openai-1"
        assert single_conv.platform == "chatgpt"



def test_claude_importer_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "conversations.json"
        sample_data = [
            {
                "uuid": "claude-uuid-1",
                "name": "Claude Export Conversation",
                "created_at": "2026-09-20T10:00:00Z",
                "updated_at": "2026-09-20T10:05:00Z",
                "chat_messages": [
                    {
                        "uuid": "cm-1",
                        "sender": "human",
                        "text": "Hello Claude",
                        "created_at": "2026-09-20T10:00:00Z"
                    },
                    {
                        "uuid": "cm-2",
                        "sender": "assistant",
                        "text": "Hello human!",
                        "created_at": "2026-09-20T10:00:05Z"
                    }
                ]
            }
        ]
        json_path.write_text(json.dumps(sample_data), encoding="utf-8")

        importer = ClaudeArchiveImporter()
        convs = importer.parse_archive(json_path)
        assert len(convs) == 1
        assert convs[0].platform == "claude_web"
        assert convs[0].title == "Claude Export Conversation"
        assert len(convs[0].messages) == 2


def test_takeout_importer():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "gemini.json"
        sample_data = {
            "conversations": [
                {
                    "conversation_id": "takeout-123",
                    "title": "Gemini Takeout Chat",
                    "turns": [
                        {"role": "user", "content": "Tell me about Mars"},
                        {"role": "assistant", "content": "Mars is the fourth planet."}
                    ]
                }
            ]
        }
        json_path.write_text(json.dumps(sample_data), encoding="utf-8")

        importer = GoogleTakeoutImporter()
        convs = importer.parse_archive(json_path)
        assert len(convs) == 1
        assert convs[0].platform == "gemini"
        assert convs[0].external_id == "takeout-123"
        assert len(convs[0].messages) == 2


@pytest.mark.asyncio
async def test_reconciler_deduplication():
    importer = ClaudeArchiveImporter()
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "conversations.json"
        sample_data = [
            {
                "uuid": "dedup-test-1",
                "name": "Dedup Test",
                "chat_messages": [
                    {"uuid": "m1", "sender": "human", "text": "Unique text 1", "created_at": "2026-09-20T10:00:00Z"}
                ]
            }
        ]
        json_path.write_text(json.dumps(sample_data), encoding="utf-8")
        convs = importer.parse_archive(json_path)

        reconciler = ArchiveReconciler(db=None, embedder=None)
        # 1st run: imported
        stats1 = await reconciler.import_conversations(convs)
        assert stats1["imported"] == 1
        assert stats1["skipped"] == 0

        # 2nd run: identical content -> skipped
        stats2 = await reconciler.import_conversations(convs)
        assert stats2["imported"] == 0
        assert stats2["skipped"] == 1

        # 3rd run: modified content -> updated
        convs[0].messages[0].content = "Modified text content"
        stats3 = await reconciler.import_conversations(convs)
        assert stats3["updated"] == 1
        assert stats3["skipped"] == 0



def test_archive_extractor():
    from src.importers.extractor import ArchiveExtractor, is_safe_path

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("sub/hello.txt", "world")
            z.writestr("root.json", '{"key": "val"}')

        res = ArchiveExtractor.extract_directory_archives(tmp_path, keep=True)
        assert res["archives_processed"] == 1
        assert res["files_extracted"] == 2
        assert (tmp_path / "sub" / "hello.txt").read_text() == "world"
        assert (tmp_path / "root.json").is_file()

        # Test path safety check
        assert is_safe_path(tmp_path, tmp_path / "sub" / "file.txt")
        assert not is_safe_path(tmp_path, Path("/etc/passwd"))


def test_takeout_master_importer():
    from src.importers.takeout_master import TakeoutMasterImporter

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Claude folder
        claude_dir = tmp_path / "claude-ai"
        claude_dir.mkdir()
        (claude_dir / "conversations.json").write_text(json.dumps([
            {
                "uuid": "claude-takeout-1",
                "name": "Test Claude",
                "chat_messages": [{"uuid": "m1", "sender": "human", "text": "Hi", "created_at": "2026-09-20T10:00:00Z"}]
            }
        ]))

        # 2. DeepSeek folder
        deepseek_dir = tmp_path / "deepseek"
        deepseek_dir.mkdir()
        (deepseek_dir / "session1.json").write_text(json.dumps({
            "chat_session": {"id": "ds-1", "title": "Test DS"},
            "chat_messages": [{"role": "user", "text": "DS query", "message_id": "m1"}]
        }))

        importer = TakeoutMasterImporter(tmp_path, auto_extract=False)
        results = importer.parse_all()

        assert "claude_web" in results
        assert len(results["claude_web"]) == 1
        assert results["claude_web"][0].external_id == "claude-takeout-1"

        assert "deepseek" in results
        assert len(results["deepseek"]) == 1
        assert results["deepseek"][0].external_id == "ds-1"

