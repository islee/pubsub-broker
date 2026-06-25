"""Config env parsing — the only non-stub logic in config.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from broker.config import Config


def test_defaults() -> None:
    c = Config()
    assert c.transports == ("sse", "longpoll", "webhook")  # ws deferred
    assert c.min_retain >= 1  # mandatory per-topic floor
    assert c.budget_bytes > 0


def test_from_env_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROKER_TRANSPORTS", "sse, webhook")
    monkeypatch.setenv("BROKER_MIN_RETAIN", "4")
    monkeypatch.setenv("BROKER_BUDGET_BYTES", "1048576")
    monkeypatch.setenv("BROKER_RATELIMIT_REFILL_PER_SEC", "2.5")
    c = Config.from_env()
    assert c.transports == ("sse", "webhook")
    assert c.min_retain == 4
    assert c.budget_bytes == 1048576
    assert c.ratelimit_refill_per_sec == 2.5


def test_secret_from_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # BROKER_X_FILE supplies the value when BROKER_X is unset (key-file credentials).
    secret_file = tmp_path / "hmac"
    secret_file.write_text("  s3cr3t\n")
    monkeypatch.delenv("BROKER_WEBHOOK_HMAC_SECRET", raising=False)
    monkeypatch.setenv("BROKER_WEBHOOK_HMAC_SECRET_FILE", str(secret_file))
    assert Config.from_env().webhook_hmac_secret == "s3cr3t"  # stripped


def test_env_var_beats_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret_file = tmp_path / "hmac"
    secret_file.write_text("from-file")
    monkeypatch.setenv("BROKER_WEBHOOK_HMAC_SECRET", "from-env")
    monkeypatch.setenv("BROKER_WEBHOOK_HMAC_SECRET_FILE", str(secret_file))
    assert Config.from_env().webhook_hmac_secret == "from-env"
