"""The reader and detection rules the WordStar run fixtures fixed (planning #549).

Each test builds its bytes here, from what the teardown run showed WordStar
doing, and cites the report section the rule comes from.
"""
from ctrlkd import core, emit

SOFT = b'\x8d\x0a'
HARD = b'\x0d\x0a'


def _ws4_word(w):
    """WS4 sets bit 7 on the last character of each word."""
    return w[:-1] + bytes([w[-1] | 0x80])


def _ws4_text(s):
    return b' '.join(_ws4_word(w.encode()) for w in s.split(' '))


# ------------------------------------------------------------ detection

def test_d1_a_page_mark_is_wordstar_evidence():
    # WS4 report 1.10, 3.14 (run marks3): the editor stores 0D 8A where it
    # paginated. Plain ASCII lines with one mark are a WS4 document.
    data = b''.join(b'line %02d' % n + HARD for n in range(1, 6))
    data += b'line 06\x0d\x8a' + b''.join(b'line %02d' % n + HARD for n in range(7, 12))
    data += b'\x1a' * 8
    assert core.detect(data)['variant'] == 'ws4'
    # the same lines without the mark are a print stream
    plain = data.replace(b'\x0d\x8a', HARD)
    assert core.detect(plain)['variant'] == 'printstream'


def test_d1_a_page_mark_needs_the_density_floor():
    # one chance 0D 8A in a large text file is below the noise floor
    line = b'just a line of plain ASCII text' + HARD
    data = line * 3000 + b'tail\x0d\x8atail' + HARD + line * 3000
    assert core.detect(data)['variant'] != 'ws4'


def test_d2_wrapped_characters_do_not_outvote_ws4_word_ends():
    # WS4 report 3.14 (run laser1): MicroPro's LASER1.DOC holds hundreds of
    # `1B xx 1C` wrapped box characters in WS4 text that sets bit 7 on every
    # word end. The triples alone are WS5+ machinery; with WS4's word ends
    # beside them the file is WS4.
    box = b'\x1b\xcd\x1c' * 60 + HARD
    prose = _ws4_text('the quick brown fox jumps over the lazy dog again and again') + HARD
    assert core.detect(box + prose * 4)['variant'] == 'ws4'
    # without the word ends the same triples stay WS5+
    plain = b'the quick brown fox jumps over the lazy dog again and again' + HARD
    assert core.detect(box + plain * 4)['variant'] == 'ws5+'


def test_d3_an_unclosed_header_shaped_block_is_text_not_binary():
    # WS4 report 3.14 (run ws5hdr): a `1D 7D 00 00 80 00` header with zero
    # fill loads as one line of `^]}^@^@...`. It does not close, so it is not
    # a header; the zeros are WS4's kept 00h, and the text after it decides.
    head = b'\x1d\x7d\x00\x00\x80' + b'\x00' * 123
    data = head + b'Body line one.' + HARD + b'Body line two.' + HARD + b'\x1a' * 20
    assert core.detect(data)['variant'] == 'ws4'
    # a binary tail after the same opening is still refused
    assert core.detect(head + bytes(range(0x80, 0xB0)) * 3)['variant'] == 'binary'


def test_d4_two_soft_returns_in_a_short_headerless_ws7_file_are_ws5():
    # WS7 report 11.7, 14.6 (runs just0, just1): soft returns whose only high
    # bits are their own 8D, no bit-7 word ends: WS5+. Two are enough when the
    # file is short.
    data = (b'The quick brown fox jumps over the lazy dog and keeps running ' + SOFT
            + b'until it reaches the far side of the field where the farmer ' + SOFT
            + b'waits for it with a bucket of cold water and a towel.' + HARD + b'\x1a')
    assert core.detect(data)['variant'] == 'ws5+'
    # the same lines with WS4's word-end flags are WS4
    ws4 = (_ws4_text('The quick brown fox jumps over the lazy dog and keeps running') + b' ' + SOFT
           + _ws4_text('until it reaches the far side of the field where the farmer') + b' ' + SOFT
           + _ws4_text('waits for it with a bucket of cold water and a towel.') + HARD + b'\x1a')
    assert core.detect(ws4)['variant'] == 'ws4'


