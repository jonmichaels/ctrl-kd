"""Round 20 item 4 (slate item 8): squashed cp437 vector glyphs in
Printed PDF.

BISECTED FIRST (per the coordinator's own ordering): CONVERT.WS's printed
PDF at the b22-pin commit (soft-return 142f478, 2026-08-17 -- the nearest
ctrl-kd commit at or before that time is 377f1b1, 2026-08-16 21:15) is
BYTE-IDENTICAL to current HEAD. Not a regression from round 9's Tz/pitch
rework (9a733a4, which post-dates 377f1b1 and changes nothing about this
output either) -- a long-standing defect, present unchanged since at
least 2026-08-16.

ROOT CAUSE: pdf.py's _graphic_ops drew every cp437 vector glyph's
fractional coordinates against the RAW (pitch, h) cell independently --
x-fractions scaled by `pitch` (a 12pt Courier's ~7.2pt advance width),
y-fractions scaled by `h` (~13.2pt, the graphics cell height). A shape
authored to look REGULAR (CONVERT.WS's '■' bullet, LJ6DTP.WS's card-suit
symbol table) came out visibly taller than wide, because pitch != h for
any real printed cell. disc()'s own radius already used `min(pitch, h)`
-- correct by construction, never squashed. poly/rect (and PART_BLOCKS'
own '■' entry) did not.

FIX: `sq = min(pitch, h)`, with every symbol/bullet shape positioned
relative to the CELL CENTER and scaled by `sq` on both axes -- a strict
generalization that reduces algebraically to the exact prior formula
whenever pitch == h, and only corrects the aspect when it doesn't (never
touches ▀▄▌▐, which are genuinely meant to fill actual cell fractions,
not look square).
"""
import re

import os
import pytest

from ctrlkd import core
from ctrlkd.pdf import emit_pdf, _graphic_ops, PART_BLOCKS, SYMBOL_SHAPES


def _esc(b):
    return b'\x1b' + bytes([b]) + b'\x1c'


def _ws_block(cmd, content, jump=None):
    if jump is None:
        jump = len(content) + 4
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([cmd]) + content + j + b'\x1d'


def _rect_ops(ops_bytes):
    """[(x, y, w, h)] from a stream of `%f %f %f %f re f` fill-rect ops."""
    return [tuple(float(v) for v in m.groups())
            for m in re.finditer(rb'([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re f',
                                 ops_bytes)]


_PT_LINE = re.compile(
    rb'^([\d.-]+) ([\d.-]+)(?: ([\d.-]+) ([\d.-]+) ([\d.-]+) ([\d.-]+))? [mlc]$',
    re.MULTILINE)


def _curve_bbox(ops_bytes):
    """Bounding box (w, h) of the FIRST closed path in a run of PDF path
    ops -- only lines shaped like 'x y m'/'x y l'/'x1 y1 x2 y2 x3 y3 c'
    are point data (excludes 're f' rects, 'q 1 g'/'Q' state ops, and any
    LATER sub-shape after the first standalone 'f'). Good enough for a
    disc/poly's own extent without a real curve-flattening implementation
    (a circle Bezier's control points lie on or very near its true
    bounding box)."""
    first_fill = ops_bytes.find(b'\nf\n')
    if first_fill == -1:
        first_fill = len(ops_bytes)
    head = ops_bytes[:first_fill]
    xs, ys = [], []
    for m in _PT_LINE.finditer(head):
        vals = [float(v) for v in m.groups() if v is not None]
        xs.extend(vals[0::2])
        ys.extend(vals[1::2])
    return max(xs) - min(xs), max(ys) - min(ys)


# ============================================================ aspect gate

def test_square_part_block_bullet_is_square_on_a_non_square_cell():
    ops = b'\n'.join(_graphic_ops('■', 0.0, 100.0, pitch=7.2, pt=12.0))
    rects = _rect_ops(ops)
    assert len(rects) == 1
    _, _, w, h = rects[0]
    assert w == pytest.approx(h, abs=0.05), (w, h)


def test_part_block_half_blocks_stay_cell_shaped_not_forced_square():
    # ▀▄▌▐ are genuinely meant to fill actual (non-square) cell fractions
    # -- the fix must NOT touch them.
    for ch, want in (('▀', (7.2, 6.6)), ('▄', (7.2, 6.6)),
                     ('▌', (3.6, 13.2)), ('▐', (3.6, 13.2))):
        ops = b'\n'.join(_graphic_ops(ch, 0.0, 100.0, pitch=7.2, pt=12.0))
        _, _, w, h = _rect_ops(ops)[0]
        assert (w, h) == pytest.approx(want, abs=0.05), (ch, w, h)


