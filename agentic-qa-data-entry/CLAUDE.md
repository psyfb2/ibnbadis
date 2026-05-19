# ibnbadis — Q&A data-entry automation for myquds.ibnbadis.org

Automates the manual chore of entering page-by-page questions and answers into the "Data iBook (Text Entry) → TextApps" form on https://myquds.ibnbadis.org/ for the books assigned to user `fadi`.

## How to run

This is **not** a script. Each book is processed by a fresh Claude Code session driving the `playwright-cli` skill. Invoke per book/semester:

```
/fill-ebook <year> <semester>
```

- `<year>` ∈ {4, 5, 6} — Year 4 / 5 / 6 English
- `<semester>` ∈ {1, 2} — semester 1 (Book A) or semester 2 (Book B)

Six total sessions cover all assigned books. Sessions are isolated to avoid context rot.

## Key files

- `RUNBOOK.md` — the procedure the agent follows step-by-step. Single source of truth for the data-entry flow.
- `.claude/commands/fill-ebook.md` — the slash command. Loads the runbook and pins the agent to one book/semester.
- `state/state.json` — resume state per book key (`year{N}-sem{N}`). Updated after every page.
- `state/extracted/<book-key>/<section-slug>/page-<NN>.json` — off-site audit log of what was extracted and appended.

## Credentials

Login `fadi` / `fadi2025` for the target site. Reference Jira CSTC-3 — never commit the password.

## Source ticket

CSTC-3 on fadyai.atlassian.net — has six screenshots of each UI stage and the worked Q&A extraction example.

## Important guarantees

- Existing rows on the site are **never** modified — only missing Q&A are appended via the "+" button.
- State is persisted after every page, so any session can be killed and resumed.
- A page is only marked complete after the Save button confirms green; save failures go to `state.errors[]`.
