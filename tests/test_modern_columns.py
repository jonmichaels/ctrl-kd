r"""Jon's ruling 2026-09-15 ("Yes. Fix it."): the Modern PDF keeps the
document's own SHEET ORIENTATION (`.pr or=l`, or a `.pl` shorter than the
sheet is wide) and its own COLUMN COUNT (`.co n`).

Two standing rulings converge on it. 2026-08-05: "Modern PDF needs to be
the printed version of the Modern RTF" -- a landscape, two-column document
rendered portrait and one-column is not a printing of anything the
document says. 2026-08-17, the paged-surface doctrine, point 2: "honor
`.pr or=l` landscape in ALL paged surfaces" -- Modern PDF was the one
paged surface it had never reached.

WHAT MODERN KEEPS OF ITS OWN (the governing-defaults principle, 2026-08-05:
the document's explicit choices win, and where it is silent Modern
gap-fills with our take): the typography. Modern fonts, 1.2 line height,
Modern's own margins scaled to the sheet, its own running heads (M5) and
its own end-matter (M1). What it takes from the document is the SHEET and
the COLUMN GRID -- the two things the document states outright.

A column's own measure is Modern's text width divided n ways with the
document's gutter, which is what `\cols n\colsx g` says to an RTF reader
and therefore what Modern PDF, as that RTF's printed form, must do.
Printed reads the same measure off `.rm` instead, because an author who
wants n real columns sets `.rm` to one column's width first -- the same
number stated in WordStar's own units. BOOKLET.WS proves they agree:
`.po .2i` + `.rm 4.50"` + a 1.00" gutter fills an 11in landscape sheet
almost exactly as the division does.

NO BALANCING, because WordStar does not balance (planning #227 §5,
measured on WINGDING.CHT's own short last column): a trailing group of
fewer than n columns is simply left short.

Synthetic fixtures only.
"""
import re

from ctrlkd import core, pdf

HARD = b'\x0d\x0a'


def _ws7(body, dots=b''):
    """A WS5+/WS7 document: the type-0 header block, then raw lines."""
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


def _mediabox(out):
    m = re.search(rb'/MediaBox \[0 0 (\d+) (\d+)\]', out)
    assert m is not None
    return int(m.group(1)), int(m.group(2))


def _page_streams(out):
    """Each page's content stream, decoded, in page order."""
    return [s.split(b'\nendstream')[0].lstrip(b'\n')
            for s in out.split(b'>>\nstream\n')[1:]]


# M15 (2026-09-15): Modern draws its running feet -- and WordStar's own
# automatic page number -- in the bottom margin zone, at y <= 44. These
# tests are about the COLUMN grid, so the zone is skipped rather than each
# assertion being taught to expect one more (centred) x; Modern's body
# never reaches it.
MODERN_FOOT_ZONE = 44.0

_TD_XY = re.compile(rb'Ts ([\d.]+) ([\d.]+) Td \((.*?)\) Tj')


def _body_ops(stream):
    """(x, y, text) for every drawn op outside the running-foot zone."""
    return [(float(x), float(y), t.decode('latin-1'))
            for x, y, t in _TD_XY.findall(stream)
            if float(y) > MODERN_FOOT_ZONE]


def _xs(stream):
    """Every drawn text x, in draw order."""
    return [x for x, _y, _t in _body_ops(stream)]


def _words(stream):
    return [t for _x, _y, t in _body_ops(stream)]


_PARA = (b'The quick brown fox jumps over the lazy dog and keeps running '
         b'until the line has to wrap somewhere sensible.' + HARD)


# -------------------------------------------------- the sheet's orientation

def test_a_landscape_document_gets_a_landscape_modern_sheet():
    doc = _ws7(b'Body text.' + HARD, dots=b'.pr or=l' + HARD)
    assert doc.meta['formatting']['orientation'] == 'landscape'
    assert _mediabox(pdf.emit_pdf(doc, mode='modern')) == (792, 612)


def test_a_landscape_pl_that_is_no_portrait_height_still_resolves_the_sheet():
    """Every real landscape template in the archive declares a `.pl` that
    matches Letter's WIDTH, not its height (`.pl 8.5"`): resolved on the
    portrait column it used to come back a square."""
    doc = _ws7(b'Body text.' + HARD,
               dots=b'.pr or=l' + HARD + b'.pl 8.50"' + HARD)
    assert _mediabox(pdf.emit_pdf(doc, mode='modern')) == (792, 612)


