"""Config: env loading, missing-var error, secret never exposed (incl. logs)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import structlog

from translation_pipeline.config import get_settings
from translation_pipeline.logging_config import configure_logging
from translation_pipeline.models import TranslationStore
from translation_pipeline.store import load_store, save_store

PW = "s3cr3t-do-not-log"


def test_loads_credentials_from_env(creds_env: dict[str, str]) -> None:
    settings = get_settings()
    assert settings.username == creds_env["username"]
    assert settings.password.get_secret_value() == creds_env["password"]


def test_missing_env_raises_clear_named_error(clean_ibnbadis_env: None) -> None:
    with pytest.raises(RuntimeError) as exc:
        get_settings()
    msg = str(exc.value)
    assert "IBNBADIS_USERNAME" in msg
    assert "IBNBADIS_PASSWORD" in msg
    assert PW not in msg  # never leak any value


def test_password_not_in_repr_or_str(creds_env: dict[str, str]) -> None:
    settings = get_settings()
    assert PW not in repr(settings)
    assert PW not in str(settings)
    assert PW not in repr(settings.password)
    assert PW not in str(settings.password)
    # ...but the real value is still retrievable explicitly.
    assert settings.password.get_secret_value() == PW


def test_password_not_emitted_when_settings_logged(
    creds_env: dict[str, str],
) -> None:
    buf = io.StringIO()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        cache_logger_on_first_use=False,
    )
    try:
        log = structlog.get_logger("test")
        settings = get_settings()
        log.info("settings_loaded", settings=settings, password=settings.password)
    finally:
        structlog.reset_defaults()

    out = buf.getvalue()
    assert "settings_loaded" in out
    assert PW not in out


def test_production_logging_config_applies() -> None:
    configure_logging("DEBUG")
    assert structlog.is_configured()
    structlog.reset_defaults()


def test_store_path_default(creds_env: dict[str, str]) -> None:
    assert get_settings().store_path == Path("store/translations.json")


def test_store_path_overridable_via_env(
    creds_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom = tmp_path / "custom" / "store.json"
    monkeypatch.setenv("IBNBADIS_STORE_PATH", str(custom))
    settings = get_settings()
    assert settings.store_path == custom

    # store I/O honours the configured path (no __file__-relative resolution).
    save_store(TranslationStore({}), settings.store_path)
    assert custom.exists()
    assert load_store(settings.store_path) == TranslationStore({})
