"""LJ6DTP parity C2: execute the document's embedded PCL rectangles.

WordStar 7 documents can embed raw PCL through `^P!` custom print controls
(WSFORMAT.TXT's 0x0F "user print control": a display string for the screen,
then "[the remaining bytes] will be sent directly to the printer"). LJ6DTP.WS
uses exactly this to draw its page border (all 8 pages) and page 4's
racing-stripe checkerboard -- our engine decoded the CONTROL (core.py's
`pctl` mark) but only ever kept its display string and declared width,
never the raw PCL payload itself, so neither shape was drawn.

core.py now carries the raw printer-payload bytes in `doc.pcl_programs`
(index on the span's own 'pcl<N>' style tag, alongside the existing
'pctl<hmi>' tag) -- the same offset-indexed mechanism `doc.graphics`/'pix<N>'
already uses. pdf.py's `_parse_pcl_program` tokenizes those bytes into the
small, explicit vocabulary this document actually uses (cursor push/pop,
absolute/relative cursor position, solid or shaded rectangle fill), and
`_pcl_rect_ops` executes one such program into the page's existing `re f`
path, anchored at wherever the running text cursor already is.

Fixture: the real LJ6DTP.WS. Tier 2 (sawyer): one of the ten committed
manifest documents (tests/SAWYER-CORPUS.md) -- migrated 2026-08-26 from the
old flat-directory env var/require_ws7 gate, per Jon's "no third bucket"
ruling that day.

BUG FOUND DURING THAT MIGRATION: the module-level `pytestmark =
pytest.mark.usefixtures('require_ws7')` this docstring used to sit above
gated EVERY test in this file, including the six purely synthetic ones
above (test_raw_pcl_bytes_survive_parsing through
test_unrecognised_pcl_is_ignored_not_failed) that never touch LJ6DTP.WS at
all -- so bare `pytest` ERRORED on all nine of this file's tests whenever
the corpus gate was unarmed, which is every clean checkout. Fixed here by
moving the marker onto only the three tests that actually open the real
document (test_real_document_border_present_on_every_page and the two
after it).
"""
import pytest

from ctrlkd import core
from ctrlkd.pdf import (PAGE_H, _parse_pcl_program, _pcl_rect_ops,
                        _PCL_UNIT_PT)


def _ws_block(cmd, content=b''):
    """One WS5+ symmetric sequence with REAL framing: `1D <jump> <cmd>
    <content> <jump> 1D`, bracketed by its own length -- same construction
    test_ctrlkd.py's `_ws_block`/`ws7_block` use."""
    jump = len(content) + 4
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([cmd]) + content + j + b'\x1d'


# The task's own worked example: LJ6DTP.WS's page border, verbatim.
BORDER_PCL = (
    b'\x1b*p0002x0085Y'
    b'\x1b*c2370a0003b0P'
    b'\x1b*c0003a3120b0P'
    b'\x1b*p0002x3202Y'
    b'\x1b*c2370a0003b0P'
    b'\x1b*p2369x0085Y'
    b'\x1b*c0003a3117b0P'
)


def test_raw_pcl_bytes_survive_parsing():
    """The gap this task started from: the 0x0F handler used to compute the
    printer payload only to search it for a `%F"NAME"` file reference, then
    drop it. A control with a display string and no file reference must now
    show up in doc.pcl_programs, indexed by its span's own 'pcl<N>' tag."""
    body = (0).to_bytes(2, 'little') + bytes([7]) + b'[LOGO] ' + BORDER_PCL
    doc = core.parse_ws(b'Before ' + _ws_block(0x0F, body) + b' after.\r\n')
    assert doc.pcl_programs == [BORDER_PCL]
    tags = set()
    for block in doc.blocks:
        for line in block.lines:
            for span in line.spans:
                tags |= span.styles
    assert 'pctl0' in tags
    assert 'pcl0' in tags


def test_no_embedded_pcl_emits_no_rectangles():
    """A document with no 0x0F control at all -- the overwhelming common
    case -- must carry an empty pcl_programs list and never invoke the
    rectangle path. (A 0x0F control that itself carries no printer bytes,
    e.g. a bare `%F"NAME"` include, must likewise leave pcl_programs empty:
    core.py only appends when `printer` is non-empty.)"""
    doc = core.parse_ws(b'Nothing but ordinary prose here.\r\n')
    assert doc.pcl_programs == []

    body = (0).to_bytes(2, 'little') + bytes([0]) + b'%F"PLEAD.PS"'
    doc = core.parse_ws(b'Before ' + _ws_block(0x0F, body) + b' after.\r\n')
    assert doc.pcl_programs == []
    assert doc.includes == ['PLEAD.PS']


def test_worked_example_parses_to_four_rectangles():
    """The task's own worked example, decoded by _parse_pcl_program: four
    moves (three absolute, since none of these are signed) and four solid
    (fill type 0) rectangle fills -- the top/left/bottom/right rules of
    LJ6DTP's page border."""
    ops = _parse_pcl_program(BORDER_PCL)
    kinds = [op[0] for op in ops]
    assert kinds == ['movex', 'movey', 'fill', 'fill',
                     'movex', 'movey', 'fill',
                     'movex', 'movey', 'fill']
    fills = [op for op in ops if op[0] == 'fill']
    assert fills == [
        ('fill', 2370, 3, 0.0),
        ('fill', 3, 3120, 0.0),
        ('fill', 2370, 3, 0.0),
        ('fill', 3, 3117, 0.0),
    ]


