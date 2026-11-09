import pytest
from src.normalizers import DeepSeekNormalizer, MarkdownGenerator


def test_deepseek_fragments_normalizer():
    # Real payload structure from DeepSeek Web API (from inspectDeepSeekFull)
    raw_data = {
        "chat_session": {
            "id": "5089000b-129b-4dcd-b31e-501017b5548e",
            "title": "Zastąpienie Claude Code przez chińskie modele",
            "inserted_at": 1790338867.6469998,
            "updated_at": 1790338870.0
        },
        "chat_messages": [
            {
                "message_id": 1,
                "parent_id": None,
                "model": "",
                "role": "USER",
                "thinking_enabled": True,
                "accumulated_token_usage": 75,
                "inserted_at": 1790338867.6499999,
                "fragments": [
                    {
                        "id": 1,
                        "type": "REQUEST",
                        "content": "Jak zastąpić Claude Code przez chińskie modele?"
                    }
                ]
            },
            {
                "message_id": 2,
                "parent_id": 1,
                "model": "",
                "role": "ASSISTANT",
                "thinking_enabled": True,
                "accumulated_token_usage": 1618,
                "inserted_at": 1790338867.6469998,
                "fragments": [
                    {
                        "id": 2,
                        "type": "THINK",
                        "content": "Użytkownik pyta, jak zastąpić Claude Code chińskimi modelami. Szukam opcji...",
                        "elapsed_secs": 1.38,
                        "stage_id": 1
                    },
                    {
                        "id": 3,
                        "type": "TOOL_SEARCH",
                        "status": "FINISHED",
                        "content": "Found 72 web pages",
                        "queries": [{"query": "chińskie modele AI zastąpić Claude Code"}],
                        "results": [
                            {
                                "url": "https://eu.36kr.com/zh/p/3888237831551749#1",
                                "title": "Claude Code 阿里已切割",
                                "snippet": "国产AI编程工具...",
                                "site_name": "36Kr"
                            },
                            {
                                "url": "https://the-decoder.de/zhipu-ais-zcode",
                                "title": "Zhipu AIs ZCode",
                                "snippet": "ZCode ist speziell auf GLM-5.2 zugeschnitten...",
                                "site_name": "THE DECODER"
                            }
                        ]
                    },
                    {
                        "id": 4,
                        "type": "THINK",
                        "content": "Wyniki wyszukiwania pokazują kilka istotnych wątków...",
                        "elapsed_secs": 1.37,
                        "stage_id": 2
                    },
                    {
                        "id": 5,
                        "type": "TOOL_OPEN",
                        "status": "FINISHED",
                        "result": {
                            "url": "https://the-decoder.de/zhipu-ais-zcode",
                            "title": "Zhipu AIs ZCode",
                            "snippet": "ZCode ist speziell..."
                        }
                    },
                    {
                        "id": 20,
                        "type": "RESPONSE",
                        "content": "Zastąpienie Claude Code chińskimi modelami jest w pełni możliwe i można to zrobić na kilka sposobów."
                    }
                ]
            }
        ]
    }

    norm = DeepSeekNormalizer()
    conv = norm.parse(raw_data)

    assert conv.platform == "deepseek"
    assert conv.external_id == "5089000b-129b-4dcd-b31e-501017b5548e"
    assert conv.title == "Zastąpienie Claude Code przez chińskie modele"
    assert conv.model == "deepseek-r1"
    assert len(conv.messages) == 2

    # User message verification
    msg0 = conv.messages[0]
    assert msg0.role == "user"
    assert msg0.content == "Jak zastąpić Claude Code przez chińskie modele?"
    assert msg0.reasoning_content is None
    assert msg0.token_usage.get("total_tokens") == 75

    # Assistant message verification
    msg1 = conv.messages[1]
    assert msg1.role == "assistant"
    assert "Zastąpienie Claude Code chińskimi modelami" in msg1.content
    assert msg1.reasoning_content is not None
    assert "Użytkownik pyta" in msg1.reasoning_content
    assert "Wyniki wyszukiwania pokazują" in msg1.reasoning_content
    assert msg1.token_usage.get("total_tokens") == 1618
    assert len(msg1.tool_calls) == 1
    assert msg1.tool_calls[0].name == "web_search"
    assert msg1.tool_calls[0].input["queries"] == ["chińskie modele AI zastąpić Claude Code"]

    # Sources deduplicated
    assert len(msg1.sources) == 2
    assert msg1.sources[0]["url"] == "https://eu.36kr.com/zh/p/3888237831551749#1"
    assert msg1.sources[1]["url"] == "https://the-decoder.de/zhipu-ais-zcode"

    # Markdown generation check
    md, rel_path = MarkdownGenerator.generate(conv)
    assert "deepseek" in rel_path
    assert "Thought Process" in md
    assert "Użytkownik pyta" in md
    assert "Źródła wyszukiwania" in md
    assert "https://eu.36kr.com" in md
    assert "Zastąpienie Claude Code chińskimi modelami" in md


def test_deepseek_legacy_export_fallback():
    raw_legacy = {
        "chat_session_id": "legacy-session-123",
        "title": "Legacy Session",
        "messages": [
            {
                "id": 1,
                "role": "user",
                "content": "Hello legacy DeepSeek",
                "inserted_at": 1700000000
            },
            {
                "id": 2,
                "role": "assistant",
                "content": "Hello! How can I help you?",
                "thinking_content": "Thinking about user greeting...",
                "inserted_at": 1700000005
            }
        ]
    }
    norm = DeepSeekNormalizer()
    conv = norm.parse(raw_legacy)
    assert conv.external_id == "legacy-session-123"
    assert conv.messages[0].content == "Hello legacy DeepSeek"
    assert conv.messages[1].content == "Hello! How can I help you?"
    assert conv.messages[1].reasoning_content == "Thinking about user greeting..."
