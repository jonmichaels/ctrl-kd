r"""E9 R1 (Jon's ruling 2026-09-17, the human-eye export audit section A):
the Printed RTF text column is the document's own ruler, not paper minus
twice `.po`.

Printed RTF used to write `\margr = \margl`, which makes the text column
*paper width - 2 x `.po`*. At the ordinary default (`.po 0.8in` on Letter)
that is exactly 69 columns, one short of the 69-character lines real
documents carry, so 6,488 facsimile lines in 216 documents came back
re-wrapped from the reader -- the one thing Printed mode exists to prevent
-- and `MAILLIST/ENVELOPE.LST` (`.poo/.poe 4.20"` on an 8.5in sheet) was
left with a text column ONE TENTH OF AN INCH wide.

The column is now `max(the widest .rm in force, the document's own longest
printed line) + one cell`, measured from the `.po` origin exactly as the
Printed PDF measures its right edge, with `\paperw` growing when the sheet
cannot hold it (capped at 22in, Word's own maximum page dimension).

The one cell of slack is not decoration: a reader breaks a line whose width
EQUALS the measure exactly (measured, LibreOffice 24.2.7.2 -- 68 characters
fit a 69-column column, 69 do not), and `pd-samples/authored/OCAPTAIN.WS`
is exactly that boundary.

Synthetic fixtures only.
"""
import re

from ctrlkd import core, emit_rtf

CELL = 144                      # one 10-CPI print column, in twips


def _ws7(body, dots=b''):
    """A WS5+/WS7 document: the type-0 header block, then raw lines."""
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


def _page_box(rtf):
    """(paperw, margl, margr) in twips."""
    m = re.search(r'\\paperw(\d+)\\paperh\d+\\margl(\d+)\\margr(\d+)', rtf)
    assert m is not None, 'no page setup'
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _column(rtf):
    paperw, margl, margr = _page_box(rtf)
    return paperw - margl - margr


def test_column_is_the_declared_ruler_plus_one_cell():
    doc = _ws7(b'short line\r\n', dots=b'.po 8\r\n.rm 60\r\n')
    rtf = emit_rtf(doc, mode='printed')
    assert _column(rtf) == (60 + 1) * CELL
    # `.po` still owns the LEFT edge -- only the right edge moved
    assert _page_box(rtf)[1] == 8 * CELL


def test_a_line_past_the_ruler_widens_the_column_not_the_reader():
    """Box art, print streams and plain-text sources overrun their own
    `.rm`; the facsimile follows the ink, not just the ruler."""
    doc = _ws7(b'X' * 100 + b'\r\n', dots=b'.po 8\r\n.rm 60\r\n')
    rtf = emit_rtf(doc, mode='printed')
    assert _column(rtf) == (100 + 1) * CELL


def test_the_69_character_line_that_used_to_break():
    """The OCAPTAIN boundary: 69 characters under the old
    paper-minus-two-page-offsets arithmetic landed in a 69-column column
    and came back as two lines."""
    doc = _ws7(b'W' * 69 + b'\r\n', dots=b'.po 8\r\n')
    rtf = emit_rtf(doc, mode='printed')
    assert _column(rtf) >= 70 * CELL
    # the sheet is still Letter: the column fits inside it
    assert _page_box(rtf)[0] == 12240


def test_trailing_spaces_do_not_widen_the_column():
    """A reader does not break a line because of the spaces hanging off its
    end (measured, LibreOffice 24.2.7.2), so neither does this measure."""
    plain = _ws7(b'Z' * 40 + b'\r\n', dots=b'.po 8\r\n.rm 60\r\n')
    padded = _ws7(b'Z' * 40 + b' ' * 40 + b'\r\n', dots=b'.po 8\r\n.rm 60\r\n')
    assert _column(emit_rtf(plain, mode='printed')) == \
        _column(emit_rtf(padded, mode='printed'))


def test_a_ruler_wider_than_the_sheet_widens_the_paper():
    """The audit's question 6, ruled yes: an envelope template declares
    `.po 4.20"` and `.rm 9.50"` on a short sheet. Mirrored offsets used to
    leave 0.1in of text column; the paper grows instead."""
    doc = _ws7(b'&name&\r\n', dots=b'.pl 4.17"\r\n.poo 4.20"\r\n.poe 4.20"\r\n.rm 9.50"\r\n')
    rtf = emit_rtf(doc, mode='printed')
    paperw, margl, margr = _page_box(rtf)
    assert _column(rtf) == (95 + 1) * CELL
    assert paperw == margl + _column(rtf) + margr
    # `\margmirror` keeps BOTH declared offsets -- the outside margin is a
    # real page-parity fact, not leftover paper
    assert margl == margr == 42 * CELL
    assert r'\margmirror' in rtf


def test_the_paper_stops_at_twenty_two_inches():
    """Word's own maximum page dimension. A document whose own lines are
    longer than that keeps the reader's re-wrap -- there is no page any
    reader will accept that would hold them."""
    doc = _ws7(b'Q' * 3000 + b'\r\n', dots=b'.po 8\r\n')
    rtf = emit_rtf(doc, mode='printed')
    assert _page_box(rtf)[0] == 22 * 1440


def test_modern_is_untouched():
    """Modern reflows; the ruler is Printed's business alone."""
    doc = _ws7(b'X' * 100 + b'\r\n', dots=b'.po 8\r\n.rm 60\r\n')
    paperw, margl, margr = _page_box(emit_rtf(doc, mode='modern'))
    # Modern mirrors `.po` into the right margin, exactly as it always has
    assert (paperw, margl, margr) == (12240, 8 * CELL, 8 * CELL)
