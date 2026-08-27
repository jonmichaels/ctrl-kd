"""LJ6DTP parity C12: page 7's proportional-spacing table draws HAIRLINE
rules; ours read visibly heavier because the double-weight box-drawing
gap was an unmeasured guess.

Page 7's PC-8/font-family grid types real double-line box-drawing
characters (═ 0xCD, ║ 0xBA, and their junction glyphs -- the SAME
mechanism as register C11's page-5 rules, just weight=2 instead of
weight=1: `core._symmetric_blocks` decodes the wrapped `<1B C4 1C>`-style
triples into the glyphs themselves, `pdf._graphic_ops`'s BOX_ARMS path
draws them as vector rectangles). Page 7 is otherwise the document's own
best-matching page -- this was the only visible difference.

Pixel-sampled at 300dpi against LJ6DTP-p7.png (10.05pt Courier, the
table's own font): real WS7 draws a double rule as two ~3px (~0.72pt)
strokes separated by a ~3px gap -- stroke and gap the SAME size. Our own
single-weight rules elsewhere on the same page already matched (~3px);
the double-weight ones did not, because `d` (the half-gap offset) was
`pt / 10.0`, an unmeasured guess with no citation, giving a ~5px
(~1.2pt) gap -- noticeably wider than the stroke itself, which is what
read as "possibly doubled" and heavier as a unit.

Fix: `d = t` (the double-line half-gap uses the SAME value as the
single-line stroke weight) instead of the independent `pt / 10.0`
formula. This only affects weight=2 box-drawing characters -- the ones
this table is built from almost exclusively in the whole corpus (107+
`║`, 176+ `═` occurrences in LJ6DTP.WS, essentially all of them inside
this one table) -- so the fix is effectively scoped to exactly the
place it was measured.
"""
import pytest

from ctrlkd import core, pdf


def test_double_weight_gap_equals_the_single_weight_stroke():
    """The formula itself: d must now be derived from t, not from an
    independent pt/10 guess."""
    pt = 10.05
    t = max(0.5, pt / 12.0)
    ops = b'\n'.join(pdf._graphic_ops('═', 0.0, 100.0, 7.2, pt))
    # Two filled rects (the double horizontal arm halves) whose y-extents
    # are t apart from each other by exactly 2*d -- recover d from the
    # emitted rectangle coordinates rather than re-deriving it, so this
    # actually pins the RENDERED geometry, not just the source formula.
    import re
    ys = sorted({float(m.group(1)) for m in
                re.finditer(rb'[\d.]+ ([\d.]+) [\d.]+ [\d.]+ re f', ops)})
    assert len(ys) == 2                       # top stroke, bottom stroke
    gap = ys[1] - ys[0] - t                  # non-inked gap between the strokes
    # d == t (within rect()'s own %.1f rounding on two independent
    # coordinates, up to +/-0.1 combined) -- NOT the old pt/10 (which would
    # put gap at ~1.2 here, off by 0.4+, far outside this tolerance).
    assert abs(gap - t) < 0.15


def test_single_weight_rule_thickness_unchanged():
    """Register C12 only touches the double-weight (`d`) parameter -- a
    plain single '─' must draw at exactly the same thickness as before
    (max(0.5, pt/12)), unaffected by this fix."""
    pt = 12.0
    t = max(0.5, pt / 12.0)
    ops = b'\n'.join(pdf._graphic_ops('─', 0.0, 100.0, 7.2, pt))
    assert ('%.1f' % t).encode() in ops


@pytest.mark.sawyer
def test_lj6dtp_proportional_spacing_table_uses_double_line_box_chars(require_sawyer_doc):
    """Confirms the root cause against the real fixture: the table's own
    header separator is genuinely built from '═' (weight-2), not a
    synthetic table-bounding rule this engine invented.

    Tier 2 (sawyer): LJ6DTP.WS, one of the ten committed manifest documents
    (tests/SAWYER-CORPUS.md)."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    found = False
    for b in doc.blocks:
        for ln in getattr(b, 'lines', []):
            t = ''.join(s.text for s in ln.spans)
            if t.count('═') > 30:            # a real rule row, not a stray char
                found = True
    assert found, 'no ═ (weight-2) rule line found in LJ6DTP.WS'
