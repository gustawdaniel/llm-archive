import json
import pytest
from src.normalizers import GrokNormalizer, GeminiNormalizer, MarkdownGenerator


def test_grok_normalizer():
    sample_grok = {
        "conversation_id": "grok-uuid-1234",
        "title": "Grok Quantum Physics Discussion",
        "model": "grok-2",
        "messages": [
            {
                "id": "msg-1",
                "sender": "HUMAN",
                "message": "Explain quantum entanglement in simple terms.",
                "created_at": "2026-09-20T12:00:00Z"
            },
            {
                "id": "msg-2",
                "sender": "ASSISTANT",
                "message": "Quantum entanglement is when two particles become deeply connected...",
                "created_at": "2026-09-20T12:00:05Z"
            }
        ]
    }

    norm = GrokNormalizer()
    conv = norm.parse(sample_grok)
    assert conv.platform == "grok"
    assert conv.external_id == "grok-uuid-1234"
    assert len(conv.messages) == 2
    assert conv.messages[0].role == "user"
    assert conv.messages[1].role == "assistant"

    md, rel_path = MarkdownGenerator.generate(conv)
    assert "grok" in rel_path
    assert "quantum entanglement" in md


def test_gemini_normalizer():
    sample_gemini = {
        "conversation_id": "gemini-uuid-5678",
        "title": "Gemini System Design",
        "model": "gemini-2.5-pro",
        "messages": [
            {
                "id": "g-1",
                "author": "USER",
                "parts": [{"text": "How should we design a distributed cache?"}],
                "created_at": "2026-09-21T08:30:00Z"
            },
            {
                "id": "g-2",
                "author": "ASSISTANT",
                "parts": [{"text": "Here is a distributed cache architecture using consistent hashing."}],
                "created_at": "2026-09-21T08:30:10Z"
            }
        ]
    }

    norm = GeminiNormalizer()
    conv = norm.parse(sample_gemini)
    assert conv.platform == "gemini"
    assert conv.external_id == "gemini-uuid-5678"
    assert len(conv.messages) == 2
    assert conv.messages[0].role == "user"
    assert "distributed cache" in conv.messages[0].content

    md, rel_path = MarkdownGenerator.generate(conv)
    assert "gemini" in rel_path
    assert "consistent hashing" in md


def test_gemini_takeout_filters_telemetry():
    raw_takeout = [
        # Telemetry events that must be ignored
        {
            "header": "Gemini",
            "title": "Wyczyszczono poprzednie opinie.",
            "time": "2026-09-20T12:00:00Z"
        },
        {
            "header": "Gemini",
            "title": "Użyto funkcji Asystenta",
            "time": "2026-09-20T12:05:00Z",
            "details": [{"url": "https://gemini.google.com/app/telemetry_id"}]
        },
        {
            "header": "Gemini",
            "title": "Utworzono artefakt Gemini Canvas o nazwie Test",
            "time": "2026-09-20T12:10:00Z"
        },
        {
            "header": "Gemini",
            "title": "Wybrana preferowana wersja odpowiedzi",
            "time": "2026-09-20T12:15:00Z"
        },
        # Real conversation turns
        {
            "header": "Gemini",
            "title": "Wysłano zapytanie: Czym jest protokół raft?",
            "time": "2026-09-20T12:20:00Z",
            "details": [{"url": "https://gemini.google.com/app/real_conv_123"}],
            "safeHtmlItem": [{"html": "<p>Raft to algorytm konsensusu rozproszonego.</p>"}]
        },
        {
            "header": "Gemini",
            "title": "Wysłano zapytanie: A jak działa wybór lidera?",
            "time": "2026-09-20T12:21:00Z",
            "details": [{"url": "https://gemini.google.com/app/real_conv_123"}],
            "safeHtmlItem": [{"html": "<p>Węzeł staje się kandydatem po upływie timeoutu.</p>"}]
        }
    ]

    convs = GeminiNormalizer.aggregate_takeout_events(raw_takeout)
    assert len(convs) == 1
    conv = convs[0]
    assert conv.external_id == "real_conv_123"
    assert "Czym jest protokół raft" in conv.title
    assert len(conv.messages) == 4
    assert conv.messages[0].role == "user"
    assert "Czym jest protokół raft?" in conv.messages[0].content
    assert conv.messages[1].role == "assistant"
    assert "Raft to algorytm konsensusu" in conv.messages[1].content
    assert conv.messages[2].role == "user"
    assert "A jak działa wybór lidera?" in conv.messages[2].content
    assert conv.messages[3].role == "assistant"
    assert "Węzeł staje się kandydatem" in conv.messages[3].content