def test_the_body_is_laid_out_on_the_landscape_sheet_not_above_it():
    """The swap alone is not the fix: Modern used to start its `y` cursor at
    Letter's own 792pt whatever sheet it was drawing on, which puts every
    line of a 612pt-tall landscape page above the top of the page."""
    doc = _ws7(_PARA, dots=b'.pr or=l' + HARD + b'.pl 8.50"' + HARD)
    out = pdf.emit_pdf(doc, mode='modern')
    _w, h = _mediabox(out)
    ys = [float(t) for t in re.findall(rb' [\d.]+ ([\d.]+) Td', out)]
    assert ys
    assert max(ys) < h, max(ys)


def test_a_portrait_document_keeps_the_portrait_modern_sheet():
    doc = _ws7(b'Body text.' + HARD, dots=b'.pr or=p' + HARD)
    assert _mediabox(pdf.emit_pdf(doc, mode='modern')) == (612, 792)


def test_a_document_that_never_declares_an_orientation_is_untouched():
    doc = _ws7(b'Body text.' + HARD)
    assert _mediabox(pdf.emit_pdf(doc, mode='modern')) == (612, 792)


# ---------------------------------------------------------- the column grid

def _columnar(cols=2, gutter=b' 10', landscape=True, body=None):
    dots = b''
    if landscape:
        dots += b'.pr or=l' + HARD + b'.pl 8.50"' + HARD
    dots += b'.co %d,%s' % (cols, gutter) + HARD
    return _ws7((body if body is not None else _PARA * 12), dots=dots)


def test_a_two_column_landscape_document_draws_both_columns_on_page_one():
    out = pdf.emit_pdf(_columnar(), mode='modern')
    assert _mediabox(out) == (792, 612)
    xs = _xs(_page_streams(out)[0])
    assert xs
    # two distinct left edges, and the second one starts past the middle
    # of the sheet -- a real second column, not an indent
    starts = sorted({round(x) for x in xs})
    assert starts[0] < 396 < starts[-1], starts


def test_the_second_column_starts_one_column_plus_the_gutter_over():
    """`.co 2, 10`: the gutter is print columns at 10 CPI, so 10 is a full
    inch -- the identical reading `emit._rtf_cols_control` gives `\\colsx`."""
    out = pdf.emit_pdf(_columnar(cols=2, gutter=b' 10'), mode='modern')
    margl, _margt, _margb, width = pdf._modern_geometry(
        _columnar(cols=2, gutter=b' 10'))
    col_w, gap = pdf._modern_column_width(width, 2, 10.0)
    assert round(gap, 1) == 72.0                       # 10 cols at 10 CPI
    xs = _xs(_page_streams(out)[0])
    left = min(xs)
    second = min(x for x in xs if x > margl + col_w)
    assert round(second - left, 1) == round(col_w + gap, 1), (second, left)


def test_a_line_wraps_at_the_column_not_at_the_page():
    """The whole point of the grid: the measure every line is broken at is
    one column's, not the sheet's."""
    doc = _columnar()
    out = pdf.emit_pdf(doc, mode='modern')
    margl, _mt, _mb, width = pdf._modern_geometry(doc)
    col_w, _gap = pdf._modern_column_width(width, 2, 10.0)
    xs = _xs(_page_streams(out)[0])
    col0 = [x for x in xs if x < margl + col_w]
    assert col0
    assert max(col0) - margl <= col_w, (max(col0), margl, col_w)


def test_columns_fill_down_then_across():
    """Fill order is down column 1, then column 2 -- research §4, confirmed
    against WINGDING.CHT/SYMBOL.CHT/PRINT.TST's own real WS7 captures."""
    body = b''.join(b'Line %03d here.' % i + HARD for i in range(1, 121))
    doc = _columnar(body=body)
    out = pdf.emit_pdf(doc, mode='modern')
    margl, _mt, _mb, width = pdf._modern_geometry(doc)
    col_w, _gap = pdf._modern_column_width(width, 2, 10.0)
    page1 = _page_streams(out)[0]
    xs, words = _xs(page1), _words(page1)
    col0 = [w for x, w in zip(xs, words)
            if x < margl + col_w and w.isdigit()]
    col1 = [w for x, w in zip(xs, words)
            if x >= margl + col_w and w.isdigit()]
    assert col0 and col1
    assert int(col0[0]) == 1
    assert int(col1[0]) > int(col0[-1]), (col0[-1], col1[0])


def test_a_one_column_document_places_every_line_at_the_same_left_edge():
    """The control: `.co 1` (or no `.co` at all) is the arithmetic that was
    there before this ruling."""
    for dots in (b'', b'.co 1' + HARD):
        doc = _ws7(_PARA * 6, dots=dots)
        xs = _xs(_page_streams(pdf.emit_pdf(doc, mode='modern'))[0])
        assert len({round(x) for x in xs}) >= 1
        assert max(xs) < 612, max(xs)


