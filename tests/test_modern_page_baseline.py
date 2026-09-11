"""planning #263: Modern PDF's PAGE BASELINE MODEL.

The third backport in the #263 family (after the verse/centre tightening
and the def-row ladder/hang, tests/test_modern_verse_defrow.py), ruled
2026-09-11 on Jon's standing principle -- "the engine needs to work the
way Soft Return does". The app's Modern view stacks LINE BOXES down from
the top edge of its text frame and puts each box's baseline one face
DESCENT above that box's bottom. This engine drew the baseline ON the box
bottom, so every Modern line sat one descent lower than the app drew the
same line, and every line's descenders hung below its own box.

WHAT MOVES AND WHAT DOES NOT. The box ladder is untouched: a line still
spends `h` (`MODERN_LINE * pt`, or the tightened height) off the cursor,
and still fits while its box BOTTOM is inside the frame. So the same lines
land on the same pages, at the same x, in the same order; what changes is
the y each one draws at, by its OWN line's descent -- which is not a rigid
shift on a page that mixes type sizes or faces.

Tier 1 is synthetic (CLAUDE.md: synthetic fixtures only). The spec's own
worked example is tier 2 (`sawyer`), on LJ6DTP.WS.
"""
import pytest

from ctrlkd import afm, core, pdf

from test_modern_verse_defrow import (HARD, _lines, _modern, _helv_typestyle,
                                      _font_block, pdf_ws7_block)

# The default Modern page: 1in margins on Letter (`_modern_geometry`'s own
# "silence is the modern page"), so 72pt off each edge of 792.
TOP = pdf.PAGE_H - 72.0
BOTTOM = 72.0


# ------------------------------------------------------ the AFM data itself

def test_afm_publishes_the_vertical_metrics_the_app_reads():
    """The port's one new public table. Adobe's Core 14 AFMs state one
    Ascender/Descender pair per face; these are those numbers, sign and
    all, so the app and sr read the identical figures rather than each
    re-deriving them."""
    assert afm.DESCENDER['Times-Roman'] == -217
    assert afm.DESCENDER['Helvetica'] == -207
    assert afm.DESCENDER['Courier'] == -157
    assert afm.ASCENDER['Times-Roman'] == 683
    assert afm.ASCENDER['Helvetica'] == 718
    assert afm.ASCENDER['Courier'] == 629
    # every variant of a family publishes its family's own figures, which
    # is why `_modern_descent` never consults bold/italic
    for fam in ('Times-Bold', 'Times-Italic', 'Times-BoldItalic'):
        assert afm.DESCENDER[fam] == afm.DESCENDER['Times-Roman']
        assert afm.ASCENDER[fam] == afm.ASCENDER['Times-Roman']
    assert afm.descender_pt('Times-Roman', 72) == pytest.approx(-15.624)
    assert afm.ascender_pt('Helvetica', 14) == pytest.approx(10.052)


def test_the_two_symbol_faces_are_absent_rather_than_invented():
    """Symbol's and ZapfDingbats' AFMs carry no Ascender and no Descender
    key at all. They are left out of both tables (an unmeasured face is
    named as unmeasured -- `_MODERN_NATURAL_LINE`'s own rule) and the
    accessors say so by returning None rather than a silent 0."""
    for face in ('Symbol', 'ZapfDingbats'):
        assert face not in afm.DESCENDER
        assert face not in afm.ASCENDER
        assert afm.descender_pt(face, 14) is None
        assert afm.ascender_pt(face, 14) is None
    # Modern PDF's own documented fallback for them is the Times row
    assert pdf._modern_descent('Symbol', 14) == pytest.approx(
        pdf._modern_descent('Times', 14))
    assert pdf._modern_descent('ZapfDingbats', 14) == pytest.approx(
        pdf._modern_descent('Times', 14))


def test_modern_descent_is_the_afm_descender_made_positive():
    assert pdf._modern_descent('Times', 14) == pytest.approx(3.038)
    assert pdf._modern_descent('Helvetica', 72) == pytest.approx(14.904)
    assert pdf._modern_descent('Courier', 12) == pytest.approx(1.884)


