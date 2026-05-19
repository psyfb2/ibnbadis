"""Deterministic **READ-ONLY** Playwright site/navigation module.

Shared by ``scrape.py`` (task 3) and ``writeback.py`` (task 5). It can log in,
select semester/book, walk the sidebar sections and step pages, open/close the
TextApps panel and *read* the grid rows by ``name``.

Interface segregation (a hard requirement): this module contains **zero**
write/fill/Save code and never imports :mod:`translation_pipeline.write_helper`,
so the scrape path provably cannot mutate the site. All side-effecting
primitives live in that separate module, imported only by write-back.

Selectors are best-effort and unverified (see :mod:`translation_pipeline.
selectors`); navigation methods are intent-based so live tuning during tasks
3/5 touches only ``selectors.py``. ``browser_session`` is the only place a real
Chromium is launched and runs only after ``make install-browsers``; unit tests
mock Playwright entirely (no browser, no network).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from translation_pipeline.config import Settings, get_settings
from translation_pipeline.logging_config import get_logger
from translation_pipeline.page_keys import book_key, compose_page_key, section_slug
from translation_pipeline.selectors import (
    ADMIN_PANEL_CLOSE_TEXT,
    BOOK_ROW_TEXT_TMPL,
    DATA_IBOOK_TEXT,
    DEFAULT_TIMEOUT_MS,
    LISTING_READY_SELECTOR,
    LOGIN_PASSWORD_SELECTOR,
    LOGIN_SUBMIT_TEXTS,
    LOGIN_USERNAME_SELECTOR,
    MODAL_CLOSE_TEXT,
    PAGE_NEXT_ARROW_SELECTOR,
    PAGE_NUMBER_ACTIVE_SELECTOR,
    ROW_INPUT_CSS,
    SEMESTER_DROPDOWN_SELECTOR,
    SEMESTER_OPTION,
    SIDEBAR_ACTIVE_CLASS,
    SIDEBAR_SECTION_SELECTOR,
    SPANNER_TRIGGER_SELECTOR,
    TEXTAPPS_TAB_TEXT,
    Field,
    parse_field_name,
)

_log = get_logger(__name__)


class SiteError(RuntimeError):
    """Base error for any site/navigation failure."""


class LoginError(SiteError):
    """Login did not land on the books listing."""


class NavigationError(SiteError):
    """Semester/book/section/page navigation failed."""


class PanelError(SiteError):
    """The TextApps panel could not be opened/closed."""


@dataclass(frozen=True)
class RowFields:
    """One TextApps row as read from the site (all by ``name``, 0-based)."""

    tq: str  # Page Questions   (English, read-only source)
    ta: str  # Page Answers     (English, read-only source)
    uq: str  # Translated Questions (Arabic, write target — value at scrape time)
    ua: str  # Translated Answers   (Arabic, write target — value at scrape time)


@dataclass(frozen=True)
class PageContext:
    """Identifies the page currently shown in the viewer."""

    book_key: str
    section_index: int  # 1-based sidebar position
    section_title: str
    part_number: int | None
    page_number: int
    page_key: str


class SiteNavigator:
    """READ-ONLY navigation over the ibnbadis ebook viewer.

    The Playwright ``Page`` is dependency-injected so the class never
    constructs a browser and is trivial to unit-test with a mock.
    """

    def __init__(self, page: Page, settings: Settings | None = None) -> None:
        self._page = page
        # Resolve eagerly so both ``None`` callers and monkeypatched-env tests
        # work without a ``NoneType`` access later in ``login()``.
        self._settings = settings if settings is not None else get_settings()

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
        self._click_first_by_text(LOGIN_SUBMIT_TEXTS)
        try:
            self._page.wait_for_selector(LISTING_READY_SELECTOR, timeout=DEFAULT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise LoginError("login did not reach the books listing") from exc
        _log.info("login_ok", username=s.username)

    # --- Semester / book ---------------------------------------------------
    def select_semester(self, semester: int) -> None:
        """Select semester 1 or 2 in the dropdown."""
        if semester not in SEMESTER_OPTION:
            raise NavigationError(f"semester must be 1 or 2 (got {semester!r})")
        self._page.select_option(SEMESTER_DROPDOWN_SELECTOR, label=SEMESTER_OPTION[semester])
        _log.info("semester_selected", semester=semester)

    def select_book(self, year: int, semester: int) -> str:
        """Select the ``Year <N> English`` book and return its book key."""
        bk = book_key(year, semester)  # validates year/semester
        self.select_semester(semester)
        self._page.get_by_text(BOOK_ROW_TEXT_TMPL.format(year=year)).first.click()
        _log.info("book_selected", book_key=bk)
        return bk

    # --- Sidebar / page walk ----------------------------------------------
    def sections(self) -> list[tuple[int, str]]:
        """Return ``(1-based index, title)`` for every sidebar section.

        Read by text (RTL-safe), never by visual position.
        """
        out: list[tuple[int, str]] = []
        for idx, el in enumerate(self._page.query_selector_all(SIDEBAR_SECTION_SELECTOR), start=1):
            out.append((idx, (el.text_content() or "").strip()))
        return out

    def iter_book_pages(self, book_key: str) -> Iterator[PageContext]:
        """Walk every page of the current book front-to-back.

        A single forward generator consumed by BOTH scrape (read each page) and
        write-back (act per page); the site has no per-page URL so pages must be
        stepped. Section is derived from the highlighted sidebar entry on each
        page (page numbers repeat across sections, so the section slug
        differentiates the key).
        """
        while True:
            ctx = self._current_page_context(book_key)
            _log.info("page", page_key=ctx.page_key)
            yield ctx
            if not self._advance_to_next_page():
                return

    def current_page_key(self, book_key: str) -> str:
        """The composed flat page key for the page currently shown."""
        return self._current_page_context(book_key).page_key

    # --- TextApps panel ----------------------------------------------------
    def open_textapps(self) -> None:
        """Open spanner -> Data iBook (Text Entry) -> TextApps tab."""
        self._page.hover(SPANNER_TRIGGER_SELECTOR)
        self._page.get_by_text(DATA_IBOOK_TEXT).first.click()
        self._page.get_by_text(TEXTAPPS_TAB_TEXT).first.click()
        try:
            self._page.wait_for_selector(ROW_INPUT_CSS, timeout=DEFAULT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise PanelError("TextApps grid did not appear") from exc

    def close_textapps(self) -> None:
        """Close the modal then the Admin & Dev panel (RUNBOOK §4.9)."""
        self._page.get_by_text(MODAL_CLOSE_TEXT).first.click()
        self._page.get_by_text(ADMIN_PANEL_CLOSE_TEXT).first.click()

    def read_rows(self) -> list[RowFields]:
        """Read every grid row, addressing inputs strictly by ``name``.

        Inputs are grouped by their 0-based index parsed from the ``name``
        attribute — never by DOM/visual order, since the UI is right-to-left.
        Inputs whose name is not a ``UQ/UA/TQ/TA{N}`` (e.g. ``Level``,
        ``Subject``, the ``+`` button) are ignored. The result is a dense list
        ``[0..max_index]``; any field absent from the DOM defaults to ``""``.
        Performs no writes.
        """
        by_index: dict[int, dict[Field, str]] = {}
        for el in self._page.query_selector_all(ROW_INPUT_CSS):
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

    # --- Internal helpers (selector-bound; # VERIFY-ON-LIVE) ---------------
    def _current_page_context(self, book_key: str) -> PageContext:
        sec_index, sec_title = self._current_section()
        part = self._current_part_number()
        page_number = self._current_page_number()
        slug = section_slug(sec_index, sec_title, part)
        key = compose_page_key(book_key, slug, page_number)
        return PageContext(
            book_key=book_key,
            section_index=sec_index,
            section_title=sec_title,
            part_number=part,
            page_number=page_number,
            page_key=key,
        )

    def _current_section(self) -> tuple[int, str]:
        """Return ``(1-based index, title)`` of the highlighted section.

        The active section is identified by its DOM POSITION among the sidebar
        entries combined with the active class — never by matching the title
        text, because sidebar titles can collide (e.g. a repeated "Part 1"),
        which would otherwise always resolve to the first occurrence.
        """
        for idx, el in enumerate(self._page.query_selector_all(SIDEBAR_SECTION_SELECTOR), start=1):
            classes = (el.get_attribute("class") or "").split()
            if SIDEBAR_ACTIVE_CLASS in classes:
                return idx, (el.text_content() or "").strip()
        raise NavigationError("no active sidebar section")

    def _current_page_number(self) -> int:
        el = self._page.query_selector(PAGE_NUMBER_ACTIVE_SELECTOR)
        if el is None:
            raise NavigationError("could not read the current page number")
        text = (el.text_content() or "").strip()
        try:
            return int(text)
        except ValueError as exc:
            raise NavigationError(f"page number {text!r} is not an int") from exc

    def _current_part_number(self) -> int | None:
        # VERIFY-ON-LIVE: part detection is not derivable from the RUNBOOK or
        # screenshots. Default to None (no ``/part-`` segment), which is
        # format-compliant; tune in the task 3/5 integration runs if the live
        # UI exposes a part indicator.
        return None

    def _advance_to_next_page(self) -> bool:
        """Click the next-page arrow; ``False`` at end of book.

        # VERIFY-ON-LIVE: end-of-book detection is ambiguous in the source —
        # treated as "no enabled next arrow".
        """
        arrow = self._page.query_selector(PAGE_NEXT_ARROW_SELECTOR)
        if arrow is None or arrow.is_disabled():
            return False
        arrow.click()
        self._wait_for_page_settled()
        return True

    def _wait_for_page_settled(self) -> None:
        """Wait for the new page's content to settle after a page change.

        ``page.click`` only auto-waits for the arrow's actionability — it does
        NOT wait for the viewer's SPA to swap the page number, the sidebar
        highlight and the grid inputs. Without this, the next
        ``_current_page_context``/``read_rows`` could read stale values from
        the previous page.

        # VERIFY-ON-LIVE: the correct settle strategy (full reload vs SPA DOM
        # swap) is unknown from the RUNBOOK/screenshots. This is the SINGLE
        # seam tasks 3/5 must implement during their live integration runs
        # (e.g. wait_for_load_state, or wait_for_function on the page-number
        # indicator changing). Intentionally a no-op until then so we do not
        # guess a wrong wait that masks the gap.
        """
        return None

    def _click_first_by_text(self, texts: tuple[str, ...]) -> None:
        """Click the first locator whose text matches any of ``texts``."""
        for text in texts:
            locator = self._page.get_by_text(text)
            if locator.count() > 0:
                locator.first.click()
                return
        raise NavigationError(f"no clickable element for any of {texts!r}")


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
