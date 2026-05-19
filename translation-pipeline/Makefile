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
scrape:
	uv run python -m translation_pipeline.scrape

validate:
	@echo "validate: not yet implemented (task 4)"

writeback:
	@echo "writeback: not yet implemented (task 5)"
