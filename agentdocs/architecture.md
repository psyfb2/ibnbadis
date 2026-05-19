# Architecture — ibnbadis repo

This repo automates page-by-page Q&A data entry for the ebooks on
<https://myquds.ibnbadis.org/> (user `fadi`, Year 4/5/6 English × semester 1/2).
It contains **two cooperating-by-key-only subprojects**:

| Subproject | Ticket | Style | Code? |
|---|---|---|---|
| `agentic-qa-data-entry/` | CSTC-3 | **Agentic** — a fresh Claude Code session per book drives `playwright-cli` per the RUNBOOK | No code (Markdown + committed `state/`) |
| `translation-pipeline/` | CSTC-4 | **Deterministic 3-step Python pipeline** | Yes (`src/translation_pipeline/`) |

**They share only the page-key STRING format** `"<book-key>/<section-slug>/page-<NN>"`
(e.g. `year4-sem1/section-1-a-new-friend/part-1/page-04`). No files or data
structures are shared. CSTC-4's store is independent of and structurally unrelated
to CSTC-3's `state/state.json`.

## CSTC-3 (agentic) vs CSTC-4 (deterministic) — why distinct artifacts

CSTC-4 is **not** a refactor of CSTC-3. The CSTC-4 ticket explicitly recommended a
deterministic 3-step pipeline (scrape → no-code translate → write-back) so that
the two side-effecting steps are idempotent, resumable and cheap to re-run, with a
validator as the safety net the scripted approach needs. CSTC-3's task (extract
English Q&A from page *images* and append rows) is inherently judgement-heavy and
stays agentic. CSTC-4's task (translate already-extracted English strings) is
isolated into a no-code step (step 2) outside the browser loop. The two therefore
remain separate artifacts that only cross-reference by key.

## CSTC-4 module map (`translation-pipeline/src/translation_pipeline/`)

| Module | Responsibility | Side effects |
|---|---|---|
| `config.py` | `Settings(BaseSettings)` — `IBNBADIS_*` env, `password: SecretStr`. `get_settings()`. | none |
| `logging_config.py` | structlog JSON → stdout (`LOG_LEVEL`). | none |
| `models.py` | Pydantic v2 store schema: `Row`, `Page`, `TranslationStore`. | none |
| `store.py` | Atomic interrupt-safe store I/O (`load_store` / `save_store`, `.bak` fallback). | filesystem |
| `page_keys.py` | Pure page-key helpers: `book_key`, `slugify`, `section_slug`, `compose_page_key`, validators. | none |
| `selectors.py` | **Pure** selector/label constants & field-name helpers. All `# VERIFY-ON-LIVE`. | none |
| `site.py` | **READ-ONLY** Playwright navigation (`SiteNavigator`, `browser_session`). Never imports the write helper. | browser (read) |
| `write_helper.py` | Side-effecting Playwright primitives (`fill_translation`, `save_page`, `read_field_value`). **Imported only by write-back.** | browser (write) |
| `scrape.py` | Step 1. Imports **only** `site` (+ store/models/config). Provably cannot mutate the site. | browser (read), store |
| `validate.py` | Pre-write-back validator. **Offline, read-only**, credential-free. | none |
| `writeback.py` | Step 3. Imports `site` + `write_helper`. Resumable & idempotent. | browser (write), store |

### Interface-segregation invariant (enforced)

`site.py` is read-only and **must never import `write_helper`**. `scrape.py`
imports **only `site`** (never `write_helper`). These invariants are enforced by
AST/import unit tests (`test_site`, `test_scrape`), so the scrape path *provably
cannot* mutate the site. Only `writeback.py` is permitted to import the write
helper. A single additive read-only `SiteNavigator.page` property exposes the
Playwright `Page` to the write helper without adding any write code to `site.py`.

## Tooling

CSTC-4 is greenfield Python in an otherwise no-code repo: `uv` (deps), `ruff`
(lint/format), `mypy` (`files=["src"]`, pydantic plugin), `pytest` (225 unit
tests, Playwright fully mocked), Playwright sync API, hatchling build backend,
`requires-python >= 3.12`. A `Makefile` exposes
`install / install-browsers / lint / format / typecheck / test / scrape /
validate / writeback`.

## Documented divergences

| Id | Divergence | Rationale |
|---|---|---|
| **A** | **Save signal.** CSTC-4 keys save-success off the `userqanssave.php` POST body `["", true]`; CSTC-3 uses the green Save-button flash. | CSTC-4 can intercept the response (deterministic); CSTC-3 cannot (agentic). Documented in **both** projects' RUNBOOK/CLAUDE.md. CSTC-3 behaviour unchanged. |
| **B** | **Store persistence.** CSTC-4 store gitignored; CSTC-3 commits `state/`. | CSTC-4 store is reproducible via re-scrape; CSTC-3 state is its only audit trail. |
| **C** | **Section-slug non-reproducibility.** CSTC-3 hand-made special slugs (`dictionary`, `ending`, `pictionary-and-alphabet`) are not algorithmic. CSTC-4 uses deterministic `section-{1-based-index}-{slug}` for both scrape and write-back. The key *format* permits an optional `/part-{n}` segment, but `_current_part_number()` is **currently a stub that always returns `None`** (pending the live selector-tuning run — §11 of the RUNBOOK), so CSTC-4 **emits no `/part-{n}` segment on any key today**. | CSTC-4 must key scrape & write-back by the same rule (internally consistent — collisions impossible because page numbers are globally sequential, not part-reset). Cross-ref with CSTC-3 is best-effort by key string only and **will not match CSTC-3 keys that contain `/part-` until part detection is implemented in the live run**. |
| **D** | **OpenTelemetry deferred.** Org standard mandates OTel; CSTC-4 uses structlog JSON to stdout only. | KISS — CSTC-4 is a single-operator local CLI; OTel infra is unjustified. Deliberate, documented divergence from the org standard. |
| **E** | **Post-validate caveat.** `make validate` is a PRE-write-back gate; a post-write-back run can flag `already_translated_write` on a defensively-reconciled row. | The reconcile deliberately keeps `*_translation` to preserve step-2 work. Out of flow; accepted trade-off (see `data-flow.md`). |

## See also

- `../translation-pipeline/RUNBOOK.md` — operator flow.
- `../translation-pipeline/docs/step-2-translation-procedure.md` — step-2 contract.
- `../agentic-qa-data-entry/RUNBOOK.md` — CSTC-3 procedure.
- `data-flow.md` — the CSTC-4 data flow & store schema.
