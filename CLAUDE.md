# ibnbadis — ebook Q&A data-entry automation

Automation for the page-by-page Q&A data entry on
<https://myquds.ibnbadis.org/> for the six books assigned to user `fadi`
(Year 4/5/6 English × semester 1/2).

## Two subprojects

| Dir | Ticket | What |
|---|---|---|
| `agentic-qa-data-entry/` | CSTC-3 | **Agentic, no code.** A fresh Claude Code session per book drives `playwright-cli` per its RUNBOOK to enter the **English** Q&A. Commits its `state/`. |
| `translation-pipeline/` | CSTC-4 | **Deterministic 3-step Python pipeline.** Reads existing English Q&A and writes **Arabic translations** into the same TextApps rows. Store is gitignored. |

They cross-reference **only** by the shared page-key string format
`"<book-key>/<section-slug>/page-<NN>"` — no shared files or data structures.

## How to run / test

**CSTC-4** (from `translation-pipeline/`; or `uv run --directory
translation-pipeline …` from repo root):

```sh
make install            # deps only (offline)
make install-browsers   # Chromium — required for scrape/writeback
make lint typecheck test
# pipeline:
make scrape   # step 1 (READ-ONLY)
#  → step 2: Claude fills uq/ua_translation (NO CODE — see step-2 doc)
make validate # step 3a — mandatory gate, must exit 0
make writeback # step 3b
```

**CSTC-3**: `/fill-ebook <year> <semester>` (one fresh session per book).

## Key shared concept

Page-key STRING format `"<book-key>/<section-slug>/page-<NN>"` (only the *string
format* is shared; the CSTC-4 store is structurally independent of CSTC-3's
`state.json`).

## Gotchas (high level)

- **RTL UI** — address fields by their `name` attribute (`UQ{N}`/`UA{N}`/`TQ{N}`/
  `TA{N}`, 0-based), never by visual position.
- **Save-success signal differs** — CSTC-4 keys off the `userqanssave.php` POST
  body `["", true]`; CSTC-3 uses the green Save-button flash (divergence A).
- **Store persistence differs** — CSTC-4 store is gitignored; CSTC-3 state is
  committed (divergence B).
- **Section slugs** — CSTC-3 uses hand-made special slugs not reproducible by
  CSTC-4's deterministic rule; cross-ref is best-effort by key (divergence C).
- **OpenTelemetry deliberately deferred** for CSTC-4 (structlog JSON to stdout
  only — KISS for a single-operator CLI; divergence D — see agentdocs).

## Pointers (depth lives here, not in this file)

- `agentdocs/architecture.md` — subproject map, CSTC-4 modules, interface
  segregation, the divergences.
- `agentdocs/data-flow.md` — pipeline data flow, store schema, resume/idempotency.
- `translation-pipeline/RUNBOOK.md` — the authoritative CSTC-4 operator runbook.
- `translation-pipeline/docs/step-2-translation-procedure.md` — the no-code
  step-2 translation contract.
- `agentic-qa-data-entry/RUNBOOK.md` — the CSTC-3 procedure.