def test_worked_example_rectangle_geometry_in_points():
    """Executed against an arbitrary anchor (irrelevant here -- every move in
    this program is absolute, so the anchor is immediately overwritten), the
    four fills land at the exact PDF points the real gpcl6 render measures
    LJ6DTP's border rules at (verified pixel-for-pixel against
    ws7-prints/gpcl6-renders/LJ6DTP-p1.png at 300dpi, where 1 pixel == 1 PCL
    unit: the top rule's dark row sits at pixel/PCL y=85..87, the left rule's
    dark column at x=77..79, the right rule's at x=2444..2446, the bottom
    rule's dark row at y=3202..3204 -- i.e. a flat +75-unit (0.25in) offset
    on X, none on Y, converting this document's own PCL-absolute coordinates
    to the page)."""
    ops = _parse_pcl_program(BORDER_PCL)
    rect_ops = _pcl_rect_ops(ops, anchor_x=0.0, anchor_y=0.0, page_h=PAGE_H,
                             restore_gray=0.0)
    # every fill is solid black (gray 0.0, the restore value): no 'g' op
    assert all(b' g' not in op for op in rect_ops)
    rects = [tuple(float(v) for v in op.split()[:4]) for op in rect_ops
            if op.endswith(b're f')]
    assert len(rects) == 4

    def pt(units):
        return units * _PCL_UNIT_PT

    top_x, top_y = pt(2 + 75), PAGE_H - pt(85)
    # top rule: 2370 x 3 at (2,85)
    assert rects[0] == pytest.approx((top_x, top_y - pt(3), pt(2370), pt(3)))
    # left rule: 3 x 3120, SAME position (no intervening move)
    assert rects[1] == pytest.approx((top_x, top_y - pt(3120), pt(3), pt(3120)))
    # bottom rule: 2370 x 3 at (2, 3202)
    bot_y = PAGE_H - pt(3202)
    assert rects[2] == pytest.approx((top_x, bot_y - pt(3), pt(2370), pt(3)))
    # right rule: 3 x 3117 at (2369, 85)
    right_x = pt(2369 + 75)
    assert rects[3] == pytest.approx((right_x, top_y - pt(3117), pt(3), pt(3117)))


def test_shaded_fill_form_is_recognised():
    """The initial byte-vocabulary inventory this task started from counted
    164 occurrences of the plain `ESC*c<w>a<h>b<f>P` form and called that the
    whole vocabulary -- it missed page 4's checkerboard entirely, which uses
    a 4th, undocumented-by-the-inventory form: `ESC*c<w>a<h>b<pct>g2P`, a
    shading-pattern fill where the `b` value is an ink PERCENTAGE, not a
    fill-type code. 100% shading reads as solid black, same as fill type 0."""
    ops = _parse_pcl_program(b'\x1b*c0075a0075b0015g2P\x1b*c0075a0075b0100g2P')
    assert ops == [
        ('fill', 75, 75, 1.0 - 0.15),
        ('fill', 75, 75, 0.0),
    ]


def test_unrecognised_pcl_is_ignored_not_failed():
    """Anything outside the four recognised forms is recorded as ignored --
    this is deliberately NOT a general PCL interpreter (task instruction)."""
    ops = _parse_pcl_program(b'\x1b(8U\x1b*c0075a0075b0P')
    assert ops[0] == ('ignored', b'\x1b(8U')
    assert ops[1] == ('fill', 75, 75, 0.0)


@pytest.mark.sawyer
def test_real_document_border_present_on_every_page(require_sawyer_doc):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    borders = [p for p in doc.pcl_programs if p.count(b'&f0S') == 0
              and p.count(b'*c') == 4]
    assert len(borders) == 8
    assert all(p == borders[0] for p in borders)


@pytest.mark.sawyer
def test_real_document_checkerboard_uses_shading(require_sawyer_doc):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    shaded = [p for p in doc.pcl_programs if b'g2P' in p]
    assert len(shaded) == 33
    percentages = set()
    for prog in shaded:
        for op in _parse_pcl_program(prog):
            if op[0] == 'fill' and op[1] == 75 and op[2] == 75:
                percentages.add(op[3])
    assert percentages == {1.0 - 0.15, 0.0}    # 15% gray and 100% (solid)


@pytest.mark.sawyer
def test_real_document_pdf_border_rect_ops_present(require_sawyer_doc):
    """End to end: emit_pdf's Printed content must contain the exact border
    rectangles, in points, at the calibrated PCL page origin -- not just the
    parser's op list, but the actual `re f` bytes a page stream carries.
    Printed page content streams are written uncompressed (no /Filter on
    them), so the op is a direct substring of the PDF bytes."""
    from ctrlkd.pdf import emit_pdf

    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    pdf_bytes = emit_pdf(doc, mode='printed')

    def pt(units):
        return units * _PCL_UNIT_PT

    top_x = pt(2 + 75)
    top_y = PAGE_H - pt(85)
    expected_top_rule = b'%.2f %.2f %.2f %.2f re f' % (
        top_x, top_y - pt(3), pt(2370), pt(3))
    assert expected_top_rule in pdf_bytes
    # the border's own left rule (3 x 3120), same position -- proof it drew
    # at the SAME cursor rather than a stray reset between fills
    expected_left_rule = b'%.2f %.2f %.2f %.2f re f' % (
        top_x, top_y - pt(3120), pt(3), pt(3120))
    assert expected_left_rule in pdf_bytes
