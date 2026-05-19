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
def clean_ibnbadis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any ambient IBNBADIS_* / LOG_LEVEL env so tests are hermetic."""
    for var in (
        "IBNBADIS_USERNAME",
        "IBNBADIS_PASSWORD",
        "IBNBADIS_BASE_URL",
        "IBNBADIS_STORE_PATH",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def creds_env(monkeypatch: pytest.MonkeyPatch, clean_ibnbadis_env: None) -> dict[str, str]:
    """Set valid credential env vars; return the values for assertions."""
    values = {"username": "fadi", "password": "s3cr3t-do-not-log"}
    monkeypatch.setenv("IBNBADIS_USERNAME", values["username"])
    monkeypatch.setenv("IBNBADIS_PASSWORD", values["password"])
    return values