def test_grok_web_api_format():
    sample_web_grok = {
        "conversation_id": "cfe1f9c6-062a-43ba-ac8b-3785638954a3",
        "title": "AMD Radeon drivers updates for hybrid GPU",
        "model": "grok-3",
        "conversation": {
            "conversationId": "cfe1f9c6-062a-43ba-ac8b-3785638954a3",
            "title": "AMD Radeon drivers updates for hybrid GPU",
            "createTime": "2026-09-24T20:43:40.140Z",
            "modifyTime": "2026-09-24T21:10:15.331Z"
        },
        "responses": [
            {
                "responseId": "d5fc846f-8900-4348-8fc3-ff4020f3c47b",
                "message": "warning: nvidia-open-dkms: ignoring package upgrade...\nopwiedz co jest w tych nowych sterownikach",
                "sender": "human",
                "createTime": "2026-09-24T20:44:09.344Z",
                "parentResponseId": "1913e880-b980-585d-bb33-cd916c0d21ca"
            },
            {
                "responseId": "beb3afa6-4d9e-4016-a379-6dc3b7259bcd",
                "message": "**Sterowniki NVIDIA 615.71.09 (New Feature Branch) vs Twoje obecne 610.57.04**\n\nGłówne zmiany istotne...",
                "sender": "assistant",
                "createTime": "2026-09-24T20:44:09.355Z",
                "parentResponseId": "d5fc846f-8900-4348-8fc3-ff4020f3c47b"
            }
        ]
    }

    norm = GrokNormalizer()
    conv = norm.parse(sample_web_grok)
    assert conv.platform == "grok"
    assert conv.external_id == "cfe1f9c6-062a-43ba-ac8b-3785638954a3"
    assert conv.title == "AMD Radeon drivers updates for hybrid GPU"
    assert len(conv.messages) == 2
    assert conv.messages[0].role == "user"
    assert conv.messages[0].external_id == "d5fc846f-8900-4348-8fc3-ff4020f3c47b"
    assert "nvidia-open-dkms" in conv.messages[0].content
    assert conv.messages[1].role == "assistant"
    assert conv.messages[1].external_id == "beb3afa6-4d9e-4016-a379-6dc3b7259bcd"
    assert "Sterowniki NVIDIA 615.71.09" in conv.messages[1].content


def test_device_propagation():
    norm_grok = GrokNormalizer()
    conv_grok = norm_grok.parse({"conversation_id": "c1", "messages": [{"id": "m1", "sender": "HUMAN", "message": "hi"}]}, metadata={"device": "rog"})
    assert conv_grok.device == "rog"

    norm_gemini = GeminiNormalizer()
    conv_gemini = norm_gemini.parse({"conversation_id": "c2", "messages": [{"id": "m2", "author": "USER", "parts": [{"text": "hi"}]}]}, metadata={"device": "mac"})
    assert conv_gemini.device == "mac"


def test_gemini_reverse_order_turns_sorted():
    norm = GeminiNormalizer()
    # Payload where turns/messages are in reverse chronological order (newest first)
    raw = {
        "conversation_id": "f4859b9b0791c5d6",
        "title": "Rozmowa z Gemini",
        "messages": [
            {
                "id": "m_new",
                "author": "USER",
                "parts": [{"text": "A nie sądzisz, że to trochę nie w porządku?"}],
                "created_at": "2026-09-24T22:55:52.045Z",
                "step_index": 0
            },
            {
                "id": "m_new_a",
                "author": "ASSISTANT",
                "parts": [{"text": "Z perspektywy użytkownika..."}],
                "created_at": "2026-09-24T22:55:52.045Z",
                "step_index": 1
            },
            {
                "id": "m_old",
                "author": "USER",
                "parts": [{"text": "jak w antigravity zrobic zeby json mial pretty format?"}],
                "created_at": "2026-09-23T18:33:55.968Z",
                "step_index": 2
            },
            {
                "id": "m_old_a",
                "author": "ASSISTANT",
                "parts": [{"text": "W edytorze Antigravity..."}],
                "created_at": "2026-09-23T18:33:55.968Z",
                "step_index": 3
            }
        ]
    }
    conv = norm.parse(raw)
    assert len(conv.messages) == 4
    # Chronological: oldest must become step_index 0
    assert conv.messages[0].step_index == 0
    assert conv.messages[0].role == "user"
    assert "antigravity" in conv.messages[0].content
    assert conv.messages[1].step_index == 1
    assert conv.messages[1].role == "assistant"
    assert conv.messages[2].step_index == 2
    assert "nie sądzisz" in conv.messages[2].content
    assert conv.messages[3].step_index == 3
    assert conv.started_at < conv.updated_at




