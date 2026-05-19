"""Interrupt-safe load/save for ``store/translations.json``.

Guarantees:

- **Atomic write**: a kill at any point leaves either the prior file intact or a
  recoverable ``<path>.bak``; the target is never a truncated/partial file.
- **No temp-file leak**: a failed ``os.replace`` unlinks the orphaned temp file.
- **UTF-8 literal Arabic**: serialised via explicit ``json.dumps(ensure_ascii=
  False)`` so the guarantee is independent of the pydantic serializer variant.

Merge-refresh on re-scrape (preserving translations) is task 3 logic — NOT here.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from pydantic import ValidationError

from translation_pipeline.logging_config import get_logger
from translation_pipeline.models import TranslationStore

_log = get_logger(__name__)


class StoreCorruptError(RuntimeError):
    """Raised when the store and its ``.bak`` are both missing/unparseable."""


def _bak_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _serialize(store: TranslationStore) -> str:
    """JSON text with literal (non-escaped) Arabic, stable formatting."""
    return json.dumps(
        store.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def load_store(path: Path) -> TranslationStore:
    """Load the store, falling back to ``<path>.bak`` if the main file is bad.

    Returns an empty store if the file does not exist.

    Raises:
        StoreCorruptError: if the main file is corrupt and there is no usable
            backup.
    """
    if not path.exists():
        return TranslationStore({})

    try:
        return TranslationStore.model_validate_json(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        bak = _bak_path(path)
        _log.warning(
            "store_main_unparseable_trying_backup",
            path=str(path),
            backup=str(bak),
            error=str(exc),
        )
        if bak.exists():
            try:
                return TranslationStore.model_validate_json(bak.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValidationError, ValueError) as bak_exc:
                raise StoreCorruptError(
                    f"both {path} and {bak} are corrupt/unparseable"
                ) from bak_exc
        raise StoreCorruptError(
            f"{path} is corrupt/unparseable and no backup {bak} exists"
        ) from exc


def save_store(store: TranslationStore, path: Path) -> None:
    """Atomically write ``store`` to ``path`` with a single ``.bak`` backup."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        shutil.copy2(path, _bak_path(path))

    payload = _serialize(store)

    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise

    # Best-effort directory durability (ignore platforms that disallow it).
    try:
        dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, AttributeError):
        pass
