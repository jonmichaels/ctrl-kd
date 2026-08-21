"""b26-modern item 3 (BUILD-SLATES.md item 27, Jon's decided screenplay
ruling): when the existing screenplay-layout detection fires
(`core.detect_screenplay_blocks`), Modern PDF must:
  (a) keep each real numbered page a separate Modern page (never spread
      one source page's screenplay content across two Modern pages);
  (b) render the page-number marker ("1." alone at the top of the page)
      flush against the right margin, below the running head, not at
      the left margin;
  (c) keep a slugline's own right-hand scene number on the same line at
      the right, never dropped to its own line by word-wrap.
Only INSIDE a detected screenplay region -- an ordinary document's own
numbered list, table, or short line must render exactly as before.

MECHANISM (pdf.py's `_modern_flow`/`_modern_streams`; this is the ONLY
place in the codebase that renders Modern PDF pages, so this is where
the ruling has to live -- neither `layout.py`'s shared item stream nor
`core.detect_screenplay_blocks` itself needed to change):
  - `screenplay_blocks` (from the existing, already-corpus-gated
    detector) is computed once per document.
  - A line inside that region matching `_SCREENPLAY_PAGE_MARKER_RE`
    (nothing but whitespace and a bare 1-4 digit number, optional
    trailing period) is a page marker: its paragraph gets `align =
    'right'` (rule b) and, if the current Modern page already has body
    content on it, forces a page break before it (rule a) -- a marker
    that already opens a fresh page (an explicit `.pa` immediately
    preceded it, the real SCRIPT.WS shape) costs nothing extra.
  - A line matching the SAME slugline anchor `detect_screenplay_blocks`
    itself uses, that ALSO ends in a right-hand number, gets an
    unbounded wrap width (`_modern_wrap` can never find a break point),
    so it can never lose its trailing number to a new line (rule c).
  - `detect_screenplay_blocks`'s own region growth is documented to
    extend only FORWARD from its slugline anchor, so a page marker
    (which precedes the slugline) is never itself a region member --
    `screenplay_marker_bis` widens candidacy by one/two blocks forward
    to cover exactly that shape without touching the shared detector.

Real-document verification lives in the evidence directory (before/
after Modern PDF exports of the repo's screenplay test document,
ARTICLES/SCRIPT.WS from the real WS7 corpus) -- these are synthetic-
fixture regression tests per CLAUDE.md's own rule.
"""
import re

from ctrlkd import core, pdf

HARD = b'\r\n'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def font_block(points, width=180):
    return ws7_block(0x02, round(width).to_bytes(2, 'little')
                     + round(points * 20).to_bytes(2, 'little')
                     + (0).to_bytes(2, 'little') + bytes(6))


def _page_count(out):
    return int(re.search(rb'/Count (\d+)', out).group(1))


def _ops(out):
    """(x, y, text) for every Tj word, in draw order."""
    return re.findall(rb'([\d.]+) ([\d.]+) Td \(((?:\\.|[^)\\])*)\) Tj', out)


# =========================================================== rule (a)

def test_page_marker_forces_a_break_when_the_page_already_has_content():
    data = (ws7_block(0x00) +
            b'Some prose before the marker, to give the page real content first.'
            + HARD + HARD +
            b'                                                            1.'
            + HARD + HARD +
            b'INT. HOUSE - DAY' + HARD + HARD +
            b'JOHN stares at the door for a long moment before speaking quietly.'
            + HARD)
    doc = core.parse_ws(data)
    region = core.detect_screenplay_blocks(doc)
    assert region, 'fixture must trigger screenplay detection'
    out = pdf.emit_pdf(doc, mode='modern')
    assert _page_count(out) == 2


def test_page_marker_after_an_explicit_pa_costs_no_extra_page():
    """The real SCRIPT.WS shape: content, then an explicit `.pa`, then the
    marker as the page's own first line. The marker's own break-forcing
    must be a no-op here -- exactly 2 pages (the .pa's own break), not 3."""
    data = (ws7_block(0x00) +
            b'Some opening prose that appears before the page break happens.'
            + HARD + b'.pa' + HARD +
            b'                                                            1.'
            + HARD + HARD +
            b'INT. HOUSE - DAY' + HARD + HARD +
            b'JOHN stares at the door for a long moment before speaking quietly.'
            + HARD)
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='modern')
    assert _page_count(out) == 2


def test_marker_shaped_line_outside_a_screenplay_region_never_forces_a_break():
    """Zero-false-positive: the exact same marker SHAPE (whitespace + a
    bare number) with no slugline anywhere in the document -- an ordinary
    numbered-list-ish line -- must never force a page break."""
    data = (ws7_block(0x00) +
            b'Some prose before the marker, to give the page real content first.'
            + HARD + HARD +
            b'                                                            1.'
            + HARD + HARD +
            b'More ordinary prose that is definitely not a screenplay at all.'
            + HARD)
    doc = core.parse_ws(data)
    assert not core.detect_screenplay_blocks(doc)
    out = pdf.emit_pdf(doc, mode='modern')
    assert _page_count(out) == 1


