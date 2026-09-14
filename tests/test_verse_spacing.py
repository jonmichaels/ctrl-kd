"""Round 20 item 2 (slate item 4): verse-classified units and wrapped
centered units get tighter internal line spacing in Modern outputs than
the surrounding prose's own (looser) default -- HTML `line-height` on the
unit's own `<p>`, RTF `\\sl`/`\\slmult0` within.

Implemented as ONE named, parameterized constant (VERSE_LINE_HEIGHT,
emit.py) read by both formats, per Jon's own framing: "single-spaced
default BUT parameterize it -- Jon gets shown options later; the
mechanism lands now." Nothing here claims 1.15 is the final value --
these tests pin the MECHANISM (the right units get tighter spacing, the
right units don't, resets happen cleanly), not the exact number.
"""
from ctrlkd import core
from ctrlkd.emit import emit_html, emit_rtf, VERSE_LINE_HEIGHT
from ctrlkd.pdf import modern_tight_line_advance_pt

SOFT = b'\x8d\x0a'
HARD = b'\x0d\x0a'


def _modern(data):
    doc = core.parse_ws(data)
    doc.meta['variant'] = 'ws4'
    return doc


def test_html_verse_unit_gets_tight_line_height():
    poem = b'     line one --' + SOFT + b'     line two --' + HARD
    html = emit_html(core.parse_ws(poem), mode='modern')
    assert f'line-height:{VERSE_LINE_HEIGHT}' in html
    assert '<br>' in html


def test_html_ordinary_prose_is_unaffected():
    data = b'An ordinary sentence that ends with terminal punctuation.\r\n'
    html = emit_html(_modern(data), mode='modern')
    assert 'line-height:' not in html


def test_html_centered_unit_gets_tight_line_height():
    title = 'A Centered Title'
    pad = (65 - len(title)) // 2
    data = (' ' * pad + title).encode() + HARD
    doc = _modern(data)
    html = emit_html(doc, mode='modern')
    assert f'text-align:center;line-height:{VERSE_LINE_HEIGHT}' in html


def test_html_dot_command_centered_paragraph_gets_tight_line_height():
    data = b'.oc on\r\nCentred.\r\n.oc off\r\nOrdinary.\r\n'
    doc = _modern(data)
    html = emit_html(doc, mode='modern')
    assert f'text-align:center;line-height:{VERSE_LINE_HEIGHT}' in html
    # the ordinary paragraph right after must NOT inherit it -- find ITS
    # OWN <p ...> opening tag specifically, not the preceding one's.
    idx = html.find('Ordinary.')
    tag_start = html.rfind('<p', 0, idx)
    assert 'line-height' not in html[tag_start:idx]


def test_rtf_verse_unit_gets_an_exact_sl_carrying_its_own_tightened_leading():
    """R3, Jon's ruling 2026-09-14. The value is NEGATIVE (RTF's EXACT
    form) because the positive/at-least form measurably did nothing --
    LibreOffice laid the reader's own 16.10pt for `\\sl280` and for no
    `\\sl` alike, and only the exact form tightened anything. And it is
    the BLOCK's own figure, the same advance the Modern PDF spends on
    that line, not a document-independent constant."""
    poem = b'     line one --' + SOFT + b'     line two --' + HARD
    doc = core.parse_ws(poem)
    rtf = emit_rtf(doc, mode='modern')
    import re
    m = re.search(r'\\sl(-?\d+)\\slmult0', rtf)
    assert m, rtf
    sl = int(m.group(1))
    assert sl < 0, 'Modern verse spacing must be EXACT (negative), not a minimum'
    first = doc.blocks[0].lines[0].spans
    want = -round(modern_tight_line_advance_pt(first, doc.fonts) * 20)
    assert sl == want, (sl, want)


def test_rtf_resets_sl_to_zero_after_a_verse_unit():
    data = (b'     line one --' + SOFT + b'     line two --' + HARD + HARD +
            b'Ordinary prose paragraph right after the verse.' + HARD)
    rtf = emit_rtf(_modern(data), mode='modern')
    import re
    sl_values = [int(m.group(1)) for m in re.finditer(r'\\sl(-?\d+)\\slmult0 ', rtf)]
    assert sl_values[0] < 0
    assert sl_values[-1] == 0, 'the ordinary paragraph after verse must reset \\sl to 0'


def test_rtf_the_blank_after_a_tightened_block_keeps_the_body_leading():
    """C2. The author's blank line after a tightened block is the
    paragraph break, and it belongs to the body's ordinary leading -- the
    same rule `pdf._modern_streams` follows when it spends its UNtightened
    `last_h` there. So the `\\sl0` reset lands BEFORE the blank `\\par`,
    not after it; with the block's compression still in force the title
    block would close tighter than the identical block closes with no
    tightening at all."""
    data = (b'     line one --' + SOFT + b'     line two --' + HARD + HARD +
            b'Ordinary prose paragraph right after the verse.' + HARD)
    rtf = emit_rtf(_modern(data), mode='modern')
    tight = rtf.index('\\sl-')
    reset = rtf.index('\\sl0\\slmult0', tight)
    blank = rtf.index('\\par \n\\par', tight) if '\\par \n\\par' in rtf[tight:] else rtf.index('\\par', reset)
    assert reset < blank, rtf[tight:tight + 400]


def test_rtf_ordinary_prose_never_gets_sl():
    data = b'An ordinary sentence that ends with terminal punctuation.\r\n'
    rtf = emit_rtf(_modern(data), mode='modern')
    assert r'\sl' not in rtf


def test_printed_rtf_line_spacing_unaffected_by_the_modern_verse_mechanism():
    # round 6's own Printed .lh-derived \sl (_rtf_sl_twips, negative/EXACT)
    # must stay completely independent of the new Modern-only mechanism.
    data = b'.lh 16\r\nSome printed text.\r\n'
    doc = core.parse_ws(data)
    rtf = emit_rtf(doc, mode='printed')
    import re
    m = re.search(r'\\sl(-?\d+)\\slmult0', rtf)
    assert m, rtf
    assert int(m.group(1)) < 0, 'Printed .lh spacing must stay EXACT (negative)'
