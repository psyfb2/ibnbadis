"""Centralized selectors, labels, timeouts and TextApps field helpers.

This module is **pure**: it imports no Playwright and performs no I/O. It is the
single place where every CSS/text selector lives so that, when selectors are
tuned against the live site during integration runs, only this file changes.

Live verification
-----------------
The constants below were **verified against the live site on 2026-05-19**
(`VERIFIED-LIVE`) during the RUNBOOK §11 first-live-run selector-tuning pass.
The full live DOM map and the navigation-model findings are recorded in
``docs/live-selectors-tuning.md``. A handful of constants that are only
exercised by the (still-unrun) write-back path remain best-effort and are
marked ``# VERIFY-ON-LIVE-WRITEBACK``.

Confirmed field mapping (authoritative — verified live + screenshot
``textapps-translated-fields.png``):

===========  ================================  ========  ====================
``name``     Column                            Language  Role for CSTC-4
===========  ================================  ========  ====================
``UQ{N}``    Translated Questions              Arabic    WRITE target
``UA{N}``    Translated Answers                Arabic    WRITE target
``TQ{N}``    Page Questions                    English   READ-ONLY source
``TA{N}``    Page Answers                      English   READ-ONLY source
===========  ================================  ========  ====================

All four are ``<input class="expinputq">`` addressed strictly by ``name``,
**0-based**, never by visual position (the UI is right-to-left). They live
inside a **cross-origin iframe** (``dev.ibnbadis.org/exp_entry.php``); see
:data:`TEXTAPPS_FRAME_URL_SUBSTR`.
"""

from __future__ import annotations

import re
from enum import StrEnum


class Field(StrEnum):
    """Every addressable TextApps grid field by its ``name`` prefix."""

    UQ = "UQ"  # Translated Questions  (Arabic, write target)
    UA = "UA"  # Translated Answers    (Arabic, write target)
    TQ = "TQ"  # Page Questions        (English, read-only source)
    TA = "TA"  # Page Answers          (English, read-only source)


class TargetField(StrEnum):
    """The write targets only (Arabic translation columns).

    Deliberately an *independent* ``StrEnum`` (no inheritance from
    :class:`Field`) so passing a :class:`TargetField` where a :class:`Field` is
    expected (or vice-versa) is a static type error — the write-helper guard is
    therefore enforced by ``mypy`` as well as at runtime.
    """

    UQ = "UQ"
    UA = "UA"


#: Matches a TextApps input ``name`` like ``UQ0`` / ``TA12`` (0-based index).
FIELD_NAME_RE: re.Pattern[str] = re.compile(r"^(UQ|UA|TQ|TA)(\d+)$")

#: Enumeration selector for every grid input on a page. VERIFIED-LIVE.
ROW_INPUT_CSS = "input.expinputq"


def field_name(field: Field | TargetField, index: int) -> str:
    """Return the ``name`` attribute for ``field`` at 0-based ``index``.

    Args:
        field: a :class:`Field` or :class:`TargetField` (only ``.value`` used,
            so the union is accepted without a ``# type: ignore``).
        index: 0-based row index.

    Raises:
        ValueError: if ``index`` is negative.
    """
    if index < 0:
        raise ValueError(f"row index must be >= 0 (got {index!r})")
    return f"{field.value}{index}"


def parse_field_name(name: str) -> tuple[Field, int] | None:
    """Parse a grid input ``name`` into ``(Field, 0-based index)``.

    Returns ``None`` for anything that is not a ``UQ/UA/TQ/TA{N}`` name (e.g.
    the ``Level``/``Subject`` inputs or the ``+`` button), so callers can simply
    skip non-matching inputs.
    """
    match = FIELD_NAME_RE.match(name)
    if match is None:
        return None
    return Field(match.group(1)), int(match.group(2))


def field_input_css(field: Field | TargetField, index: int) -> str:
    """Return an ``input[name="..."]`` CSS selector for one grid field."""
    return f'input[name="{field_name(field, index)}"]'