def test_turning_columns_off_starts_a_fresh_sheet():
    """A change of column regime starts its own sheet, the same rule
    `_doc_to_pagelines`' own block loop follows in Printed."""
    doc = _ws7(b'Columnar text.' + HARD
               + b'.co 1' + HARD
               + b'Back to one column.' + HARD,
               dots=b'.co 2, 10' + HARD)
    out = pdf.emit_pdf(doc, mode='modern')
    streams = _page_streams(out)
    assert len(streams) == 2
    assert 'Columnar' in ' '.join(_words(streams[0]))
    assert 'Back' in ' '.join(_words(streams[1]))


def test_a_pa_inside_a_columnar_region_is_absorbed():
    """The identical reading Printed has carried since planning #227,
    measured against WINGDING.CHT's own WS7 capture: the author's `.pa`
    markers are a manual column simulation that predates the real `.co`
    governing the same content."""
    doc = _ws7(b'First.' + HARD + b'.pa' + HARD + b'Second.' + HARD,
               dots=b'.co 2, 10' + HARD)
    streams = _page_streams(pdf.emit_pdf(doc, mode='modern'))
    assert len(streams) == 1
    assert {'First.', 'Second.'} <= set(_words(streams[0]))


def test_a_pa_outside_a_columnar_region_is_still_a_page_break():
    doc = _ws7(b'First.' + HARD + b'.pa' + HARD + b'Second.' + HARD)
    streams = _page_streams(pdf.emit_pdf(doc, mode='modern'))
    assert len(streams) == 2


def test_cb_breaks_to_the_next_column_inside_a_columnar_region():
    doc = _ws7(b'First.' + HARD + b'.cb' + HARD + b'Second.' + HARD,
               dots=b'.co 2, 10' + HARD)
    streams = _page_streams(pdf.emit_pdf(doc, mode='modern'))
    assert len(streams) == 1
    xs, words = _xs(streams[0]), _words(streams[0])
    first_x = next(x for x, w in zip(xs, words) if w == 'First.')
    second_x = next(x for x, w in zip(xs, words) if w == 'Second.')
    assert second_x > first_x, (first_x, second_x)


def test_cb_outside_a_columnar_region_draws_nothing_and_breaks_nothing():
    """`.cb` with no live `.co` is a no-op -- the twin of Printed RTF
    writing no `\\column` for one."""
    doc = _ws7(b'First.' + HARD + b'.cb' + HARD + b'Second.' + HARD)
    streams = _page_streams(pdf.emit_pdf(doc, mode='modern'))
    assert len(streams) == 1
    assert {'First.', 'Second.'} <= set(_words(streams[0]))


def test_the_last_column_group_is_not_balanced():
    """WordStar does not balance. A document with barely any text fills
    column 1 and leaves column 2 empty rather than splitting it evenly."""
    doc = _ws7(b'Only one short line.' + HARD, dots=b'.co 2, 10' + HARD)
    margl, _mt, _mb, width = pdf._modern_geometry(doc)
    col_w, _gap = pdf._modern_column_width(width, 2, 10.0)
    streams = _page_streams(pdf.emit_pdf(doc, mode='modern'))
    assert len(streams) == 1
    xs = _xs(streams[0])
    assert xs and max(xs) < margl + col_w, xs   # nothing in column 2


def test_the_column_measure_is_modern_own_width_divided_not_the_rm():
    """`.rm` inside a columnar region IS the column measure restated in
    WordStar's own units; spending it on top of the division would narrow
    every column twice."""
    doc = _ws7(_PARA * 8, dots=b'.co 2, 10' + HARD + b'.rm 4.50"' + HARD)
    _margl, _mt, _mb, width = pdf._modern_geometry(doc)
    col_w, gap = pdf._modern_column_width(width, 2, 10.0)
    xs = _xs(_page_streams(pdf.emit_pdf(doc, mode='modern'))[0])
    left = min(xs)
    col0 = [x for x in xs if x < left + col_w - 1]
    # the widest line in column 1 reaches well past what a doubly-cut
    # column would allow (which would be col_w minus the `.rm` shortfall)
    assert max(col0) - left > col_w / 2, (max(col0) - left, col_w)
    assert round(gap, 1) == 72.0


def test_modern_column_width_is_the_gutter_default_of_one_print_column():
    """An author who names no gutter gets one print column, the same
    default `emit._rtf_cols_control` writes into `\\colsx`."""
    assert pdf._modern_column_width(500.0, 1, None) == (500.0, 0.0)
    w, gap = pdf._modern_column_width(500.0, 2, None)
    assert round(gap, 2) == 7.2
    assert round(w, 2) == round((500.0 - 7.2) / 2, 2)


