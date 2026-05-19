.PHONY: install install-browsers lint format typecheck test scrape validate writeback

# Deterministic dependency install. NO browser download so it always succeeds offline.
install:
	uv sync

# Separate target: downloads the Chromium browser used by later tasks (2/3/5).
install-browsers:
	uv run playwright install chromium

# Lint + format check (CI-safe; does not modify files).
lint:
	uv run ruff check .
	uv run ruff format --check .

# Auto-format the codebase.
format:
	uv run ruff format .

# Static type checking (repo Python standard).
typecheck:
	uv run mypy

# Run the unit test suite.
test:
	uv run pytest

# --- Pipeline step placeholders (implemented in tasks 3 / 4 / 5) ---
# `make scrape` runs all 6 books headless. For the live selector-tuning run:
#   make scrape ARGS='--headed --book year4-sem1'
scrape:
	uv run python -m translation_pipeline.scrape $(ARGS)

# `make validate` is the offline, credential-free pre-write-back gate
# (run after step-2 translation, before step-3 write-back). Non-zero exit on
# any finding. Optional store override:
#   make validate ARGS='--store /path/to/translations.json'
validate:
	uv run python -m translation_pipeline.validate $(ARGS)

writeback:
	@echo "writeback: not yet implemented (task 5)"
