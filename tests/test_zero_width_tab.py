"""A tab whose stop the pen has already reached is ZERO columns wide.

Triage Q10 (research/2026-09-12_pcl-v4-untriaged-triage.md), measured on
`sawyer/REF/FONT-TAG.CMP` against its real WS7 LaserJet capture
(ws7-prints/v4, page 1): the document types `Bit #:`, a type-9 tab block,
then `Usage:`. The tab's absolute stop is 273.6pt from the page's left
edge, which is exactly where `Bit #:` already ends, and its own width word
says 28 HMI -- under a sixth of a 10-CPI column. Real WS7 prints
`Bit #:Usage:` with nothing between them (`Bit` at 230.4pt, `#:Usage:` at
259.2pt, one continuous run).

This engine spent a placeholder column anyway -- `max(1, ...)` in
`core._tab_columns`, and a one-space-wide nudge in the printed PDF's own
overrun branch -- so `Usage:` printed 7.2pt right of where WordStar puts
it, on every surface at once: printed, layout, RTF, HTML, plain text.

The other half of the same mechanism, and the reason zero columns is not
simply "drop the tab": a zero-column tab is still a POSITIONING
instruction. `sawyer/MICKEE/MICKEE.WS` page 23 opens a line with a 90-HMI
tab -- half a 10-CPI column, so no whole column at all -- and real WS7
starts that line at 10.8pt where the margin alone would put it at 7.2pt.
The span carrying the stop has no characters now, so the printed renderer
has to keep it rather than drop it with the other empty runs.
"""
from ctrlkd import core, pdf

HARD = b'\r\n'


def _ws7_block(cmd, content=b''):
    """One WS5+ symmetric sequence -- copied from test_fidelity_gate.py's
    own helper, per test_ctrlkd.py's "copy, don't import" guidance."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _tab(size_hmi, abs_hmi, tab_type=0x20):
    """A type-9 tab block in the archive's own shape: width word, absolute
    stop word, type byte, terminator."""
    return _ws7_block(0x09, size_hmi.to_bytes(2, 'little')
                      + abs_hmi.to_bytes(2, 'little')
                      + bytes([tab_type, 0xFF]))


def _doc(body):
    return core.parse_ws(_ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)


def _line_texts(doc):
    return [''.join(s.text for s in line.spans)
            for b in doc.blocks for line in (b.lines or [])]


# ------------------------------------------------------------ the width
def test_a_tab_the_pen_has_already_reached_is_zero_columns():
    """FONT-TAG.CMP's own block, byte for byte: 28 HMI of width, which is
    no whole 10-CPI column (180 HMI) at all."""
    cols, leader = core._tab_columns(b'\x1c\x00\xb0\x13\x20\xff')
    assert (cols, leader) == (0, b' ')


def test_an_ordinary_tab_still_measures_its_own_columns():
    """The floor is gone, not the arithmetic: a real 3-column tab is
    still three columns wide."""
    assert core._tab_columns((540).to_bytes(2, 'little')
                             + b'\xb0\x13\x20\xff')[0] == 3


def test_a_zero_width_tab_leaves_no_placeholder_in_the_text():
    """The text surfaces (plain text, Markdown, RTF, HTML, layout) all
    read this same decoded run: `Bit #:Usage:`, exactly as WS7 prints it,
    with no spent column between the two words."""
    doc = _doc(b'Bit #:' + _tab(28, 5040) + b'Usage:' + HARD)
    assert _line_texts(doc) == ['Bit #:Usage:']


# ------------------------------------------------- the positioning half
def test_a_zero_width_tab_still_sets_the_printed_pen():
    """MICKEE.WS page 23's shape: a leading tab of 90 HMI -- half a
    column, so zero whole columns -- whose absolute stop is still 3.6pt
    in from the margin. WS7 starts the line there, not at the margin, so
    the empty span carrying the stop must survive into the printed page.
    """
    doc = _doc(_tab(90, 90) + b'Spell,' + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    plain = _doc(b'Spell,' + HARD)
    base = pdf.emit_pdf(plain, mode='printed')
    assert _first_x(out, 'Spell,') == round(_first_x(base, 'Spell,') + 3.6, 1)


def _first_x(pdf_bytes, word):
    """The Td x of the first text object whose operand starts with
    `word` -- the printed page draws this single-span line as one Tj."""
    import re
    import zlib
    streams = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', pdf_bytes, re.S):
        try:
            streams.append(zlib.decompress(m[1]))
        except zlib.error:
            streams.append(m[1])
    pat = re.compile(rb'([\d.]+) [\d.]+ Td \(' + re.escape(word.encode()))
    for stream in streams:
        m = pat.search(stream)
        if m:
            return float(m[1])
    return None
