---
description: Run one session of the CSTC-3 Q&A data-entry automation for a single book/semester
argument-hint: <year:4|5|6> <semester:1|2>
---

You are running **CSTC-3**: automated Q&A data entry on https://myquds.ibnbadis.org/ for user `fadi`.

**Arguments passed in**: `$ARGUMENTS` — expected format: `<year> <semester>` (e.g. `4 1`).

## Your task

1. Parse `$ARGUMENTS` into `<year>` and `<semester>`. Validate `<year> ∈ {4,5,6}` and `<semester> ∈ {1,2}`. If invalid, stop and ask the user.
2. Read `RUNBOOK.md` in this repo end-to-end. It is the authoritative procedure — follow it exactly.
3. Read `state/state.json` and determine the resume point for book key `year<year>-sem<semester>`.
4. Use the `playwright-cli` skill for **all** browser interactions. Use `Read` to inspect page screenshots for Q&A extraction.
5. Process pages one at a time, persisting `state/state.json` after every page (interrupt-safe).
6. Stop at the end of the book or when context budget gets tight. The user will re-invoke for the next book.

## Non-negotiables

- **Never modify or delete existing rows** on the site — only append missing Q&A.
- **Always click Save** and verify the green confirmation before marking a page complete. If it doesn't go green, record the page under `state["<book-key>"].errors[]` and move on.
- **Persist `state.json` after every page** so the session is resumable from any crash point.
- **English-only**: fill `Page Questions` and `Page Answers` columns. Leave the Arabic "Translated" columns blank.

Begin by reading `RUNBOOK.md`.
