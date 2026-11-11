"""Testy schematu nazw plików archiwum (tag urządzenia w nazwie)."""

import os

from src.naming import conversation_rel_path, device_tag


def test_device_tag_is_filesystem_safe(monkeypatch):
    monkeypatch.setenv("BRAIN_DEVICE", "Mac Book Pro (Daniel)")
    assert device_tag() == "mac-book-pro"


def test_device_tag_falls_back_to_hostname(monkeypatch):
    monkeypatch.delenv("BRAIN_DEVICE", raising=False)
    monkeypatch.setattr("platform.node", lambda: "rog.local")
    assert device_tag() == "rog-local"


def test_device_tag_is_never_empty(monkeypatch):
    monkeypatch.setenv("BRAIN_DEVICE", "///")
    assert device_tag() == "unknown"


def test_rel_path_carries_device(monkeypatch):
    monkeypatch.setenv("BRAIN_DEVICE", "rog")
    path = conversation_rel_path("aider", "2026-10-24", "jakis-temat", "abcd1234")
    assert path == "aider/2026-10-24_jakis-temat_abcd1234-rog.md"


def test_two_devices_never_collide(monkeypatch):
    monkeypatch.setenv("BRAIN_DEVICE", "mac")
    a = conversation_rel_path("claude_code", "2026-11-09", "temat", "abcd1234")
    monkeypatch.setenv("BRAIN_DEVICE", "rog")
    b = conversation_rel_path("claude_code", "2026-11-09", "temat", "abcd1234")
    assert a != b
