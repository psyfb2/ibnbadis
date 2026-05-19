"""Shared fixtures. All external services (browser/site/network) are absent —
task-1 tests are pure-Python (no Playwright import, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

# A representative Arabic string used to assert UTF-8 round-tripping.
ARABIC_Q = "ما اسمك؟"
ARABIC_A = "اسمي علي."


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A throwaway store path inside a tmp dir (parent exists)."""
    return tmp_path / "store" / "translations.json"


@pytest.fixture
def clean_ibnbadis_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Hermetic config env: drop ambient IBNBADIS_*/LOG_LEVEL AND chdir into an
    empty tmp dir so a developer's gitignored ``.env`` cannot leak in and give a
    false green (pydantic-settings reads ``.env`` relative to CWD)."""
    for var in (
        "IBNBADIS_USERNAME",
        "IBNBADIS_PASSWORD",
        "IBNBADIS_BASE_URL",
        "IBNBADIS_STORE_PATH",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def creds_env(monkeypatch: pytest.MonkeyPatch, clean_ibnbadis_env: None) -> dict[str, str]:
    """Set valid credential env vars; return the values for assertions."""
    values = {"username": "fadi", "password": "s3cr3t-do-not-log"}
    monkeypatch.setenv("IBNBADIS_USERNAME", values["username"])
    monkeypatch.setenv("IBNBADIS_PASSWORD", values["password"])
    return values