# --------------------------------------------- where the first baseline goes

PROSE = (b'An ordinary sentence that ends with terminal punctuation.' + HARD
         + b'A second ordinary sentence, also ending in a full stop.' + HARD
         + b'A third ordinary sentence, ending in a full stop as well.' + HARD)


def test_the_first_baseline_sits_one_descent_above_its_box_bottom():
    """The app's rule: fragment 1 occupies [top, top + h] and its baseline
    is at `top + h - descent`. Here, top-down: 72 + 16.8 - 3.038."""
    out = pdf.emit_pdf(_modern(PROSE), mode='modern')
    first = _lines(out)[0][0]
    h = pdf.MODERN_LINE * pdf.MODERN_BODY_PT
    assert first == pytest.approx(TOP - h + pdf._modern_descent('Times', 14),
                                  abs=0.05)
    # ... which is exactly one descent ABOVE where this engine used to put
    # it (the box bottom), never at or below it
    assert first > TOP - h
    assert first - (TOP - h) == pytest.approx(3.038, abs=0.05)


def test_a_line_still_advances_by_its_own_box_height():
    """Only the offset INSIDE the box moved. On a uniform page every box
    is the same height, so every baseline-to-baseline advance is still
    exactly `MODERN_LINE * pt` and the whole grid reads as a rigid lift."""
    out = pdf.emit_pdf(_modern(PROSE), mode='modern')
    ys = [y for y, _x, _t in _lines(out)]
    assert [round(a - b, 4) for a, b in zip(ys, ys[1:])] == [
        pytest.approx(16.8), pytest.approx(16.8)]


# ------------------------------------------ a page that mixes size and face

def _mixed(tail=b''):
    """One page setting three sizes in two faces: uncovered prose, which
    Modern reads in TIMES at the 14pt body size (descent 217/1000), then a
    24pt and a 30pt COURIER line under a font block (descent 157/1000)."""
    return (pdf_ws7_block(0x00, bytes([0x70]) + bytes(15))
            + PROSE
            + _font_block(0, 24.0) + b'A courier banner line.' + HARD
            + _font_block(0, 30.0) + b'Another courier banner.' + HARD
            + tail)


MIXED_FACES = [('Times', 14.0)] * 3 + [('Courier', 24.0), ('Courier', 30.0)]


def test_each_line_lifts_by_its_own_faces_descent_not_the_pages():
    """The lift is NOT one number per page: a 30pt Courier line lifts
    4.71pt where a 14pt Times line above it lifts 3.04. Checked as the
    property that actually holds -- every baseline plus its own descent
    lands back on the ladder of box bottoms the boxes themselves make,
    which is the ladder this engine drew its baselines on before."""
    doc = core.parse_ws(_mixed())
    doc.meta['variant'] = 'ws4'
    rows = _lines(pdf.emit_pdf(doc, mode='modern'))
    assert len(rows) == len(MIXED_FACES)
    bottom = TOP
    for (y, _x, _t), (fam, pt) in zip(rows, MIXED_FACES):
        assert pdf._modern_line_face(_face_probe(doc, _t)) == (fam, pt)
        bottom -= pdf.MODERN_LINE * pt
        assert y == pytest.approx(bottom + pdf._modern_descent(fam, pt),
                                  abs=0.05)
    # ... and those lifts really are three different numbers on one page
    assert len({round(pdf._modern_descent(f, p), 2)
                for f, p in MIXED_FACES}) == 3


def _face_probe(doc, ink):
    """The flow paragraph whose own ink is `ink` -- so the face/size the
    assertion above names is the one `_modern_line_face` actually resolved,
    never a second guess at it."""
    for item in pdf._modern_flow(
            doc, frozenset(('footnote', 'endnote', 'annotation')),
            text_width_pt=468.0):
        if item[0] == 'para' and ''.join(
                t[0] for t in item[1]).replace(' ', '') == ink:
            return item[1]
    raise AssertionError(ink)


# ----------------------------------------------------------- the fit test

def _many(n):
    return b''.join(b'Sentence number %d, which ends in a full stop.' % i
                    + HARD for i in range(n))


