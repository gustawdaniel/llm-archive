"""Jedno miejsce, które decyduje, czy i gdzie raportujemy błędy.

Raportowanie idzie do Bugsinka (protokół Sentry), jednego projektu na instalację.
Brak `SENTRY_DSN` oznacza raportowanie **wyłączone** i zero ruchu sieciowego —
instalacja bez konta w Bugsinku zachowuje się dokładnie jak przed integracją.

To repozytorium przechowuje treści rozmów z modelami, więc prywatność nie jest
tu opcją: `send_default_pii=False` i `max_request_body_size="never"` są
ustawione na sztywno. Do Bugsinka jadą wyłącznie wyjątki, stack trace i tag
usługi — nigdy ciało żądania ani metadane użytkownika.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("llm-archive.observability")


def init_error_reporting(service: str = "llm-archive-api") -> bool:
    """Włącza raportowanie błędów, jeśli jest skonfigurowane.

    Zwraca `True`, gdy SDK faktycznie wystartowało (przydatne w testach i przy
    weryfikacji na instalacji), `False` gdy DSN nie jest ustawiony.
    """
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("SENTRY_DSN nie ustawiony — raportowanie błędów wyłączone.")
        return False

    import sentry_sdk

    try:
        traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0") or 0)
    except ValueError:
        traces_sample_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("SENTRY_RELEASE") or None,
        traces_sample_rate=traces_sample_rate,
        # Archiwum rozmów: żadnych danych osobowych ani ciał żądań.
        send_default_pii=False,
        max_request_body_size="never",
    )
    sentry_sdk.set_tag("service", service)
    logger.info("Raportowanie błędów aktywne (Bugsink), usługa: %s.", service)
    return True
