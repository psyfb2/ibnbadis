# RUNBOOK — Automated Q&A data entry on myquds.ibnbadis.org

This is the procedure a Claude Code agent follows for **one book / one semester** per session. Source ticket: [CSTC-3](https://fadyai.atlassian.net/browse/CSTC-3).

---

## 0. Inputs

| Argument | Values | Meaning |
|---|---|---|
| `<year>` | 4 \| 5 \| 6 | Year 4 / 5 / 6 English |
| `<semester>` | 1 \| 2 | Semester 1 = "Book A" tab, Semester 2 = "Book B" tab |

Derived:
- **Book key**: `year{N}-sem{N}` (e.g. `year4-sem1`) — used as the top-level key in `state/state.json` and the folder name in `state/extracted/`.

## 1. Tools

- `playwright-cli` skill — for all browser actions (navigation, clicks, hovers, screenshots, reading input values, filling fields).
- `Read` tool — for inspecting page screenshots when extracting Q&A.
- `Edit` / `Write` — for updating `state/state.json` and writing per-page audit JSON.

Use a single, persistent browser context for the whole session. Headed mode is fine.

## 2. Login

1. Navigate to `https://myquds.ibnbadis.org/`.
2. Fill the login form: username `fadi`, password `fadi2025`.
3. Click the login button (Arabic label: شغول / دخول).
4. Verify you land on the user's books listing page (the table with Year 4 / 5 / 6 English rows).

## 3. Select book

1. On the books listing page, set the semester dropdown to match `<semester>`:
   - 1 → الفصل 1
   - 2 → الفصل 2
2. The book table updates. Click the row whose title is `Year <year> English` (e.g. `Year 4 English A`).
3. You should now see the e-book viewer: sidebar with sections/parts on the left, page image on the right, page navigation arrows at the top.

## 4. Per-page loop

Walk the book in **section order from the sidebar, top to bottom**. Inside each section, use the **top-bar page arrows** to step pages sequentially. The navigator usually advances from the last page of one section into the first page of the next on its own; verify against the sidebar.

For each page:

### 4.1 Resume check
1. Read `state/state.json`.
2. Compute `page_key = "<book-key>/<section-slug>/page-<NN>"` where:
   - `<section-slug>` is a stable kebab-case slug from the sidebar (e.g. `section-1-a-new-friend/part-1`).
   - `<NN>` is the page number shown on the page (zero-padded to 2 digits, e.g. `04`).
3. If `page_key` is already in `state["<book-key>"].completed_pages`, click next-page and skip to the next iteration.

### 4.2 Screenshot the page
Take a clean screenshot of the right-pane page image (just the e-book content, not the surrounding UI). Save it under a scratch path (e.g. `/tmp/cstc3/<page_key>.png`) so it can be `Read`.

### 4.3 Open the TextApps editor
1. Hover the spanner / wrench icon in the top-left (the "Admin & Dev" trigger).
2. In the panel that appears, click **Data iBook (Text Entry)** under the "Data Entry" group.
3. A modal opens. Click the **TextApps** tab in the top bar (it sits between "BoosterApps" and the next tab).

### 4.4 Read existing rows
The TextApps panel shows rows with four fields (rightmost two columns are English): **Page Questions** and **Page Answers**. For each existing row, read both values. Store as `existing_rows: [{q, a}, ...]`. Empty rows count as not-present.

### 4.5 Extract Q&A from the page screenshot
Use `Read` on the saved screenshot. Extract **only genuine question→answer pairs**, typically:
- "Say." or speech-bubble exchanges where one bubble asks and another answers.
- Comprehension questions with their model answers.

**Do NOT extract**:
- Fill-in-the-blank exercises (no canonical answer on the page).
- Multiple-choice prompts (the answer is selected, not written).
- Vocabulary lists or labels.
- Instructions to the student ("Read.", "Listen and write.").

Worked example from the ticket (page "A new friend"): the only valid pairs are
1. Q: "How many brothers / sisters do you have?" — A: "I have a brother."
2. Q: "How old is your brother?" — A: "He's ten."

Be conservative — when in doubt, skip the row rather than invent.

### 4.6 Diff and append
Normalize for comparison: lowercase, collapse whitespace, strip surrounding quotes/punctuation. For each extracted `{q, a}` not present in `existing_rows`:
1. Click the **+** button to add a new row.
2. Fill the new row's **Page Questions** with the English question (verbatim from the page, original casing/punctuation).
3. Fill the new row's **Page Answers** with the English answer (verbatim).
4. Leave the Arabic "Translated Questions" / "Translated Answers" columns blank.

**Never edit, blank, or overwrite an existing row** — even if you think it's wrong.

### 4.7 Save
1. Click the **Save** button (top-right of the TextApps panel).
2. Wait up to 5 seconds for the button to flash green (success indicator per the ticket).
3. If it does NOT turn green within the timeout → treat as a server error:
   - Append `{page_key, error: "save_failed", timestamp}` to `state["<book-key>"].errors`.
   - Do **not** add the page to `completed_pages`.
   - Skip to step 4.9 (close & advance).

### 4.8 Persist audit log + completion
1. Write `state/extracted/<book-key>/<section-slug>/page-<NN>.json`:
   ```json
   {
     "page_key": "...",
     "timestamp": "ISO-8601 UTC",
     "existing_rows": [{"q": "...", "a": "..."}],
     "extracted_rows": [{"q": "...", "a": "..."}],
     "appended_rows": [{"q": "...", "a": "..."}]
   }
   ```
2. Append `page_key` to `state["<book-key>"].completed_pages` in `state/state.json` and write the file immediately. One file-write per page keeps state interrupt-safe.

### 4.9 Close & advance
1. Click **إغلاق** (close) on the modal.
2. Click **Close** on the "Admin & Dev" sidebar.
3. Click the next-page arrow on the top bar. If you've just finished the last page of the section, verify the sidebar highlights the next section; otherwise click that section's first page.

## 5. Termination

Stop the loop when:
- You've processed the final page of the last section in the sidebar (e.g. "Ending"), **or**
- Context budget feels constrained — the next session resumes from `state.json`.

End the session. The user re-invokes `/fill-ebook` for the next book in a fresh session.

## 6. Gotchas

- **Always click Save before closing the modal.** Per the ticket, unsaved work is lost.
- **Right-to-left UI.** The visual layout is mirrored; "rightmost column" in English-reading terms means the leftmost in DOM order. Confirm by reading element text, not position.
- **Page numbers vs. sidebar order.** Sections can share or repeat page numbers. The `page_key` includes the section slug, so duplicates across sections are fine.
- **Page already 100% filled.** If `existing_rows` already covers everything you extracted, append nothing — still click Save (or skip Save if it's disabled), write the audit JSON (empty `appended_rows`), and mark complete.
- **Server save errors are real** (called out in the ticket). Don't retry blindly in-session; record in `errors[]` and move on. The user can re-run for that book to retry failures.
- **Empty forms always 5xx.** The save endpoint (`submitForms`) returns a 5xx error whenever the form has zero non-empty rows. This is **client-observable as a red Save button** and a console error. Practical consequence: pages with no canonical Q→A on them (pure exercises — fill-in-blank, multiple choice, T/F, matching, write-aloud, handwriting, narrative-only passages) cannot be persisted through this interface. Process them per `4.5`/`4.6` (extracted = []), click Save once, expect red, log as `save_failed` in `errors[]`, and move on. Do **not** invent Q&A to satisfy validation.
- **One retry for transient 5xx on filled forms.** When the form has filled rows and Save still goes red, the cause is often a one-off server 5xx (not validation). A single retry is worth attempting before recording the page as failed — observed success rate is high. Click Save a second time; if still red, then log to `errors[]`. Do not retry more than once.
- **Save button colour is authoritative.** Green = persisted. Red = not persisted (regardless of reason). The button state is the only reliable signal — don't rely on console messages alone, but `console error` from playwright-cli will confirm whether it was a 5xx (server) vs. client validation when diagnosing.