# --------------------------------------------------------------- reader

def test_e2_enter_under_ls2_keeps_the_soft_return_soft():
    # WS7 report 15.10 (runs w16-ls2, w16-ls3): Enter under `.ls n` stores
    # `8D 0A`, n-2 empty soft lines and an empty hard line. The text line
    # stays soft although the paragraph ends there.
    for filler, ls in ((HARD, b'.ls 2'), (SOFT + HARD, b'.ls 3')):
        data = ls + HARD + b'first line' + SOFT + filler + b'Z' + HARD + b'second line' + HARD
        lines = [ln for b in core.parse(data, variant='ws5+').blocks for ln in b.lines]
        first = next(ln for ln in lines if ln.spans and ln.spans[0].text == 'first line')
        assert first.soft
        z = next(ln for ln in lines if ln.spans and ln.spans[0].text == 'Z')
        assert not z.soft
        # reflow still ends the paragraph there: no join space is left behind
        merged = [''.join(sp.text for sp in ln.spans)
                  for b in core.parse(data, variant='ws5+').blocks
                  for ln in core.merged_lines(b)]
        assert 'first line' in merged


def test_e3_ws4_reads_a_bare_rr_as_a_rejected_ruler():
    # WS4 report, evidence/pass3/exe-static.md P17, P19B: a bare `.RR` has
    # LM = RM and is rejected; the next line is ordinary text. (In WS7 it
    # introduces a ruler image on the next line.)
    data = b'.RR' + HARD + b'     XZ' + HARD + b'\x1a'
    ws4 = core.parse(data, variant='ws4')
    assert ws4.meta['dot_commands'] == ['.RR']
    assert ''.join(sp.text for b in ws4.blocks for ln in b.lines for sp in ln.spans) == '     XZ'
    ws7 = core.parse(data, variant='ws5+')
    assert len(ws7.meta['dot_commands']) == 2


def test_e3_a_bare_rr_restores_the_document_start_ruler_in_ws4():
    data = (b'.RR-----!-----!----R' + HARD + b'one' + HARD + b'.RR' + HARD
            + b'two' + HARD + b'\x1a')
    doc = core.parse(data, variant='ws4')
    assert doc.meta['dot_commands'] == ['.RR-----!-----!----R', '.RR']
    # the ruler's R pip set a right margin; the rejected `.RR` clears it
    rights = [b.right_margin for b in doc.blocks if b.kind == 'para']
    assert rights[0] is not None and rights[-1] is None


def test_e4_a_nondocument_keeps_bit_7():
    # WS7 report 14.2 (run ws4an): a WS4 file opened as a nondocument shows
    # its high-bit bytes as CP437 characters; only the flagged return, line
    # feed and form feed keep their meaning.
    data = (b'Thi\xf3 i\xf3 a\xa0 soft\xa0 wrappe\xe4 line\x8d\x0a'
            b'Extended \x1b\x82\x1c and \x1bA\x1c items.\r\n'
            b'Line before a page mark.\r\x8aLast line.\r\nZ\x1a')
    doc = core.parse(data, variant='text')
    text = [''.join(sp.text for sp in ln.spans) for b in doc.blocks for ln in b.lines]
    assert text[0] == 'Thi≤ i≤ aá softá wrappeΣ line'
    assert text[1] == 'Extended é and A items.'
    assert text[2] == 'Line before a page mark.'
    assert text[3] == 'Last line.'
    assert emit.emit_text(doc, mode='printed').count('é') == 1


def test_e4_a_print_stream_still_masks_stray_high_bits():
    # Only a file opened as a nondocument keeps bit 7. A print-to-disk
    # capture's stray high bits are printer noise, as before.
    data = b'abc\xe4 def\r\n'
    assert core.parse(data, variant='printstream').blocks[0].lines[0].spans[0].text == 'abcd def'
    assert core.parse(data, variant='text').blocks[0].lines[0].spans[0].text == 'abc\u03a3 def'
