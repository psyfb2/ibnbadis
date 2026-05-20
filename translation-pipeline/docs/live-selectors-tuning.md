# Live selector-tuning record (RUNBOOK §11)

First live run performed **2026-05-19** (`fadi`). This is the record RUNBOOK
§11 requires: every changed `selectors.py` constant and the `site.py`
navigation-model change, with the live DOM facts that justified them.

> **2026-05-19 — corrections from the first real scrape run (rounds 2–4).**
> The original pass below was never exercised end-to-end and got four live
> facts wrong; each was found by an actual `make scrape` and fixed:
>
> - **Round 2 — page range.** Assumed each Part anchor's `data-name` encoded
>   `<paper>_<first>_<last>`. **False:** `data-name` is the literal `"X"` and
>   the link text is only the label; the sidebar has **no** page range. It is
>   read live from the loaded Part's pager. Retired
>   `SIDEBAR_PART_DATANAME_ATTR`, `PART_DATANAME_RE`, `PAGE_NUMBER_SELECTOR`
>   and `SiteNavigator._parse_page_range`.
> - **Round 2b — panel grid wait.** `open_textapps` waited for the first grid
>   input to be *visible*, but the live first input (Arabic `UQ0`) is
>   `hidden` by the RTL layout → `PanelError` on every page. Now waits for
>   `state="attached"` (still fully readable by `read_rows`).
> - **Round 3 — single-page Parts.** They render no `currentpage` marker and
>   a plain `#next`; added `_at_last_page()` + a sole-link fallback in
>   `_current_page_number()`.
> - **Round 4 — semester filter.** The listing IS semester-filtered; sem-2
>   ("B") book rows are `display:none` until `#changeYear` is set, so
>   `select_book` now selects the semester before clicking the book link.
>
> The corrected facts are in the rows below and the *Navigation model*
> section. Round-1 fixes (login/iframe/sidebar-tree) remain valid as recorded.

> Scope: the **READ-ONLY scrape path** only. The write-back path
> (`write_helper.py` / `writeback.py`) is **not** covered here — see
> "Write-back not yet tuned" below.

## Why a code change (not just constants) was needed

The shipped `selectors.py` constants were best-effort guesses (`# VERIFY-ON-LIVE`)
and the live site differs **structurally** from what `site.py` assumed:

1. The TextApps grid + Save button live inside a **cross-origin iframe**
   (`#LFrm`, `https://dev.ibnbadis.org/exp_entry.php?...`). The old `site.py`
   queried the top-level page only → it could never see the grid.
2. The book is navigated as a sidebar **Section → Part** tree where each Part
   is its own `content.php?gid=…` page; there is **no "active section" CSS
   class**. The old `_current_section()` (position + `.active`) cannot work.
3. The login submit is `<input type="submit">` — `get_by_text` cannot match an
   input's `value`, so the old text-based submit click could never fire.

So `site.py` navigation was reworked (public API unchanged: `login`,
`select_book`, `iter_book_pages`, `open_textapps`, `read_rows`,
`close_textapps`, `page`, `PageContext`, `browser_session` — so `scrape.py`,
`writeback.py` and their mocked tests are unaffected; only `test_site.py` was
rewritten to the new internal model).

## Verified DOM facts → constant

