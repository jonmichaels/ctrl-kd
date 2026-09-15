r"""M18 (Jon's queue 2026-09-15): MODERN LAYS OUT ON THE SHEET IT DECLARES.

Modern's MediaBox has been the document's own declared sheet since
2026-08-06 ("the page is the document's declared size -- Letter/Legal/A4").
Its composing ORIGIN was Letter's 792pt regardless, so a document whose
sheet is not 11in tall had its text drawn at coordinates that are not on
the page the PDF says it drew: `sawyer/MAILLIST/ENVELOPE.LST` (`.pl 4.17"`)
came out a 612x300 box with every line at y >= 552 -- six blank pages. The
taller direction lost space instead of text: a 13in Rolodex template began
its first line 144pt below the top of its own sheet.

M17 fixed the LANDSCAPE half of the same arithmetic and named this half in
`_modern_sheet_h`'s own docstring as "a real, separate defect ... it waits
for its own". This is it. One definition of Modern's sheet height now
serves both the MediaBox and the composing origin, so the two cannot
disagree again.

`.pl 0` is not a sheet: it is WordStar's "page breaks off" (bug 12284),
and the page BOX falls back to Letter -- verbatim what Printed has always
done (`_resolved_page_height`), quoted rather than re-decided. Before this
fix Modern gave such a document a ZERO-HEIGHT MediaBox. (The document that
carries it in the archive, `sawyer/REF/-PATCHES.WS`, is separately an
excluded `degenerate` document by Jon's ruling 2026-09-10, planning #261 --
excluded from JUDGING its fidelity, which is not a licence to emit an
invalid PDF for it.)

Synthetic fixtures only.
"""
import re

from ctrlkd import core, pdf

HARD = b'\x0d\x0a'


def _ws7(body, dots=b''):
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


def _mediabox(out):
    m = re.search(rb'/MediaBox \[0 0 (\d+) (\d+)\]', out)
    assert m is not None
    return int(m.group(1)), int(m.group(2))


def _ys(out):
    return [float(t) for t in re.findall(rb' [\d.]+ ([\d.]+) Td', out)]


_PARA = (b'The quick brown fox jumps over the lazy dog and keeps running '
         b'until the line has to wrap somewhere sensible.' + HARD)


def _sheet(pl, body=None, extra=b''):
    return _ws7(body if body is not None else _PARA,
                dots=b'.pl %s' % pl + HARD + extra)


# ------------------------------------------- the short sheet, the whole defect

def test_a_short_portrait_sheet_is_laid_out_on_itself():
    """ENVELOPE.LST's own `.pl 4.17"`: a 300pt sheet whose every line used
    to be drawn at y >= 552, i.e. above the top of the page it was on."""
    out = pdf.emit_pdf(_sheet(b'4.17"'), mode='modern')
    assert _mediabox(out) == (612, 300)
    ys = _ys(out)
    assert ys
    assert max(ys) < 300, max(ys)


def test_a_tall_sheet_starts_at_its_own_top_not_letters():
    """The taller direction lost space rather than text: a 13in Rolodex
    template began 144pt below the top of its own sheet."""
    out = pdf.emit_pdf(_sheet(b'13.00"'), mode='modern')
    assert _mediabox(out) == (612, 936)
    assert max(_ys(out)) > 792, max(_ys(out))


def test_a_letter_document_is_untouched():
    out = pdf.emit_pdf(_ws7(_PARA), mode='modern')
    assert _mediabox(out) == (612, 792)


def test_the_mediabox_and_the_composing_height_are_one_number():
    """The defect was two derivations of "how tall is this sheet" that
    disagreed. There is one now, and this asserts it for each shape."""
    for pl in (b'4.17"', b'13.00"', b'8.50"', b'1.00"'):
        doc = _sheet(pl)
        assert _mediabox(pdf.emit_pdf(doc, mode='modern'))[1] == \
            pdf._modern_sheet_h(doc), pl


# ------------------------------------------------------------------- `.pl 0`

def test_pl_zero_falls_back_to_letter_not_a_zero_height_page():
    """`.pl 0` is "page breaks off", not a zero-tall sheet. Printed has
    read it that way since `_resolved_page_height` was written; Modern
    used to emit a `/MediaBox [0 0 612 0]`."""
    doc = _sheet(b'0')
    assert pdf._modern_sheet_h(doc) == pdf.PAGE_H
    assert _mediabox(pdf.emit_pdf(doc, mode='modern')) == (612, 792)


def test_pl_zero_reads_the_same_in_both_modes():
    doc = _sheet(b'0')
    assert pdf._modern_sheet_h(doc) == pdf._resolved_page_height(doc, True)


# --------------------------------------------------------- degenerate shapes

def test_a_sheet_shorter_than_the_footnote_floor_keeps_the_floor():
    """Printed's own floor and Printed's own reason: a page has to hold
    `FOOTNOTE_FLOOR + 1` lines."""
    doc = _sheet(b'0.25"')
    floor = pdf.LEAD * (pdf.FOOTNOTE_FLOOR + 1)
    assert pdf._modern_sheet_h(doc) == floor
    assert _mediabox(pdf.emit_pdf(doc, mode='modern')) == (612, floor)


def test_a_sheet_shorter_than_moderns_own_margins_still_terminates():
    """A 1in sheet with no `.mt`/`.mb` of its own leaves Modern's default
    1in top and 1in bottom margins overlapping. It must still produce a
    finite PDF rather than paginating forever."""
    out = pdf.emit_pdf(_sheet(b'1.00"'), mode='modern')
    assert _mediabox(out) == (612, 72)
    assert out.count(b'/Type /Page ') >= 1


# -------------------------------------------------------- M17 still stands

def test_a_landscape_sheet_still_resolves_the_swapped_pair():
    doc = _ws7(_PARA, dots=b'.pr or=l' + HARD + b'.pl 8.50"' + HARD)
    out = pdf.emit_pdf(doc, mode='modern')
    assert _mediabox(out) == (792, 612)
    assert max(_ys(out)) < 612
