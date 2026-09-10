"""Planning #251(c): cp437 graphic-character cell geometry moves onto the
page-lines model, and a PUBLIC function exposes the unit-cell geometry
without exporting `pdf.py`'s own internal tables.

Two halves:
  1. `graphic_cell_rects(char)` -- the geometry lookup itself, pure and
     document-independent (every one of the six categories: arcCorners/
     boxArms/shadeGray/partBlocks/symbolShapes/fullBlock).
  2. `PageLine.graphic_cells` / the `layout` JSON's own 'graphic_cells' --
     the PER-DOCUMENT placement (x/width) of each graphic character a
     line actually draws, moved off `_line_ops_printed`'s own render-time
     advance onto the model.
"""
import json

from ctrlkd import core, pdf, layout as _layout

HARD = b'\r\n'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


# ------------------------------------------------------- graphic_cell_rects

def test_graphic_cell_rects_covers_every_graphic_character():
    """No character in GRAPHIC_CHARS (the union of all six categories) is
    silently unrepresented -- every one returns at least one rect."""
    for ch in sorted(pdf.GRAPHIC_CHARS):
        rects = pdf.graphic_cell_rects(ch)
        assert rects, f'{ch!r} (U+{ord(ch):04X}) has no rects'
        for x, y, w, h in rects:
            assert w > 0 and h > 0


def test_graphic_cell_rects_empty_for_a_non_graphic_character():
    assert pdf.graphic_cell_rects('A') == []
    assert pdf.graphic_cell_rects(' ') == []


def test_graphic_cell_rects_full_block_and_shades_fill_the_cell():
    assert pdf.graphic_cell_rects('█') == [(0.0, 0.0, 1.0, 1.0)]
    for ch in '░▒▓':
        assert pdf.graphic_cell_rects(ch) == [(0.0, 0.0, 1.0, 1.0)]


def test_graphic_cell_rects_part_blocks_match_the_table_fractions():
    # At the square-cell assumption this function documents, a part
    # block's rect is exactly PART_BLOCKS' own stored fraction (see that
    # function's own docstring for why the square correction reduces to
    # the identity here).
    assert pdf.graphic_cell_rects('▀') == [pdf.PART_BLOCKS['▀']]
    assert pdf.graphic_cell_rects('■') == [pdf.PART_BLOCKS['■']]


def test_graphic_cell_rects_box_arms_cross_has_four_stubs():
    # '┼' has all four arms (up, down, left, right), single weight --
    # two horizontal stubs (left/right halves) and two vertical.
    rects = pdf.graphic_cell_rects('┼')
    assert len(rects) == 4
    xs = sorted(r[0] for r in rects)
    assert xs[0] == 0.0    # left arm starts at the cell edge


def test_graphic_cell_rects_double_line_has_two_strokes():
    # '═' is a double-weight horizontal rule (left AND right arms, weight
    # 2) -- two stroke rects per side present, none for up/down (absent).
    rects = pdf.graphic_cell_rects('═')
    assert len(rects) == 4    # 2 strokes x (left half + right half)


def test_graphic_cell_rects_symbol_shape_omits_knockouts():
    # '☻' has three positive shapes (a disc + nothing else after
    # dropping the four 'white' knockout sub-shapes for eyes/mouth).
    rects = pdf.graphic_cell_rects('☻')
    assert len(rects) == 1


def test_graphic_cell_rects_arc_corner_is_a_bounding_approximation():
    # '╭' (was '┌') gets the same two-stub SHAPE as its square-cornered
    # BOX_ARMS sibling would -- an honest approximation, not a curve.
    arc = pdf.graphic_cell_rects('╭')
    square = pdf.graphic_cell_rects('┌')
    assert len(arc) == len(square) == 2


# --------------------------------------------------- PageLine.graphic_cells

def _box_doc():
    body = (b'\xda\xc4\xc4\xbf' + HARD    # \xda=┌ \xc4=─ \xbf=┐  (cp437)
            + b'\xb3ab\xb3' + HARD         # \xb3=│
            + b'\xc0\xc4\xc4\xd9' + HARD)  # \xc0=└ \xd9=┘
    return core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)


def test_graphic_cells_land_on_the_pageline_model():
    doc = _box_doc()
    pages = pdf._doc_to_pagelines(doc, True)
    lines = [ln for ln in pages[0] if getattr(ln, 'graphic_cells', None)]
    assert len(lines) == 3
    top = lines[0].graphic_cells
    chars = [c for c, x, w in top]
    assert chars == ['┌', '─', '─', '┐']
    # sequential, non-overlapping cells at a constant pitch (fontless =
    # Courier grid, every cell the SAME width).
    widths = {w for c, x, w in top}
    assert len(widths) == 1
    xs = [x for c, x, w in top]
    assert xs == sorted(xs)
    assert all(round(xs[i + 1] - xs[i], 1) == round(list(widths)[0], 1)
              for i in range(len(xs) - 1))

    middle = lines[1].graphic_cells
    assert [c for c, x, w in middle] == ['│', '│']   # only the two bars --
                                                       # 'ab' is ordinary text


def test_graphic_cells_absent_for_a_line_with_no_graphics():
    doc = _box_doc()
    pages = pdf._doc_to_pagelines(doc, True)
    prose_only = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'An ordinary line of prose, nothing graphic here at all.' + HARD)
    prose_pages = pdf._doc_to_pagelines(prose_only, True)
    assert getattr(prose_pages[0][0], 'graphic_cells', None) is None


def test_graphic_cells_x_matches_what_the_pdf_actually_draws():
    """The model's own x is not a re-derivation that could drift from the
    PDF -- byte-check one cell's x against the real content stream."""
    import re
    import zlib
    doc = _box_doc()
    pages = pdf._doc_to_pagelines(doc, True)
    top = pages[0][0].graphic_cells
    first_x, first_w = top[0][1], top[0][2]
    mx = first_x + first_w / 2.0   # '┌' = (down, right): both its arms
                                   # meet at the cell's own horizontal
                                   # center, `_graphic_ops`'s own `mx`

    out = pdf.emit_pdf(doc, mode='printed')
    streams = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', out, re.S):
        try:
            streams.append(zlib.decompress(m[1]))
        except zlib.error:
            streams.append(m[1])
    body = b'\n'.join(streams)
    assert ('%.1f' % mx).encode() in body


def test_graphic_cells_in_layout_json():
    doc = _box_doc()
    out = json.loads(_layout.emit_layout(doc))
    assert out['version'] == 5
    top = out['printed']['pages'][0]['lines'][0]
    assert 'graphic_cells' in top
    assert [c['char'] for c in top['graphic_cells']] == ['┌', '─', '─', '┐']
    assert all({'char', 'x', 'width'} <= set(c) for c in top['graphic_cells'])
    # a prose-only document carries the key nowhere.
    prose = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'An ordinary line of prose, nothing graphic here at all.' + HARD)
    prose_out = json.loads(_layout.emit_layout(prose))
    assert 'graphic_cells' not in prose_out['printed']['pages'][0]['lines'][0]
