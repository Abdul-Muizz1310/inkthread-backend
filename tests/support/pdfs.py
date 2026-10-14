"""Synthetic PDFs, made in-process with PyMuPDF, so reader tests know the exact truth.

Every factory returns PDF bytes. The helpers are adapted from inkgrid's
`tests/support/pdf_factory.py` (same author, MIT).
"""

from __future__ import annotations

import pymupdf

LETTER = (612, 792)
BLACK = (0, 0, 0)

SECTIONED_TITLE = "Exchange Fee Rules"
HYPHEN_LEFT = "settle-"
HYPHEN_RIGHT = "ment"
FOOTNOTE_NOTE = "1 Applies to every trade on the order book."
HIDDEN_WORDS = ("ignore", "previous", "instructions")
RULED_CELLS = {
    "Service": (72, 120, 222, 140),
    "Fee": (222, 120, 372, 140),
    "Filing": (72, 140, 222, 160),
    "350.00": (222, 140, 372, 160),
    "Renewal": (72, 160, 222, 180),
    "125.50": (222, 160, 372, 180),
}


def _save(doc: pymupdf.Document, **kw: object) -> bytes:
    doc.set_metadata({})
    data: bytes = doc.tobytes(garbage=0, no_new_id=True, **kw)
    return data


def _page(doc: pymupdf.Document) -> pymupdf.Page:
    return doc.new_page(width=LETTER[0], height=LETTER[1])


def _lines(page: pymupdf.Page, y: float, lines: list[str], size: float = 10) -> float:
    for line in lines:
        page.insert_text((72, y), line, fontsize=size)
        y += size * 1.2
    return y


def sectioned() -> bytes:
    """A title, headings `1`, `1.1`, `2` with paragraphs; the first paragraph hyphenates a word."""
    doc = pymupdf.open()
    page = _page(doc)
    page.insert_text((72, 72), SECTIONED_TITLE, fontsize=20, fontname="hebo")
    page.insert_text((72, 110), "1 Scope", fontsize=14, fontname="hebo")
    _lines(
        page,
        132,
        [
            "These rules govern the fees that members pay for every",
            f"trade they make on the exchange and its daily {HYPHEN_LEFT}",
            f"{HYPHEN_RIGHT} cycle, including the charges for late filing.",
        ],
    )
    page.insert_text((72, 190), "1.1 Members", fontsize=12, fontname="hebo")
    _lines(page, 210, ["A member is any firm admitted to trade on the exchange floor."])
    page.insert_text((72, 250), "2 Fees", fontsize=14, fontname="hebo")
    _lines(page, 272, ["Each member pays the fees in the schedule below every month."])
    return _save(doc)


def ruled_table() -> bytes:
    """A paragraph, then a fully ruled 3 x 2 table with a header row and numeric cells."""
    doc = pymupdf.open()
    page = _page(doc)
    _lines(page, 80, ["The schedule below lists the fees for each service in dollars."])
    shape = page.new_shape()
    for x0, y0, x1, y1 in RULED_CELLS.values():
        shape.draw_rect(pymupdf.Rect(x0, y0, x1, y1))
    shape.finish(color=BLACK, width=0.8)
    shape.commit()
    for text, (x0, y0, x1, y1) in RULED_CELLS.items():
        bold = y0 == 120
        width = pymupdf.get_text_length(text, fontname="hebo" if bold else "helv", fontsize=9)
        page.insert_text(
            ((x0 + x1 - width) / 2, (y0 + y1) / 2 + 3),
            text,
            fontsize=9,
            fontname="hebo" if bold else "helv",
        )
    return _save(doc)


def footnoted() -> bytes:
    """A paragraph whose `applies` carries a raised `1`, and a 7 pt note `1 Applies ...` below."""
    doc = pymupdf.open()
    page = _page(doc)
    _lines(
        page,
        64,
        [
            "Members pay the fees in this schedule every month without",
            "exception, and the exchange bills them on the first day.",
        ],
    )
    lead = "The index surcharge applies"
    page.insert_text((72, 100), lead, fontsize=10)
    x = 72 + pymupdf.get_text_length(lead, fontsize=10) + 0.3
    page.insert_text((x, 96), "1", fontsize=6)
    page.insert_text((x + 4, 100), "to options on the index.", fontsize=10)
    page.insert_text((72, 700), FOOTNOTE_NOTE, fontsize=7)
    return _save(doc)


def hidden_text() -> bytes:
    """A paragraph whose last words are in render mode 3 (in the text layer, never drawn)."""
    doc = pymupdf.open()
    page = _page(doc)
    lead = "Members pay the fee"
    page.insert_text((72, 100), lead, fontsize=10)
    x = 72 + pymupdf.get_text_length(lead + " ", fontsize=10)
    page.insert_text((x, 100), " ".join(HIDDEN_WORDS), fontsize=10, render_mode=3)
    return _save(doc)


def two_pages() -> bytes:
    """Two pages, each with a heading and a paragraph."""
    doc = pymupdf.open()
    for n in (1, 2):
        page = _page(doc)
        page.insert_text((72, 72), f"Part {n}", fontsize=14, fontname="hebo")
        _lines(page, 100, [f"This is the body of part {n} of the document."])
    return _save(doc)


def encrypted(user_pw: str = "u", owner_pw: str = "o") -> bytes:
    """AES-256 encryption with a user password."""
    doc = pymupdf.open()
    _page(doc).insert_text((72, 100), "secret", fontsize=10)
    return _save(doc, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw=owner_pw)


def image_only() -> bytes:
    """An image and no text layer at all."""
    doc = pymupdf.open()
    page = _page(doc)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    pix.set_rect(pix.irect, (200, 40, 40))
    page.insert_image(pymupdf.Rect(72, 72, 400, 400), pixmap=pix)
    return _save(doc)


def garbage() -> bytes:
    """Bytes that start like a PDF and are not one."""
    return b"%PDF-1.7\n" + b"\x00garbage, not a pdf\xff" * 40