# --- Login (VERIFIED-LIVE 2026-05-19) --------------------------------------
# The login page has TWO forms: a hidden "Demo" form (``form2``) with duplicate
# id="login"/"pass" decoy inputs, and the real form. The real visible inputs
# are disambiguated by ``type`` + ``name`` (the decoys are ``type=hidden``).
LOGIN_USERNAME_SELECTOR = 'input[type="text"][name="form_login"]'  # VERIFIED-LIVE
LOGIN_PASSWORD_SELECTOR = 'input[type="password"][name="form_password"]'  # VERIFIED-LIVE
#: Submit is ``<input type="submit" id="logbutt" value="دخول">`` — its label is
#: a ``value`` attribute, so ``get_by_text`` cannot match it; address by id.
LOGIN_SUBMIT_SELECTOR = "#logbutt"  # VERIFIED-LIVE
#: Present only once the post-login books listing has rendered (login OK).
LISTING_READY_SELECTOR = 'a[href*="bounce.php?course="]'  # VERIFIED-LIVE

# --- Book selection (VERIFIED-LIVE 2026-05-19) -----------------------------
#: The listing IS semester-filtered (round-4 correction — the earlier "no
#: dropdown" claim was wrong). A ``<select id="changeYear">`` (options
#: ``الفصل 1`` / ``الفصل 2``, values ``"1"`` / ``"2"``) toggles which book
#: rows are shown: a semester's other-term rows sit in ``<tr style=
#: "display:none">`` until its option is selected. It MUST be set before the
#: book link (sem-2 / "B" rows are hidden by default) is clickable.
SEMESTER_SELECT_SELECTOR = "#changeYear"  # VERIFIED-LIVE (id is a misnomer)
#: semester -> ``#changeYear`` option *value*.
SEMESTER_SELECT_VALUE: dict[int, str] = {1: "1", 2: "2"}  # VERIFIED-LIVE
#: Each book is still an exact-text link ``"Year {year} English A"`` (sem 1)
#: / ``"... B"`` (sem 2); selected by exact accessible name once its row is
#: un-hidden by the semester select above. ``{suffix}`` is ``A``/``B``.
BOOK_LINK_NAME_TMPL = "Year {year} English {suffix}"  # VERIFIED-LIVE
#: semester -> book-name suffix.
SEMESTER_BOOK_SUFFIX: dict[int, str] = {1: "A", 2: "B"}  # VERIFIED-LIVE

# --- Ebook viewer: sidebar Section -> Part tree (VERIFIED-LIVE) ------------
# The book is navigated as an ordered sidebar tree: SECTION header spans, each
# followed by its "Part" anchors. Each Part anchor is a separate
# ``content.php?gid=…`` page covering a page range embedded in its link text
# (e.g. "Part 1 4 - 6", "Pictionary 58 - 61", "Ending 64"). Page numbers are
# GLOBAL and sequential (never reset per part) — so keys never collide.
SIDEBAR_SECTION_SELECTOR = 'span.inlineEdits[name="outahgfolder1"]'  # VERIFIED-LIVE
#: Combined selector walked in DOM order to interleave section headers and part
#: links. Anchors are then filtered by :data:`SIDEBAR_PART_HREF_RE` to drop the
#: skip-nav links (which carry a ``#fragment``).
SIDEBAR_TREE_SELECTOR = (
    'span.inlineEdits[name="outahgfolder1"], a[href*="content.php?gid="]'  # VERIFIED-LIVE
)
#: A genuine Part link: ``/content.php?gid=<d>_<d>_<d>`` with NO ``#fragment``
#: (the page skip-links share the path but end in ``#content`` etc.).
SIDEBAR_PART_HREF_RE: re.Pattern[str] = re.compile(r"/content\.php\?gid=\d+_\d+_\d+$")
#: Part anchors expose their human label in ``title`` ("Part 1", "Pictionary",
#: "Ending", "xxxxx"); Section header spans expose ``title="Section N: …"``.
#: NOTE (verified-live 2026-05-19): every Part anchor's ``data-name`` is the
#: literal placeholder ``"X"`` — it does NOT encode a page range, and the
#: link text is only the label. The GLOBAL page range is therefore NOT in the
#: sidebar; it is read live from the loaded Part page's pager (PAGE_* below).
SIDEBAR_TITLE_ATTR = "title"  # VERIFIED-LIVE

