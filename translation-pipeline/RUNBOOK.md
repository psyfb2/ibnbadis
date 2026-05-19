# RUNBOOK — CSTC-4 Arabic-translation pipeline

The single authoritative operator runbook for the **deterministic 3-step CSTC-4
pipeline** that writes Arabic translations of existing English ebook Q&A into the
TextApps `Translated Questions` / `Translated Answers` fields on
<https://myquds.ibnbadis.org/>. Source ticket:
[CSTC-4](https://fadyai.atlassian.net/browse/CSTC-4).

> This RUNBOOK owns the **operator flow** (scrape → validate → write-back). The
> **manual translation contract** (step 2) is owned by
> [`docs/step-2-translation-procedure.md`](docs/step-2-translation-procedure.md)
> and is referenced — never duplicated or contradicted — from here.

---

## 1. Purpose & relationship to CSTC-3

CSTC-4 is the **translation counterpart** of CSTC-3 (`../agentic-qa-data-entry/`,
see its [RUNBOOK](../agentic-qa-data-entry/RUNBOOK.md)). CSTC-3 (agentic, no code)
enters the **English** Q&A into TextApps. CSTC-4 does **not** re-enter English; it
reads whatever English rows exist on the site and writes their **Arabic
translations** into the `UQ{N}` / `UA{N}` fields of the same rows.

The two projects are independent artifacts that cross-reference **only** by the
shared page-key *string format* `"<book-key>/<section-slug>/page-<NN>"`. They share
no files or data structures (CSTC-4's store is gitignored; CSTC-3 commits its
`state/`).

The pipeline covers all six books assigned to user `fadi`: Year 4 / 5 / 6 English,
semester 1 (Book A) and semester 2 (Book B), every section and page.

## 2. Prerequisites

All commands run from inside the project directory:

```sh
cd translation-pipeline
make install            # uv sync — deps only, no browser, works offline
make install-browsers   # downloads Chromium — REQUIRED for scrape & write-back
```

Credentials are supplied **only** via environment variables (pydantic-settings,
`env_prefix=IBNBADIS_`); an optional gitignored `.env` in `translation-pipeline/`
is also read:

| Variable | Required | Default | Notes |
|---|---|---|---|
| `IBNBADIS_USERNAME` | yes | — | Site login (`fadi`). |
| `IBNBADIS_PASSWORD` | yes | — | `SecretStr` — masked in every log/repr. |
| `IBNBADIS_BASE_URL` | no | `https://myquds.ibnbadis.org/` | |
| `IBNBADIS_STORE_PATH` | no | `store/translations.json` | CWD-relative. |
| `LOG_LEVEL` | no | `INFO` | structlog JSON to stdout. |

> **Never** hardcode, commit, log, or paste the password into any file. `.env`,
> `store/translations.json`, `store/*.bak` and `screenshots/` are gitignored.

`make scrape` / `make writeback` require `make install-browsers` first.
`make validate` is offline and credential-free (no browser, no env needed).

## 3. The 3-step flow

```text
  make scrape                 step 2 (no code)        make validate      make writeback
  ───────────►  store/        ───────────────►  store ───────────►  gate ───────────►  site
  read English  translations  Claude Code fills  (must  (PRE-write-  fill UQ/UA, Save,
  + site state  .json         uq/ua_translation  exit 0) back gate)   confirm via
  (READ-ONLY)                 per step-2 doc                          userqanssave.php
```

1. **`make scrape`** — deterministic Playwright; READ-ONLY; populates the store.
2. **Step 2 (no code)** — Claude Code fills the Arabic per
   [`docs/step-2-translation-procedure.md`](docs/step-2-translation-procedure.md).
3. **`make validate`** — mandatory offline gate; must exit `0`.
4. **`make writeback`** — deterministic Playwright; fills the Arabic and Saves.

Each step is killable and resumable; the store is written atomically after every
page.

## 4. Step 1 — Scrape (`make scrape`)

```sh
make scrape                                  # all 6 books, headless
make scrape ARGS='--headed --book year4-sem1'  # single book, visible (live tuning)
```

- Walks all six books `year{4,5,6}-sem{1,2}`, every section, every page, opens the
  TextApps panel and reads each existing row's English `TQ{N}` / `TA{N}` and the
  current site `UQ{N}` / `UA{N}`. **No site writes** are ever performed by scrape
  (interface-segregation is enforced — `scrape.py` cannot import the write helper).
- One browser session **per book** (6 logins per full run); `--book` restricts to
  one book key.
- Pages with no English Q&A are recorded with `skip_reason="no_english_qa"` and
  cause no error (CSTC-3 partial-completion handling — see §9).
- **Resumable**: the store is saved after every page; a killed run resumes from
  disk on restart.
- **Merge-refresh** (re-running scrape after step 2 or 3 is safe): a re-scrape
  refreshes the English source, the site snapshot (`tq/ta/uq/ua`) and the four
  per-field flags from live data, but **preserves** every `uq_translation` /
  `ua_translation` you wrote in step 2 and the page-level `writeback_status`. Your
  translation work and write-back progress are **never** destroyed by a re-scrape.

## 5. Step 2 — Manual translation (NO CODE)

Step 2 has **no code**. Claude Code reads `store/translations.json` and writes
consistent, primary-school-register Arabic into the **only two writable fields**
`uq_translation` / `ua_translation`, deciding UQ and UA independently per row.

The full, authoritative contract — what to fill, the hard prohibitions
(never alter `tq/ta/uq/ua` or any flag; never overwrite an `*_already_translated`
field), the consistency rule, and the `ValidationCode` → fix table — lives in
**[`docs/step-2-translation-procedure.md`](docs/step-2-translation-procedure.md)**.
Read it in full before editing the store. It is **not** duplicated here.

## 6. Step 3a — Validate (`make validate`)

```sh
make validate                                  # default store
make validate ARGS='--store /path/to/translations.json'
```

`make validate` is **offline, credential-free, and the mandatory gate**:

- **Exit code `0` ⇒ proceed to write-back.**
- **Any non-zero exit ⇒ the store is NOT ready.** Fix the reported findings and
  re-run until it exits `0`. **Never** run `make writeback` after a non-zero
  validate.

For the `ValidationCode` → fix table see
[step-2 doc §6](docs/step-2-translation-procedure.md#6-verification--make-validate-is-the-gate-before-write-back)
(not copied here to avoid drift).

> **PRE-write-back gate only.** `make validate` is designed to run *after* step 2
> and *before* write-back. Running it *after* write-back may legitimately report
> `already_translated_write` on a row the write-back defensively reconciled (the
> reconcile deliberately keeps `*_translation` so step-2 work is preserved). This
> is **out of the pipeline flow** and an accepted, documented trade-off (see
> divergence **E** in §10) — do not run validate post-write-back as a check.

## 7. Step 3b — Write-back (`make writeback`)

```sh
make writeback                                  # all pending/failed pages, headless
make writeback ARGS='--headed --book year4-sem1'  # single book, visible (live tuning)
```

- Walks the validated store and decides **per field, independently**: a `UQ` or
  `UA` is written iff its `*_needs_translation` is `true` **and** its
  `*_translation` is non-blank.
- Fills `UQ{N}` / `UA{N}` **by row index only**. **Never** uses the `+` button,
  **never** adds/removes/reorders rows, **never** touches `TQ{N}` / `TA{N}`.
- **Defensive no-overwrite guard**: immediately before filling, it re-reads the
  target field's live value; if non-blank it is **skipped** (never overwritten), a
  warning is logged, and the store row is reconciled in-place (keeping
  `*_translation`) so it stays consistent without a full re-scrape.
- Clicks **Save once per page**. Save success is keyed **strictly** off the
  `https://dev.ibnbadis.org/TextEntry/userqanssave.php` POST body — **not** the
  fleeting green Save-button flash.

**`writeback_status` semantics:**

| Status | Meaning | On re-run |
|---|---|---|
| `pending` | Not yet acted (default after scrape). | Re-acted. |
| `failed` | Save rejected / server error / panel error. | Re-acted; can recover to `success` (its `writeback_error` is then cleared). |
| `success` | Persisted, **or** nothing to do for the page. | **Terminal** — resume-skipped (no navigation work). |

**Save mapping** (via `userqanssave.php` body only):

- `["", true]` → `success`.
- `["", false]` → `failed` (**not** retried — it is a definitive rejection).
- 5xx / timeout / unparseable → **exactly one** retry (filled form only) then
  status per the final outcome.
- `PanelError` opening the TextApps panel → page `failed` (re-runnable next run).

**Two terminal-success-WITHOUT-Save branches** (an empty form is **never**
submitted): (a) nothing is planned for the page; (b) the plan was non-empty but
every field was defensively skipped. Both reach the terminal `success` so re-runs
never re-navigate the page.

Any unexpected exception other than `PanelError` aborts the run by design (resume
from disk on the next run) — fail-fast on the genuinely unexpected.

## 8. Resume & retry guidance

- Every step is **kill/restart safe**. The store is written atomically after every
  page; restart resumes from the on-disk store.
- To retry failures: simply re-run `make writeback` — only `pending` / `failed`
  pages are re-acted; `success` pages are skipped.
- The whole pipeline can be re-run end-to-end as CSTC-3 enters more English. The
  scrape merge-refresh (§4) makes this safe: translations and write-back progress
  survive a re-scrape.

## 9. CSTC-3 partial-completion handling

CSTC-3 may not have entered the English Q&A for every page yet. CSTC-4 operates
**only on the English rows that exist on the site at run time**:

- Pages/rows with no English Q&A are skipped without error
  (`skip_reason="no_english_qa"`; nothing to translate, nothing to write).
- Re-run the full pipeline (`scrape → step 2 → validate → writeback`) periodically
  as CSTC-3 progresses; the merge-refresh guarantees prior translations and
  write-back progress are preserved.

## 10. Divergences (authoritative consolidated list)

| Id | Divergence | Rationale |
|---|---|---|
| **A** | **Save signal.** CSTC-4 keys save-success strictly off the `userqanssave.php` POST body `["", true]` (a `["", false]` body or 5xx = failed). CSTC-3 (agentic) intentionally continues to use the **green Save-button flash**. | Same underlying endpoint; CSTC-4 can intercept the response (deterministic), CSTC-3 cannot (agentic, observes the UI). Documented in **both** projects: this §10, the CSTC-3 [RUNBOOK §4.7](../agentic-qa-data-entry/RUNBOOK.md) note and CSTC-3 [CLAUDE.md](../agentic-qa-data-entry/CLAUDE.md) "Important guarantees". CSTC-3 behaviour is unchanged. |
| **B** | **Store persistence.** CSTC-4's `store/translations.json` is **gitignored**; CSTC-3 **commits** its `state/`. | CSTC-4's store may contain large scraped page content and is reproducible by re-running scrape; CSTC-3's state is its only audit trail. |
| **C** | **Section-slug.** CSTC-3 uses hand-made special slugs (e.g. `dictionary`, `ending`, `pictionary-and-alphabet`) that are **not** algorithmically reproducible. CSTC-4 deterministically uses `section-{1-based-index}-{slug}` (+ optional `/part-{n}`) for **both** scrape and write-back. | CSTC-4 must key scrape and write-back by the *same* deterministic rule; it is internally consistent. Cross-reference with CSTC-3 keys is therefore **best-effort by key string** only. |
| **D** | **OpenTelemetry deferred.** The org standard mandates OpenTelemetry; CSTC-4 uses **structlog JSON to stdout only**. | KISS — CSTC-4 is a single-operator local CLI; OTel infrastructure is unjustified here. Deliberate, documented divergence (see `../agentdocs/architecture.md`). |
| **E** | **Post-validate caveat.** `make validate` is a **PRE**-write-back gate. Running it *after* write-back can flag `already_translated_write` on a defensively-reconciled row. | The defensive-skip reconcile deliberately keeps `*_translation` to preserve step-2 work. Out of the pipeline flow; accepted trade-off (see §6 and `../agentdocs/data-flow.md`). |

## 11. First live run / selector-tuning caveat

> **Operationally important.** The Playwright selectors in
> `src/translation_pipeline/selectors.py` are all marked `# VERIFY-ON-LIVE` and
> the live selector/settle tuning run is **still PENDING** (it is *not* a
> unit-test gate — the unit suite mocks Playwright fully).

The first live `make scrape ARGS='--headed --book year4-sem1'` may require tuning
`selectors.py` constants and the `_wait_for_page_settled` / `_current_part_number`
seams in `site.py` to match the real DOM. Confine any selector change to
`selectors.py`, run it `--headed` against a single book first, and **record any
changed constant** (in `progress.txt` / a follow-up note) before a full run.

## 12. Security

- Credentials only via `IBNBADIS_USERNAME` / `IBNBADIS_PASSWORD` (env or gitignored
  `.env`). `password` is a `SecretStr` — masked in every log and repr.
- `store/translations.json`, `store/*.bak`, `.env` and `screenshots/` are
  gitignored. The store contains **no secrets**.
- Structured logs never contain the password or translation values (only page
  keys, row indices, field names, statuses and counts).
- Never paste credentials into this or any other doc.
