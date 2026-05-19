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

> Only steps 1 and 3 contain code. The authoritative operator **RUNBOOK** and the step-2
> translation procedure are added in later tasks (tasks 6 and 4 respectively). This task
> delivers only the project scaffold, the data-store schema, and store I/O.

Credentials are supplied via environment variables (`IBNBADIS_USERNAME`,
`IBNBADIS_PASSWORD`) — never hardcoded, logged, or committed.

## Quick commands

```sh
make install          # uv sync (no browser download)
make install-browsers # download Chromium (needed by later tasks)
make lint             # ruff check + format --check
make test             # pytest
```