# --------------------------------------------- M17b: the Modern RTF says so too
# The 2026-08-05 ruling runs in both directions: Modern PDF is the printed
# form of the Modern RTF, so the RTF has to SAY the sheet and the column grid
# its PDF draws. Before M17b a landscape two-column document's Modern RTF was
# a square `\paperw12240\paperh12240` with no `\landscape` and no `\cols` --
# an RTF its own PDF could not print. Reuses planning #264 R1's section spine
# (`emit._rtf_columns_state`, `_rtf_cols_control`, `_rtf_section_breaks`),
# which is also what keeps the two engines' readings of "which column regime
# is this block in" from ever drifting apart.

def _modern_rtf(doc):
    from ctrlkd import emit
    return emit.emit_rtf(doc, mode='modern')


def test_the_modern_rtf_carries_the_landscape_sheet():
    doc = _ws7(b'Body text.' + HARD,
               dots=b'.pr or=l' + HARD + b'.pl 8.50"' + HARD)
    rtf = _modern_rtf(doc)
    assert r'\paperw15840' in rtf and r'\paperh12240' in rtf
    assert r'\landscape' in rtf


def test_the_modern_rtf_sheet_is_its_own_pdf_mediabox():
    """The 08-05 tie, asserted directly: what the RTF declares in twips and
    what its printed form draws in points are the same sheet."""
    doc = _ws7(_PARA, dots=b'.pr or=l' + HARD + b'.pl 8.50"' + HARD)
    w, h = _mediabox(pdf.emit_pdf(doc, mode='modern'))
    rtf = _modern_rtf(doc)
    assert r'\paperw%d' % (w * 20) in rtf, (w, rtf[:200])
    assert r'\paperh%d' % (h * 20) in rtf, (h, rtf[:200])


def test_a_portrait_modern_rtf_says_nothing_about_orientation():
    doc = _ws7(b'Body text.' + HARD, dots=b'.pr or=p' + HARD)
    rtf = _modern_rtf(doc)
    assert r'\landscape' not in rtf
    assert r'\paperw12240' in rtf


def test_the_modern_rtf_carries_the_column_count_and_gutter():
    rtf = _modern_rtf(_columnar(cols=2, gutter=b' 10'))
    assert r'\cols2' in rtf
    assert r'\colsx1440' in rtf          # 10 print columns x 144 twips


def test_the_modern_rtf_gutter_is_the_pdf_gutter():
    doc = _columnar(cols=2, gutter=b' 10')
    _margl, _mt, _mb, width = pdf._modern_geometry(doc)
    _col_w, gap_pt = pdf._modern_column_width(width, 2, 10.0)
    m = re.search(r'\\colsx(\d+)', _modern_rtf(doc))
    assert m and int(m.group(1)) == round(gap_pt * 20), (m, gap_pt)


def test_a_one_column_modern_rtf_writes_no_cols():
    assert r'\cols' not in _modern_rtf(_ws7(_PARA))


def test_a_mid_document_co_opens_a_modern_section():
    doc = _ws7(b'Opening.' + HARD + b'.co 2, 10' + HARD + _PARA)
    rtf = _modern_rtf(doc)
    assert r'\sect\sectd' in rtf
    assert r'\cols2' in rtf


def test_cb_is_a_column_break_in_the_modern_rtf():
    doc = _ws7(b'First.' + HARD + b'.cb' + HARD + b'Second.' + HARD,
               dots=b'.co 2, 10' + HARD)
    assert r'\column' in _modern_rtf(doc)


def test_cb_outside_a_columnar_region_writes_nothing_in_modern_rtf():
    doc = _ws7(b'First.' + HARD + b'.cb' + HARD + b'Second.' + HARD)
    assert r'\column' not in _modern_rtf(doc)


def test_a_pa_inside_a_columnar_region_is_absorbed_in_the_modern_rtf():
    """The same reading Modern PDF takes (planning #227, WINGDING.CHT's own
    WS7 capture): those `.pa` markers are a manual column simulation, and
    honouring them fragments one real column into two short pages."""
    doc = _ws7(b'First.' + HARD + b'.pa' + HARD + b'Second.' + HARD,
               dots=b'.co 2, 10' + HARD)
    assert r'\page ' not in _modern_rtf(doc)
    plain = _ws7(b'First.' + HARD + b'.pa' + HARD + b'Second.' + HARD)
    assert r'\page ' in _modern_rtf(plain)