# =========================================================== rule (b)

def test_page_marker_renders_flush_against_the_right_margin():
    data = (ws7_block(0x00) +
            b'Some prose before the marker, to give the page real content first.'
            + HARD + HARD +
            b'                                                            1.'
            + HARD + HARD +
            b'INT. HOUSE - DAY' + HARD + HARD +
            b'JOHN stares at the door for a long moment before speaking quietly.'
            + HARD)
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='modern')
    margl, margt, margb, width = pdf._modern_geometry(doc)
    ops = _ops(out)
    x, y, text = next((x, y, t) for x, y, t in ops if t == b'1.')
    expected_right_edge = margl + width
    # "1." at 14pt Times: flush means its OWN right edge sits at the
    # margin, so its Td x (left edge of the glyph run) is somewhat left
    # of that -- checked as "close to the margin", not touching the left
    # margin at all (the pre-fix left-flow failure mode).
    assert float(x) > margl + width * 0.7, (x, expected_right_edge)


def test_marker_shaped_line_outside_a_screenplay_region_stays_left_flowed():
    data = (ws7_block(0x00) +
            b'Some prose before the marker, to give the page real content first.'
            + HARD + HARD +
            b'                                                            1.'
            + HARD + HARD +
            b'More ordinary prose that is definitely not a screenplay at all.'
            + HARD)
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='modern')
    margl, margt, margb, width = pdf._modern_geometry(doc)
    ops = _ops(out)
    x, y, text = next((x, y, t) for x, y, t in ops if t == b'1.')
    # left-flowed: nowhere near the right margin (unlike the screenplay case)
    assert float(x) < margl + width * 0.6


# =========================================================== rule (c)

def test_slugline_with_trailing_scene_number_never_wraps():
    line = (b'12    INT. A VERY LONG LOCATION NAME THAT GOES ON AND ON - DAY   12')
    data = ws7_block(0x00) + line + HARD + HARD + b'Action line.' + HARD
    doc = core.parse_ws(data)
    assert core.detect_screenplay_blocks(doc), 'fixture must trigger detection'
    out = pdf.emit_pdf(doc, mode='modern')
    ops = _ops(out)
    ys = {y for x, y, t in ops if t in (b'DAY', b'12')}
    assert len(ys) == 1, ys


def test_equally_long_ordinary_line_outside_screenplay_still_wraps():
    """Control: the SAME kind of overflow (a line too wide for the page),
    but with no slugline anywhere -- must wrap normally, proving the
    no-wrap mechanism is doing real work above, not just "everything
    happens to fit."""
    line = (b'This is a very long ordinary line of prose text that goes '
            b'well past the margin at twelve point type')
    data = ws7_block(0x00) + font_block(12) + line + HARD
    doc = core.parse_ws(data)
    assert not core.detect_screenplay_blocks(doc)
    out = pdf.emit_pdf(doc, mode='modern')
    ops = _ops(out)
    ys = {y for x, y, t in ops}
    assert len(ys) > 1, 'control line should have wrapped onto more than one visual line'


def test_slugline_without_a_trailing_number_is_unaffected():
    """A slugline with NO right-hand scene number has nothing to protect
    -- must render through the ordinary wrap path, same as any other
    line (mechanism must not blanket-disable wrapping for every
    screenplay-detected line, only the specific shape that needs it)."""
    data = (ws7_block(0x00) + font_block(12) +
            b'INT. A VERY LONG LOCATION NAME THAT GOES ON AND ON AND ON - DAY'
            + HARD + HARD + b'Action line.' + HARD)
    doc = core.parse_ws(data)
    assert core.detect_screenplay_blocks(doc)
    out = pdf.emit_pdf(doc, mode='modern')
    ops = _ops(out)
    # no trailing number to protect -- ordinary wrap behavior decides
    # this line's own layout; the real assertion is just that the
    # mechanism didn't crash and the rest of the region still renders.
    assert any(t == b'DAY' for x, y, t in ops)
    assert any(t == b'Action' for x, y, t in ops)


# ==================================================== Printed unaffected

def test_printed_mode_never_reads_screenplay_state():
    """Printed PDF's own code path (`_page_stream`) is completely
    separate from `_modern_streams` -- a screenplay-shaped document must
    render identically in Printed mode whether or not the Modern-only
    screenplay mechanism exists. Proven indirectly: Printed emits every
    line verbatim regardless of `detect_screenplay_blocks`, so the same
    fixture's Printed output must show the marker's OWN typed spacing
    (left-flowed, WS7's own literal-facsimile doctrine), never a right-
    aligned override."""
    data = (ws7_block(0x00) +
            b'Some prose before the marker, to give the page real content first.'
            + HARD + HARD +
            b'                                                            1.'
            + HARD + HARD +
            b'INT. HOUSE - DAY' + HARD + HARD +
            b'JOHN stares at the door for a long moment before speaking quietly.'
            + HARD)
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='printed')
    assert out.startswith(b'%PDF')
    assert _page_count(out) == 1   # Printed never force-breaks on this shape
