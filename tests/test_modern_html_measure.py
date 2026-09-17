r"""E9 H4 (Jon's ruling 2026-09-17, the human-eye export audit section G):
Modern HTML gets a measure and an overflow guard.

The stylesheet carried `body{margin:0;padding:2rem 1rem}` and nothing else
-- no `max-width`, no `overflow-wrap`, no width media query anywhere in any
of the 1,022 files the audit rendered. A 1400px window gave about 150
characters to the line, roughly twice a comfortable measure, and at 400px a
long DOS path, a run of RTF control words or a wide row of block graphics
pushed the whole page sideways: 60 of 509 Modern documents scrolled
horizontally, four of them more than four times the viewport.

Four rules, Modern only:
  - `max-width:38em` with `margin:0 auto` -- about 70 characters at the
    14pt Georgia body, inside the 65-75 a reader wants.
  - `overflow-wrap:anywhere` (not `break-word`: only `anywhere` also
    shrinks the element's MIN-CONTENT width, which is what a 400px viewport
    hands a long unbroken path).
  - `p{overflow-x:auto}` -- this emitter's own answer to the audit's
    "`overflow-x:auto` on pre/tables". There are no `<pre>` or `<table>`
    elements here, but there IS content a paragraph may not fold: a picture
    row (`span.ws-nowrap`, planning #264 item 3) and a run of box-drawing
    characters. The paragraph scrolls inside itself instead.
  - `span.ws-nowrap` made a `max-width:100%` inline-block, because the
    paragraph's own scroll is not always the container that ends up holding
    the overflow (`LJ6DTP.WS`'s banner row escaped it, 602px).

Printed is deliberately untouched: it was already clean at 400px, its
`p.ws-native` blocks scroll inside themselves, and a measure imposed on a
line-for-line page would be exactly the page-width opinion the round 3
addendum rejected.

Synthetic fixtures only.
"""
from ctrlkd import core, emit_html

HARD = b'\x0d\x0a'

MEASURE = 'body{max-width:38em;margin:0 auto;overflow-wrap:anywhere}'
PARA_SCROLL = 'p{overflow-x:auto}'
NOWRAP_SCROLL = ('span.ws-nowrap{display:inline-block;max-width:100%;'
                 'overflow-x:auto;vertical-align:top}')


def _ws7(body, dots=b''):
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


def test_modern_carries_the_measure():
    html = emit_html(_ws7(b'some prose' + HARD), mode='modern')
    assert MEASURE in html
    assert PARA_SCROLL in html


def test_the_nowrap_scroll_is_appended_only_when_a_row_uses_it():
    """Same "no CSS-byte delta for a feature this document never used"
    discipline the other conditional rules follow."""
    plain = emit_html(_ws7(b'some prose' + HARD), mode='modern')
    assert NOWRAP_SCROLL not in plain
    graphic = emit_html(_ws7('\u250c\u2500\u2500\u2500\u2510'.encode('cp437') + HARD),
                        mode='modern')
    assert 'class="ws-nowrap"' in graphic
    assert NOWRAP_SCROLL in graphic


def test_printed_does_not():
    html = emit_html(_ws7(b'some prose' + HARD), mode='printed')
    assert MEASURE not in html
    assert PARA_SCROLL not in html


def test_the_facsimile_block_keeps_its_own_scroll():
    """`p.ws-native` needed nothing from this round -- it already scrolls
    inside itself, which is the right behaviour for a facsimile."""
    html = emit_html(_ws7(b'some prose' + HARD), mode='modern')
    assert '.ws-native{white-space:pre;overflow-x:auto;' in html
