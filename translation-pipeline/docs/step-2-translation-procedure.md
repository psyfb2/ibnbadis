# Step 2 — Manual Translation Procedure (the only *no-code* step)

> **Scope of this document:** the *contract* for the no-code step-2 manual
> translation only. It does **not** describe login, scraping, navigation or
> write-back operations — those live in the project RUNBOOK (assembled
> separately). This document is referenced by, never duplicated into, the
> RUNBOOK. Read it in full before editing the store.

CSTC-4 is a deterministic 3-step pipeline:

1. **Step 1 — scrape** (code): reads the live English Q&A and current site
   translation state into `store/translations.json`.
2. **Step 2 — translation** (THIS doc, *no code*): **Claude Code** reads the
   store and writes consistent Arabic into it.
3. **Step 3 — write-back** (code): pushes the Arabic into the site.

Step 2 is performed directly by Claude Code editing the JSON store. No
translation code is written or run.

---

## 1. What you do in step 2

Read `store/translations.json` and, for every row that needs it, write a
primary-school-register Arabic translation into the **only two writable
fields**: `uq_translation` and `ua_translation`. Save the file as valid UTF-8
JSON with **literal Arabic** (`ensure_ascii=False` — never `\uXXXX` escapes).

---

## 2. Store shape recap

`store/translations.json` is a single JSON object:

```text
{ "<page-key>": Page, ... }
```

- The top-level key is the flat page key
  `"<book-key>/<section-slug>/page-<NN>"` — **do not add, remove or rename
  page keys.**
- `Page.rows` is an ordered array; the array index **is** the 0-based row
  index. **Do not add, remove or reorder rows.**

Each `Row` has:

| Field | Meaning | You may… |
|---|---|---|
| `tq` | Page Question — English source | **READ-ONLY. Never modify.** |
| `ta` | Page Answer — English source | **READ-ONLY. Never modify.** |
| `uq` | Translated Questions value on the site at scrape time | **READ-ONLY. Never modify.** |
| `ua` | Translated Answers value on the site at scrape time | **READ-ONLY. Never modify.** |
| `uq_translation` | Arabic question to write back | **WRITE — your output for UQ** |
| `ua_translation` | Arabic answer to write back | **WRITE — your output for UA** |
| `uq_already_translated` | UQ already has a translation on the site | **READ-ONLY flag. Never modify.** |
| `uq_needs_translation` | UQ has English but no site translation | **READ-ONLY flag. Never modify.** |
| `ua_already_translated` | UA already has a translation on the site | **READ-ONLY flag. Never modify.** |
| `ua_needs_translation` | UA has English but no site translation | **READ-ONLY flag. Never modify.** |

`Page` also has `writeback_status`, `writeback_error`, `writeback_timestamp`,
`skip_reason` — **all read-only in step 2. Never modify them.**

---

## 3. What to fill — UQ and UA decided **independently**

For **each row**, decide each side on its own (a row may need only one side):

- **UQ side:** if `uq_needs_translation` is `true` **and** `uq_translation` is
  blank → translate `tq` into Arabic and put it in `uq_translation`.
- **UA side:** if `ua_needs_translation` is `true` **and** `ua_translation` is
  blank → translate `ta` into Arabic and put it in `ua_translation`.

A field is "blank" if it is empty or whitespace-only (the same whitespace-aware
rule the pipeline uses everywhere).

---

## 4. Hard prohibitions

- **Never** alter `tq`, `ta`, `uq` or `ua` (the English source and the site
  snapshot are read-only).
- **Never** write a translation for a field whose `*_already_translated` flag
  is `true`. Leave `uq_translation` / `ua_translation` blank there — a
  pre-existing partial manual translation on the site must be **preserved**,
  not overwritten.
- **Never** add, remove or reorder rows or pages; **never** change any of the
  per-field flags, `writeback_status`, `writeback_error`,
  `writeback_timestamp` or `skip_reason`.
- Keep the JSON valid and UTF-8 with **literal Arabic**; make **minimal edits**
  (only the `*_translation` fields that need filling).
- Rows/pages with no English (e.g. CSTC-3 has not entered them yet) have
  nothing to translate — leave them untouched.

---

## 5. Quality contract

- **Register:** vocabulary and tone appropriate for **primary-school**
  textbooks; meaning-preserving and natural Arabic.
- **Consistency (PRD req-11):** the **same English source string always maps to
  the same Arabic string** everywhere — within a page, across pages, and across
  all six books. This spans both questions and answers: if an identical English
  string appears as a `tq` on one row and a `ta` on another, both must receive
  the **same** Arabic. Practical guidance: keep a running glossary while you
  work and reuse the exact prior Arabic verbatim on every recurrence so
  translations stay **consistent**.

---

## 6. Verification — `make validate` is the gate before write-back

After step 2 and **before** step-3 write-back, run:

```bash
make validate            # or: make validate ARGS='--store <path>'
```

It is offline and credential-free. **Exit code 0 = ready for write-back.** Any
non-zero exit means the store is **not** ready — fix the reported findings and
re-run until it exits 0. The pipeline must **not** proceed to write-back until
`make validate` exits 0.

The validator reports these codes:

| `ValidationCode` | Meaning | How to fix |
|---|---|---|
| `missing_translation` | A field with `*_needs_translation` has a blank `*_translation`. | Add the Arabic translation for that side. |
| `inconsistent_translation` | The same English source maps to ≥2 different Arabic strings. | Pick one Arabic rendering and apply it to **every** occurrence of that English string. |
| `already_translated_write` | An `*_already_translated` field has a non-blank `*_translation` (would overwrite a pre-existing site translation). | Clear that `*_translation` back to `""` — never overwrite an already-translated field. |
| `source_flag_mismatch` | The stored per-field flags don't match the flags recomputed from `tq/ta/uq/ua` (an English/site field or a flag was changed after scrape). | Do **not** edit `tq/ta/uq/ua` or any flag. Revert the change; if the site genuinely changed, re-run step-1 scrape. |

---

## 7. Re-running step 1 is safe

Re-running the step-1 scrape after step 2 performs a **merge-refresh**: it
refreshes the English source and site state and recomputes the flags, but
**preserves** every `uq_translation` / `ua_translation` you wrote and the
page-level `writeback_status`. Your step-2 work is never destroyed by a
re-scrape, so the pipeline can be re-run as CSTC-3 progressively enters more
English Q&A.

---

## 8. Security

The store contains **no secrets** and is gitignored. Never put credentials,
tokens or any sensitive data into the store or into this/any doc. Site
credentials are supplied only via the `IBNBADIS_*` environment variables.
