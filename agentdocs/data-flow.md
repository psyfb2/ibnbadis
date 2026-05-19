# Data flow — CSTC-4 translation pipeline

End-to-end:

```text
make scrape           step 2 (no code)            make validate        make writeback
  │  READ-ONLY          │  Claude Code fills          │  PRE-write-back    │  fill UQ/UA,
  ▼  Playwright         ▼  uq/ua_translation          ▼  gate (offline)    ▼  Save once/page
site ──────────► store/translations.json ──────────► (exit 0?) ──────────► site
                                                                            │
                                                  confirmed by  ◄───────────┘
                                              userqanssave.php body ["", true]
```

1. **Scrape** reads each existing row's English `tq/ta` and current site `uq/ua`,
   computes the four per-field flags, and writes the store. No site writes.
2. **Step 2 (no code)** — Claude Code fills `uq_translation` / `ua_translation`
   per `../translation-pipeline/docs/step-2-translation-procedure.md`.
3. **Validate** — offline, credential-free gate. Exit `0` ⇒ proceed.
4. **Write-back** fills `UQ{N}` / `UA{N}` by row index, Saves once per page, and
   confirms persistence via the `userqanssave.php` POST body `["", true]`.

## Store schema summary

`store/translations.json` is a single JSON object keyed by the flat page-key
string `"<book-key>/<section-slug>/page-<NN>"`. `models.py` is the source of
truth; this is a high-level summary only.

- **`Page`**: `rows: list[Row]` (ordered — **the list index is the 0-based row
  index**, there is no explicit index field); `writeback_status`
  (`pending` | `success` | `failed`); `writeback_error`; `writeback_timestamp`
  (ISO-8601 UTC); `skip_reason` (e.g. `"no_english_qa"`).
- **`Row`**: `tq` / `ta` (English source, read-only); `uq` / `ua` (site values as
  captured at scrape time); `uq_translation` / `ua_translation` (Arabic to write,
  filled in step 2); four **independent** per-field flags
  `uq_already_translated` / `uq_needs_translation` /
  `ua_already_translated` / `ua_needs_translation`.

The page key is **only** the dict key — it is never duplicated inside `Page`.

## Per-field decision logic

UQ and UA are decided **independently** per row, using the single whitespace-aware
blank rule (`value.strip() == ""`) shared by scrape, validate and write-back:

- `*_needs_translation` ⟺ the English source is non-blank **and** the site target
  is blank.
- `*_already_translated` ⟺ the site target is non-blank.
- Step 2 fills `*_translation` only where `*_needs_translation` is true.
- Write-back writes a field iff `*_needs_translation` **and** `*_translation` is
  non-blank.

## Resume / idempotency model

- The store is written **atomically after every page** (`store.py`: temp file +
  `fsync` + `os.replace`, previous good copy kept as `.bak`). Any step is
  kill/restart safe — restart resumes from the on-disk store.
- **Merge-refresh on re-scrape**: a re-run refreshes `tq/ta/uq/ua`, the four
  flags and `skip_reason` from live data, but **preserves** `uq_translation` /
  `ua_translation` (by row index) and `writeback_status` / `writeback_error` /
  `writeback_timestamp`. Rows are rebuilt fresh each scrape (never appended → no
  duplicate rows). Re-running scrape after step 2/3 never destroys translations or
  write-back progress. Scrape is refresh/add-only — it never prunes store keys it
  did not revisit and never sets `writeback_status`.
- **Write-back** is resumable: only `pending` / `failed` pages are re-acted; only
  `success` is terminal/skipped (including the "nothing to do" success — a page
  with nothing to fill is marked terminal `success` without Saving). An empty
  form is never submitted; a filled-form 5xx is retried exactly once.

## Cross-reference with CSTC-3

Cross-referencing CSTC-4 store keys with CSTC-3 `state/` keys is **best-effort by
the page-key string only**. The files are independent. CSTC-3 uses hand-made
special section slugs (`dictionary`, `ending`, `pictionary-and-alphabet`) that
CSTC-4 cannot reproduce algorithmically; CSTC-4 deterministically uses
`section-{1-based-index}-{slug}` (+ optional `/part-{n}`) for both scrape and
write-back, so CSTC-4 is internally consistent but a 1:1 key match with CSTC-3 is
not guaranteed (divergence **C** in `architecture.md`).

## Post-validate caveat (divergence E)

`make validate` is a **PRE-write-back** gate (run after step 2, before
write-back). The write-back defensive no-overwrite guard, when it skips a field
that turned non-blank on the site between scrape and write-back, reconciles the
store row in-place **but deliberately keeps `*_translation`** so step-2 work is
preserved. Consequently, running `make validate` *after* write-back can flag
`already_translated_write` on such a row. This is **out of the pipeline flow** and
an accepted, documented trade-off — do not use a post-write-back validate as a
correctness check.