# --- Page navigation within a Part (VERIFIED-LIVE 2026-05-19) -------------
#: The pager is a ``<ul>`` of ``<a href="#pageN" rel="i">`` links whose
#: trimmed TEXT is the GLOBAL page number. ``PAGE_LIST_SELECTOR`` matches
#: every page link: its presence means the Part page loaded; its *absence*
#: marks a no-content placeholder Part (e.g. the dashed "xxxxx" intro) to skip.
PAGE_LIST_SELECTOR = 'a[href^="#page"]'  # VERIFIED-LIVE
#: The page currently in view: the page link carrying class ``currentpage``
#: (its trimmed TEXT is the current global page number).
PAGE_CURRENT_SELECTOR = 'a[href^="#page"].currentpage'  # VERIFIED-LIVE
#: Forward page step (anchor ``«``/``»`` are href="#previous"/"#next").
PAGE_NEXT_ARROW_SELECTOR = 'a[href="#next"]'  # VERIFIED-LIVE
#: The ``#next`` arrow gains class ``disabled`` (``class="prevnext disabled"``)
#: on the Part's LAST page — the authoritative end-of-Part signal.
PAGE_NEXT_DISABLED_SELECTOR = 'a[href="#next"].disabled'  # VERIFIED-LIVE

# --- Admin & Dev -> Data iBook (Text Entry) -> TextApps (VERIFIED-LIVE) ----
#: The "spanner": ``<a id="adminTab_" href="javascript:openAdminMenu(1)">`` —
#: opened by a CLICK (not hover; it is a JS handler).
ADMIN_DEV_TRIGGER_SELECTOR = "#adminTab_"  # VERIFIED-LIVE
#: "Data iBook (Text Entry)" entry: ``<a id="xwcode">`` (loads the iframe).
DATA_IBOOK_SELECTOR = "#xwcode"  # VERIFIED-LIVE
#: The TextApps panel lives in a CROSS-ORIGIN iframe whose ELEMENT is this CSS
#: selector and whose URL contains :data:`TEXTAPPS_FRAME_URL_SUBSTR`. All grid
#: reads/writes happen inside that frame (Playwright drives cross-origin frames
#: fine — same-origin policy does not apply to the automation driver).
TEXTAPPS_IFRAME_SELECTOR = "#LFrm"  # VERIFIED-LIVE
TEXTAPPS_FRAME_URL_SUBSTR = "exp_entry.php"  # VERIFIED-LIVE
#: Tab text inside the iframe that switches the grid to the TextApps view.
TEXTAPPS_TAB_TEXT = "TextApps"  # VERIFIED-LIVE
#: Closes the Data-iBook modal/iframe: ``<a id="secondClose"
#: href="javascript:ahgsideshowhide()">إغلاق</a>`` (must close before the
#: page-step arrows are clickable again).
ADMIN_MODAL_CLOSE_SELECTOR = "#secondClose"  # VERIFIED-LIVE
#: Closes the Admin & Dev side menu: ``<a
#: href="javascript:closeAdminMenu(1)">Close</a>``.
ADMIN_PANEL_CLOSE_SELECTOR = 'a[href*="closeAdminMenu"]'  # VERIFIED-LIVE

# --- Save (write-back path; not exercised by the read-only scrape) ---------
#: ``<button id="saveAll">Save</button>`` INSIDE the TextApps iframe. Verified
#: present live; the click+confirm flow itself is # VERIFY-ON-LIVE-WRITEBACK.
SAVE_BUTTON_SELECTOR = "#saveAll"  # VERIFIED-LIVE (element); flow VERIFY-ON-LIVE-WRITEBACK
#: Substring of the cross-origin POST that confirms a save (host-agnostic: the
#: app is myquds.ibnbadis.org but the POST goes to dev.ibnbadis.org). VERIFIED.
SAVE_ENDPOINT_SUBSTR = "userqanssave.php"

# --- Timeouts --------------------------------------------------------------
DEFAULT_TIMEOUT_MS = 30_000
SAVE_RESPONSE_TIMEOUT_MS = 15_000