def test_diamond_symbol_is_regular_not_stretched():
    ops = b'\n'.join(_graphic_ops('♦', 0.0, 100.0, pitch=7.2, pt=12.0))
    w, h = _curve_bbox(ops)
    assert w == pytest.approx(h, abs=0.6), (w, h)


def test_disc_based_symbols_stay_circular_on_a_non_square_cell():
    # disc() already used min(pitch, h) for its radius before this round
    # -- this is a non-regression pin, not a new fix.
    for ch in ('☻', '♥', '♣', '♠', '☼'):
        ops = b'\n'.join(_graphic_ops(ch, 0.0, 100.0, pitch=7.2, pt=12.0))
        w, h = _curve_bbox(ops)
        assert w == pytest.approx(h, abs=0.9), (ch, w, h)


def test_square_cell_reproduces_the_prior_formula_exactly():
    # When pitch == h the new cell-center-relative math must reduce
    # algebraically to the old `x0 + fx*pitch, yb + fy*h` formula -- the
    # fix is a strict generalization, not a behavior change for the
    # (never-hit-in-practice, but worth proving) square-cell case.
    ops_new = b'\n'.join(_graphic_ops('■', 0.0, 100.0, pitch=10.0, pt=100.0 / 11))
    # pt chosen so h = 1.1*pt = 10.0 == pitch; tolerance covers the ops'
    # own %.1f coordinate formatting, not a real precision claim.
    rects = _rect_ops(ops_new)
    x, y, w, h = rects[0]
    fx, fy, fw, fh = PART_BLOCKS['■']
    assert x == pytest.approx(fx * 10.0, abs=0.06)
    assert w == pytest.approx(fw * 10.0, abs=0.06)
    assert h == pytest.approx(fh * 10.0, abs=0.06)


# ==================================================== end-to-end (real doc)

def test_convert_ws_bullet_square_end_to_end():
    """CONVERT.WS's own '■' bullet, through the real parse+emit pipeline
    (not a synthetic _graphic_ops call) -- the exact document the round-20
    brief named."""
    font = _ws_block(0x02, (240).to_bytes(2, 'little') + (480).to_bytes(2, 'little')
                     + (0).to_bytes(2, 'little') + bytes(6))
    data = font + b'\x1b\xfe\x1c bullet line\r\n'
    doc = core.parse_ws(data)
    out = emit_pdf(doc, mode='printed')
    rects = _rect_ops(out)
    assert rects, 'no vector rect ops found'
    _, _, w, h = rects[0]
    assert w == pytest.approx(h, abs=0.1), (w, h)


@pytest.mark.sawyer
def test_real_convert_ws_bullet_is_square(require_sawyer_doc):
    """Tier 2 (sawyer): CONVERT.WS, one of the ten committed manifest
    documents (tests/SAWYER-CORPUS.md)."""
    path = require_sawyer_doc('CONVERT.WS')
    doc = core.parse(open(path, 'rb').read())
    out = emit_pdf(doc, mode='printed')
    rects = [r for r in _rect_ops(out) if 3 < r[2] < 8 and 3 < r[3] < 8]
    assert rects, 'no bullet-sized rect ops found'
    for _, _, w, h in rects:
        assert w == pytest.approx(h, abs=0.2), (w, h)


@pytest.mark.sawyer
def test_real_lj6dtp_ws_symbols_are_regular(require_sawyer_doc):
    """LJ6DTP.WS's own symbol table (block 24-28: copyright/heart/diamond/
    club/spade/sun) -- the exact 'Shows on screen as' column the round-20
    brief named. Each glyph's own closed path (a contiguous run of m/l/c
    ops ending in 'f') should have a roughly-square bounding box.

    Tier 2 (sawyer): one of the ten committed manifest documents
    (tests/SAWYER-CORPUS.md)."""
    path = require_sawyer_doc('LJ6DTP.WS')
    doc = core.parse(open(path, 'rb').read())
    present = {sp.text for b in doc.blocks for line in b.lines
              for sp in line.spans if sp.text in SYMBOL_SHAPES}
    assert present, 'LJ6DTP.WS no longer carries any of the ruled 7 symbols'
    checked = 0
    for ch in present:
        ops = b'\n'.join(_graphic_ops(ch, 0.0, 100.0, pitch=7.2, pt=12.0))
        if not _PT_LINE.search(ops):
            continue                    # rect-only glyph (e.g. '≡'), no curve to measure
        w, h = _curve_bbox(ops)
        if w < 1.0 or h < 1.0:
            continue
        checked += 1
        assert w == pytest.approx(h, rel=0.35), (ch, w, h)
    assert checked > 0
