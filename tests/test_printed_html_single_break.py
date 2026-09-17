r"""E9 H1 (Jon's ruling 2026-09-17, the human-eye export audit section D):
one newline per facsimile line in Printed HTML, and no `<br>`.

`p.ws-native` settled on `white-space:pre` (its `overflow-x:auto` is what
lets a wide facsimile line scroll inside itself instead of dragging the
page sideways), and under `pre` the newline IS the break. The emitter also
wrote a `<br>` at the end of every line, so there were TWO breaks per line:
every line of the document was followed by a blank one, a 57-page novel
arrived twice as tall as it is, and the 1990 line grid was gone. 481 of 511
Printed HTML documents used `ws-native`; 195 Modern ones did, through the
print-stream/ruler-line documents that are forced to the facsimile path.

Synthetic fixtures only.
"""
import re

from ctrlkd import core, emit_html

HARD = b'\x0d\x0a'


def _ws7(body, dots=b''):
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


_NATIVE_P = re.compile(r'<p class="[^"]*ws-native[^"]*">(.*?)</p>', re.S)


def _native_block(html):
    """The text inside the first `<p class="... ws-native">`."""
    m = _NATIVE_P.search(html)
    assert m is not None, 'no ws-native block'
    return m.group(1)


def test_printed_lines_are_separated_by_one_newline():
    doc = _ws7(b'first line' + HARD + b'second line' + HARD + b'third line' + HARD)
    html = emit_html(doc, mode='printed')
    assert '<br>' not in html
    assert _native_block(html).split('\n') == ['first line', 'second line',
                                               'third line']


def test_the_block_is_still_a_pre_block():
    """The newline only IS the break because `white-space:pre` says so --
    if that ever changes the `<br>` has to come back."""
    html = emit_html(_ws7(b'a line' + HARD), mode='printed')
    assert '.ws-native{white-space:pre;overflow-x:auto;' in html


def test_leading_column_spacing_survives():
    """`pre` is also what keeps the typed columns lined up, which is the
    whole point of the facsimile."""
    doc = _ws7(b'    indented' + HARD + b'plain' + HARD)
    assert _native_block(emit_html(doc, mode='printed')) == '    indented\nplain'
