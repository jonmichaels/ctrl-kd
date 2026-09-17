r"""E9 H2 (Jon's ruling 2026-09-17, the human-eye export audit section E):
newspaper columns are a SECTION, not a paragraph.

Modern HTML wrapped every paragraph of a `.co n` region in its own
`column-count` box, so each paragraph balanced itself across the columns
and a fresh pair started underneath -- half-empty right-hand columns and a
reading order that looks broken, on a document the RTF emitter gets right
with a single `\cols2` section. Printed HTML dropped the columns entirely:
0 of 511 Printed HTML documents carried any, where the Printed RTF of the
same file composes them properly.

Both modes now open ONE container per columnar section: the wrapper is
written per block (the only place `.co` is in scope) and adjacent identical
wrappers are welded together afterwards. A phone gets one column -- two
columns at 400px is about twenty characters a line, which is a stack of
fragments, not a column.

Synthetic fixtures only.
"""
import re

from ctrlkd import core, emit_html

HARD = b'\x0d\x0a'


def _ws7(body, dots=b''):
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


def _two_column_doc():
    body = (b'first paragraph' + HARD + HARD
            + b'second paragraph' + HARD + HARD
            + b'third paragraph' + HARD)
    return _ws7(body, dots=b'.co 2, 0.25"\r\n')


def _containers(html):
    return re.findall(r'<div class="ws-cols" style="([^"]*)">', html)


def test_modern_opens_one_container_for_the_whole_section():
    html = emit_html(_two_column_doc(), mode='modern')
    assert _containers(html) == ['column-count:2; column-gap:0.25in']
    # and all three paragraphs live inside it
    inside = html.split('<div class="ws-cols"', 1)[1].split('</div>', 1)[0]
    assert inside.count('<p') == 3


def test_printed_keeps_the_columns_it_used_to_drop():
    html = emit_html(_two_column_doc(), mode='printed')
    assert _containers(html) == ['column-count:2; column-gap:0.25in']
    assert 'ws-native' in html          # still the facsimile block inside


def test_a_phone_gets_one_column():
    html = emit_html(_two_column_doc(), mode='modern')
    assert '@media(max-width:600px){div.ws-cols{column-count:1!important}}' in html


def test_a_document_without_columns_pays_no_css_for_them():
    html = emit_html(_ws7(b'plain' + HARD), mode='modern')
    assert 'ws-cols' not in html


def test_columns_off_closes_the_container():
    """`.co 1` is columns OFF; what follows is not part of the section."""
    doc = _ws7(b'in columns' + HARD + HARD + b'.co 1\r\n' + b'after' + HARD,
               dots=b'.co 2\r\n')
    html = emit_html(doc, mode='modern')
    inside = html.split('<div class="ws-cols"', 1)[1].split('</div>', 1)[0]
    assert 'after' not in inside
