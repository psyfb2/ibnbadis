"""Environment-driven configuration.

Credentials are supplied via environment variables (or a gitignored ``.env``)
and are NEVER hardcoded. The password is a :class:`~pydantic.SecretStr` so it is
masked in ``repr``/``str`` and in structured logs.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Default store location, resolved against the current working directory
#: (Makefile targets run from ``translation-pipeline/``). Exposed as a module
#: constant so it is a single source of truth shared by :class:`Settings` and
#: the credential-free offline path resolution in
#: :func:`translation_pipeline.validate._resolve_store_path` — neither reaches
#: into pydantic ``FieldInfo`` internals.
DEFAULT_STORE_PATH = Path("store/translations.json")


class Settings(BaseSettings):
    """Runtime settings, populated from ``IBNBADIS_*`` env vars / ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="IBNBADIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # No defaults — these MUST be supplied via the environment.
    username: str
    password: SecretStr

    base_url: str = "https://myquds.ibnbadis.org/"

    #: Store location. Resolved against the current working directory (Makefile
    #: targets run from ``translation-pipeline/``). NEVER derived from package
    #: ``__file__`` — that breaks for non-editable installs. Defaults to the
    #: shared :data:`DEFAULT_STORE_PATH` constant.
    store_path: Path = DEFAULT_STORE_PATH


def get_settings() -> Settings:
    """Build :class:`Settings` from the environment.

    Raises:
        RuntimeError: with a clear message naming the missing variables when
            required env vars are absent. The password value is never included.
    """
    try:
        return Settings()  # values come from env / .env (pydantic-settings)
    except ValidationError as exc:  # -> friendly, secret-free message
        missing: list[str] = []
        for err in exc.errors():
            if err.get("type") == "missing":
                loc = err.get("loc", ())
                if loc:
                    missing.append(f"IBNBADIS_{str(loc[0]).upper()}")
        if missing:
            raise RuntimeError(
                "Missing required environment variable(s): "
                + ", ".join(sorted(set(missing)))
                + ". Set them in the environment or a gitignored .env file."
            ) from exc
        raise
