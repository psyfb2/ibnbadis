"""Deterministic **READ-ONLY** Playwright site/navigation module.

Shared by ``scrape.py`` and ``writeback.py``. It can log in, select a book,
walk the sidebar ``Section -> Part`` tree (each Part is a separate
``content.php?gid=…`` page covering a global page range), step pages, open/close
the TextApps panel and *read* the grid rows by ``name``.

Live model (verified 2026-05-19 — see ``docs/live-selectors-tuning.md``)
-----------------------------------------------------------------------
* The post-login books listing lists all six books as exact links
  ``"Year N English A|B"`` (A = semester 1, B = semester 2) — no semester
  dropdown is involved.
* The viewer sidebar is an ordered tree: ``SECTION`` header spans, each
  followed by its ``Part`` anchors. Every Part anchor navigates to its own
  ``content.php?gid=…`` URL. The sidebar carries NO page range (each Part's
  ``data-name`` is the literal ``"X"`` and its text is just a label); the
  range is discovered live from the loaded Part's pager — a ``<ul>`` of
  ``<a href="#pageN">`` links whose text is the GLOBAL page number, the
  ``currentpage`` link being the page in view and the ``#next`` arrow
  gaining ``disabled`` on the Part's last page. Page numbers are globally
  sequential (never reset per part) so composed keys never collide. This
  replaces CSTC-3's "active sidebar highlight" heuristic with a fully
  deterministic walk (divergence C: ``part`` is always ``None`` —
  :meth:`_current_part_number` is a documented stub, so no ``/part-`` segment
  is ever emitted).
* The TextApps grid + Save button live inside a **cross-origin iframe**
  (``dev.ibnbadis.org/exp_entry.php``); reads happen through a Playwright
  ``frame_locator`` (the automation driver is not bound by same-origin policy).

Interface segregation (a hard requirement): this module contains **zero**
write/fill/Save code and never imports :mod:`translation_pipeline.write_helper`,
so the scrape path provably cannot mutate the site. ``browser_session`` is the
only place a real Chromium is launched; unit tests mock Playwright entirely.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urljoin

from playwright.sync_api import FrameLocator, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from translation_pipeline.config import Settings, get_settings
from translation_pipeline.logging_config import get_logger
from translation_pipeline.models import RowFields
from translation_pipeline.page_keys import book_key, compose_page_key, section_slug
from translation_pipeline.selectors import (
    ADMIN_DEV_TRIGGER_SELECTOR,
    ADMIN_MODAL_CLOSE_SELECTOR,
    ADMIN_PANEL_CLOSE_SELECTOR,
    BOOK_LINK_NAME_TMPL,
    DATA_IBOOK_SELECTOR,
    DEFAULT_TIMEOUT_MS,
    LISTING_READY_SELECTOR,
    LOGIN_PASSWORD_SELECTOR,
    LOGIN_SUBMIT_SELECTOR,
    LOGIN_USERNAME_SELECTOR,
    PAGE_CURRENT_SELECTOR,
    PAGE_LIST_SELECTOR,
    PAGE_NEXT_ARROW_SELECTOR,
    PAGE_NEXT_DISABLED_SELECTOR,
    ROW_INPUT_CSS,
    SEMESTER_BOOK_SUFFIX,
    SEMESTER_SELECT_SELECTOR,
    SEMESTER_SELECT_VALUE,
    SIDEBAR_PART_HREF_RE,
    SIDEBAR_SECTION_SELECTOR,
    SIDEBAR_TITLE_ATTR,
    SIDEBAR_TREE_SELECTOR,
    TEXTAPPS_IFRAME_SELECTOR,
    TEXTAPPS_TAB_TEXT,
    Field,
    parse_field_name,
)

_log = get_logger(__name__)

#: JS predicate for the page-step settle wait: true once the page-number
#: element exists and its trimmed text differs from the value snapshotted
#: before the next-arrow click. The snapshot-before-click contract is fixed.
_PAGE_SETTLE_JS = (
    "([sel, prev]) => {"
    " const el = document.querySelector(sel);"
    " return el !== null && (el.textContent || '').trim() !== prev;"
    " }"
)


class SiteError(RuntimeError):
    """Base error for any site/navigation failure."""


class LoginError(SiteError):
    """Login did not land on the books listing."""


class NavigationError(SiteError):
    """Semester/book/section/page navigation failed."""


class PanelError(SiteError):
    """The TextApps panel could not be opened/read."""


@dataclass(frozen=True)
class PageContext:
    """Identifies the page currently shown in the viewer."""

    book_key: str
    section_index: int  # 1-based sidebar Section ordinal
    section_title: str
    part_number: int | None  # always None (divergence C)
    page_number: int
    page_key: str


@dataclass(frozen=True)
class _SidebarUnit:
    """One navigable sidebar Part (a ``content.php?gid=…`` page).

    The sidebar exposes NO page range (every Part's ``data-name`` is the
    literal ``"X"``); the range is discovered live by walking the loaded
    Part's pager, so this unit only carries its identity + Section grouping.
    """

    section_index: int
    section_title: str
    href: str


class SiteNavigator:
    """READ-ONLY navigation over the ibnbadis ebook viewer.

    The Playwright ``Page`` is dependency-injected so the class never
    constructs a browser and is trivial to unit-test with a mock.
    """

    def __init__(self, page: Page, settings: Settings | None = None) -> None:
        self._page = page
        # Resolve eagerly so both ``None`` callers and monkeypatched-env tests
        # work without a ``NoneType`` access later.
        self._settings = settings if settings is not None else get_settings()

    @property
    def page(self) -> Page:
        """The injected Playwright page (read accessor for write-back).

        Exposing the already-injected page adds **no** write surface to this
        module: every side-effecting primitive still lives solely in
        :mod:`translation_pipeline.write_helper` (imported only by write-back).
        """
        return self._page

    # --- Authentication ----------------------------------------------------
    def login(self) -> None:
        """Log in with the env-supplied credentials.

        The password is read from :class:`Settings` only at the point of
        ``page.fill`` and is never logged or stored.
        """
        s = self._settings
        _log.info("login_attempt", username=s.username, base_url=s.base_url)
        self._page.goto(s.base_url)
        self._page.fill(LOGIN_USERNAME_SELECTOR, s.username)
        # Secret used here ONLY; never logged/stored.
        self._page.fill(LOGIN_PASSWORD_SELECTOR, s.password.get_secret_value())
        # Submit is <input type="submit">; its label is a ``value`` attribute,
        # so it must be addressed by selector, not by visible text.
        self._page.click(LOGIN_SUBMIT_SELECTOR)
        try:
            # Presence probe (login OK), not interaction: the listing has many
            # book links and the first in DOM order may be hidden, so wait for
            # ATTACHED, not visible.
            self._page.wait_for_selector(
                LISTING_READY_SELECTOR, state="attached", timeout=DEFAULT_TIMEOUT_MS
            )
        except PlaywrightTimeoutError as exc:
            raise LoginError("login did not reach the books listing") from exc
        _log.info("login_ok", username=s.username)

    # --- Book selection ----------------------------------------------------
    def select_book(self, year: int, semester: int) -> str:
        """Open the ``Year <N> English A|B`` book and return its book key.

        The listing IS semester-filtered: a semester's book rows live in
        ``<tr style="display:none">`` until the ``#changeYear`` ("الفصل")
        ``<select>`` is set to that semester's option value, so the semester
        MUST be selected before the (otherwise hidden, unclickable) book link.
        ``A`` = semester 1, ``B`` = semester 2.
        """
        bk = book_key(year, semester)  # validates year/semester
        suffix = SEMESTER_BOOK_SUFFIX[semester]
        name = BOOK_LINK_NAME_TMPL.format(year=year, suffix=suffix)
        # Reveal this semester's rows first (sem-2 rows are display:none by
        # default); select_option fires the change handler that re-filters.
        self._page.select_option(SEMESTER_SELECT_SELECTOR, SEMESTER_SELECT_VALUE[semester])
        self._page.get_by_role("link", name=name, exact=True).first.click()
        try:
            # Presence probe (viewer loaded): the sidebar may be collapsed, so
            # wait for ATTACHED rather than visible.
            self._page.wait_for_selector(
                SIDEBAR_SECTION_SELECTOR, state="attached", timeout=DEFAULT_TIMEOUT_MS
            )
        except PlaywrightTimeoutError as exc:
            raise NavigationError(f"book viewer for {bk!r} did not load") from exc
        _log.info("book_selected", book_key=bk)
        return bk

    # --- Sidebar Section -> Part tree --------------------------------------
    def _parse_sidebar_units(self) -> list[_SidebarUnit]:
        """Parse the sidebar into an ordered list of navigable Part units.

        Walks ``SECTION`` header spans and ``Part`` anchors in DOM order. Each
        Part is attributed to the nearest preceding Section; a Part with no
        preceding Section (e.g. a leading ``"xxxxx 1 - 2"``) becomes its own
        Section using its own label. Section ordinals are 1-based and stable
        for both scrape and (future) write-back, so keys are deterministic.
        """
        units: list[_SidebarUnit] = []
        section_index = 0
        section_title: str | None = None
        for el in self._page.query_selector_all(SIDEBAR_TREE_SELECTOR):
            tag = (el.evaluate("e => e.tagName") or "").upper()
            label = (el.get_attribute(SIDEBAR_TITLE_ATTR) or el.text_content() or "").strip()
            if tag != "A":  # a SECTION header span
                section_index += 1
                section_title = label
                continue
            href = el.get_attribute("href") or ""
            if SIDEBAR_PART_HREF_RE.search(href) is None:
                continue  # a skip-nav link sharing the path (#fragment) — ignore
            if section_title is None:  # orphan Part before any Section header
                section_index += 1
                title = label
            else:
                title = section_title
            units.append(_SidebarUnit(section_index=section_index, section_title=title, href=href))
        if not units:
            raise NavigationError("no navigable sidebar Part links found")
        return units

    def _next_disabled(self) -> bool:
        """True iff the forward page-step arrow carries class ``disabled``.

        A *multi-page* Part marks ``#next`` ``disabled`` on its last page.
        (A single-page Part's ``#next`` is plain — see :meth:`_at_last_page`.)
        """
        return self._page.query_selector(PAGE_NEXT_DISABLED_SELECTOR) is not None

    def _at_last_page(self) -> bool:
        """True iff the viewer is on the current Part's LAST page.

        Two verified-live pager shapes: a multi-page Part marks ``#next``
        ``disabled`` on its last page; a single-page Part has exactly one
        page link, **no** ``currentpage`` marker and a plain (non-
        ``prevnext``) ``#next`` — there is nowhere to step, so its sole page
        is also its last. Either shape ends the Part.
        """
        if self._next_disabled():
            return True
        if self._page.query_selector(PAGE_CURRENT_SELECTOR) is None:
            return len(self._page.query_selector_all(PAGE_LIST_SELECTOR)) == 1
        return False

    def iter_book_pages(self, book_key: str) -> Iterator[PageContext]:
        """Walk every page of the current book, Part by Part, front-to-back.

        A single forward generator consumed by BOTH scrape (read each page) and
        write-back (act per page). Navigates to each Part's gid URL (which
        lands on its first page) and steps with the next-arrow until that arrow
        is ``disabled`` (the authoritative end-of-Part signal — the sidebar
        carries no page range). A Part whose pager never appears is a
        no-content placeholder (e.g. the dashed "xxxxx" intro) and is skipped,
        not fatal. Page numbers are global and sequential so keys never collide.
        """
        units = self._parse_sidebar_units()
        for unit in units:
            self._page.goto(urljoin(self._settings.base_url, unit.href))
            try:
                self._page.wait_for_selector(
                    PAGE_LIST_SELECTOR, state="attached", timeout=DEFAULT_TIMEOUT_MS
                )
            except PlaywrightTimeoutError:
                # No pager => a placeholder Part with no real pages. Skip it
                # (resumable, non-fatal) rather than abort the whole book.
                _log.warning("part_has_no_pages", href=unit.href)
                continue
            page_number = self._current_page_number()
            while True:
                part = self._current_part_number()
                slug = section_slug(unit.section_index, unit.section_title, part)
                yield PageContext(
                    book_key=book_key,
                    section_index=unit.section_index,
                    section_title=unit.section_title,
                    part_number=part,
                    page_number=page_number,
                    page_key=compose_page_key(book_key, slug, page_number),
                )
                if self._at_last_page():
                    break  # last page of the Part (multi- or single-page)
                self._page.click(PAGE_NEXT_ARROW_SELECTOR)
                self._wait_for_page_settled(str(page_number))
                advanced = self._current_page_number()
                if advanced <= page_number:
                    # Did not advance (stuck nav): stop this Part rather than
                    # loop forever — scrape is resumable, so a re-run retries.
                    _log.warning("page_did_not_advance", href=unit.href, page_number=page_number)
                    break
                page_number = advanced

    # --- TextApps panel (inside the cross-origin iframe) -------------------
    def _textapps_frame(self) -> FrameLocator:
        """A ``FrameLocator`` for the cross-origin TextApps iframe."""
        return self._page.frame_locator(TEXTAPPS_IFRAME_SELECTOR)

    def open_textapps(self) -> None:
        """Open Admin & Dev -> Data iBook (Text Entry) -> TextApps tab.

        The grid lives in a cross-origin iframe; this clicks the parent-page
        triggers, then switches into the frame to select the TextApps tab and
        waits for the grid inputs. The readiness wait is for the ATTACHED
        state, **not** visible: the live form's first input is the Arabic
        ``UQ0`` (*Translated Questions*) field, which the RTL layout renders
        ``hidden`` by default — yet it (and every UQ/UA/TQ/TA) is fully
        readable by ``read_rows`` (addressed by ``name``; ``input_value``
        works on hidden inputs). Waiting for visibility here would wrongly
        time out on every page. Any failure to reach the grid is a
        :class:`PanelError` (the page is then retried on a later run).
        """
        try:
            self._page.click(ADMIN_DEV_TRIGGER_SELECTOR)
            self._page.click(DATA_IBOOK_SELECTOR)
            frame = self._textapps_frame()
            frame.get_by_text(TEXTAPPS_TAB_TEXT, exact=True).first.click(timeout=DEFAULT_TIMEOUT_MS)
            frame.locator(ROW_INPUT_CSS).first.wait_for(
                state="attached", timeout=DEFAULT_TIMEOUT_MS
            )
        except PlaywrightTimeoutError as exc:
            raise PanelError("TextApps grid did not appear") from exc

    def close_textapps(self) -> None:
        """Close the data-entry modal then the Admin & Dev side menu.

        Best-effort and tolerant: each control is clicked independently and a
        missing/already-closed control is ignored, because the modal MUST be
        dismissed before the page-step arrows become clickable again, and a
        transient close failure must never abort a book.
        """
        for selector in (ADMIN_MODAL_CLOSE_SELECTOR, ADMIN_PANEL_CLOSE_SELECTOR):
            try:
                self._page.locator(selector).first.click(timeout=DEFAULT_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                _log.warning("textapps_close_control_absent", selector=selector)

    def read_rows(self) -> list[RowFields]:
        """Read every grid row, addressing inputs strictly by ``name``.

        Inputs are grouped by their 0-based index parsed from the ``name``
        attribute — never by DOM/visual order, since the UI is right-to-left.
        Inputs whose name is not a ``UQ/UA/TQ/TA{N}`` (e.g. ``Level``,
        ``Subject``, the ``+`` button) are ignored. The result is a dense list
        ``[0..max_index]``; any field absent from the DOM defaults to ``""``.
        Reads run inside the cross-origin TextApps iframe. Performs no writes.
        """
        inputs = self._textapps_frame().locator(ROW_INPUT_CSS)
        by_index: dict[int, dict[Field, str]] = {}
        for el in inputs.all():
            name = el.get_attribute("name")
            if name is None:
                continue
            parsed = parse_field_name(name)
            if parsed is None:
                continue
            field, index = parsed
            by_index.setdefault(index, {})[field] = el.input_value()

        if not by_index:
            return []
        return [
            RowFields(
                tq=by_index.get(i, {}).get(Field.TQ, ""),
                ta=by_index.get(i, {}).get(Field.TA, ""),
                uq=by_index.get(i, {}).get(Field.UQ, ""),
                ua=by_index.get(i, {}).get(Field.UA, ""),
            )
            for i in range(max(by_index) + 1)
        ]

    # --- Internal helpers --------------------------------------------------
    def _current_page_number(self) -> int:
        el = self._page.query_selector(PAGE_CURRENT_SELECTOR)
        if el is None:
            # A single-page Part does not mark its lone page link
            # ``currentpage``; that sole link IS the current page.
            links = self._page.query_selector_all(PAGE_LIST_SELECTOR)
            if len(links) != 1:
                raise NavigationError("could not read the current page number")
            el = links[0]
        text = (el.text_content() or "").strip()
        try:
            return int(text)
        except ValueError as exc:
            raise NavigationError(f"page number {text!r} is not an int") from exc

    def _current_part_number(self) -> int | None:
        # Divergence C: a stable per-part indicator is not exposed in a form
        # this deterministic walk needs (the gid Part pages already bound the
        # walk by global page range). Always None -> no ``/part-`` segment is
        # emitted; keys stay collision-free because page numbers are global.
        return None

    def _wait_for_page_settled(self, prev_page_text: str) -> None:
        """Block until the page-step after a next-arrow click completes.

        ``page.click`` only auto-waits for the arrow's actionability — not for
        the viewer to swap the page. Without this the next
        ``_current_page_number``/``read_rows`` could read STALE values.

        Strategy: block until the page-number indicator's text differs from
        ``prev_page_text`` (snapshotted *before* the click), then settle on a
        network/DOM load-state backstop. Each wait is bounded by
        ``DEFAULT_TIMEOUT_MS``; a page-number wait that times out is logged and
        tolerated so a single mismatch degrades to the load-state backstop
        rather than aborting the book — a genuinely stale read then surfaces
        downstream (and ``iter_book_pages`` independently breaks the Part if
        the number did not advance).
        """
        try:
            self._page.wait_for_function(
                _PAGE_SETTLE_JS,
                arg=[PAGE_CURRENT_SELECTOR, prev_page_text],
                timeout=DEFAULT_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            _log.warning("page_number_unchanged_after_advance", prev_page_text=prev_page_text)
        try:
            self._page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            try:
                self._page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                # Bounded + tolerated per this method's contract: never abort
                # the book here. A genuinely stale read surfaces downstream.
                _log.warning("page_load_state_not_settled", prev_page_text=prev_page_text)


@contextmanager
def browser_session(
    *, headless: bool = True, settings: Settings | None = None
) -> Iterator[SiteNavigator]:
    """Launch Chromium, yield a :class:`SiteNavigator`, guarantee teardown.

    Runtime-only (requires ``make install-browsers``). Unit-tested with
    ``sync_playwright`` patched so no real browser/network is used.
    """
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=headless)
        try:
            context = browser.new_context(locale="ar")
            page = context.new_page()
            yield SiteNavigator(page, settings)
        finally:
            browser.close()
    finally:
        pw.stop()
