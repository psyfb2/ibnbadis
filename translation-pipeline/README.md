# translation-pipeline (CSTC-4)

Deterministic 3-step pipeline that writes **Arabic translations** of existing English
ebook Q&A into the TextApps `Translated Questions` / `Translated Answers` fields on
<https://myquds.ibnbadis.org/> for the six books assigned to user `fadi`.

It is the translation counterpart of CSTC-3 (`../agentic-qa-data-entry/`). It does **not**
re-enter English Q&A; it translates whatever English rows already exist on the site.

The pipeline has three steps:

1. **Scrape** (code, deterministic Playwright) — read every existing row's English source
   and current translation state into `store/translations.json`.
2. **Translate** (no code) — Claude Code reads the store and writes consistent Arabic back
   into it.
3. **Write-back** (code, deterministic Playwright) — fill the Arabic into the matching
   `UQ{N}`/`UA{N}` fields and Save, confirming persistence via the `userqanssave.php`
   response body.

> Only steps 1 and 3 contain code (step 2 is a no-code manual translation step
> performed by Claude Code).

Credentials are supplied via environment variables (`IBNBADIS_USERNAME`,
`IBNBADIS_PASSWORD`) — never hardcoded, logged, or committed.

## Documentation

- **[`RUNBOOK.md`](RUNBOOK.md)** — the authoritative end-to-end operator runbook
  (prerequisites, the 3-step flow, resume/retry, `writeback_status` semantics,
  divergences, security). **Start here.**
- **[`docs/step-2-translation-procedure.md`](docs/step-2-translation-procedure.md)**
  — the no-code step-2 manual translation contract.

## Quick commands

```sh
make install            # uv sync (no browser download)
make install-browsers   # download Chromium (required for scrape & writeback)
make lint typecheck test

# End-to-end pipeline (see RUNBOOK.md for full detail):
make scrape             # step 1 — scrape English + site state (READ-ONLY)
#  → step 2: Claude Code fills uq/ua_translation (NO CODE — see step-2 doc)
make validate           # step 3a — mandatory offline gate, must exit 0
make writeback          # step 3b — write Arabic back & Save
```
