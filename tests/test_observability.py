"""Raportowanie błędów: kontrakt „brak DSN = cisza" i twarde flagi prywatności.

Te testy nie dotykają sieci — `sentry_sdk` jest podstawiany atrapą, więc
sprawdzają wyłącznie to, co nas interesuje: kiedy SDK w ogóle startuje i z jakimi
ustawieniami (archiwum rozmów nie może wysyłać ciał żądań ani danych osobowych).
"""

import sys
import types

import pytest

from src.observability import init_error_reporting


@pytest.fixture
def fake_sentry(monkeypatch):
    captured: dict = {}
    fake = types.ModuleType("sentry_sdk")

    def fake_init(**kwargs):
        captured.update(kwargs)

    def fake_set_tag(key, value):
        captured["tag"] = (key, value)

    fake.init = fake_init  # type: ignore[attr-defined]
    fake.set_tag = fake_set_tag  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    return captured


def test_disabled_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_error_reporting("test-service") is False


def test_disabled_with_blank_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "   ")
    assert init_error_reporting("test-service") is False


def test_enabled_with_privacy_flags(monkeypatch, fake_sentry):
    monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)

    assert init_error_reporting("llm-archive-api") is True

    assert fake_sentry["dsn"] == "https://key@localhost/1"
    assert fake_sentry["environment"] == "test"
    assert fake_sentry["send_default_pii"] is False
    assert fake_sentry["max_request_body_size"] == "never"
    assert fake_sentry["traces_sample_rate"] == 0.0
    assert fake_sentry["tag"] == ("service", "llm-archive-api")


def test_broken_sample_rate_falls_back_to_zero(monkeypatch, fake_sentry):
    monkeypatch.setenv("SENTRY_DSN", "https://key@localhost/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "nie-liczba")

    assert init_error_reporting() is True
    assert fake_sentry["traces_sample_rate"] == 0.0