| Concern | Live DOM fact | `selectors.py` constant |
|---|---|---|
| Login user | `<input type=text name=form_login id=login>` (a decoy hidden `#login` exists) | `LOGIN_USERNAME_SELECTOR='input[type="text"][name="form_login"]'` |
| Login pass | `<input type=password name=form_password id=pass>` | `LOGIN_PASSWORD_SELECTOR='input[type="password"][name="form_password"]'` |
| Login submit | `<input type=submit id=logbutt value="دخول">` | `LOGIN_SUBMIT_SELECTOR='#logbutt'` (replaces `LOGIN_SUBMIT_TEXTS`) |
| Logged-in | books listing has `bounce.php?course=` links | `LISTING_READY_SELECTOR='a[href*="bounce.php?course="]'` |
| Semester filter | **Round-4 correction:** the listing IS filtered. `<select id="changeYear">` (options `الفصل 1`/`الفصل 2`, values `"1"`/`"2"`; the `id` is a misnomer) toggles book rows; a semester's other rows sit in `<tr style="display:none">`. Must be selected before the book link. | `SEMESTER_SELECT_SELECTOR='#changeYear'`, `SEMESTER_SELECT_VALUE={1:'1',2:'2'}` |
| Book pick | links named exactly `Year N English A` (sem 1) / `...B` (sem 2); clickable only **after** the matching semester is selected (sem-2 rows are `display:none` by default — the cause of the round-4 `select_book` 30s click timeout) | `BOOK_LINK_NAME_TMPL`, `SEMESTER_BOOK_SUFFIX` |
| Sidebar section | `<span class="inlineEdits" name="outahgfolder1" title="Section N: …">` | `SIDEBAR_SECTION_SELECTOR` |
| Sidebar tree | section spans + `a[href*="content.php?gid="]` Part links, in DOM order; skip-nav links share the path but carry a `#fragment` | `SIDEBAR_TREE_SELECTOR`, `SIDEBAR_PART_HREF_RE` |
| Page range | **Not in the sidebar** (round-2 correction). `data-name` is the literal `"X"`; link text is only the label. The range is the set of `#pageN` link **texts** on the *loaded Part page*. | *(no sidebar constant — retired `SIDEBAR_PART_DATANAME_ATTR`, `PART_DATANAME_RE`)* |
| Page list / load probe | the pager `<ul>` of `<a href="#pageN" rel="i">`; absent ⇒ a no-content placeholder Part to skip | `PAGE_LIST_SELECTOR='a[href^="#page"]'` |
| Current page | a *multi-page* Part marks the in-view link `class="currentpage"` (text = global page number). **Round-3 fact:** a *single-page* Part (e.g. "Ending") renders its lone `<a href="#page1">` with **no `currentpage` class**, so `_current_page_number` falls back to the sole `PAGE_LIST_SELECTOR` link. | `PAGE_CURRENT_SELECTOR='a[href^="#page"].currentpage'` (replaces `PAGE_NUMBER_SELECTOR`) |
| Next page | `<a href="#next" class="prevnext">»</a>` (a single-page Part's `#next` is **plain** — no `prevnext`/`disabled`) | `PAGE_NEXT_ARROW_SELECTOR='a[href="#next"]'` |
| End of Part | multi-page: `#next` gains class `disabled` (`class="prevnext disabled"`). single-page: no `.currentpage` + exactly one page link. `_at_last_page()` covers **both** (replaces the bare `#next.disabled` check that crashed on single-page Parts). | `PAGE_NEXT_DISABLED_SELECTOR='a[href="#next"].disabled'` |
| Admin&Dev | `<a id="adminTab_" href="javascript:openAdminMenu(1)">` (click, not hover) | `ADMIN_DEV_TRIGGER_SELECTOR='#adminTab_'` (replaces `SPANNER_TRIGGER_SELECTOR`) |
| Data iBook | `<a id="xwcode">Data iBook (Text Entry)</a>` | `DATA_IBOOK_SELECTOR='#xwcode'` |
| TextApps frame | iframe `#LFrm`, URL contains `exp_entry.php` | `TEXTAPPS_IFRAME_SELECTOR`, `TEXTAPPS_FRAME_URL_SUBSTR` |
| TextApps tab | text `TextApps` **inside the iframe** | `TEXTAPPS_TAB_TEXT` (unchanged value; now resolved in-frame) |
| Grid inputs | `input.expinputq` named `UQ/UA/TQ/TA{N}` **inside the iframe**. **Round-2 fact:** the first input (`UQ0`, Arabic *Translated Questions*) is rendered `hidden` by the RTL layout but is fully readable by `read_rows` (by `name`; `input_value` works on hidden inputs). | `ROW_INPUT_CSS` (value unchanged). `open_textapps` grid-ready wait is now `state="attached"` (NOT visible) — a visibility wait timed out on every page (`60 × locator resolved to hidden <input name="UQ0">`). |
| Modal close | `<a id="secondClose" href="javascript:ahgsideshowhide()">إغلاق</a>` | `ADMIN_MODAL_CLOSE_SELECTOR='#secondClose'` |
| Menu close | `<a href="javascript:closeAdminMenu(1)">Close</a>` | `ADMIN_PANEL_CLOSE_SELECTOR='a[href*="closeAdminMenu"]'` |
| Save (write-back) | `<button id="saveAll">Save</button>` inside the iframe | `SAVE_BUTTON_SELECTOR='#saveAll'` (element verified; click/confirm flow NOT yet run) |

`SAVE_ENDPOINT_SUBSTR='userqanssave.php'` confirmed (POST goes to
`dev.ibnbadis.org`).

## Navigation model (divergence C update — round-2 corrected)

`iter_book_pages` parses the sidebar into ordered `_SidebarUnit`s of just
(`section_index`, `section_title`, `href`) — **no page range is read from the
sidebar** (it carries none). For each unit it visits the Part's gid URL
(which lands on its first page); if the pager (`PAGE_LIST_SELECTOR`) never
appears the Part is a no-content placeholder (e.g. the dashed `"xxxxx"`
intro, `gid=…_0_0`) and is **skipped non-fatally** (`part_has_no_pages`
warning) rather than aborting the book. Otherwise it reads the current global
page from the `currentpage` link (or, for a single-page Part, the sole page
link) and steps with the next-arrow until `_at_last_page()` — which covers
**both** a multi-page Part's `#next.disabled` last page **and** a single-page
Part (no `.currentpage`, one page link, plain `#next`) — with a stuck-nav
guard (page number failed to advance) as a resumable backstop. Section ordinals are 1-based in sidebar order; a Part
with no preceding Section header becomes its own Section.
`_current_part_number()` remains a stub returning `None` (divergence C
unchanged — **no `/part-` segment is emitted**), so CSTC-4 keys deliberately
differ from CSTC-3 keys that contain `/part-`; this is the documented,
accepted best-effort cross-reference. Page numbers are global/sequential so
composed keys never collide. (Because the skipped `"xxxxx"` placeholder still
consumes a 1-based Section ordinal, the first real Section is `section-2-…`;
this is internally consistent and deterministic for scrape and write-back.)

## Write-back — reworked in-frame (round 5); live Save flow canary-pending

`write_helper.py` originally filled/saved on the **top-level page**, but the
grid is in the `#LFrm` iframe. It has been **reworked** to operate in-frame
(same `frame_locator` approach as `site.read_rows`):

- `fill_translation` / `read_field_value` / the `save_page` Save click are
  all scoped to `_textapps_frame(page) = page.frame_locator("#LFrm")`.
- The Arabic `UQ`/`UA` cells are **hidden** by the RTL layout (same fact as
  the round-2b panel-wait fix), so `Locator.fill` (visibility-gated) cannot
  be used. `fill_translation` instead sets `.value` and dispatches
  `input`/`change` via `Locator.evaluate` (`_SET_VALUE_JS`) — `evaluate`
  only needs the element ATTACHED, mirroring the read path's
  address-hidden-inputs-by-name rationale.
- `save_page` keeps `page.expect_response` (page-level capture sees
  sub-frame requests); only the `#saveAll` click moved in-frame. Success is
  still keyed strictly off the `userqanssave.php` body (`["", true]`).

All of the above is unit-tested (Playwright fully mocked). The live Save flow
was first confirmed by a one-page canary on `year4-sem1/.../a-new-friend/page-04`
(`["", true]`), then **VERIFIED-LIVE end-to-end (2026-05-19) by the full
multi-book write-back**: all 6 books, **398/398 pages terminal
`writeback_status="success"`** (the canary resume-skipped, 397 freshly
written), **843 `UQ`/`UA` fields** filled across the 109 content pages, **0
failed / 0 rejected / 0 server-error retries / 0 defensive overwrite-skips /
0 panel errors**. Only warnings: 6× `part_has_no_pages` (one per book —
benign single-page-Part-with-no-pager). So `SAVE_BUTTON_SELECTOR='#saveAll'`,
the in-frame click, and the `_SET_VALUE_JS` hidden-input fill are now
**VERIFIED-LIVE at full scale**; every remaining `# VERIFY-ON-LIVE-WRITEBACK`
marker is confirmed.
