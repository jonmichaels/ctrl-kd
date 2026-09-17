r"""E9 R2 (Jon's ruling 2026-09-17, the human-eye export audit section C):
WordStar's colour 15 is REVERSE VIDEO, not a colour, so RTF and HTML give
it a ground.

The exporters kept the colour -- RTF `\cf16`, HTML `.ws-colour-15 {
color:#ffffff }` -- and never produced the black bar WordStar printed it
in, so the line was painted white on a white page and simply was not there.
19 runs in 3 documents (`LJ6DTP.WS` twice and `PSPRINT.TST`, whose own text
reads "White Text on a Black Background"); the Text export still carried
the words, which is how the audit could tell nothing was lost upstream.

`\chcbpat` is RTF's own character shading and `\highlight` is the same fact
in the vocabulary Word reads; `\cf1` is the colour table's Black. Every
other palette index is untouched -- white is the only one that vanishes.

Synthetic fixtures only.
"""
from ctrlkd import core, emit_html, emit_rtf

HARD = b'\x0d\x0a'


def _ws7_block(cmd, content=b''):
    """One WS7 symmetrical sequence: 0x1D, count, type byte, content, the
    matching trailing count, closing 0x1D (count = len(content) + 4)."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _header():
    return _ws7_block(0x00, bytes([0x70]) + bytes(15))


def _colour(index):
    """A type-1 colour record: current colour `index`, previous Black."""
    return _ws7_block(0x01, bytes([index, 0]))


def _doc(index, text):
    return core.parse_ws(_header() + _colour(index) + text + HARD)


def _white_doc():
    return _doc(15, b'White Text on a Black Background')


def _cyan_doc():
    return _doc(3, b'Cyan')


def test_rtf_white_run_gets_a_black_ground():
    rtf = emit_rtf(_white_doc(), mode='printed')
    assert r'\cf16 ' in rtf                      # the white is still white
    assert r'\chcbpat1 \highlight1 ' in rtf      # on the table's Black


def test_rtf_other_colours_get_no_ground():
    rtf = emit_rtf(_cyan_doc(), mode='printed')
    assert r'\cf4 ' in rtf
    assert r'\chcbpat' not in rtf


def test_html_white_run_gets_a_black_ground():
    html = emit_html(_white_doc(), mode='printed')
    assert '.ws-colour-15 { color:#ffffff; background:#000000 }' in html


def test_html_other_colours_get_no_ground():
    html = emit_html(_cyan_doc(), mode='printed')
    assert '.ws-colour-3 { color:#00aaaa }' in html
    assert 'background:#000000' not in html


def test_both_modes_carry_it():
    """A knockout banner is unreadable in either mode; nothing about the
    reverse-video fact is Printed's alone."""
    for mode in ('printed', 'modern'):
        assert r'\chcbpat1 \highlight1 ' in emit_rtf(_white_doc(), mode=mode)
        assert 'background:#000000' in emit_html(_white_doc(), mode=mode)


def test_inline_styling_off_still_strips_it():
    """`--inline-styling off` strips the author's own colour choice; the
    ground rides with it and never outlives it."""
    rtf = emit_rtf(_white_doc(), mode='printed', inline_styling=False)
    assert r'\chcbpat' not in rtf and r'\cf' not in rtf