def _pages(out):
    pages, i = [], 1
    while True:
        try:
            rows = _lines(out, page=i)
        except IndexError:
            return pages
        pages.append(rows)
        i += 1


def _check_fit(src, faces):
    doc = core.parse_ws(src)
    doc.meta['variant'] = 'ws4'
    pages = _pages(pdf.emit_pdf(doc, mode='modern'))
    assert len(pages) > 1
    for page in pages[:-1]:                    # every page that filled up
        box_bottom = page[-1][0] - pdf._modern_descent(*faces)
        # the last box on a full page ends INSIDE the bottom margin ...
        assert box_bottom >= BOTTOM - 0.05
        # ... and there was no room under it for one more step of this
        # page's own pitch (which is the line box plus whatever blank this
        # document puts between its paragraphs)
        pitch = page[-2][0] - page[-1][0]
        assert box_bottom - pitch < BOTTOM
        # while the BASELINE itself is above that bottom, so a descender no
        # longer hangs past the bottom margin the way it used to
        assert page[-1][0] > box_bottom


def test_a_line_fits_while_its_box_bottom_is_inside_the_frame():
    """The app's fit test, and this engine's: `fragmentTop + h <= top + H`.
    What the fit is judged on is the ladder of box BOTTOMS, which this
    rule does not move -- so a full page still ends exactly where it did,
    with the baseline one descent above that."""
    _check_fit(_many(120), ('Times', 14.0))


def test_a_tall_first_line_does_not_shift_the_pages_below_it():
    """The same check on a document that OPENS mixed -- a 30pt line whose
    own descent is half again a body line's. The lift is per line, so a
    tall opening line does not drag the rest of the document's page breaks
    with it: the box ladder underneath is untouched."""
    _check_fit(_mixed(_many(120)), ('Times', 14.0))


# ------------------------------------------ the spec's own worked example

@pytest.mark.sawyer
def test_lj6dtp_page_one_baselines_lift_by_their_own_descents(
        require_sawyer_doc):
    """Tier 2. The spec's RULE 3 worked example, on LJ6DTP.WS: `.mt 1.1"`
    (margt 79.2), `.mb .5"` (margb 36.0), a 72pt banner at the top and
    12pt body text at the foot.

    The spec quotes the app at a first baseline of 148.60 and this library
    at 165.60 = 79.2 + 86.40. Both of those are numbers about an
    UNTIGHTENED 72pt box; they predate the verse/centre backport (measured
    at c06ea7a), and this banner is a centred row, so on today's engine
    that box is the tightened 59.14 plus its own 13.47pt leading spacer,
    not 86.40. What RULE 3 itself says is reproduced exactly: the baseline
    sits one Helvetica-72 descent (14.904pt) above the bottom of whatever
    box the line got, instead of on it.

    The residual against the app's own 148.60 is therefore not this rule:
    it is that the app does not tighten this banner and this engine does
    (a RULE 1 question), plus the Mac face's real descent against
    Helvetica's published -207/1000.

    Also pinned here: the named last body line the spec tracks is on page
    1, and the document's page count is what it was before the port --
    this rule moves no line onto a different page."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    out = pdf.emit_pdf(doc, mode='modern')
    rows = _lines(out, page=1)
    margt = 79.2
    box = pdf._modern_tight_h('Helvetica', 72)
    spacer = 13.471
    assert box == pytest.approx(59.143, abs=0.005)
    first = rows[0][0]
    box_bottom = pdf.PAGE_H - margt - spacer - box
    assert first == pytest.approx(
        box_bottom + pdf._modern_descent('Helvetica', 72), abs=0.06)
    # stated top-down, the way the spec states its own figures
    assert pdf.PAGE_H - first == pytest.approx(136.90, abs=0.06)
    named = ('This manual describes a Printer Description File for WordStar '
             'for DOS 6.0 and 7.0 that gives').replace(' ', '')
    assert any(r[2].startswith(named) for r in rows)
    assert len(pdf._modern_streams(doc, {}, pdf.FontRes())) == 11
