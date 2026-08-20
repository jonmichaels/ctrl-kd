"""ctrl-kd tests — all fixtures are SYNTHETIC, built byte-by-byte here.

They encode real WordStar behaviors verified against a 1987-92 corpus during
development (that corpus is personal and is not shipped).
"""
import pytest
import re
from ctrlkd import core, emit, convert

SOFT = b'\x8d\x0a'
HARD = b'\x0d\x0a'

def ws4_word(w):
    """WS4 sets bit 7 on the last character of each word."""
    return w[:-1] + bytes([w[-1] | 0x80])

def ws4_text(s):
    return b' '.join(ws4_word(w.encode()) for w in s.split(' '))

# ---------------------------------------------------------------- detection

def test_detect_ws4():
    data = ws4_text('hello there friendly world this line wraps') + SOFT + \
           ws4_text('and continues here') + HARD + b'\x1a'
    d = core.detect(data)
    assert d['variant'] == 'ws4'

def test_detect_printstream():
    data = b'Line one of printed page\r\nLine two\r\nLine three\r\n\x1a'
    assert core.detect(data)['variant'] == 'printstream'

def test_detect_binary():
    assert core.detect(bytes(range(256)) * 4)['variant'] == 'binary'

# ---------------------------------------------------------------- line engine

def make_prose():
    """Two paragraphs; first wraps twice at a 65 margin (long lines), second short."""
    l1 = ('x' * 55 + ' words').encode()             # 61 chars, wrapped
    l2 = ('y' * 50 + ' continuing').encode()        # 61 chars, wrapped
    l3 = b'ends here.'
    p2 = b'Second paragraph.'
    return l1 + SOFT + l2 + SOFT + l3 + SOFT + HARD + SOFT + p2 + HARD

def test_wrap_joins_prose():
    lines, margin = core.lines_pass(make_prose())
    seps = [s for _, s, _m in lines]
    # 2026-08-03: blank lines are CONTENT now and are emitted with their own
    # terminator kind, after the line they follow. The text lines' own
    # classification is unchanged -- assert that separately from the blanks.
    assert [x for x in seps if not x.startswith('blank-')] == \
        ['wrap', 'wrap', 'para', 'eof']
    assert seps.count('blank-hard') + seps.count('blank-soft') == 2

def test_poem_lines_kept():
    # short lines ending in SOFT returns where the next word would have fit:
    # deliberate breaks (the wrap test), stanza gap = soft+hard run -> para
    poem = (b'     A short poem line,' + SOFT +
            b'     another short line.' + SOFT + HARD + SOFT +
            b'     Second stanza opens,' + SOFT +
            b'     and closes.' + HARD)
    lines, _ = core.lines_pass(poem)
    assert [s for _, s, _m in lines if not s.startswith('blank-')] == \
        ['line', 'para', 'line', 'eof']
    # the stanza gap is SOFT+HARD+SOFT = two real blank lines on paper, and
    # both survive with their own terminator kinds
    assert [s for _, s, _m in lines if s.startswith('blank-')] == \
        ['blank-hard', 'blank-soft']

def test_wrap_boundary_is_strict():
    # word landing EXACTLY at the margin: WS4 still wrapped -> join, not break
    l1 = (' ' * 5 + 'a' * 52).encode()              # len 57
    lines, margin = core.lines_pass(l1 + SOFT + b'mother.' + HARD)
    assert margin == 65
    assert lines[0][1] == 'wrap'                    # 57 + 1 + 7 == 65: not < 65

def test_single_hard_is_line_break():
    data = b'Jon Michaels' + SOFT + b'March 6, 1992' + SOFT + HARD + SOFT + b'Body text.' + HARD
    lines, _ = core.lines_pass(data)
    assert [s for _, s, _m in lines if not s.startswith('blank-')] == \
        ['line', 'para', 'eof']
    assert [s for _, s, _m in lines if s.startswith('blank-')] == \
        ['blank-hard', 'blank-soft']

def test_double_spaced_wrap_collapses():
    # double-spaced files put a blank soft line between every wrapped line
    l1 = ('z' * 58 + ' filler').encode()
    data = l1 + SOFT + SOFT + b'continues on.' + HARD
    lines, _ = core.lines_pass(data)
    assert lines[0][1] == 'wrap'

# ---------------------------------------------------------------- WS parsing

def test_bold_and_paragraphs():
    data = (b'\x02' + ws4_text('Big Title') + b'\x02' + HARD + HARD +
            ws4_text('Plain body text follows the heading here.') + HARD)
    doc = core.parse_ws(data)
    paras = [b for b in doc.blocks if b.kind == 'para']
    assert len(paras) == 2
    assert 'b' in paras[0].lines[0].spans[0].styles
    assert paras[0].lines[0].text().strip() == 'Big Title'
    assert paras[1].lines[0].spans[0].styles == frozenset()

def test_underline_spans_and_hibit_strip():
    data = ws4_text('I read') + b' \x13' + ws4_text('A Book') + b'\x13' + HARD
    doc = core.parse_ws(data)
    spans = doc.blocks[0].lines[0].spans
    assert any('u' in s.styles and s.text.strip() == 'A Book' for s in spans)
    assert 'I read' in doc.blocks[0].lines[0].text()

def test_dot_pa_becomes_pagebreak():
    data = b'Page one text here.' + HARD + b'.pa' + HARD + b'Page two text here.' + HARD
    doc = core.parse_ws(data)
    kinds = [b.kind for b in doc.blocks]
    assert kinds == ['para', 'pagebreak', 'para']

def test_ruler_marks_columnar():
    data = b'.rr----!----!----R' + HARD + b'Col1    Col2' + HARD
    doc = core.parse_ws(data)
    assert doc.meta['columnar'] is True

# ---------------------------------------------------------------- print streams

def test_printstream_superscript_and_ff():
    data = b'treaties with Indians.\x181\x12  More text\r\n\x14page one\r\n\x0cpage two\r\n'
    doc = core.parse_printstream(data)
    txt = emit.emit_text(doc, 'printed')
    assert 'treaties with Indians.1' in txt.replace('\n', ' ')
    spans = doc.blocks[0].lines[0].spans
    assert any(s.text == '1' and 'sup' in s.styles for s in spans)
    assert any(b.kind == 'pagebreak' for b in doc.blocks)
    assert '\x14' not in txt

# ---------------------------------------------------------------- emitters

@pytest.fixture
def prose_doc():
    return core.parse_ws(make_prose())

def test_emit_text(prose_doc):
    t = emit.emit_text(prose_doc)
    assert 'ends here.' in t and '\n\n' in t

def test_emit_markdown_styles():
    data = b'\x02' + ws4_text('Bold') + b'\x02 ' + b'\x19' + ws4_text('ital') + b'\x19' + HARD
    md = emit.emit_markdown(core.parse_ws(data), mode='modern')
    assert '**Bold**' in md and '*ital*' in md

def test_emit_html_poem_breaks():
    # Round 2 (2026-08-17): the paragraph-assembly heuristic now reads
    # verse from a run's SHAPE (terminal punctuation, quote-opening,
    # attribute shift -- see core.looks_like_verse), not merely "short and
    # indented" -- a comma/period-terminated pair like the original
    # 'line one,'/'line two.' reads as two finished, if terse, prose
    # sentences (correctly, per the same signal real short dialogue relies
    # on) and is no longer this test's fixture. Neither line here ends in
    # terminal punctuation, matching the enjambment shape real verse in
    # the corpus was found to have.
    poem = b'     line one --' + SOFT + b'     line two --' + HARD
    h = emit.emit_html(core.parse_ws(poem), mode='modern')
    assert '<br>' in h and '<p' in h

def test_emit_html_printed_native_flow():
    """Round 3 addendum (2026-08-17): Native/printed HTML retired <pre> --
    a boxed, non-wrapping element implies a width opinion this project no
    longer states in HTML at all. Line-for-line structure is now explicit
    <br> in normal flow, with the monospace identity carried by the
    `ws-native` CSS class (white-space:pre-wrap keeps literal column
    spacing intact while still allowing the browser to wrap a long line)."""
    data = b'A    B    C\r\nD    E    F\r\n'
    h = emit.emit_html(core.parse_printstream(data), 'printed')
    assert '<pre' not in h
    assert 'class="ws-native"' in h
    assert 'A    B    C' in h and '<br>' in h

def test_emit_rtf_valid_shape():
    r = emit.emit_rtf(core.parse_ws(make_prose()))
    assert r.startswith(r'{\rtf1') and r.rstrip().endswith('}')
    assert r.count('{') == r.count('}')

def test_convert_api():
    out = convert(make_prose(), to='markdown')
    assert 'Second paragraph.' in out

def test_parse_refuses_binary():
    with pytest.raises(ValueError):
        core.parse(bytes(range(256)) * 4)

# ---------------------------------------------------------------- WS5+/WS7
# synthetic 1D symmetric blocks, structure verified against the Sawyer archive

def ws7_block(cmd, content=b''):
    """One WS7 symmetrical sequence: 0x1D, count, type byte, content, the
    matching trailing count, closing 0x1D. Count = len(content) + 4 (per the
    WordStar 7.0 file format spec, WordStar International, 1992: the count is
    the sequence's own length minus 3, and it's stored so that adding it to
    the address of the opening 0x1D lands on the trailing count)."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'

def ws7_note(cmd, text, number=1, line_count=1, number_format=3, convert_to=0):
    """One footnote/endnote/annotation/comment note block (types 3-6): line
    count, note number (embedded directly -- tag-word high bit clear),
    conversion flag (high nybble = numbering format, low nybble = convert-to
    type), then the note text."""
    conv_flag = ((number_format & 0x0F) << 4) | (convert_to & 0x0F)
    content = (line_count.to_bytes(2, 'little') + number.to_bytes(2, 'little') +
               bytes([conv_flag]) + text)
    return ws7_block(cmd, content)

def ws7_note_with_tag(cmd, text, number, line_count=1, number_format=3, convert_to=0):
    """A note whose number and conversion flag live in a nested internal tag
    sequence (tag-word high bit set) instead of the outer header -- the
    common case for footnotes/endnotes once WordStar has assigned a display
    number. The tag is embedded partway through the text, as real files do,
    to prove nested-sequence stripping doesn't just get lucky on placement."""
    conv_flag = ((number_format & 0x0F) << 4) | (convert_to & 0x0F)
    tag_content = b'\x00\x00' + number.to_bytes(2, 'little') + bytes([conv_flag])
    tag = ws7_block(cmd, tag_content)
    split = len(text) // 2
    outer_text = text[:split] + tag + text[split:]
    content = line_count.to_bytes(2, 'little') + b'\x00\x80' + b'\x00' + outer_text
    return ws7_block(cmd, content)

def test_ws7_footnote_extraction_and_ref():
    # number=0: WordStar's own file format stores a 0-based internal index
    # (confirmed against a real WS7 file), so the FIRST footnote in a
    # document is stored as 0 -- the display number a reader/emitter shows
    # is that index plus WordStar's documented starting value of 1 (see
    # test_footnote_endnote_number_is_1_based_not_stored_index below).
    data = (ws7_block(0x00) + b'Treaties were made.' +
            ws7_note(0x03, b'See the 1868 accords.', number=0) +
            b' More text follows here.' + HARD)
    doc = core.parse_ws(data)
    assert doc.meta['variant'] == 'ws5+'
    assert len(doc.footnotes) == 1
    assert ''.join(s.text for s in doc.footnotes[0]) == 'See the 1868 accords.'
    spans = doc.blocks[0].lines[0].spans
    ref = [s for s in spans if 'fnref' in s.styles]
    assert ref and ref[0].text == '1' and 'sup' in ref[0].styles
    md = emit.emit_markdown(doc, mode='modern')
    assert '[^1]' in md and '[^1]: See the 1868 accords.' in md


def test_footnote_marker_stays_inline_before_a_blank_paragraph_line():
    """b26 fix, byte-verified against LYING.WS (jon_vault's pd-samples):
    a footnote's own bytes contribute NOTHING to the cleaned stream
    (_symmetric_blocks), so its 'fnref' mark's offset is always wherever
    `out` already was when the block was stripped -- the ANCHOR text's own
    end. When that anchor sits at the end of a line immediately followed
    by a blank paragraph line (a real, common pattern: sentence, footnote,
    paragraph break), that offset is ALSO the start of the next (zero-
    length) line -- the general mark-placement rule in `lines_pass`
    ("a mark landing on a boundary belongs to the line that follows")
    then put the marker on that blank line, alone, at the left margin
    (byte-verified: block 3 held nothing but the fnref span, LYING.WS's
    real Prize./footnote pair). Real WS7 (LYING.pcl +
    LYING.measurements.json) prints the superscript inline: 'Prize.' at
    (2786, 1461) decipoints, the footnote's '1' at (3079, 1416) -- SAME
    row (a 4.5pt rise, not a new line), immediately to its right."""
    data = (ws7_block(0x00) + b'Anchor text ends here.' +
            ws7_note(0x03, b'Note body text.', number=0) + HARD + HARD +
            b'Next paragraph starts fresh.' + HARD)
    doc = core.parse_ws(data)
    # the marker rides on the SAME line as its anchor text, not a block of
    # its own -- exactly one block still separates it from the next
    # paragraph (the blank spacer line survives, unlike the marker).
    anchor_line = doc.blocks[0].lines[0]
    assert 'Anchor text ends here.' in anchor_line.text()
    ref = [s for s in anchor_line.spans if 'fnref' in s.styles]
    assert ref and ref[0].text == '1' and 'sup' in ref[0].styles
    assert not any(
        all('fnref' in s.styles for s in ln.spans) and ln.spans
        for b in doc.blocks for ln in b.lines
    ), 'the marker must never be the SOLE content of its own line'

    from ctrlkd.pdf import emit_pdf
    pdf = emit_pdf(doc, mode='printed')
    spans = _content_spans(pdf)
    anchor = next(s for s in spans if s[5] == b'Anchor text ends here.')
    marker = next(s for s in spans if s[5] == b'1')
    assert marker[4] == anchor[4]              # same y -- same physical line
    assert marker[3] > anchor[3]                # to the right of its anchor


def test_ws7_heading_and_softpage():
    # Heading level comes from the NAME the style handle resolves to in the
    # document's own library -- never from the slot number (the old mapping
    # promoted NOVEL.WS's footer style to a heading while its real H1/H2/H3
    # went unmapped). Slot 2 here resolves to 'H2'.
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        ('H2', True, _style_record()),
    ])
    style = ws7_block(0x11, (0x0202).to_bytes(2, 'little') + (0x0201).to_bytes(2, 'little')
                      + (0x0300).to_bytes(2, 'little') + (0x0201).to_bytes(2, 'little'))
    body = (ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4)) + style +
            b'Chapter One' + HARD + HARD +
            b'Body text of the chapter.' + HARD + ws7_block(0x0B) + b'Next page text.' + HARD)
    base = ((len(body) + 127) // 128) * 128
    data = bytearray(body.ljust(base, b'\x1a')) + lib
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    doc = core.parse_ws(bytes(data))
    heads = [b for b in doc.blocks if b.heading]
    assert heads and heads[0].heading == 2
    assert heads[0].style_name == 'H2' and heads[0].style_id == 2
    assert heads[0].lines[0].text().strip() == 'Chapter One'
    assert any(ln.softpage for b in doc.blocks for ln in b.lines)
    md = emit.emit_markdown(doc, mode='modern')
    # H2's own style record declares bold (rec[91:93], _style_record's own
    # default) -- round 5 (2026-08-17): a style's declared attrs render in
    # every format, headings included, so the heading text is correctly
    # bold-wrapped now, not just the bare '#'-implied emphasis a browser's
    # own default heading styling would have given it for free.
    assert '## **Chapter One**' in md
    h = emit.emit_html(doc, mode='modern')
    assert re.search(r'<h2[^>]*>Chapter One</h2>', h)

def _style_record(left=1800, tabs=(900, 1800), n_dec=0, just=0, inherit_tabs=False):
    # 102-byte style record per WSFORMAT's field list (validated corpus-wide
    # 2026-08-04: 59/59 records). Inheritance sentinels: margins -2, most
    # others -1 -- and tab COUNTS are 0xFF when inherited (the spec's prose
    # says 0; the corpus says 0xFF, 56/118 fields), with the 32-word tab
    # array then holding STALE bytes that must not be read.
    rec = bytearray(102)
    rec[0:2] = (0xFFFF).to_bytes(2, 'little')            # font: inherited
    rec[10:12] = left.to_bytes(2, 'little')              # left margin HMI
    rec[12:14] = (0xFFFE).to_bytes(2, 'little')          # right: inherited
    rec[14:16] = (0xFFFE).to_bytes(2, 'little')          # para: inherited
    if inherit_tabs:
        rec[18] = rec[19] = 0xFF
        for k in range(32):                               # stale junk on purpose
            rec[20 + 2*k:22 + 2*k] = (0xBEEF).to_bytes(2, 'little')
    else:
        rec[18], rec[19] = len(tabs) - n_dec, n_dec
        for k, t in enumerate(tabs):
            rec[20 + 2*k:22 + 2*k] = t.to_bytes(2, 'little')
    rec[86] = just % 256
    rec[87] = 1                                           # wrap on
    rec[88:90] = (0xFFFF).to_bytes(2, 'little')           # line height: inherit
    rec[90] = 0xFF                                        # spacing: inherit
    rec[91:93] = (0b1000000).to_bytes(2, 'little')        # attrs on: bold
    rec[95] = 0xFF                                        # colour: inherit
    return bytes(rec)

def _style_library(entries):
    # master index header (13 bytes) + one object-index block, stride-33 items
    n = len(entries)
    items = b''
    records = b''
    rec_base = 13 + 5 + 33 * n
    for name, has_rec, rec in entries:
        if name is None:
            items += b'\x3f' * 24 + bytes(9)              # unused/deleted slot
            continue
        nm = name.encode('cp437').ljust(24)
        if has_rec:
            ptr = rec_base + len(records)
            items += nm + b'\x02' + bytes(4) + ptr.to_bytes(4, 'little')
            records += rec
        else:
            items += nm + b'\x00' + bytes(4) + bytes(4)
    head = (b'\x1a\x55' + (1).to_bytes(2, 'little') + b'\x01'
            + n.to_bytes(2, 'little') + (102).to_bytes(2, 'little')
            + (13).to_bytes(4, 'little'))
    block = bytes([n]) + bytes(4) + items
    return head + block + records

def test_style_library_parses_with_33_byte_stride():
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        (None, False, None),                              # deleted slot: skipped
        ('MS Body Copy', True, _style_record(just=0)),
        ('Old Tabs', True, _style_record(inherit_tabs=True)),
    ])
    body = ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4)) + \
        b'Some body text follows.' + HARD
    base = ((len(body) + 127) // 128) * 128               # 128-byte boundary
    data = bytearray(body.ljust(base, b'\x1a')) + lib
    # patch the header pointer (content offsets 12-15 inside the 0x00 block)
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    doc = core.parse_ws(bytes(data))
    names = [s['name'] for s in doc.styles]
    assert names == ['WordStar Defaults', 'WordStar Defaults',
                     'MS Body Copy', 'Old Tabs']
    body_style = doc.styles[2]
    assert body_style['left_margin_hmi'] == 1800
    assert body_style['right_margin_hmi'] is None         # -2 sentinel
    assert body_style['tabs_hmi'] == [900, 1800]
    assert body_style['justification'] == 'left'
    assert body_style['attrs_on'] == 0b1000000
    assert body_style['line_spacing'] is None
    # tab counts 0xFF mean INHERITED and the array is stale -- never read it
    assert doc.styles[3]['tabs_hmi'] is None

def test_style_library_pointer_at_eof_means_no_library():
    # 56 of 85 corpus documents: pointer == file length, WordStar's "next
    # available offset" default when no style was ever defined. Not an error.
    body = ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4)) + b'Text.' + HARD
    data = bytearray(body)
    data[4 + 12:4 + 16] = len(body).to_bytes(4, 'little')
    doc = core.parse_ws(bytes(data))
    assert doc.styles == []

def test_p_hash_cc_tb_are_recorded_not_lost():
    # All three have ZERO users in the archive, so they are RECORDED
    # deliberately rather than modelled: .p# format alphabet documented in
    # Sawyer's PARAGRAP.NUM ('1' numerals, 'Z'/'z' letters, 'I' roman);
    # .cc is .cp's column partner (we don't simulate column filling);
    # .tb sets ASCII-tab stops (spec default is modulus 8, unchanged).
    data = (b'.p# Z.1\r\n.cc 5\r\n.tb 8 16 2.5"\r\n'
            b'Ordinary body text follows the dot commands here.\r\n')
    doc = core.parse_ws(data)
    f = doc.meta['formatting']
    assert f['paranum_format'] == 'Z.1'
    assert f['cond_col'] == ['5']
    assert f['tab_stops'][0:2] == [8, 16] and f['tab_stops'][2] == 25
    assert 'Ordinary body text' in emit.emit_text(doc, mode='modern')

def _style_handle(slot):
    return ws7_block(0x11, (0x0200 | slot).to_bytes(2, 'little')
                     + (0x0201).to_bytes(2, 'little')
                     + (0x0300).to_bytes(2, 'little')
                     + (0x0201).to_bytes(2, 'little'))

def test_style_record_formatting_applies_and_persists():
    # A 0x11 selection applies its record's formatting from that paragraph ON,
    # until the next selection (real documents switch back explicitly --
    # NOVEL.WS re-selects 'MS Body Copy' after every heading). Inherited
    # fields fall back to the running dot-command state; selecting the
    # recordless base entry resets everything.
    rec = _style_record(left=900, just=(-2) % 256)         # centered, lm 5 cols
    rec = rec[:91] + (0x40).to_bytes(2, 'little') + rec[93:]   # attrs_on: bold
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        ('Callout', True, rec),
    ])
    body = (ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4)) +
            b'Plain opening paragraph.' + HARD +
            _style_handle(2) + b'Styled paragraph one.' + HARD +
            b'Still styled, no new selection.' + HARD +
            _style_handle(1) + b'Back to defaults.' + HARD)
    base = ((len(body) + 127) // 128) * 128
    data = bytearray(body.ljust(base, b'\x1a')) + lib
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    doc = core.parse_ws(bytes(data))
    texts = [b.lines[0].text() for b in doc.blocks]
    # consecutive hard-return lines share a block, so the two styled lines
    # arrive as ONE two-line block -- persistence shows in its second line
    assert texts == ['Plain opening paragraph.', 'Styled paragraph one.',
                     'Back to defaults.']
    plain, styled, reset = doc.blocks
    assert [ln.text() for ln in styled.lines] == [
        'Styled paragraph one.', 'Still styled, no new selection.']
    assert plain.align == 'left' and plain.style_attrs == frozenset()
    assert styled.style_name == 'Callout'
    assert styled.align == 'center'
    assert styled.left_margin == 5                   # 900 HMI / 180
    assert styled.right_margin is None               # -2 sentinel: inherited
    assert styled.style_attrs == frozenset({'b'})
    assert reset.style_name == 'WordStar Defaults'   # recordless base entry
    assert reset.align == 'left' and reset.style_attrs == frozenset()
    # the PDF path merges style attrs into every span, like heading bold
    from ctrlkd.pdf import _doc_to_pagelines
    segs = [seg for pg in _doc_to_pagelines(doc, False) for ln in pg for seg in ln]
    assert any(t == 'Styled' and 'b' in st for t, st in segs)
    assert any(t == 'Plain' and 'b' not in st for t, st in segs)

def test_style_pass_through_html_css_and_rtf_stylesheet():
    # Jon's ruling 2026-08-04: styles are a PASS-THROUGH -- no hardwiring a
    # name to a font; expose the record's own data as CSS/RTF so a consumer
    # can attach font/size. Properties below all come from the fixture's
    # 102-byte record, none from the name.
    rec = _style_record(left=1800, just=(-2) % 256)
    rec = rec[:91] + (0x40).to_bytes(2, 'little') + rec[93:]      # bold
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        ('Callout', True, rec),
    ])
    body = (ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4)) +
            b'Plain opening paragraph with plenty of ordinary prose.' + HARD +
            _style_handle(2) + b'Styled paragraph in the Callout style.' + HARD +
            _style_handle(1) + b'Back to defaults for the closing prose.' + HARD)
    base = ((len(body) + 127) // 128) * 128
    data = bytearray(body.ljust(base, b'\x1a')) + lib
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    doc = core.parse_ws(bytes(data))
    # PRINTED keeps the WS4-absolute margin verbatim -- Printed's whole
    # point is the file's own page geometry (round 3 ruling, 2026-08-17:
    # "it remains Printed/Native's domain").
    hp = emit.emit_html(doc, mode='printed')
    assert '.ws-2-callout { ' in hp
    assert 'text-align:center' in hp and 'margin-left:1.00in' in hp
    assert 'font-weight:bold' in hp
    rp = emit.emit_rtf(doc, mode='printed')
    assert r'{\stylesheet{\s0 Normal;}{\s3\qc\li1440\b Callout;}' in rp
    # MODERN drops the WS-absolute margin entirely (not a quote style, so
    # no substitute inset either -- full measure) but keeps every OTHER
    # property: alignment, weight, and the style's own CSS class/RTF \sN
    # tag are all still a pass-through, just not page geometry.
    h = emit.emit_html(doc, mode='modern')
    assert '.ws-2-callout { ' in h                    # generated CSS rule
    assert 'text-align:center' in h and 'margin-left' not in h
    assert 'font-weight:bold' in h
    assert 'class="ws-2-callout"' in h.split('<body>')[1]
    assert emit.emit_html(doc, mode='modern', styles=False).count('ws-2-callout') == 0
    r = emit.emit_rtf(doc, mode='modern')
    assert r'{\stylesheet{\s0 Normal;}{\s3\qc\b Callout;}' in r  # no \li/\ri
    assert r'\s3 ' in r.split(r'\stylesheet')[1]

def test_style_font_field_changes_the_active_font():
    # A style record's font field is the SAME (width, height, typestyle)
    # triple as an inline type-2 Font block, and selecting the style changes
    # the active font. Left unapplied, the last inline block bled across
    # every style-governed paragraph: LJ6DTP's proportional body copy
    # rendered at Courier's 7.2pt fixed pitch, pushing its 93-character
    # soft-wrapped lines 10 inches wide (Jon's page-width finding,
    # 2026-08-05).
    rec = _style_record()
    rec = ((155).to_bytes(2, 'little') + (240).to_bytes(2, 'little')
           + (49710).to_bytes(2, 'little') + rec[6:])    # 12pt Univers
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        ('Univers copy font', True, rec),
    ])
    courier = ws7_block(0x02, (180).to_bytes(2, 'little')
                        + (240).to_bytes(2, 'little')
                        + (17411).to_bytes(2, 'little') + bytes(6))
    body = (ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4)) +
            courier + b'Fixed pitch opening paragraph of prose.' + HARD +
            _style_handle(2) + b'Styled proportional paragraph.' + HARD)
    base = ((len(body) + 127) // 128) * 128
    data = bytearray(body.ljust(base, b'\x1a')) + lib
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    doc = core.parse_ws(bytes(data))
    # the style's font joined doc.fonts, decoded like any inline block
    assert any(f['width_1800'] == 155 and f['typestyle_name'] and
               f['typestyle_name'].startswith('Univers') for f in doc.fonts)
    spans = [sp for b in doc.blocks for ln in b.lines for sp in ln.spans]
    def _font_of(sp):
        idx = next((int(t[4:]) for t in sp.styles
                    if t.startswith('font') and t[4:].isdigit()), None)
        return None if idx is None else doc.fonts[idx]
    opening = next(sp for sp in spans if sp.text.startswith('Fixed'))
    styled = next(sp for sp in spans if sp.text.startswith('Styled'))
    assert _font_of(opening)['typestyle_name'] == 'Courier'
    assert _font_of(styled)['width_1800'] == 155
    assert _font_of(styled)['proportional'] is True

def test_print_control_display_string_is_screen_only_in_printed_pdf():
    # 0x0F user print control: the display string is what WordStar SHOWS on
    # screen; on paper it sends the raw printer payload and advances by the
    # block's own HMI word (0 for LJ6DTP's rule-drawing controls). Reading
    # modes keep the string -- it is the only human-visible trace of what
    # the control does -- but the printed facsimile drops it, exactly as the
    # printout did.
    note = b'EMPTY 3-dot rule'
    ctl = ws7_block(0x0F, (0).to_bytes(2, 'little') + bytes([len(note)])
                    + note + b'\x1b*c2370a0003b0P')
    body = (ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4)) +
            b'Heading before the control' + ctl + HARD +
            b'Plain paragraph of ordinary prose padding for detection.' + HARD)
    doc = core.parse_ws(body)
    # Round 3 (2026-08-06): display strings are SCREEN-ONLY everywhere --
    # Modern shows nothing (command codes are invisible; M4 extended)
    assert 'EMPTY 3-dot rule' not in emit.emit_text(doc, mode='modern')
    assert 'EMPTY 3-dot rule' not in emit.emit_rtf(doc, mode='modern')
    from ctrlkd.pdf import emit_pdf
    pdf = emit_pdf(doc, 'printed')
    assert b'EMPTY 3-dot rule' not in pdf
    assert b'Heading before the control' in pdf

def test_proportional_font_keeps_its_own_hmi_grid_via_tz():
    # Every font run is width-matched onto ITS OWN font block's HMI grid
    # with Tz -- proportional faces included. PS.TST's faces declare
    # distinct per-character HMIs (Helv Narrow 4.80pt, Univ. Roman
    # 10.08pt): the grid is what preserves each face's true measure and
    # keeps text registered with tabs, rules and vector graphics (Jon's
    # review, 2026-08-05, after a natural-width detour flattened them all
    # to the substitute's uniform average).
    univers = ws7_block(0x02, (155).to_bytes(2, 'little')
                        + (240).to_bytes(2, 'little')
                        + (49710).to_bytes(2, 'little') + bytes(6))
    body = (ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4)) +
            univers + b'iiii mmmm a proportional line of prose.' + HARD)
    from ctrlkd.pdf import emit_pdf
    pdf = emit_pdf(core.parse_ws(body), 'printed')
    assert b' Tz ' in pdf                       # scaled onto the 6.2pt grid
    # words are placed one op each (word-anchored grid layout), so the text
    # appears word by word, never as a phrase
    assert b'(proportional)' in pdf and b'(prose.)' in pdf

def test_detect_honours_the_header_blocks_declaration():
    # A WS5+ file DECLARES itself: a valid type-0 header block at offset 0.
    # Detection must believe it before running byte statistics -- and before
    # the 0x1A truncation, because the header's own content can contain 0x1A:
    # a real 6.6 KB document was judged on its first 17 bytes ("58% text but
    # no structure") and refused, styles, prose and all.
    content = bytes([0x70]) + b'LASERJET\x00' + bytes([0x00, 0x1A]) + bytes(4)
    data = ws7_block(0x00, content) + b'\x00' * 40   # nothing text-like after
    det = core.detect(data)
    assert det['variant'] == 'ws5+'
    assert 'declared release 7.0' in det['reason']
    # a random 0x1D start with broken framing must NOT impersonate a header
    det2 = core.detect(b'\x1d\x10\x00\x00' + b'\x00' * 40)
    assert det2['variant'] == 'binary'

def test_detect_counts_wrapped_extended_chars_as_ws5_machinery():
    # A document whose body is <1B x 1C>-wrapped box-drawing (BOX.WS) read as
    # "63% text but no structure": each triple is three bytes of WS5+
    # machinery around ONE character. Triples are structure.
    row = b'\x1b\xda\x1c' + b'\x1b\xc4\x1c' * 8 + b'\x1b\xbf\x1c'
    data = b'.aw off\r\n' + row + b'\r\n' + row + b'\r\n'
    det = core.detect(data)
    assert det['variant'] == 'ws5+'
    assert det['wrapped_extended'] >= 3
    txt = emit.emit_text(core.parse_ws(data), mode='printed')
    assert '─' in txt and '┌' in txt

def test_flagged_control_bytes_are_controls_not_cp437_glyphs():
    # MEASURED on WordStar 7 (2026-08-04): a real document's bare 0x8A
    # (flagged ^J) performed a line advance in the printed PCL -- zero
    # glyphs -- and an injected 0x94 (flagged ^T) toggled superscript with
    # a visible font-size/baseline change. Real extended characters travel
    # as <1B xx 1C> triples. Decoding these bytes as cp437 invented an
    # e-grave at 14 page boundaries of one document.
    data = (ws7_block(0x00) +
            b'the dirt underfoot\x8d\x8aash gray.\r\n' +      # WS7's soft pair
            b'wa\x94s\x94 raised text here.\r\n')             # flagged ^T pair
    doc = core.parse_ws(data)
    txt = emit.emit_text(doc, mode='printed')
    assert 'è' not in txt and 'ö' not in txt
    assert 'underfoot' in txt and 'ash gray.' in txt
    spans = [s for b in doc.blocks for ln in b.lines for s in ln.spans]
    sup = [s.text for s in spans if 'sup' in s.styles]
    assert sup == ['s']                                        # ^T...^T span
    # (wrap-vs-line classification of the soft pair is the margin
    # heuristic's call, same as any 0x8D return -- not asserted here)

def test_pl_zero_turns_page_breaks_off():
    # MicroPro bug 12284 (engineering note 649): '.pl0' at the start of PRVIEW
    # output exists so "displayed page breaks are thus avoided" -- .pl 0 means
    # NO page breaks in 7.0 document mode. The old page model computed a
    # 0-height page, floored to a 4-line cap: maximal breakage, the exact
    # opposite. 60 lines must now stay on one printed page.
    body = b''.join(b'Line %d of the continuous document.\r\n' % i for i in range(60))
    doc = core.parse_ws(b'.pl 0\r\n' + body)
    from ctrlkd.pdf import _doc_to_pagelines
    assert len(_doc_to_pagelines(doc, True)) == 1

def test_softpage_never_breaks_a_page():
    # WSFORMAT.TXT on 0Bh End of page: "This sequence should usually be
    # ignored. It's used by the WordStar editor to keep track of page breaks.
    # It is TRANSIENT, and moves around with the page break."
    #
    # MEASURED on WordStar 7 (2026-08-04): the same document printed with and
    # without 0x0B marks produced BYTE-IDENTICAL output. The marks carry two
    # words (VMIs on page, line # on page) and the print pipeline never reads
    # them. Honouring them as breaks changed the page count of 43 archive
    # documents. The block is still PARSED (real structure a viewer may want);
    # no renderer may act on it.
    prose = (b'First paragraph of perfectly plain prose.' + HARD +
             b'Second paragraph, still plain.' + HARD +
             b'Third paragraph closes the document.' + HARD)
    mark = ws7_block(0x0B, (24).to_bytes(2, 'little') + (3).to_bytes(2, 'little'))
    base = ws7_block(0x00) + prose
    marked = (ws7_block(0x00) +
              b'First paragraph of perfectly plain prose.' + HARD + mark +
              b'Second paragraph, still plain.' + HARD + mark +
              b'Third paragraph closes the document.' + HARD)
    d_base, d_marked = core.parse_ws(base), core.parse_ws(marked)
    assert sum(ln.softpage for b in d_marked.blocks for ln in b.lines) == 2
    # and the mark must not sever the flow into extra blocks
    assert [b.kind for b in d_marked.blocks] == [b.kind for b in d_base.blocks]
    from ctrlkd.pdf import _doc_to_pagelines
    for mode in ('printed', 'modern'):
        assert emit.emit_text(d_base, mode=mode) == emit.emit_text(d_marked, mode=mode)
        assert emit.emit_html(d_base, mode=mode) == emit.emit_html(d_marked, mode=mode)
        assert emit.emit_rtf(d_base, mode=mode) == emit.emit_rtf(d_marked, mode=mode)
    for printed in (True, False):
        assert (len(_doc_to_pagelines(d_base, printed))
                == len(_doc_to_pagelines(d_marked, printed)))

def test_ws7_tab_block():
    data = ws7_block(0x00) + ws7_block(0x09) + b'Indented by tab block.' + HARD
    doc = core.parse_ws(data)
    assert doc.blocks[0].lines[0].text().startswith('    ')

def test_ws7_note_text_is_not_the_conversion_flag_byte():
    # regression for the original bug: _note_text() split on 0x1D and took
    # inner[1], which for a header-less note (no nested tag) returned the
    # conversion-flag BYTE decoded as text, not the note itself.
    data = ws7_note(0x03, b'Real footnote text.')
    doc = core.parse_ws(data)
    assert len(doc.notes) == 1
    assert doc.notes[0].text == 'Real footnote text.'
    assert doc.notes[0].text not in ('3', '4', '\x33', '\x34')

def test_ws7_four_note_kinds_distinguished():
    # all four note types (footnote/endnote/annotation/comment) in one file:
    # each must be modeled as its own kind, not flattened together, and
    # comments must never surface in the inline-referenced footnote view.
    data = (ws7_block(0x00) +
            ws7_note(0x03, b'Footnote One.', number=1) +
            b'body one ' +
            ws7_note(0x04, b'Endnote one.', number=1) +
            b'body two ' +
            ws7_note(0x05, b'An annotation.', number=0) +
            b'body three ' +
            ws7_note(0x06, b'A hidden author aside.', number=0) +
            b'body four' + HARD)
    doc = core.parse_ws(data)
    kinds = [n.kind for n in doc.notes]
    assert kinds == ['footnote', 'endnote', 'annotation', 'comment']
    assert [n.text for n in doc.notes] == [
        'Footnote One.', 'Endnote one.', 'An annotation.', 'A hidden author aside.']
    # footnotes/endnotes/annotations render inline like footnotes (3 refs);
    # comments never do
    assert len(doc.footnotes) == 3
    assert len(doc.endnotes) == 1 and doc.endnotes[0][0].text == 'Endnote one.'
    assert len(doc.annotations) == 1 and doc.annotations[0][0].text == 'An annotation.'
    assert len(doc.comments) == 1 and doc.comments[0].text == 'A hidden author aside.'
    refs = [s for s in doc.blocks[0].lines[0].spans if 'fnref' in s.styles]
    # comments emit reference marks too since 2026-08-06 -- position, not
    # ink; every rendering path still hides them unless --comments opts in
    assert [r.text for r in refs] == ['1', '2', '3', '4']
    # the comment's text must not leak into rendered output at all
    md = emit.emit_markdown(doc)
    assert 'hidden author aside' not in md

def test_ws7_note_metadata_captured():
    # line count, resolved number, and the conversion flag's two nybbles
    # (format/convert-to) must survive -- previously discarded entirely.
    data = ws7_note(0x04, b'Two-line endnote text.', number=7, line_count=2,
                    number_format=1, convert_to=0)
    doc = core.parse_ws(data)
    note = doc.notes[0]
    assert note.kind == 'endnote'
    assert note.line_count == 2
    assert note.number == 7
    assert note.number_format == 1          # upper-case lettering
    assert note.convert_to == 0             # not converted
    assert note.offset == 0                 # source byte offset of the opening 0x1D

def test_ws7_note_nested_tag_resolves_number_and_strips_bytes():
    # the note text may hold ONE nested symmetrical sequence -- the internal
    # tag carrying the real number/conv-flag once WordStar assigns one. It
    # must be stripped from the visible text and its number/flag must win.
    data = ws7_note_with_tag(0x03, b'Split across the tag boundary.',
                             number=42, number_format=2, convert_to=0)
    doc = core.parse_ws(data)
    note = doc.notes[0]
    assert note.text == 'Split across the tag boundary.'
    assert note.number == 42
    assert note.number_format == 2
    assert '\x1d' not in note.text

def ws7_annotation_with_tag(dot_lines, text, tag_text, junk_conv_flag=0x05):
    """An annotation shaped like a real WS7 one: its OWN text embeds one or
    more dot-command lines (a ruler, a '..' comment -- WordStar notes can
    carry these same as the body can), followed by a nested tag sequence
    whose remaining bytes are a display TEXT string (not a number -- that's
    footnote/endnote-only), followed by the real annotation text. The
    conversion-flag byte is documented "not used" for annotations, so it's
    deliberately junk here to prove it's ignored rather than misreported."""
    tag_content = b'\x00\x00\x00\x00' + bytes([junk_conv_flag]) + tag_text
    tag = ws7_block(0x05, tag_content)
    body = b'\r\n'.join(dot_lines) + b'\r\n' + tag + b' ' + text + b'\r\n'
    content = b'\x01\x00' + b'\x00\x80' + bytes([junk_conv_flag]) + body
    return ws7_block(0x05, content)

def test_ws7_annotation_own_dot_commands_stripped_and_tag_captured():
    # reproduces the real NOTES.TST annotation shape: the note's own text
    # embeds a dot-command line that must not leak into rendered text (but
    # must be preserved verbatim), and its nested tag holds a TEXT string,
    # not a number -- annotations don't have a numeric identity.
    data = ws7_annotation_with_tag(
        dot_lines=[b'.. a descriptive remark', b'.rrL----!----R'],
        text=b'Annotation One', tag_text=b'AC1')
    doc = core.parse_ws(data)
    note = doc.notes[0]
    assert note.kind == 'annotation'
    assert note.text == 'Annotation One'
    assert note.tag == 'AC1'
    assert note.number is None
    assert note.dot_commands == ['.. a descriptive remark', '.rrL----!----R']
    assert '.rr' not in note.text and '..' not in note.text
    # the conversion flag is documented unused for annotations: don't report
    # noise from it even though the byte in this fixture is non-zero
    assert note.number_format == 0 and note.convert_to == 0

def test_ws7_note_own_dot_command_stripped_generally():
    # NOT special-cased to .rr: any dot-command line inside ANY note kind's
    # text must be stripped from the rendered text and preserved verbatim.
    text = b'.. an internal editorial remark\r\nThe real footnote text.'
    data = ws7_note(0x03, text, number=1)
    doc = core.parse_ws(data)
    note = doc.notes[0]
    assert note.text == 'The real footnote text.'
    assert note.dot_commands == ['.. an internal editorial remark']

def test_ws7_unknown_symmetric_type_preserved():
    # an unrecognised symmetrical-sequence type must be kept as an opaque
    # blob with its source offset, not silently dropped.
    data = b'lead in ' + ws7_block(0x63, b'mystery payload') + b' trailing text' + HARD
    doc = core.parse_ws(data)
    assert len(doc.unknown_blocks) == 1
    blob = doc.unknown_blocks[0]
    assert blob.cmd == 0x63
    assert blob.offset == len(b'lead in ')
    assert b'mystery payload' in blob.data
    # it must not leak into the visible text either
    text = doc.blocks[0].lines[0].text()
    assert 'mystery payload' not in text
    assert 'lead in' in text and 'trailing text' in text

def test_tiny_file_not_misdetected_as_ws4():
    # regression: len(core)//20 == 0 made 'hi >= 0' always true for tiny files
    assert core.detect(b'ab cd ef\r\n\x1a')['variant'] != 'ws4'

# ---------------------------------------------------------------- extension API

def test_custom_emitter_registration():
    from ctrlkd import emitter, convert, formats
    @emitter('shout', ext='.loud', aliases=('yell',))
    def emit_shout(doc, mode='modern', **options):
        return ' '.join(l.text() for b in doc.blocks for l in b.lines).upper()
    assert 'shout' in formats() and 'yell' in formats()
    out = convert(b'quiet words here.\r\n', to='yell')
    assert 'QUIET WORDS HERE.' in out

def test_emitters_accept_unknown_options():
    from ctrlkd import convert
    for fmt in ('text', 'markdown', 'html', 'rtf'):
        convert(b'some words here.\r\n', to=fmt, title='x', frob=1)

def test_ws4_highbit_control_toggle():
    # WS4 sets bit 7 on the last char of a word EVEN when it's a style toggle:
    # 0x94 == ^T|0x80 must close the superscript, not leak into the text
    data = (ws4_text('Treaties were made.') + b'\x141\x94  ' +
            ws4_text('Officially the era ended there.') + HARD)
    doc = core.parse_ws(data)
    assert doc.meta['variant'] == 'ws4'
    spans = doc.blocks[0].lines[0].spans
    sup = [s for s in spans if 'sup' in s.styles]
    assert sup and ''.join(s.text for s in sup) == '1'
    tail = spans[-1]
    assert 'sup' not in tail.styles and '\x14' not in tail.text

def test_highbit_binary_not_ws4():
    # binary with high-bit density but low text% (e.g. game data) is not WordStar
    data = (b'+,(\x14 /0\x02' + bytes([0x88, 0x99, 0xAA, 0x07, 0x01]) * 40 +
            b'some ascii' + b'\x00' * 150)
    assert core.detect(data)['variant'] == 'binary'

# ---------------------------------------------------------------- pdf

def test_pdf_structure():
    from ctrlkd.pdf import emit_pdf
    pdf = emit_pdf(core.parse_ws(make_prose()))
    assert isinstance(pdf, bytes) and pdf.startswith(b'%PDF-1.4')
    assert pdf.rstrip().endswith(b'%%EOF')
    assert pdf.count(b'/Type /Page ') == 1 and b'/Courier' in pdf
    assert b'(Second paragraph.)' in pdf

def test_pdf_pagebreak_makes_pages():
    from ctrlkd.pdf import emit_pdf
    data = b'Page one text here.' + HARD + b'.pa' + HARD + b'Page two text here.' + HARD
    pdf = emit_pdf(core.parse_ws(data))
    assert pdf.count(b'/Type /Page ') == 2

def test_pdf_styles_and_escaping():
    from ctrlkd.pdf import emit_pdf
    data = b'\x02' + ws4_text('Bold (word)') + b'\x02 ' + b'\x13' + ws4_text('under') + b'\x13' + HARD
    pdf = emit_pdf(core.parse_ws(data))
    assert b'/F2' in pdf                      # Courier-Bold used
    assert b'\\(word\\)' in pdf               # parens escaped
    assert b' l S' in pdf                     # underline stroke drawn

def test_pdf_via_cli_registry():
    from ctrlkd import get_emitter
    out = get_emitter('pdf')['fn'](core.parse_ws(make_prose()))
    assert out[:5] == b'%PDF-'

def test_pdf_chapter_drop_survives():
    # machine top margin (uniform blanks on every page) strips; the author's
    # extra blank lines on page 1 (chapter-drop) survive
    from ctrlkd.pdf import emit_pdf
    page1 = b'\r\n' * 8 + b'Chapter opening text here.\r\n'
    page2 = b'\r\n' * 2 + b'Second page text here.\r\n'
    pdf = emit_pdf(core.parse_printstream(page1 + b'\x0c' + page2), 'printed')
    import re
    ys = [float(m) for m in re.findall(rb'([0-9.]+) Td \(Chapter', pdf)]
    y2 = [float(m) for m in re.findall(rb'([0-9.]+) Td \(Second', pdf)]
    assert ys and y2 and ys[0] < y2[0]   # page-1 text starts LOWER than page-2 text

def test_md_multistyle_span_is_deterministic():
    # frozenset iteration made bold+strike nesting vary across runs (hash seed);
    # found by the Swift port. sorted() pins it: delimiters inside, tags outside.
    from ctrlkd.emit import _md_span
    from ctrlkd.core import Span
    assert _md_span(Span('w', frozenset({'b', 'strike'}))) == '~~**w**~~'
    assert _md_span(Span('w', frozenset({'b', 'u'}))) == '<u>**w**</u>'

def test_pdf_headings_render_bold():
    # the docstring promised it; the Swift port (job-011) found it unimplemented
    from ctrlkd.pdf import _doc_to_pagelines
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        ('MS Chapter Title', True, _style_record()),
    ])
    style = ws7_block(0x11, (0x0202).to_bytes(2, 'little') + (0x0201).to_bytes(2, 'little')
                      + (0x0300).to_bytes(2, 'little') + (0x0201).to_bytes(2, 'little'))
    # a style selection PERSISTS until the next one, so the fixture switches
    # back to the recordless base before the body -- exactly what real
    # documents do (NOVEL.WS re-selects 'MS Body Copy' after every heading).
    # Prose padding keeps the block-heavy fixture detecting as ws5+, not
    # binary (the documented small-fixture trap).
    body = (ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4)) + style +
            b'Chapter One' + HARD + HARD +
            _style_handle(1) + b'Body text here, at a perfectly ordinary '
            b'length for a paragraph of running prose in a real document.' + HARD +
            b'A second sentence keeps the prose-to-binary ratio realistic.' + HARD)
    base = ((len(body) + 127) // 128) * 128
    data = bytearray(body.ljust(base, b'\x1a')) + lib
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    pages = _doc_to_pagelines(core.parse_ws(bytes(data)), False)
    segs = [seg for pg in pages for line in pg for seg in line]
    # wrapLine tokenizes into words: assert at segment granularity
    assert any(t == 'Chapter' and 'b' in st for t, st in segs)
    assert any(t == 'Body' and 'b' not in st for t, st in segs)

def test_pdf_exact_fill_no_blank_sheet():
    # job-011 finding; the 1.1.5 fix popped BEFORE stripping and missed it, and
    # this test's first version used input that detects as printstream, so it
    # could never fail (job-012 finding). Now: real WS4 bytes, via parse().
    from ctrlkd.pdf import _doc_to_pagelines, LINES_MODERN
    # 26 one-line paragraphs + a final paragraph long enough to wrap once:
    # 54 entries of content on page 1, the final structural blank spills to
    # page 2, stripping hollows it -> the 1.1.5 blank sheet ([54, 0])
    n = (LINES_MODERN - 2) // 2
    data = b''.join(ws4_text('Paragraph %d here today.' % i) + HARD + HARD
                    for i in range(n))
    data += ws4_text('This final paragraph is deliberately long enough that the '
                     'wrap test must break it across two physical lines.') + HARD
    doc = core.parse(data)
    assert doc.meta['variant'] == 'ws4'          # the test's own premise, pinned
    pages = _doc_to_pagelines(doc, False)
    assert [len(pg) for pg in pages] == [LINES_MODERN]

def test_pdf_trailing_double_pagebreak_no_blank_sheet():
    # the other pop path: an explicitly empty final page from trailing .pa .pa
    from ctrlkd.pdf import _doc_to_pagelines
    data = (b'Page one text here.' + HARD + b'.pa' + HARD + b'.pa' + HARD)
    pages = _doc_to_pagelines(core.parse_ws(data), False)
    assert all(pg for pg in pages), [len(pg) for pg in pages]
    # interior blank pages from .pa .pa BETWEEN content are preserved
    data2 = (b'One.' + HARD + b'.pa' + HARD + b'.pa' + HARD + b'Two.' + HARD)
    pages2 = _doc_to_pagelines(core.parse_ws(data2), False)
    assert [bool(pg) for pg in pages2] == [True, False, True]

# ---------------------------------------------------------------- note-aware export
# footnote/endnote/annotation/comment inclusion (convert.py) and per-format,
# per-kind rendering (emit.py). One synthetic doc carries all four kinds so
# every format/inclusion test exercises the real mix a WS7 file has.

def four_kind_data():
    # number=0 for the (only, i.e. first) footnote/endnote: WS7's own
    # storage is a 0-based index: see
    # test_footnote_endnote_number_is_1_based_not_stored_index.
    return (ws7_block(0x00) +
            b'one ' + ws7_note(0x03, b'Footnote text.', number=0) +
            b' two ' + ws7_note(0x04, b'Endnote text.', number=0) +
            b' three ' + ws7_annotation_with_tag(
                dot_lines=[b'.. remark'], text=b'Annotation text', tag_text=b'AC1') +
            b' four ' + ws7_note(0x06, b'Comment text.', number=0) +
            b' five' + HARD)

@pytest.fixture
def four_kind_doc():
    return core.parse_ws(four_kind_data())

# -- display numbering: WordStar shows 1-based, core.py stores a 0-based index --

def test_footnote_endnote_number_is_1_based_not_stored_index():
    # WordStar's own documented numbering starts at 1 (WSCHANGE's factory
    # defaults render a footnote mark as "1." and an endnote as "(1)" for
    # the first note; a `.f#`-style dot command can move the start point,
    # but 1 is the default). core.py's Note.number is the file's raw
    # internal index, and that index is 0-based (confirmed against a real
    # WS7 file) -- so the first footnote/endnote in a document is STORED as
    # 0 and must be DISPLAYED as 1. Showing 0 leaks a storage detail no
    # WordStar user ever saw.
    data = (ws7_block(0x00) +
            b'a ' + ws7_note(0x03, b'First footnote.', number=0) +
            b' b ' + ws7_note(0x03, b'Second footnote.', number=1) +
            b' c ' + ws7_note(0x04, b'First endnote.', number=0) + b' d' + HARD)
    doc = core.parse_ws(data)
    md = emit.emit_markdown(doc, mode='modern')
    assert '[^1]: First footnote.' in md
    assert '[^2]: Second footnote.' in md
    assert '[^e1]: First endnote.' in md
    t = emit.emit_text(doc, mode='modern')
    assert '[1] First footnote.' in t and '[2] Second footnote.' in t
    h = emit.emit_html(doc, mode='modern')
    assert '<a id="fnref1" href="#fn1" role="doc-noteref">1</a>' in h
    assert '<a id="fnref2" href="#fn2" role="doc-noteref">2</a>' in h
    r = emit.emit_rtf(doc, mode='modern')
    assert 'First footnote.' in r and 'Second footnote.' in r
    # presentation-only: the raw stored index must survive untouched
    assert [n.number for n in doc.notes if n.kind == 'footnote'] == [0, 1]
    assert doc.notes[2].number == 0 and doc.notes[2].kind == 'endnote'

def test_note_number_field_marker_and_area_agree_when_nonzero():
    # b26 notes wave, Fix 3: a note whose embedded `number` field is nonzero
    # (WordStar's own 0-based stored index -- see
    # test_footnote_endnote_number_is_1_based_not_stored_index above, which
    # only exercises 0 and 1 through emit_markdown) must show the SAME
    # display number at its inline marker and in its end-matter area, in
    # every format -- not just the number=0 case every other note fixture
    # in this file uses. Regression coverage for a reported inline-vs-area
    # double-increment ("found during the b26 port, pre-existing both
    # engines"); every format here already routes both consumers through
    # emit.py's shared _annotated_notes/_display_number, so on this repo
    # this is a cross-format pin, not evidence a fix was needed here.
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) +
            b'Ref line' + ws7_note(0x03, b'Footnote body.', number=1) +
            b' end.' + HARD)
    doc = core.parse_ws(data)
    t = emit.emit_text(doc, mode='modern')
    assert 'Ref line[2] end.' in t and '[2] Footnote body.' in t
    md = emit.emit_markdown(doc, mode='modern')
    assert '[^2]' in md and '[^2]: Footnote body.' in md
    h = emit.emit_html(doc, mode='modern')
    assert 'id="fnref2"' in h and 'id="fn2"' in h
    r = emit.emit_rtf(doc, mode='modern')
    assert 'Footnote body.' in r
    pp = emit_pdf(doc, mode='printed')
    ptexts = b' '.join(re.findall(rb'\(((?:\\.|[^)\\])*)\)\s*Tj', pp))
    assert b'2. Footnote body.' in ptexts
    pm = emit_pdf(doc, mode='modern')
    mtexts = b' '.join(re.findall(rb'\(((?:\\.|[^)\\])*)\)\s*Tj', pm))
    assert b'[2] Footnote body.' in mtexts

def test_footnote_number_start_hook_ready_for_future_dot_command():
    # core.py doesn't parse a `.f#`-style starting-number dot command yet
    # (another agent is adding dot-command parsing separately) -- this
    # proves the one named place designed to receive that value
    # (doc.meta['footnote_number_start']) already produces the right
    # display number today, so wiring in real `.f#` parsing later is a
    # one-line change in core.py, not a redesign here.
    data = ws7_block(0x00) + b'x ' + ws7_note(0x03, b'Only footnote.', number=0) + b' y' + HARD
    doc = core.parse_ws(data)
    doc.meta['footnote_number_start'] = 5
    md = emit.emit_markdown(doc, mode='modern')
    assert '[^5]: Only footnote.' in md

# -- Task 1: convert() / select_notes() inclusion API --------------------

def test_select_notes_default_excludes_comments(four_kind_doc):
    from ctrlkd.emit import DEFAULT_NOTE_KINDS, ALL_NOTE_KINDS, select_notes
    kinds = [n.kind for n in select_notes(four_kind_doc)]
    assert kinds == ['footnote', 'endnote', 'annotation']
    assert select_notes(four_kind_doc, DEFAULT_NOTE_KINDS) == select_notes(four_kind_doc)
    all_kinds = [n.kind for n in select_notes(four_kind_doc, ALL_NOTE_KINDS)]
    assert all_kinds == ['footnote', 'endnote', 'annotation', 'comment']

def test_select_notes_unknown_kind_ignored_not_raised(four_kind_doc):
    from ctrlkd.emit import select_notes
    assert select_notes(four_kind_doc, {'bogus'}) == []

def test_convert_default_excludes_comments_opt_in_surfaces_them():
    from ctrlkd import convert
    from ctrlkd.convert import ALL_NOTE_KINDS
    data = four_kind_data()
    default_out = convert(data, to='markdown')
    assert 'Comment text.' not in default_out
    opt_in = convert(data, to='markdown', notes=ALL_NOTE_KINDS)
    assert 'Comment text.' in opt_in

def test_convert_notes_option_forwards_to_html_and_rtf():
    from ctrlkd import convert
    from ctrlkd.convert import ALL_NOTE_KINDS
    data = four_kind_data()
    assert 'Comment text.' not in convert(data, to='html')
    assert 'Comment text.' in convert(data, to='html', notes=ALL_NOTE_KINDS)
    assert 'Comment text.' not in convert(data, to='rtf')
    assert 'Comment text.' in convert(data, to='rtf', notes=ALL_NOTE_KINDS)

# -- Task 2: text -----------------------------------------------------

def test_emit_text_sections_labeled_by_kind(four_kind_doc):
    t = emit.emit_text(four_kind_doc)
    assert 'Footnotes:\n[1] Footnote text.' in t
    assert 'Endnotes:\n[1] Endnote text.' in t
    assert 'Annotations:\n[AC1] Annotation text' in t
    assert 'Comments:' not in t and 'Comment text.' not in t

def test_emit_text_comments_opt_in_own_section(four_kind_doc):
    from ctrlkd.emit import ALL_NOTE_KINDS
    t = emit.emit_text(four_kind_doc, 'modern', notes=ALL_NOTE_KINDS)
    assert 'Comments:\n[1] Comment text.' in t
    # printed is always silent about comments (ruling 2026-08-06)
    assert 'Comment text.' not in emit.emit_text(four_kind_doc, 'printed',
                                                 notes=ALL_NOTE_KINDS)

# -- Task 2: markdown ---------------------------------------------------

def test_emit_markdown_kinds_get_distinct_labels(four_kind_doc):
    md = emit.emit_markdown(four_kind_doc, mode='modern')
    assert '[^1]' in md and '[^1]: Footnote text.' in md
    assert '[^e1]' in md and '[^e1]: Endnote text.' in md
    assert '[^aAC1]' in md and '[^aAC1]: Annotation text' in md
    assert 'Comment text.' not in md

def test_emit_markdown_comments_opt_in_are_orphan_defs(four_kind_doc):
    from ctrlkd.emit import ALL_NOTE_KINDS
    md = emit.emit_markdown(four_kind_doc, notes=ALL_NOTE_KINDS, mode='modern')
    assert '[^c1]: Comment text.' in md
    # comments never get an inline reference (WordStar never printed them,
    # so there's no source anchor point to reference)
    assert '[^c1]]' not in md

def test_emit_markdown_excluding_a_kind_also_drops_its_inline_ref(four_kind_doc):
    md = emit.emit_markdown(four_kind_doc, notes={'footnote'}, mode='modern')
    assert '[^1]' in md and '[^1]: Footnote text.' in md
    assert '[^e1]' not in md and 'Endnote text.' not in md
    assert '[^aAC1]' not in md and 'Annotation text' not in md

# -- Task 2: html (DPUB-ARIA) --------------------------------------------

def test_emit_html_noteref_anchors_and_backlinks(four_kind_doc):
    h = emit.emit_html(four_kind_doc)
    assert '<a id="fnref1" href="#fn1" role="doc-noteref">1</a>' in h
    assert '<a id="enref1" href="#en1" role="doc-noteref">1</a>' in h
    assert '<a id="anrefAC1" href="#anAC1" role="doc-noteref">AC1</a>' in h
    assert '<a href="#fnref1" role="doc-backlink">' in h
    assert '<a href="#enref1" role="doc-backlink">' in h
    assert '<a href="#anrefAC1" role="doc-backlink">' in h

def test_emit_html_sections_use_doc_endnotes_not_deprecated_roles(four_kind_doc):
    h = emit.emit_html(four_kind_doc)
    # doc-endnotes: "a collection of notes at the end of a work" -- the
    # spec-correct landmark for ALL our note kinds, since none of them are
    # rendered at their original in-body position (no format here has pages)
    assert h.count('role="doc-endnotes"') == 3           # footnote/endnote/annotation
    assert '<h2 id="footnotes-label">Footnotes</h2>' in h
    assert '<h2 id="endnotes-label">Endnotes</h2>' in h
    assert '<h2 id="annotations-label">Annotations</h2>' in h
    # doc-footnote is spec'd for in-body notes (ours are moved to the end,
    # so it doesn't apply); doc-endnote is deprecated as a listitem role.
    # Neither should appear anywhere.
    assert 'role="doc-footnote"' not in h
    assert 'role="doc-endnote"' not in h
    # doc-endnotes must not be applied directly to the list itself
    assert '<ol role="doc-endnotes">' not in h
    assert 'data-note-kind="annotation"' in h and 'data-note-tag="AC1"' in h

def test_emit_html_comments_excluded_by_default_opt_in_no_backlink(four_kind_doc):
    from ctrlkd.emit import ALL_NOTE_KINDS
    default_h = emit.emit_html(four_kind_doc)
    assert 'Comment text.' not in default_h and 'doc-endnotes' in default_h
    # printed is always silent about comments (ruling 2026-08-06)
    assert 'Comment text.' not in emit.emit_html(four_kind_doc, 'printed',
                                                 notes=ALL_NOTE_KINDS)
    h = emit.emit_html(four_kind_doc, 'modern', notes=ALL_NOTE_KINDS)
    assert 'Comment text.' in h
    assert '<h2 id="comments-label">Comments</h2>' in h
    # word scheme: no visible inline anchor, hence no backlink either
    assert '>↩</a></li></ol></section>' not in h.split('Comments</h2>')[1]

# -- Task 2: rtf (real \footnote destination) ----------------------------

def test_emit_rtf_footnote_uses_real_chftn_destination(four_kind_doc):
    r = emit.emit_rtf(four_kind_doc)
    assert r'\chftn' in r and r'\*\footnote' in r
    assert 'Footnote text.' in r
    assert r.count('{') == r.count('}')

def test_emit_rtf_endnote_and_annotation_use_ftnalt(four_kind_doc):
    r = emit.emit_rtf(four_kind_doc)
    assert r'\ftnalt' in r
    # exactly two \footnote destinations carry \ftnalt: the endnote and the
    # tagged annotation (the plain footnote must NOT carry it)
    assert r.count(r'\footnote\ftnalt') == 2
    assert 'Endnote text.' in r and 'Annotation text' in r
    assert r'AC1' in r                      # annotation's own tag as its mark

def test_emit_rtf_comments_use_real_annotation_destination(four_kind_doc):
    from ctrlkd.emit import ALL_NOTE_KINDS
    default_r = emit.emit_rtf(four_kind_doc)
    assert r'\annotation' not in default_r and 'Comment text.' not in default_r
    # printed + comments is inert (ruling 2026-08-06): WordStar printed
    # nothing for a comment, so the facsimile doesn't either
    printed_r = emit.emit_rtf(four_kind_doc, 'printed', notes=ALL_NOTE_KINDS)
    assert 'Comment text.' not in printed_r
    # Modern anchors a real Word margin comment at the TRUE position --
    # inline between the words around it, not dumped at the document end
    r = emit.emit_rtf(four_kind_doc, 'modern', notes=ALL_NOTE_KINDS)
    assert r'\*\annotation' in r and r'\chatn' in r and r'\atnid' in r
    assert 'Comment text.' in r
    assert r.index('Comment text.') < r.index('five')
    assert r.count('{') == r.count('}')

def test_emit_rtf_no_extra_font_codes_in_note_destinations(four_kind_doc):
    # house rule: never write font attributes onto every paragraph/note --
    # \fs (size) inside a note destination is fine (matches the existing
    # heading-size precedent), but \f0/\f1 (an actual FONT change) must only
    # ever appear where the document declares its one-time default.
    from ctrlkd.emit import ALL_NOTE_KINDS
    bare = emit.emit_rtf(core.parse_ws(make_prose()))
    baseline = bare.count(r'\f0') + bare.count(r'\f1')
    with_notes = emit.emit_rtf(four_kind_doc, notes=ALL_NOTE_KINDS)
    assert with_notes.count(r'\f0') + with_notes.count(r'\f1') == baseline

# -- fonts/HTML CSS untouched by this rework ------------------------------

def test_emit_html_css_stays_one_head_blob(four_kind_doc):
    h = emit.emit_html(four_kind_doc)
    assert h.count('<style>') == 1
    assert 'style=' not in h                # no inline per-element font/style attrs

# ================================================================== 8< ====
# The three sections below are core.py/pdf.py work: dot-command page
# geometry (.pl/.po/.mt/.mb), a couple of small parser additions (the
# undocumented right-tab type, WordTsar producer detection, COMMENT.BUG),
# and Printed mode's period-authentic footnote page layout.

# ---------------------------------------------------------------- page geometry

def test_page_geometry_defaults_to_letter():
    # no .pl/.po/.mt/.mb anywhere -- WordStar's own .pl 66 default, and what
    # the PDF emitter already rendered before any of this existed.
    doc = core.parse_ws(b'Body text, no dot commands.' + HARD)
    page = doc.meta['page']
    assert page['pl_lines'] == 66.0
    assert page['height_in'] == 11.0
    assert page['size_name'] == 'Letter'
    assert page['size_source'] == 'default'
    assert page['mt_lines'] == 3.0 and page['mt_source'] == 'default'
    assert page['mb_lines'] == 8.0 and page['mb_source'] == 'default'
    # 8, not 0: WS7 manual, "The default page offset is .8 inch" -- since 2.0.0
    # renders the offset, the manual's stated default governs
    assert page['po_cols'] == 8.0 and page['po_source'] == 'default'

def test_page_geometry_pl_unitless_is_lines_not_inches():
    # THE trap: WordTsar's own @todo admits it falls back to inches when
    # .pl has no unit suffix. A bare 66 must resolve to 66 LINES (11in,
    # Letter) -- reading it as 66 INCHES would be an absurd ~6ft page, and
    # would NOT come back around to Letter by coincidence.
    doc = core.parse_ws(b'.PL 66' + HARD + b'Body text.' + HARD)
    page = doc.meta['page']
    assert page['pl_lines'] == 66.0
    assert page['height_in'] == 11.0
    assert page['size_name'] == 'Letter'
    assert page['size_source'] == 'file'

def test_page_geometry_pl_legal_and_foolscap():
    # 6 LPI: .pl 84 -> 14in (Legal), .pl 81 -> 13.5in (Foolscap Folio, the
    # pre-ISO UK long sheet) -- the spec's own worked example plus the two
    # other named sizes this project recognises.
    for lines, name, inches in ((84, 'Legal', 14.0), (81, 'Foolscap Folio', 13.5)):
        doc = core.parse_ws(('.PL %d' % lines).encode() + HARD + b'x' + HARD)
        page = doc.meta['page']
        assert page['size_name'] == name
        assert page['height_in'] == inches
        assert page['size_source'] == 'file'

def test_page_geometry_mt_mb_po_parsed():
    data = b'.MT 4' + HARD + b'.MB 9' + HARD + b'.PO 12' + HARD + b'Body.' + HARD
    page = core.parse_ws(data).meta['page']
    assert page['mt_lines'] == 4.0 and page['mt_source'] == 'file'
    assert page['mb_lines'] == 9.0 and page['mb_source'] == 'file'
    assert page['po_cols'] == 12.0 and page['po_source'] == 'file'

def test_page_geometry_explicit_unit_suffix_converts():
    # NOT the trap case above -- WordStar 5.0+ DOES allow an explicit unit
    # suffix, and that must still convert correctly (inches here; .pl's
    # argument is always resolved back to lines internally).
    doc = core.parse_ws(b'.PL 11"' + HARD + b'Body.' + HARD)
    assert doc.meta['page']['pl_lines'] == 66.0
    assert doc.meta['page']['size_name'] == 'Letter'

def test_page_geometry_snaps_close_but_honours_far_raw_geometry():
    close = core.parse_ws(b'.PL 67' + HARD + b'x' + HARD)     # 11.1667in: within 0.25 of Letter
    assert close.meta['page']['size_name'] == 'Letter'
    assert close.meta['page']['height_in'] == 11.0             # snapped to the named figure
    # .PL 70 = 11.667in: within 0.026 of A4's 11.693 -- since 2026-08-06
    # ("the 3 main page sizes") that IS A4, at the 210mm width
    a4 = core.parse_ws(b'.PL 70' + HARD + b'x' + HARD)
    assert a4.meta['page']['size_name'] == 'A4'
    assert abs(a4.meta['page']['pw_in'] - 8.268) < 1e-6
    far = core.parse_ws(b'.PL 74' + HARD + b'x' + HARD)        # 12.33in: far from all
    assert far.meta['page']['size_name'] == 'Custom'
    assert far.meta['page']['pw_in'] == 8.5
    assert far.meta['page']['height_in'] == pytest.approx(74 / 6)   # raw geometry honoured

def test_page_geometry_dot_commands_still_preserved_verbatim():
    # recognising .pl/.mt/.mb/.po must not stop them being kept in the
    # project's standing verbatim dot-command log.
    doc = core.parse_ws(b'.PL 84' + HARD + b'Body.' + HARD)
    assert '.PL 84' in doc.meta['dot_commands']

def test_page_geometry_malformed_pl_does_not_crash():
    # a truncated/garbage argument must degrade to the default, never raise
    doc = core.parse_ws(b'.PL' + HARD + b'Body.' + HARD)
    assert doc.meta['page']['pl_lines'] == 66.0
    assert doc.meta['page']['size_source'] == 'default'

# ------------------------------------------- the vertical model (text_lines)

def test_page_geometry_defaults_give_wordstar_55_not_60():
    # THE fix this section exists for: WordStar's own defaults (.pl 66
    # .mt 3 .mb 8 .lh 8) put 55 text lines on a page -- the manual's model,
    # (pl - mt - mb) at 6 LPI -- not the 60 a naive 1in-margin Letter
    # computation produced for every document before 1.3.0.
    from ctrlkd.pdf import _printed_cap
    doc = core.parse_ws(b'Body text.' + HARD)
    assert doc.meta['page']['text_lines'] == 55
    assert _printed_cap(doc) == 55

def test_page_geometry_mt_mb_change_capacity():
    doc = core.parse_ws(b'.MT 6' + HARD + b'.MB 6' + HARD + b'x' + HARD)
    assert doc.meta['page']['text_lines'] == 54          # 66 - 6 - 6

def test_page_geometry_lh_parsed_and_scales_capacity():
    # .lh is 1/48in units: .lh 16 doubles the line height, halving capacity
    # (the manual: "Changing the line height affects the number of lines
    # that can be printed on a page"). floor(55 * 8 / 16) = 27.
    doc = core.parse_ws(b'.LH 16' + HARD + b'x' + HARD)
    page = doc.meta['page']
    assert page['lh_48'] == 16.0 and page['lh_source'] == 'file'
    assert page['text_lines'] == 27

def test_page_geometry_lh_unit_suffix_converts():
    # .lh 12p = 12/72in = 8/48in -> the standard height, stated in points
    doc = core.parse_ws(b'.LH 12P' + HARD + b'x' + HARD)
    assert doc.meta['page']['lh_48'] == 8.0
    assert doc.meta['page']['text_lines'] == 55

def test_page_geometry_lh_zero_and_auto_rejected():
    # .lh 0 is meaningless and .lh a is auto-leading -- both leave the
    # default standing (and stay preserved verbatim in dot_commands)
    for arg in (b'.LH 0', b'.LH A'):
        doc = core.parse_ws(arg + HARD + b'x' + HARD)
        assert doc.meta['page']['lh_48'] == 8.0
        assert doc.meta['page']['lh_source'] == 'default'
        assert doc.meta['page']['text_lines'] == 55

def test_page_geometry_ls_recorded_but_never_divides_capacity():
    # the trap the manual defuses: line-spacing blanks are LITERAL lines in
    # the file ("when you use line spacing, the blank lines become part of
    # the file" -- WS7 manual, "Line Spacing"), so the body already carries
    # them; dividing capacity by .ls would double-count.
    doc = core.parse_ws(b'.LS 2' + HARD + b'x' + HARD)
    page = doc.meta['page']
    assert page['ls'] == 2.0 and page['ls_source'] == 'file'
    assert page['text_lines'] == 55                       # unchanged

def test_page_geometry_ls_out_of_range_rejected():
    # spec: "a line spacing of between 1 and 9"
    for arg in (b'.LS 0', b'.LS 12'):
        doc = core.parse_ws(arg + HARD + b'x' + HARD)
        assert doc.meta['page']['ls'] == 1.0
        assert doc.meta['page']['ls_source'] == 'default'

def test_page_geometry_hm_fm_parsed_but_reserve_no_space():
    # header/footer margins position header and footer INSIDE .mt/.mb
    # (".MT ... The header is printed within this margin") -- parsed with
    # provenance for --diagnose, never subtracted from capacity
    doc = core.parse_ws(b'.HM 1' + HARD + b'.FM 3' + HARD + b'x' + HARD)
    page = doc.meta['page']
    assert page['hm_lines'] == 1.0 and page['hm_source'] == 'file'
    assert page['fm_lines'] == 3.0 and page['fm_source'] == 'file'
    assert page['text_lines'] == 55                       # unchanged

def test_page_geometry_absurd_margins_clamp_not_crash():
    # margins that eat the whole page (garbage in a misdetected binary)
    # degrade to a 1-line model, never zero/negative/crash
    doc = core.parse_ws(b'.PL 12' + HARD + b'.MT 40' + HARD + b'.MB 40' + HARD + b'x' + HARD)
    assert doc.meta['page']['text_lines'] == 1

def test_pdf_printed_top_offset_follows_mt():
    # UPDATED 2026-08-20 (round 26 wave 3, WS7 ground truth): a document
    # that never sets `.mt` gets (.mt + .hm) lines -- the default .mt 3 +
    # .hm 2 = 5 lines = 60pt (was 36, .mt alone) -- the print driver's own
    # factory PAIR. UPDATED AGAIN same day (PREVIEW.WS ground truth,
    # fidelity_gate.py Finding B/top-margin refinement): `.hm` only rides
    # along with the FACTORY `.mt`, not an author-declared one -- a
    # document that sets its OWN `.mt` (mt_source == 'file') gets that
    # value ALONE, no `.hm` added. See _printed_top's docstring.
    from ctrlkd.pdf import _printed_top
    assert _printed_top(core.parse_ws(b'x' + HARD)) == 60
    assert _printed_top(core.parse_ws(b'.MT 6' + HARD + b'x' + HARD)) == 72

def test_pdf_printed_lead_follows_lh():
    # .lh 8 IS the 12pt lead; .lh 16 prints double-spaced at 24pt
    from ctrlkd.pdf import _printed_lead
    assert _printed_lead(core.parse_ws(b'x' + HARD)) == 12.0
    assert _printed_lead(core.parse_ws(b'.LH 16' + HARD + b'x' + HARD)) == 24.0

def test_pdf_output_bytes_carry_mt_top_and_lh_lead():
    # end-to-end: the geometry must reach the CONTENT STREAM, not just the
    # helpers. UPDATED 2026-08-20 (round 26 wave 3, refined same day on
    # PREVIEW.WS ground truth): top is `.mt` ALONE = 6*12 = 72pt -- an
    # author-declared `.mt` (mt_source == 'file') does not also inherit
    # the factory `.hm` pairing, see _printed_top's docstring -- and the
    # FIRST line's own baseline-within-line offset is its own lead (here
    # the document-default 24pt from .lh 16, since `.lh 16` is set before
    # any line so line 0 carries no per-line override -- see
    # _page_stream), not a flat 12pt. Read the Td y-coordinates back out
    # of the bytes.
    import re
    from ctrlkd.pdf import emit_pdf
    data = (b'.MT 6' + HARD + b'.LH 16' + HARD +
            b'Line one.' + HARD + b'Line two.' + HARD + b'Line three.' + HARD)
    pdf = emit_pdf(core.parse_ws(data), mode='printed')
    ys = [float(m) for m in re.findall(rb'[\d.]+ ([\d.]+) Td', pdf)]
    assert ys[0] == 792 - 72 - 24                  # top from .mt alone, first lead from .lh
    assert ys[0] - ys[1] == 24.0                   # lead from .lh, not fixed 12
    assert ys[1] - ys[2] == 24.0

# ------------------------------------------- horizontal geometry (2.0.0)

# WS4-shaped bytes: soft return = 8D 0A, hard = 0D 0A. ws4_text-style helper
# fixtures exist above for style codes; plain ASCII is enough here.
SOFT = b'\x8d\x0a'

def _ws_wrapped_para():
    # two soft-wrapped physical lines then a hard return -- classic word wrap.
    # Lines are near the 65-col default margin so lines_pass reads the soft
    # breaks as wrap (joining would overflow), not as deliberate breaks.
    l1 = b'w' * 30 + b' ' + b'x' * 30
    l2 = b'y' * 30 + b' ' + b'z' * 30
    return l1 + SOFT + l2 + HARD

def test_soft_wrapped_lines_stay_physical_in_the_ir():
    doc = core.parse_ws(_ws_wrapped_para())
    para = [b for b in doc.blocks if b.kind == 'para'][0]
    assert len(para.lines) == 2                    # physical lines preserved
    assert para.lines[0].soft is True              # ...and marked
    assert para.lines[1].soft is False

def test_merged_lines_reproduces_the_old_logical_line():
    # the reflow view: soft runs joined with the old space rule
    doc = core.parse_ws(_ws_wrapped_para())
    para = [b for b in doc.blocks if b.kind == 'para'][0]
    logical = core.merged_lines(para)
    assert len(logical) == 1
    text = logical[0].text()
    assert text == 'w' * 30 + ' ' + 'x' * 30 + ' ' + 'y' * 30 + ' ' + 'z' * 30

def test_merged_lines_suppresses_space_after_hyphen():
    # l1 must be long enough that lines_pass reads the soft break as wrap
    # (L + 1 + W >= the 65-col default margin), or the break is 'line' and
    # never merges at all
    l1 = b'a' * 56 + b' hyphen-'
    data = l1 + SOFT + b'ated word plus enough text to reach the margin here.' + HARD
    doc = core.parse_ws(data)
    para = [b for b in doc.blocks if b.kind == 'para'][0]
    logical = core.merged_lines(para)
    assert 'hyphen-ated' in logical[0].text()      # no space injected

def test_printed_text_renders_physical_lines_modern_renders_logical():
    # emit_text on a parse_ws doc directly: convert()'s auto-detect would
    # read these low-high-bit synthetic bytes as a printstream and never
    # exercise the soft flags at all (a vacuous pass)
    from ctrlkd.emit import emit_text
    doc = core.parse_ws(_ws_wrapped_para())
    printed = emit_text(doc, mode='printed')
    modern = emit_text(doc, mode='modern')
    assert 'w' * 30 + ' ' + 'x' * 30 + '\n' + 'y' * 30 in printed   # break kept
    assert 'x' * 30 + ' ' + 'y' * 30 in modern                       # joined

def test_page_geometry_cw_parsed_and_units():
    doc = core.parse_ws(b'.CW 10' + HARD + b'x' + HARD)
    assert doc.meta['page']['cw_120'] == 10.0
    assert doc.meta['page']['cw_source'] == 'file'
    # 0.1 inch = 12/120ths -- the default pitch, stated in inches
    doc = core.parse_ws(b'.CW 0.1"' + HARD + b'x' + HARD)
    assert doc.meta['page']['cw_120'] == pytest.approx(12.0)

def test_page_geometry_cw_zero_rejected():
    doc = core.parse_ws(b'.CW 0' + HARD + b'x' + HARD)
    assert doc.meta['page']['cw_120'] == 12.0
    assert doc.meta['page']['cw_source'] == 'default'

def test_pdf_printed_size_and_left_follow_cw_po():
    from ctrlkd.pdf import _printed_size, _printed_left
    d_default = core.parse_ws(b'x' + HARD)
    assert _printed_size(d_default) == 12
    assert _printed_left(d_default, 12) == pytest.approx(8 * 7.2)   # 57.6
    d_elite = core.parse_ws(b'.CW 10' + HARD + b'.PO 12' + HARD + b'x' + HARD)
    assert _printed_size(d_elite) == 10
    assert _printed_left(d_elite, 10) == pytest.approx(12 * 7.2)    # 86.4: fixed pt/col (dx exp 2026-08-20)

def test_pdf_output_bytes_carry_po_left_and_cw_size():
    # end-to-end: x-coordinates and Tf size come from the file's own .po/.cw
    import re
    from ctrlkd.pdf import emit_pdf
    data = (b'.PO 12' + HARD + b'.CW 10' + HARD + b'Line one.' + HARD)
    pdf = emit_pdf(core.parse_ws(data), mode='printed')
    m = re.search(rb'/F1 (\d+) Tf \d+ Ts ([\d.]+) [\d.]+ Td', pdf)
    assert m and m.group(1) == b'10'               # elite type size
    assert m.group(2) == b'86.4'                   # 12 cols x 7.2pt/col, pitch-independent

def test_pdf_printstream_keeps_fixed_margin_and_size():
    from ctrlkd.pdf import _printed_size, _printed_left
    ps = core.parse_printstream(b'line one\r\n')
    assert _printed_size(ps) == 12
    assert _printed_left(ps, 12) == 72.0           # streams: offset is in-band

def test_pdf_printstream_uses_wordstars_documented_page():
    # CORRECTED 2026-08-03. This used to assert 66 -- the FULL page -- on the
    # premise that "a print stream IS the printed page, its margin blanks
    # travel in-band". Checked against raw bytes, that is false: real
    # print-to-disk output carries no form feeds and no top margin after its
    # first page. 66 was a page size WordStar does not document and no evidence
    # supports.
    #
    # A stream that declares no page geometry now gets WordStar's documented
    # defaults, exactly like a document that declares none: .pl 66 - .mt 3
    # - .mb 8 = 55. That is also what WordStar 4 produces when actually run.
    from ctrlkd.pdf import _printed_cap, _printed_top
    doc = core.parse_printstream(b'line one\r\nline two\r\n')
    assert _printed_cap(doc) == 55
    assert _printed_top(doc) == 36                        # fixed: not .mt-derived

# ---------------------------------------------------------------- small parser additions

def _ws7_tab(size_hmi, tab_type_byte, tenths=0):
    content = (size_hmi.to_bytes(2, 'little') + size_hmi.to_bytes(2, 'little') +
               bytes([tab_type_byte]) + bytes([tenths]))
    return ws7_block(0x09, content)

def test_ws7_tab_undocumented_right_align_type():
    # ']' is an undocumented right-align tab variant WordTsar's author found
    # testing MicroPro's own PRINT.TST; a real type-9 block there carries
    # tab type ']' with size 4500 HMI. An HMI is 1/1800in (HORTAB.TXT), so
    # 4500 HMI = 2.5in = 25 ten-CPI columns. (The old expectation of 31 came
    # from dividing by 144 -- VMI's 1/1440in unit misapplied to the
    # horizontal axis; every archive tab block's own tenths-byte says /180.)
    data = ws7_block(0x00) + _ws7_tab(4500, ord(']')) + b'Indented.' + HARD
    doc = core.parse_ws(data)
    text = doc.blocks[0].lines[0].text()
    assert text.startswith(' ' * 25)
    assert text.strip() == 'Indented.'

def test_ws7_tab_dot_leader_repeats_leader_character():
    # spec: "Other character such as '.' or '*' are used for dot leaders."
    # A leading "Row" keeps the expanded leader dots from starting the
    # physical line -- a line literally starting with '.' is (correctly,
    # pre-existing behaviour, unrelated to this fix) read as a dot command.
    data = ws7_block(0x00) + b'Row' + _ws7_tab(720, ord('.')) + b'Contents' + HARD  # 720 HMI = 0.4in = 4 cols
    doc = core.parse_ws(data)
    text = doc.blocks[0].lines[0].text()
    assert '.' * 4 in text
    assert text.startswith('Row') and text.endswith('Contents')

def test_ws7_tab_malformed_block_does_not_crash():
    data = ws7_block(0x00) + ws7_block(0x09) + b'Still here.' + HARD   # empty content
    doc = core.parse_ws(data)
    assert doc.blocks[0].lines[0].text().endswith('Still here.')

def test_producer_detection_wordtsar_dot_commands():
    # .PT/.PSA/.PSB are WordTsar's OWN invented dot commands ("not a
    # Wordstar command" per its own source) -- their presence is a
    # provenance signal, not a format one.
    data = b'.PT 5' + HARD + b'.PSA 1.5' + HARD + b'.PSB 2' + HARD + b'Body.' + HARD
    doc = core.parse_ws(data)
    assert doc.meta['producer'] == 'wordtsar'
    assert doc.meta['pt_raw'] == '5'                    # recorded verbatim, not mapped
    assert doc.meta['space_after_lines'] == 1.5
    assert doc.meta['space_before_lines'] == 2.0

def test_producer_absent_for_real_wordstar_files():
    doc = core.parse_ws(b'.PL 66' + HARD + b'Body.' + HARD)
    assert 'producer' not in doc.meta

def test_comment_bug_detected_on_bare_lf_line_ending():
    # COMMENT.BUG signature: a line ending in a bare LF instead of CR LF.
    # Framed as WordStar's OWN print-time damage, not a parse failure.
    good = b'Line one.\r\nLine two.\r\n'
    bad = b'Line one.\r\nLine two.\n'
    assert core.parse_printstream(good).meta.get('comment_bug') is None
    bug = core.parse_printstream(bad).meta.get('comment_bug')
    assert bug is not None and bug['count'] == 1

def test_comment_bug_flags_stray_ctrl_t():
    bad = b'Comment line\x14 truncated here\nNext line.\r\n'
    bug = core.parse_printstream(bad).meta.get('comment_bug')
    assert bug is not None and bug['stray_ctrl_t'] is True

# ---------------------------------------------------------------- Printed footnote layout

def _page_texts(pages):
    """Pages (as returned by pdf._doc_to_pagelines) -> plain strings, styling
    dropped, for content assertions."""
    return [[''.join(t for t, _ in line) for line in pg] for pg in pages]

def test_pdf_printed_footnote_area_basic_shape():
    from ctrlkd.pdf import _doc_to_pagelines, FOOTNOTE_SEPARATOR
    data = (b'.PL 24' + HARD +
            b'Line one text.' + HARD +
            b'Line two text.' + HARD +
            ws7_block(0x00) +
            b'Line three has a note' + ws7_note(0x03, b'Short note text.', number=0) +
            b' here.' + HARD +
            b'Line four text.' + HARD)
    doc = core.parse_ws(data)
    pages = _doc_to_pagelines(doc, True)
    texts = _page_texts(pages)
    assert len(pages) == 1                       # small note, plenty of room: one page
    flat = texts[0]
    # the reference never moved off its own body line
    ref_lines = [l for l in flat if 'Line three has a note' in l]
    assert ref_lines and ref_lines[0].rstrip().endswith('here.')
    assert any(l == FOOTNOTE_SEPARATOR for l in flat)
    assert any(l.startswith('1. Short note text.') for l in flat)
    # VMI-240 rhythm: one blank line immediately above and below the separator
    sep_i = flat.index(FOOTNOTE_SEPARATOR)
    assert flat[sep_i - 1] == '' and flat[sep_i + 1] == ''

def test_pdf_printed_footnote_splits_with_continuation_and_loses_nothing():
    from ctrlkd.pdf import _doc_to_pagelines, CONTINUATION_TEXT
    words = [f'word{i:03d}' for i in range(80)]
    data = (b'.PL 18' + HARD +                    # a small page: forces a split
            b'.MT 3' + HARD + b'.MB 3' + HARD +   # stated so capacity is 18-3-3=12,
                                                   # not left to the 3+8 defaults
            ws7_block(0x00) +
            b'First body line has the note' + ws7_note(0x03, ' '.join(words).encode(), number=0) +
            b' right here.' + HARD +
            b'Second body line.' + HARD + b'Third body line.' + HARD +
            b'Fourth body line.' + HARD + b'Fifth body line.' + HARD +
            b'Sixth body line.' + HARD + b'Seventh body line.' + HARD +
            b'Eighth body line.' + HARD)
    doc = core.parse_ws(data)
    pages = _doc_to_pagelines(doc, True)
    texts = _page_texts(pages)
    assert len(pages) > 1                         # it really did overflow

    # the reference never moved -- it's on whichever page the body naturally lands on
    ref_page = next(i for i, pg in enumerate(texts) if any('First body line' in l for l in pg))
    assert ref_page == 0

    # the floor: pages before the note is fully drained still carry >= 3 body lines
    # (every non-footnote, non-blank, non-separator line counts as body)
    def body_count(pg):
        return sum(1 for l in pg if l and l != CONTINUATION_TEXT and 'word' not in l
                   and not l.startswith('-'))
    assert body_count(texts[0]) == 3

    # continuation marker shows up, and nothing after page 0 repeats the "1." marker
    later_lines = [l for pg in texts[1:] for l in pg]
    assert any(l == CONTINUATION_TEXT for l in later_lines)
    assert not any(l.startswith('1. word000') for l in later_lines)

    # completeness: every word appears, in order, exactly once, across all pages
    collected = []
    for l in (ln for pg in texts for ln in pg):
        if l == CONTINUATION_TEXT or l == '' or l.startswith('-'):
            continue
        if 'word' in l:
            collected.append(l[3:] if l.startswith('1. ') else l)
    reconstructed = ' '.join(collected).split()
    assert reconstructed == words

def test_pdf_printed_reference_position_independent_of_note_length():
    # rule 1: "the reference never moves" -- whether the note is one word or
    # a hundred, the line carrying the reference lands on the SAME page,
    # because only the FOOTNOTE area's split, never the body's, absorbs overflow.
    def page_of_ref(note_text):
        data = (b'.PL 18' + HARD + ws7_block(0x00) +
                b'Ref line' + ws7_note(0x03, note_text) + b' end.' + HARD +
                b'Two.' + HARD + b'Three.' + HARD + b'Four.' + HARD + b'Five.' + HARD)
        doc = core.parse_ws(data)
        texts = _page_texts(_doc_to_pagelines_local(doc, True))
        return next(i for i, pg in enumerate(texts) if any('Ref line' in l for l in pg))
    from ctrlkd.pdf import _doc_to_pagelines as _doc_to_pagelines_local
    short = page_of_ref(b'Tiny.')
    long_ = page_of_ref(' '.join(f'w{i}' for i in range(200)).encode())
    assert short == 0 and long_ == 0

def test_pdf_printed_last_page_overflow_prints_at_top_no_floor():
    from ctrlkd.pdf import _doc_to_pagelines, FOOTNOTE_SEPARATOR, CONTINUATION_TEXT
    words = [f'word{i:03d}' for i in range(60)]
    data = (b'.PL 12' + HARD +                     # tiny page: cap well under the note's size
            ws7_block(0x00) +
            b'Only line has a note' + ws7_note(0x03, ' '.join(words).encode(), number=0) +
            b' here.' + HARD)
    doc = core.parse_ws(data)
    pages = _doc_to_pagelines(doc, True)
    texts = _page_texts(pages)
    assert len(pages) > 1                          # the note alone can't fit with the body
    # no body text anywhere on the trailing (note-only) pages
    for pg in texts[1:]:
        assert not any('Only line' in l for l in pg)
        assert pg[0] == '' and any(l == FOOTNOTE_SEPARATOR for l in pg)   # block starts at the top
    # completeness again, even across a multi-page spill
    collected = []
    for l in (ln for pg in texts for ln in pg):
        if l == CONTINUATION_TEXT or l == '' or l.startswith('-'):
            continue
        if 'word' in l:
            collected.append(l[3:] if l.startswith('1. ') else l)
    assert ' '.join(collected).split() == words

def test_pdf_printed_endnotes_collect_at_end_with_no_heading():
    from ctrlkd.pdf import _doc_to_pagelines, FOOTNOTE_SEPARATOR
    data = (ws7_block(0x00) + b'Body text has an endnote' +
            ws7_note(0x04, b'The endnote text goes here.', number=0) + b' done.' + HARD)
    doc = core.parse_ws(data)
    pages = _doc_to_pagelines(doc, True)
    texts = _page_texts(pages)
    flat = [l for pg in texts for l in pg]
    assert any(l.strip() == '(1) The endnote text goes here.' for l in flat)
    # endnotes never trigger the footnote-area separator (they don't share
    # its page-bottom mechanism), and get no author-less heading of any kind
    assert not any(l == FOOTNOTE_SEPARATOR for l in flat)
    assert not any('endnote' in l.lower() and l.strip().startswith(('Endnote', 'ENDNOTE'))
                   for l in flat)

def test_pdf_printed_endnotes_numbered_independently_of_footnotes():
    # WordStar has SEPARATE .f#/.e# starting-value commands -- two
    # independent counters, not one shared one. 2 footnotes then 2 endnotes
    # must show endnotes as (1)/(2), not (3)/(4) (the shared-counter bug a
    # previous round of this work had -- caught by cross-checking against
    # the concurrently-built flat emitters, which already got this right).
    data = (ws7_block(0x00) +
            b'a' + ws7_note(0x03, b'First footnote.', number=0) +
            b' b' + ws7_note(0x03, b'Second footnote.', number=1) +
            b' c' + ws7_note(0x04, b'First endnote.', number=0) +
            b' d' + ws7_note(0x04, b'Second endnote.', number=1) + b' e' + HARD)
    doc = core.parse_ws(data)
    from ctrlkd.pdf import _doc_to_pagelines
    pages = _doc_to_pagelines(doc, True)
    flat = [l for pg in _page_texts(pages) for l in pg]
    assert any(l.strip() == '1. First footnote.' for l in flat)
    assert any(l.strip() == '2. Second footnote.' for l in flat)
    assert any(l.strip() == '(1) First endnote.' for l in flat)
    assert any(l.strip() == '(2) Second endnote.' for l in flat)
    assert not any('(3)' in l or '(4)' in l for l in flat)
    # the body reference for footnote 1 and endnote 1 are BOTH a bare "1" --
    # WordStar's own documented ambiguity, resolved by mark style, not number
    ref_line = flat[0]
    assert ref_line.count('1') == 2 and ref_line.count('2') == 2

def test_pdf_printed_footnote_and_endnote_markers_share_the_same_rise():
    # b26 notes wave, Fix 2 (item 18): WS7 gives a footnote marker and an
    # endnote marker the identical superscript treatment (-SCREEN.WS oracle:
    # both inline "1"s are raised the same amount). core.py tags every
    # fnref span 'sup' regardless of note kind (frozenset({'sup', 'fnref'})),
    # so the Printed PDF's own `Ts` (text rise) operator preceding each
    # marker's glyph must match between the two kinds -- pins the oracle's
    # "same treatment" claim directly against the rendered PDF bytes, not
    # just the IR's style set. Already true on main (no production change
    # needed for this one); see the sibling test below for the one real
    # fix this branch's Fix 2 made.
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) +
            b'A footnote' + ws7_note(0x03, b'Footnote text.', number=0) +
            b' and an endnote' + ws7_note(0x04, b'Endnote text.', number=0) +
            b' both on one line.' + HARD)
    doc = core.parse_ws(data)
    stream = emit_pdf(doc, mode='printed')
    rises = [int(m.group(1)) for m in
             re.finditer(rb'(-?\d+) Ts [\d.]+ [\d.]+ Td \(1\) Tj', stream)]
    assert len(rises) == 2, f'expected exactly 2 raised "1" markers, got {rises}'
    assert rises[0] == rises[1] != 0

def test_pdf_printed_note_area_anchors_at_the_page_bottom_on_a_short_page():
    """Finding 2 (b26-print-fidelity-2): a short page's footnote/endnote
    area used to flow-append right after the body -- wherever the body's
    own y happened to end -- landing mid-page. Real WS7 anchors it at the
    page bottom instead (measured: -SCREEN.pcl's "1. Footnote"/"(1)
    Endnote"/dash-rule at PDF y=84/60/108, i.e. top-down 708/732/684;
    LYING.pcl's own single-footnote area lands on the SAME y=84/108 --
    its page is full, so flow-append and bottom-anchor coincide there,
    which is exactly why the gate never caught this). This doc's body is
    two short lines -- nowhere near a full (default) 55-line page -- so a
    flow-appended area would land far above y=108; anchored, it lands
    exactly where WS7 does, at every page-geometry DEFAULT (.mb 8 lines
    -> 84pt reserve, see _printed_notes_reserve_pt)."""
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) +
            b'Short body line has a note' + ws7_note(0x03, b'Footnote text.', number=0) +
            b' and an endnote' + ws7_note(0x04, b'Endnote text.', number=0) +
            b' here.' + HARD)
    doc = core.parse_ws(data)
    pdf = emit_pdf(doc, mode='printed')
    spans = {text: y for _, _, _, x, y, text in _content_spans(pdf)}
    assert spans[b'--------------------'] == 108.0
    assert spans[b'1. Footnote text.'] == 84.0
    assert spans[b'\\(1\\) Endnote text.'] == 60.0


def test_pdf_printed_note_area_anchor_is_a_no_op_on_an_already_full_page():
    """The bottom-anchor override only fires when it would push the area
    DOWN past where sequential flow already puts it -- a page whose body
    already reaches (within one default lead of) the anchor target is
    untouched, which is what keeps LYING.WS's printed PDF byte-identical
    (sha256 unchanged across this branch: see the fidelity_gate.py
    report). Pinned here with a synthetic page sized so the body runs
    right up to the anchor at every page-geometry DEFAULT (cap 55 =
    .pl 66 - .mt 3 - .mb 8): 51 body lines (one carrying the footnote
    ref) leave the 4-line footnote area exactly filling the rest of the
    55-line cap -- the SAME "flow already gets there" case LYING.WS's
    own full pages are in (measured: override computes to exactly 0.0
    here, so the area renders at its natural flow position, 12pt above
    where the bottom-anchor formula alone would put it)."""
    from ctrlkd.pdf import emit_pdf, _printed_cap
    data = (ws7_block(0x00) +
            b'Body line 1 has a note' + ws7_note(0x03, b'Note.', number=0) +
            b' here.' + HARD +
            b''.join(b'Body line %d.' % i + HARD for i in range(2, 52)))
    doc = core.parse_ws(data)
    assert _printed_cap(doc) == 55
    pdf = emit_pdf(doc, mode='printed')
    spans = {text: y for _, _, _, x, y, text in _content_spans(pdf)}
    # natural flow (top 60 + 51 body lines * 12 + this line's own 12 =
    # 96, PDF bottom-origin) -- ONE line short of the 84pt anchor's own
    # target for a 4-line area (108), confirming the override did NOT
    # fire and pull the rule down to the anchor position.
    assert spans[b'--------------------'] == 96.0
    assert spans[b'1. Note.'] == 72.0


def test_doc_to_pagelines_modern_notes_dump_uses_per_kind_labels():
    # b26 notes wave, Fix 2: `_doc_to_pagelines`'s own legacy end-of-document
    # notes dump (superseded for real Modern PDF output by `_modern_streams`,
    # ruling 2026-08-05, but still directly unit-testable) used to renumber
    # every kept note through ONE shared sequential index regardless of
    # kind -- a footnote #1 and an endnote #1 both printed "[1]"/"[2]",
    # disagreeing with every real emitter's own _annotated_notes-based
    # label. Fixed in pdf.py's `_doc_to_pagelines` to match _note_marker/
    # _endnote_marker: "1." for the footnote, "(1)" for the endnote --
    # oracle-verified against -SCREEN.WS. Fails against pre-fix pdf.py
    # (confirmed: pre-fix produces "[1] Foot text."/"[2] End text.").
    from ctrlkd.pdf import _doc_to_pagelines
    data = (ws7_block(0x00) +
            b'a' + ws7_note(0x03, b'Foot text.', number=0) +
            b' b' + ws7_note(0x04, b'End text.', number=0) + b' c' + HARD)
    doc = core.parse_ws(data)
    pages = _doc_to_pagelines(doc, False)
    flat = [l for pg in _page_texts(pages) for l in pg]
    assert any(l.strip() == '1. Foot text.' for l in flat)
    assert any(l.strip() == '(1) End text.' for l in flat)
    assert not any(l.strip() in ('[1] Foot text.', '[2] End text.') for l in flat)

def test_footnote_endnote_number_start_dot_commands():
    # .F#/.E# (WordStar 7.0 file format spec): set the starting numbering
    # value -- the hook emit.py's per-kind numbering already reads.
    data = (b'.F# 5' + HARD + b'.E# 10' + HARD +
            ws7_block(0x00) + b'x' + ws7_note(0x03, b'Foot.', number=0) +
            b' y' + ws7_note(0x04, b'End.', number=0) + b' z' + HARD)
    doc = core.parse_ws(data)
    assert doc.meta['footnote_number_start'] == 5
    assert doc.meta['endnote_number_start'] == 10
    from ctrlkd.pdf import _doc_to_pagelines
    pages = _doc_to_pagelines(doc, True)
    flat = [l for pg in _page_texts(pages) for l in pg]
    assert any(l.strip() == '5. Foot.' for l in flat)
    assert any(l.strip() == '(10) End.' for l in flat)

def test_footnote_endnote_number_start_absent_defaults_to_one():
    doc = core.parse_ws(b'.PL 66' + HARD + b'Body.' + HARD)
    assert 'footnote_number_start' not in doc.meta
    assert 'endnote_number_start' not in doc.meta

def test_pdf_printed_annotation_uses_its_own_tag_as_marker():
    from ctrlkd.pdf import _doc_to_pagelines
    data = (ws7_block(0x00) + b'Body text has an annotation' +
            ws7_annotation_with_tag(dot_lines=[b'.. internal remark'],
                                    text=b'Annotation body text.', tag_text=b'AC1') +
            b' done.' + HARD)
    doc = core.parse_ws(data)
    assert doc.notes[0].kind == 'annotation' and doc.notes[0].tag == 'AC1'
    pages = _doc_to_pagelines(doc, True)
    flat = [l for pg in _page_texts(pages) for l in pg]
    assert any(l.strip() == 'AC1 Annotation body text.' for l in flat)

def test_pdf_printed_pl_geometry_changes_page_capacity():
    # Task 1 x Task 2: a Legal-length file should hold noticeably more
    # lines per printed page than the same content forced small by .pl.
    from ctrlkd.pdf import _printed_cap
    letter_doc = core.parse_ws(b'.PL 66' + HARD + b'x' + HARD)
    small_doc = core.parse_ws(b'.PL 12' + HARD + b'x' + HARD)
    assert _printed_cap(small_doc) < _printed_cap(letter_doc)

def test_pdf_printed_no_page_ever_exceeds_its_capacity():
    # the one invariant everything else rests on: body lines already
    # committed this page must count against how much footnote-area room
    # is left, not just against the floor -- a ceiling that only knows
    # cap-FOOTNOTE_FLOOR (and ignores how many body lines are already on
    # the page) can admit MORE footnote content than the page has room for
    # once even one body line has been placed on a terminal page.
    from ctrlkd.pdf import _doc_to_pagelines, _printed_cap
    words = [f'word{i:03d}' for i in range(60)]
    data = (b'.PL 12' + HARD +
            b'.MT 3' + HARD + b'.MB 3' + HARD +   # capacity 12-3-3=6, margins stated
            ws7_block(0x00) +
            b'Only line has a note' + ws7_note(0x03, ' '.join(words).encode(), number=0) +
            b' here.' + HARD)
    doc = core.parse_ws(data)
    cap = _printed_cap(doc)
    pages = _doc_to_pagelines(doc, True)
    assert all(len(pg) <= cap for pg in pages), [len(pg) for pg in pages]


# --- CLI surface -----------------------------------------------------------
# The library had 89 passing tests while `ctrl-kd --diagnose` crashed on an
# import error: every test exercised the API, none ran main(). These cover the
# thing a user actually types.

def _run_cli(tmp_path, data, *args):
    from ctrlkd import cli
    src = tmp_path / 'SAMPLE.WS'
    src.write_bytes(data)
    out = tmp_path / 'out.txt'
    rc = cli.main([str(src), '-t', 'text', '-o', str(out), *args])
    return rc, (out.read_text() if out.exists() else '')

def test_cli_converts_and_writes_a_file(tmp_path):
    rc, text = _run_cli(tmp_path, four_kind_data())
    assert rc == 0
    assert 'Footnote text.' in text

def test_cli_default_includes_notes_but_never_comments(tmp_path):
    _, text = _run_cli(tmp_path, four_kind_data())
    assert 'Footnote text.' in text and 'Endnote text.' in text
    assert 'Annotation text' in text
    assert 'Comment text.' not in text     # WordStar never printed comments

def test_cli_no_notes_suppresses_all_note_kinds(tmp_path):
    _, text = _run_cli(tmp_path, four_kind_data(), '--no-notes')
    for gone in ('Footnote text.', 'Endnote text.', 'Annotation text', 'Comment text.'):
        assert gone not in text

def test_cli_comments_flag_opts_them_in(tmp_path):
    _, text = _run_cli(tmp_path, four_kind_data(), '--comments')
    assert 'Comment text.' in text
    assert 'Footnote text.' in text        # and does not displace the defaults

def test_cli_diagnose_emits_valid_json_with_note_counts_and_page(tmp_path, capsys):
    import json
    from ctrlkd import cli
    src = tmp_path / 'SAMPLE.WS'
    src.write_bytes(four_kind_data())
    assert cli.main([str(src), '--diagnose']) in (0, None)
    info = json.loads(capsys.readouterr().out)
    assert info['notes'] == {'footnote': 1, 'endnote': 1,
                             'annotation': 1, 'comment': 1}
    assert info['page']['size_name'] == 'Letter'
    assert info['page']['size_source'] == 'default'


# --- regressions found by the pre-publish audit ------------------------------

def test_printed_pdf_terminates_on_tiny_page_with_wrapping_footnote():
    """A small .pl plus a footnote that wraps used to hang forever: a split
    prepends a continuation line, so at room==1 each pass admitted one line and
    added one back. Real WordStar files used small page lengths (labels, index
    cards), so this was reachable, not exotic."""
    from ctrlkd import pdf
    words = ' '.join(f'w{i}' for i in range(30)).encode()
    data = (b'.PL 6\r\n' + ws7_block(0x00) + b'Ref' +
            ws7_note(0x03, words, number=0) + b' end.\r\n')
    doc = core.parse(data)
    pages = pdf._doc_to_pagelines(doc, True)      # must return, not spin
    assert len(pages) < 200                        # bounded, not runaway
    body = '\n'.join(''.join(t for t, _ in ln) for p in pages for ln in p)
    assert 'w29' in body                           # and no text was lost

@pytest.mark.parametrize('fmt', ['text', 'markdown', 'html', 'rtf'])
def test_stray_sentinel_byte_in_body_does_not_crash(fmt):
    """SENT_FNREF is a raw 0x07, so a literal 0x07 in a document body is
    miscounted as a note reference with no note behind it. That must degrade to
    text, not raise IndexError."""
    data = ws7_block(0x00) + b'Body with a stray byte: \x07 right there.' + HARD
    out = getattr(emit, f'emit_{fmt}')(core.parse(data))
    assert 'right there.' in out

def test_repeated_wordtsar_spacing_dot_commands_first_occurrence_wins():
    """The first-wins guard checked key names the parser never writes, so the
    last occurrence silently won instead of the first."""
    data = b'.PSA 1\r\n.PSA 99\r\n' + ws7_block(0x00) + b'Body.' + HARD
    assert core.parse(data).meta['space_after_lines'] == 1.0


# ---------------------------------------------------------------- A2: blank lines are content

def test_ws4_leading_blank_lines_survive_to_pagelines():
    """Jon's chapter drop: extra returns before the first text are AUTHORIAL
    layout and must print. WordStar's own rule (WS7 Reference, "Page Layout"):
    `.sb` defaults OFF, so blank lines at the top of a page DO print; only SOFT
    blanks created by line spacing > 1 are suppressed, and only at a page top.

    Shape taken from a real WS4 document: a dot command, then soft/soft/
    hard/hard/soft blank terminators, then the first text.
    """
    from ctrlkd.pdf import _doc_to_pagelines
    data = (b'.op' + HARD + SOFT + SOFT + HARD + HARD + SOFT
            + ws4_text('In 1867 and 1868, the government made its last treaties.') + HARD)
    pages = _doc_to_pagelines(core.parse_ws(data), True)
    blanks = 0
    for line in pages[0]:
        if ''.join(t for t, _ in line).strip():
            break
        blanks += 1
    assert blanks >= 4, f'chapter drop lost: {blanks} leading blank lines, expected >= 4'


def test_ws4_double_spacing_survives_to_pagelines():
    """`.ls 2` materialises its filler as SOFT blank lines in the file (WS7
    Reference: "when you use line spacing, the blank lines become part of the
    file"). A real double-spaced WS4 essay is stored this way -- text lines
    interleaved with soft blanks -- and collapsing them destroys the document's
    vertical rhythm and its page count.
    """
    from ctrlkd.pdf import _doc_to_pagelines
    body = b''
    for n in range(6):
        body += ws4_text(f'Line number {n} of the double spaced body text.') + SOFT + SOFT
    pages = _doc_to_pagelines(core.parse_ws(body), True)
    pat = ''.join('T' if ''.join(t for t, _ in ln).strip() else '.' for ln in pages[0])
    assert pat.startswith('T.T.T.'), f'double spacing collapsed: {pat[:20]!r}'


# ---------------------------------------------------------------- release eras

def test_era_table_drives_the_version_behaviour():
    """Version differences live in ONE table, not scattered inline checks, so a
    new release (WS3, WS6) is an entry rather than a hunt through the parser."""
    from ctrlkd.core import era_for, ERAS
    assert era_for('ws4').high_bit_wordwrap is True     # microjustify flags
    assert era_for('ws5+').high_bit_wordwrap is False   # high byte = cp437 char
    assert era_for('ws4').has_notes is False            # notes arrive at 5.5/6.0
    assert era_for('ws5+').has_notes is True
    assert era_for('ws4').has_sb is False               # .sb absent pre-WS5
    assert era_for('ws5+').has_sb is True
    assert era_for('ws3').pc_default == 33              # changed to 28 in WS4
    assert era_for('ws4').pc_default == 28
    # an unknown variant must not strip high bits: that would silently destroy
    # extended characters, which is the worst available failure
    assert era_for('ws9-from-the-future').high_bit_wordwrap is False
    # ...but the fallback is a guess about ENCODING and nothing more. 'binary' is
    # a variant detect() actually returns, so it gets its own row rather than
    # inheriting ws5+ -- see the next test for what inheriting it destroyed.
    assert era_for('binary').symmetric_blocks is False
    assert era_for('binary').high_bit_wordwrap is False


def test_binary_variant_does_not_get_symmetric_block_parsing():
    """Regression: 'binary' inherited the ws5+ fallback, which switched symmetric
    blocks on for a file detect() had declined to identify. _symmetric_blocks
    treats EVERY 0x1D as a block-start marker, so an escaped 0x1D swallowed the
    rest of the line.

    Found by the Swift port's extended-escape test, which had no counterpart
    here. All five escaped control bytes must survive identically."""
    from ctrlkd.core import CP437_GRAPHICS
    for b in (0x01, 0x1C, 0x1D, 0x1E, 0x1F):
        data = b'A' + bytes([0x1B, b]) + b'B' + HARD
        doc = core.parse_ws(data)
        assert doc.meta['variant'] == 'binary'
        text = ''.join(s.text for s in doc.blocks[0].lines[0].spans)
        # the escaped byte survives as its cp437 GLYPH (☺∟↔▲▼) -- WSFORMAT:
        # the wrapped byte is "a character to display", and for the control
        # range that display is IBM's graphics, never the control action.
        # Nothing is swallowed either way.
        assert text == 'A' + CP437_GRAPHICS[b] + 'B', \
            f'escaped {b:#04x} was not passed through'


def test_parse_records_the_era_it_used():
    """The era is reported, so a caller can see which rules were applied rather
    than having to re-derive them."""
    data = ws4_text('Some ordinary body text here.') + HARD
    assert core.parse_ws(data).meta['era'] in ('ws4', 'ws5+')


# ---------------------------------------------------------------- .cp

def _cp_doc(cp_before, n, total=60):
    """Numbered lines with a `.cp n` inserted before line `cp_before`."""
    out = []
    for i in range(1, total + 1):
        if i == cp_before:
            out.append(f'.cp {n}')
        out.append(f'LINE {i:03d} ' + '-' * 40)
    return ('\r\n'.join(out) + '\r\n').encode()


def test_cp_does_not_break_when_there_is_room():
    """`.cp` exists so a heading is NOT stranded at a page bottom. Firing it
    unconditionally inserts the very break it was there to prevent -- which is
    what the old code did, treating .CP exactly like .PA."""
    from ctrlkd.pdf import _doc_to_pagelines
    pages = _doc_to_pagelines(core.parse_ws(_cp_doc(20, 10)), True)
    # 36 of 55 lines remain at line 20: plenty of room, no break there.
    first = [''.join(t for t, _ in ln) for ln in pages[0]]
    assert any('LINE 020' in l for l in first), 'line 20 was pushed off page 1'
    assert any('LINE 055' in l for l in first), 'page 1 should still hold 55 lines'


def test_cp_breaks_when_short_of_room():
    from ctrlkd.pdf import _doc_to_pagelines
    pages = _doc_to_pagelines(core.parse_ws(_cp_doc(50, 10)), True)
    first = [''.join(t for t, _ in ln) for ln in pages[0]]
    # 6 of 55 remain at line 50 -- fewer than 10, so it breaks BEFORE line 50
    assert any('LINE 049' in l for l in first)
    assert not any('LINE 050' in l for l in first), '.cp did not break'


def test_cp_boundary_is_strict():
    """Measured on WordStar 4 (2026-08-03): with EXACTLY n lines remaining it
    does not break -- the test is `remaining < n`, not `<=`."""
    from ctrlkd.pdf import _doc_to_pagelines
    pages = _doc_to_pagelines(core.parse_ws(_cp_doc(46, 10)), True)
    first = [''.join(t for t, _ in ln) for ln in pages[0]]
    assert any('LINE 046' in l for l in first), 'exactly n remaining must NOT break'
    assert any('LINE 055' in l for l in first)


# ---------------------------------------------------------------- dropped codes

def test_overprint_is_reported_not_silently_dropped():
    """^H (0x08) is how WordStar-era authors composed accented letters and ad-hoc
    symbols: type, backspace, overtype. Discarding it silently loses content with
    no trace at all -- unlike its neighbours, which at least get counted. The
    project's own rule is never to go quiet."""
    data = ws4_text('cafe') + bytes([0x08]) + ws4_text("'") + HARD
    doc = core.parse_ws(data)
    assert '0x08' in doc.meta['unknown_codes'], \
        'overprint vanished without even a diagnostic'


def test_fnref_sentinel_cannot_collide_with_a_real_wordstar_code():
    """The note-reference sentinel must be a byte a document CANNOT contain.
    It was 0x07 -- ^G, phantom rubout: rare by 1990 but real, and a literal one
    in a WS5+ body was read as a note reference. Out of range degraded
    gracefully; an in-range collision silently attached the WRONG footnote to
    body text."""
    from ctrlkd.core import SENT_FNREF, WS_TOGGLES, WS_DROP
    assert SENT_FNREF not in WS_TOGGLES, 'sentinel collides with a style toggle'
    assert SENT_FNREF != 0x07, 'sentinel is back on ^G, which documents can hold'
    # and a literal ^G in a body must not be mistaken for a reference
    doc = core.parse_ws(ws4_text('before') + bytes([0x07]) + ws4_text('after') + HARD)
    assert 'before' in doc.blocks[0].lines[0].text()


# ---------------------------------------------------------------- headers/footers

def _hf_doc(n=120):
    out = ['.he HEADER-TEXT PAGE #', '.fo FOOTER-TEXT PAGE #']
    out += [f'LINE {i:03d} ' + '-' * 40 for i in range(1, n + 1)]
    return ('\r\n'.join(out) + '\r\n').encode()


def test_head_foot_text_reaches_the_ir():
    """`.he`/`.fo` are fully-documented dot commands that had NO field anywhere
    in the IR: the text was captured only in the dot_commands diagnostic and
    discarded by every emitter. The reserved SPACE was honoured; the content
    was not."""
    doc = core.parse_ws(b'.he TOP\r\n.h2 TOP2\r\n.fo BOTTOM\r\nbody\r\n')
    assert doc.headers == {1: 'TOP', 2: 'TOP2'}
    assert doc.footers == {1: 'BOTTOM'}


def test_head_foot_land_where_wordstar_puts_them():
    """Header placement MEASURED on WordStar 4 (2026-08-03): header on page
    line 0, footer on line 60 (.pl - .mb + .fm) -- `_running_ops` positions
    both independently of `_printed_top` and is unchanged. Body start was
    ALSO measured at line 3 (.mt alone) on WS4 at the time, but that reading
    is now SUPERSEDED by real WS7 evidence (round 26, fidelity_gate.py
    Finding A): -README (ws7-prints/v1), a genuine WS7 capture with a `.h1`
    header, prints its body at line 5 (.mt 3 + .hm 2) on every headered page,
    the same offset headerless WS7 documents already measure -- `_printed_top`
    reserves `.hm` unconditionally now. 55 body lines per page is capacity
    (`_printed_cap`), unaffected by where line 0 sits. Asserted in lines, not
    points, so it stays readable."""
    import re
    from ctrlkd.pdf import emit_pdf
    pdf = emit_pdf(core.parse_ws(_hf_doc()), 'printed')
    body = re.search(rb'stream\r?\n(.*?)\r?\nendstream', pdf, re.S).group(1)
    rows = [(float(y), t.decode('latin-1'))
            for _, y, t in re.findall(rb'([\d.]+) ([\d.]+) Td \((.*?)\) Tj', body)]
    line_of = lambda y: round((792 - y - 12) / 12)
    hdr = [line_of(y) for y, t in rows if 'HEADER-TEXT' in t]
    txt = [line_of(y) for y, t in rows if t.strip().startswith('LINE')]
    ftr = [line_of(y) for y, t in rows if 'FOOTER-TEXT' in t]
    assert hdr == [0], f'header should sit on page line 0, got {hdr}'
    assert txt[0] == 5, f'body should start at .mt+.hm = 5, got {txt[0]}'
    assert len(txt) == 55, f'55 body lines per page, got {len(txt)}'
    assert ftr == [60], f'footer at .pl-.mb+.fm = 60, got {ftr}'


def test_hash_becomes_the_page_number():
    import re
    from ctrlkd.pdf import emit_pdf
    pdf = emit_pdf(core.parse_ws(_hf_doc()), 'printed')
    assert sorted(set(re.findall(rb'HEADER-TEXT PAGE (\d)', pdf))) == [b'1', b'2', b'3']


def test_op_does_not_suppress_a_hash_in_a_header_or_footer():
    """WSFORMAT.TXT: ".OP  Omit page number.  At print time no page numbers are
    printed UNLESS THE '#' HAS BEEN USED IN FOOTERS OR HEADERS."

    `.op` suppresses the AUTOMATIC page number -- the one `.pc` positions. A `#`
    the author put in a running head is the spec's explicit EXEMPTION, not the
    target.

    This test asserted the opposite until 2026-08-03, and its own docstring quoted
    the exempting clause while doing so. It therefore PASSED against a backwards
    implementation and confirmed it -- a test written from the same misreading as
    the code cannot catch the misreading. The spec caught it; the test could not.
    """
    import re
    from ctrlkd.pdf import emit_pdf
    doc = core.parse_ws(b'.op\r\n' + _hf_doc(10))
    assert re.search(rb'HEADER-TEXT PAGE \d', emit_pdf(doc, 'printed'))


def test_op_and_pg_are_a_stateful_pair():
    """".PG  Number pages ... Usually used to restore page numbering after being
    turned off with .OP." Front matter turns it off, the body turns it back on --
    so a one-way flag is wrong. Only the AUTOMATIC number is affected."""
    assert core.parse_ws(b'.op\r\nT.\r\n').meta['formatting']['auto_page_numbers'] is False
    assert core.parse_ws(b'.op\r\n.pg\r\nT.\r\n').meta['formatting']['auto_page_numbers'] is True
    # never mentioned -> not recorded at all, same provenance rule as the rest
    assert 'auto_page_numbers' not in core.parse_ws(b'T.\r\n').meta['formatting']


def test_default_mode_is_printed():
    """Jon's ruling 2026-08-03: 'the CLI ships now and with the app. The CLI
    decisions are the app decisions.' Soft Return.app opens documents in Printed
    style; the CLI defaulted to Modern. One product, two defaults.

    This is a BREAKING change -- every script that omitted --mode changes output
    -- and is why the release is a major version."""
    import subprocess, sys as _s
    help_text = subprocess.run([_s.executable, '-c',
        'import sys; sys.argv=["ctrl-kd","--help"];'
        'from ctrlkd.cli import main; main()'],
        capture_output=True, text=True).stdout
    assert 'DEFAULT' in help_text and 'printed:' in help_text, \
        'the CLI help no longer states printed as the default'
    # and the library agrees with the CLI, so a caller who omits mode gets the
    # same answer as someone at a shell
    md = emit.emit_markdown(core.parse_ws(make_prose()))
    assert md.lstrip().startswith('```'), 'library default is not printed'


def _paranum(level, *counters):
    """A 0x0D block body per WSFORMAT.TXT: two level-move bytes, a 1-BASED level
    byte, then eight 0-BASED level counters as words, then a 31-byte format
    string. Binary throughout -- there is no text in it."""
    body = bytes([0, 0, level])
    for n in range(8):
        body += (counters[n] if n < len(counters) else 0).to_bytes(2, 'little')
    return body + bytes(31)


def test_paragraph_number_is_computed_from_its_level_counters():
    """Type 0x0D is WordStar's AUTOMATIC outline/legal numbering (`.p#`), and the
    block is BINARY: level counters, 0 based, not a rendered string.

    This test used to feed the block `b'2.1.3'` as literal text and assert that
    text came back -- the same misunderstanding the code had, so it passed against
    an implementation that scanned for printable bytes. That implementation
    emitted NOTHING for real archive blocks (the counters are below 0x20) while
    its commit claimed to have recovered the numbers, and would fabricate a number
    from any counter that landed in the printable range: a level byte of '2'
    (0x32 = 50) yields "12591.13103".

    Level 3 with counters 1, 0, 2 renders "2.1.3"."""
    # Enough ordinary text that `detect` calls this ws5+ rather than binary -- the
    # 31-byte format field is all NULs, and a short fixture is mostly zeroes.
    data = ws7_block(0x00) + ws7_block(0x0D, _paranum(3, 1, 0, 2)) \
        + b' body text here, with enough ordinary prose that detection is not in doubt.' \
        + HARD
    txt = emit.emit_text(core.parse_ws(data), 'printed')
    assert '2.1.3' in txt, txt


def test_a_paragraph_number_never_fabricates_digits_from_binary():
    """The failure mode the printable-byte scan had: counters that happen to sit
    in the ASCII range must not become characters."""
    txt = emit.emit_text(core.parse_ws(
        ws7_block(0x00) + ws7_block(0x0D, _paranum(1, 0))
        + b' text, with enough ordinary prose that detection is not in doubt.'
        + HARD), 'printed')
    assert '1 text' in txt, txt          # level 1, counter 0 -> "1"


def test_index_item_phrase_survives():
    """Type 0x0E carries an inline indexed PHRASE. WordStar prints the phrase in
    the body -- the index ENTRY is the non-printing part -- so dropping the block
    risks losing text outright."""
    data = (ws7_block(0x00) + ws7_block(0x0E, b'\x00\x00' + b'Chandrasekhar') +
            b' was an astrophysicist' + HARD)
    txt = emit.emit_text(core.parse_ws(data), 'printed')
    assert 'Chandrasekhar' in txt, 'the indexed phrase was lost'


def test_pagelines_carry_the_soft_flag():
    """`Line.soft` has existed since 2.0.0 but never reached the PAGINATED
    representation, so anything working from pagelines could not tell WordStar's
    own word wrap (and the filler `.ls > 1` materialises) from the author
    pressing Return. That distinction carries authorial intent at a page top,
    and Soft Return.app needs it for Show Invisibles."""
    from ctrlkd.pdf import _doc_to_pagelines, PageLine
    long_line = b'the quick brown fox jumps over the lazy dog and keeps running onward'
    doc = core.parse_ws(long_line + SOFT + b'continuation of that sentence' + HARD)
    page = _doc_to_pagelines(doc, True)[0]
    assert isinstance(page[0], PageLine)
    assert page[0].soft is True, 'a wrapped line lost its soft flag'
    assert page[1].soft is False, 'a hard-terminated line was marked soft'


def test_pagelines_keep_soft_hard_of_a_chapter_drop():
    """The drop is SOFT/SOFT/HARD/HARD/SOFT in a real file: the hard blanks are
    the author's own returns, the soft ones are line-spacing filler. WordStar
    treats them differently at a page top, so the distinction has to survive."""
    from ctrlkd.pdf import _doc_to_pagelines
    data = (b'.op' + HARD + SOFT + SOFT + HARD + HARD + SOFT +
            ws4_text('First line of the chapter.') + HARD)
    blanks = [ln.soft for ln in _doc_to_pagelines(core.parse_ws(data), True)[0]
              if not ''.join(t for t, _ in ln).strip()]
    assert blanks[:5] == [True, True, False, False, True]


def test_pageline_is_still_a_plain_list_for_existing_callers():
    """Deliberately a list subclass: every existing consumer iterates a pageline
    as a list of (text, styles) segments and must keep working untouched."""
    from ctrlkd.pdf import _doc_to_pagelines
    page = _doc_to_pagelines(core.parse_ws(make_prose()), True)[0]
    assert isinstance(page[0], list)
    assert all(isinstance(seg, tuple) and len(seg) == 2 for seg in page[0])


def test_dot_commands_have_a_position():
    """`dot_commands` is a flat list with no anchor, so a consumer that wants to
    SHOW a dot command in place -- Soft Return.app's Show Invisibles -- had
    nowhere to put the mark. (block, line) is the coarsest anchor that is
    actually stable: it survives reflow, which a byte offset does not."""
    doc = core.parse_ws(b'.op\r\nfirst para line\r\n\r\n.cp 5\r\nsecond para\r\n')
    pos = doc.meta['dot_positions']
    assert [t for _, _, t in pos] == ['.op', '.cp 5']
    assert pos[0][:2] == (0, 0), 'a leading dot command should anchor at the start'
    assert pos[1][0] > pos[0][0], 'the second command is in a later block'
    # the flat list still exists for callers that only want to know what was seen
    assert doc.meta['dot_commands'] == ['.op', '.cp 5']


def test_tab_indent_does_not_look_like_an_authors_indent():
    """`lines_pass` treats a next line starting with a space as a DELIBERATE
    break -- a poem, a block quote. Sound, but `_symmetric_blocks` expands
    WordStar's type-9 TAB sequences into literal spaces before the classifier
    runs, and WordStar re-stamps a left indent onto every wrapped line. So every
    machine-wrapped line looked author-indented, and whole paragraphs never
    reflowed in Modern: they rendered as physical lines with the wrong margins.

    Tested at `lines_pass` directly, because that is where the decision is made
    and the tab offsets are its input. Offsets are recorded in the CLEANED
    stream rather than injected as a sentinel byte -- the day's other sentinel
    (0x07) collided with a real WordStar code."""
    a = b'the quick brown fox jumps over the lazy dog and it runs onward'
    b = b'     continuing the very same sentence with no real break at all'
    data = a + SOFT + b + HARD

    # No tab information: the leading spaces read as the author's -> deliberate
    plain = core.lines_pass(data)[0]
    assert plain[0][1] == 'line'

    # Told that the second line's indent came from a TAB -> word wrap
    marked = core.lines_pass(data, {len(a) + len(SOFT)})[0]
    assert marked[0][1] == 'wrap', \
        'a tab-indented wrapped line was still read as a deliberate break'


def test_a_typed_indent_is_still_a_deliberate_break():
    """The rule must keep working for what it was FOR: an indent the author
    actually typed still marks a deliberate break, or every poem reflows into
    prose. The poem corpus is the acceptance gate for any change here."""
    poem = (b'     A short poem line,' + SOFT +
            b'     another short line.' + HARD)
    assert core.lines_pass(poem)[0][0][1] == 'line'


def test_pn_sets_the_starting_page_number():
    """`.pn n` numbers the page it appears on, so a chapter file in a larger
    manuscript starts where the previous one stopped. MEASURED on WordStar 4
    (2026-08-03): `.pn 7` on a three-page document numbers the pages 7, 8, 9 --
    in both the header's `#` and the footer's."""
    import re
    from ctrlkd.pdf import emit_pdf
    body = '\r\n'.join(f'LINE {i:03d} ' + '-' * 40 for i in range(1, 121))
    doc = core.parse_ws(('.pn 7\r\n.he HEADER PAGE #\r\n' + body + '\r\n').encode())
    assert doc.meta['page']['pn_start'] == 7
    assert doc.meta['page']['pn_source'] == 'file'
    nums = sorted(set(re.findall(rb'HEADER PAGE (\d+)', emit_pdf(doc, 'printed'))))
    assert nums == [b'7', b'8', b'9']


def test_page_number_defaults_to_one_and_says_so():
    doc = core.parse_ws(b'.he H #\r\nbody text here\r\n')
    assert doc.meta['page']['pn_start'] == 1
    assert doc.meta['page']['pn_source'] == 'default'


def test_pc_is_recorded_but_does_not_move_a_hash_in_a_footer():
    """MEASURED on WordStar 4: `.pc 40` did NOT move a `#` placed in a footer --
    it stayed at the `.po` offset. `.pc` positions the AUTOMATIC page number,
    the one WordStar prints on its own; a `#` an author puts in a header or
    footer prints where they put it. Two separate mechanisms, and conflating
    them would move text the author positioned deliberately."""
    import re
    from ctrlkd.pdf import emit_pdf
    body = '\r\n'.join(f'LINE {i:03d}' for i in range(1, 60))
    doc = core.parse_ws(('.pc 40\r\n.fo #\r\n' + body + '\r\n').encode())
    assert doc.meta['page']['pc_col'] == 40
    pdf = emit_pdf(doc, 'printed')
    xs = {float(x) for x, _, t in
          re.findall(rb'([\d.]+) ([\d.]+) Td \((.*?)\) Tj', pdf) if t.strip() == b'1'}
    assert xs and min(xs) < 100, '.pc must not reposition an authored # in a footer'


def test_print_stream_paragraphs_stay_separated_in_modern_layout():
    """A print stream's ONLY paragraph separation is the author's blank line.

    Once blank lines became content (2026-08-03) an entire print stream is one
    block, so the Modern layout's "one structural blank per block" fired exactly
    ONCE for the whole document and every paragraph ran together in the PDF.
    emit_text kept its blanks and _doc_to_pagelines did not, which is how the two
    silently disagreed. Found by the Swift port.
    """
    from ctrlkd.pdf import _doc_to_pagelines
    data = b''.join(b'Paragraph %d here.\r\n\r\n' % i for i in range(4))
    doc = core.parse(data)
    assert doc.meta['variant'] == 'printstream'          # the test's own premise
    page = _doc_to_pagelines(doc, False)[0]
    text = [''.join(t for t, _ in ln) for ln in page]
    assert text == ['Paragraph 0 here.', '', 'Paragraph 1 here.', '',
                    'Paragraph 2 here.', '', 'Paragraph 3 here.'], text


def test_hard_blanks_do_not_double_space_a_block_that_ends_with_one():
    """The other half: a WS4 document whose blank lines END each block already
    gets a structural blank from the Modern layout. Emitting the author's blank
    as well double-spaced every paragraph ([52, 26] where [54] was right), so
    hard blanks are emitted only BETWEEN content, never trailing."""
    from ctrlkd.pdf import _doc_to_pagelines, LINES_MODERN
    n = (LINES_MODERN - 2) // 2
    data = b''.join(ws4_text('Paragraph %d here today.' % i) + HARD + HARD
                    for i in range(n))
    data += ws4_text('This final paragraph is deliberately long enough that the '
                     'wrap test must break it across two physical lines.') + HARD
    assert [len(pg) for pg in _doc_to_pagelines(core.parse(data), False)] == [LINES_MODERN]


# ------------------------------------------------- Category C: formatting state

def test_oc_centering_is_stateful_and_stamps_its_blocks():
    """C16. `.oc on`/`.oc off` bracket individual headings inside otherwise flush
    text -- 17 files in the WS7 archive do exactly this -- so the state has to be
    stamped per block, not resolved once per document."""
    doc = core.parse_ws(b'Normal.\r\n.oc on\r\nCentred heading\r\n.oc off\r\nNormal again.\r\n')
    assert [b.align for b in doc.blocks] == ['left', 'center', 'left']


def test_oj_takes_c_and_r_not_just_on_off():
    """C17. The manual leads with on/off; the archive really uses `.oj r` and
    `.oj c` as well, so all four forms are read."""
    assert core.parse_ws(b'.oj r\r\nText.\r\n').blocks[0].align == 'right'
    assert core.parse_ws(b'.oj c\r\nText.\r\n').blocks[0].align == 'center'
    assert core.parse_ws(b'.oj on\r\nText.\r\n').blocks[0].align == 'justify'
    assert core.parse_ws(b'.oj off\r\nText.\r\n').blocks[0].align == 'left'


def test_centering_wins_over_justification():
    """WordStar centres the line whatever the justification setting says, which is
    what lets the archive's `.oc on`/`.oc off` pairs sit inside justified text."""
    doc = core.parse_ws(b'.oj on\r\n.oc on\r\nCentred.\r\n')
    assert doc.blocks[0].align == 'center'


def test_aw_off_marks_a_block_as_hand_placed():
    """C23. With word wrap off the author is positioning lines by hand, so a
    reflowing consumer must not re-wrap them."""
    doc = core.parse_ws(b'.aw off\r\nHand placed.\r\n')
    assert doc.blocks[0].wrap is False
    assert core.parse_ws(b'Ordinary.\r\n').blocks[0].wrap is True


def test_pr_orientation_uses_the_syntax_files_actually_use():
    """C18. `.pr or=l`, not a bare argument -- 18 archive files set landscape this
    way, and every one of them was rendering portrait with no diagnostic."""
    assert core.parse_ws(b'.pr or=l\r\nT.\r\n').meta['formatting']['orientation'] == 'landscape'
    assert core.parse_ws(b'.pr or=p\r\nT.\r\n').meta['formatting']['orientation'] == 'portrait'
    # an unrelated `.pr` form must not invent an orientation
    assert 'orientation' not in core.parse_ws(b'.pr profile-edit\r\nT.\r\n').meta['formatting']


def test_sr_roll_reads_fractions_points_and_bare_48ths():
    """C22. All four forms appear in the archive."""
    def roll(arg):
        return core.parse_ws(b'.sr ' + arg + b'\r\nT.\r\n').meta['formatting'].get('sub_super_roll_48')
    assert roll(b'3') == 3.0                 # bare = 48ths, WordStar's own unit
    assert roll(b'3/48"') == 3.0
    assert roll(b'4/48i') == 4.0
    assert roll(b'0') == 0.0                 # a real value: do not shift at all
    assert abs(roll(b'6pt') - 4.0) < 1e-9    # 6/72in = 4/48in


def test_formatting_records_only_what_the_file_set():
    """Same provenance rule as the page geometry: a consumer must be able to tell
    'the author asked for portrait' from 'nobody said'."""
    assert core.parse_ws(b'Just text.\r\n').meta['formatting'] == {}
    flags = core.parse_ws(b'.ul on\r\n.ps off\r\n.kr on\r\n.sb on\r\nT.\r\n').meta['formatting']
    assert flags == {'underline_blanks': True, 'proportional': False,
                     'kerning': True, 'suppress_blanks': True}


def test_centering_actually_renders_in_every_format_that_can_show_it():
    """C16/C17 -- the half that was missing. The dot commands were parsed and
    recorded and then had no effect anywhere: a centred heading came out flush
    left in text, HTML, RTF and PDF alike. That was a gap, not a decision."""
    from ctrlkd.emit import emit_text, emit_html, emit_rtf
    src = b'.oc on\r\nCentred.\r\n.oc off\r\n.oj on\r\nJustified body.\r\n'
    doc = core.parse_ws(src)
    doc.meta['variant'] = 'ws4'                  # the reflowing path, not <pre>

    text = emit_text(doc, mode='modern')
    centred = [l for l in text.split('\n') if 'Centred.' in l][0]
    assert centred.startswith(' '), 'centred line was not indented'
    assert centred.strip() == 'Centred.'

    html = emit_html(doc, mode='modern')
    # round 20 (slate item 4): centered units get tight line-height too.
    assert '<p style="text-align:center;line-height:1.15">' in html
    assert '<p style="text-align:justify">' in html

    rtf = emit_rtf(doc, mode='modern')
    assert r'\qc ' in rtf and r'\qj ' in rtf


def test_left_aligned_documents_are_byte_identical_to_before():
    """WordStar's default is flush left, so a document that never touches
    `.oc`/`.oj` must emit exactly what it always did -- no stray style attribute,
    no stray RTF control."""
    from ctrlkd.emit import emit_html, emit_rtf
    doc = core.parse_ws(ws4_text('Just ordinary text.') + HARD)
    assert 'text-align' not in emit_html(doc, mode='modern')
    assert r'\qc' not in emit_rtf(doc, mode='modern')
    assert r'\ql' not in emit_rtf(doc, mode='modern')


def test_justify_is_not_faked_with_padding_in_plain_text():
    """WordStar justifies by widening the spaces it already has. Padding a plain
    text rendering to a hard column would fabricate whitespace the author never
    typed, so left and justify render identically there -- and the distinction
    survives in the IR for the formats that can express it."""
    from ctrlkd.emit import emit_text
    doc = core.parse_ws(b'.oj on\r\nJustified body.\r\n')
    doc.meta['variant'] = 'ws4'
    assert 'Justified body.' in emit_text(doc, mode='modern')
    assert '  Justified' not in emit_text(doc, mode='modern')


def test_margins_are_per_block_state_not_first_occurrence():
    """C9. `.lm`/`.rm`/`.pm` are stateful, and emphatically not first-occurrence
    the way page geometry is -- one archive file sets `.pm` seven hundred times."""
    doc = core.parse_ws(b'.lm 5\r\n.rm 60\r\nIndented.\r\n.pm 4\r\nPara margin.\r\n')
    # left_margin is stored as OFFSET columns (`.lm 5` = text at column 5 =
    # 4 columns in), matching the style-block hmi path -- see the LM handler.
    # `.pm` shares the same 1-based column frame (b26 fix) so `.pm 4` -> 3.0
    # offset columns, same normalization as `.lm`.
    assert [(b.left_margin, b.right_margin, b.para_margin) for b in doc.blocks] == [
        (4.0, 60.0, None), (4.0, 60.0, 3.0)]
    # never set -> None, so a consumer applies its own default rather than a
    # fabricated one
    b = core.parse_ws(b'Plain.\r\n').blocks[0]
    assert (b.left_margin, b.right_margin, b.para_margin) == (None, None, None)


def test_margins_accept_columns_and_inches():
    """The archive writes both `.rm 65` and `.rm 6.5"`."""
    assert core.parse_ws(b'.rm 65\r\nT.\r\n').blocks[0].right_margin == 65.0
    assert core.parse_ws(b'.rm 6.5"\r\nT.\r\n').blocks[0].right_margin == 65.0


def test_centering_measures_against_the_documents_own_margins():
    """A centred line sits between `.lm` and `.rm`, not inside a hardcoded 65 --
    so narrowing the margin moves the centre."""
    from ctrlkd.emit import emit_text

    def indent(src):
        doc = core.parse_ws(src)
        doc.meta['variant'] = 'ws4'
        line = [l for l in emit_text(doc, mode='modern').split('\n') if l.strip()][0]
        return len(line) - len(line.lstrip())

    narrow = indent(b'.rm 40\r\n.oc on\r\nCentre me.\r\n')
    wide = indent(b'.rm 70\r\n.oc on\r\nCentre me.\r\n')
    assert narrow < wide, (narrow, wide)
    # `.lm` shifts the centre too: WordStar centres BETWEEN the margins
    assert indent(b'.lm 10\r\n.rm 40\r\n.oc on\r\nCentre me.\r\n') > narrow


def test_margins_do_not_leak_into_document_formatting():
    """They are per-block state; `meta['formatting']` is for document-wide flags."""
    meta = core.parse_ws(b'.lm 5\r\n.rm 60\r\nT.\r\n').meta['formatting']
    assert meta == {}


def _ws_block(cmd, content=b''):
    """One WS5+ symmetric sequence with REAL framing: `1D <jump> <cmd> <content>
    <jump> 1D`, bracketed by its own length. Same construction as
    tools/ws_fixture.py, whose self-test checks it byte-for-byte against real
    WordStar output."""
    jump = len(content) + 4
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([cmd]) + content + j + b'\x1d'


def test_inset_graphics_are_recorded_and_placeheld():
    """C10. An INSET picture's block content IS its path, and the whole block was
    being dropped -- so a document with figures rendered as if it had none, with
    no indication anything was missing.

    A converter cannot render a 1987 .PIX file, but it must not go quiet about
    one: the path is recorded and a visible placeholder goes where the picture sat.
    """
    from ctrlkd.emit import emit_text
    block = _ws_block(0x10, br'C:\PIX\FIGURE1.PIX')
    doc = core.parse_ws(b'Before. ' + block + b' After.\r\n')
    assert doc.graphics == [r'C:\PIX\FIGURE1.PIX']
    text = emit_text(doc, mode='printed')
    assert '[image: FIGURE1.PIX]' in text, text
    assert 'Before.' in text and 'After.' in text
    assert not doc.unknown_blocks, 'the graphic should no longer be an unknown block'


def test_a_document_with_no_graphics_reports_none():
    assert core.parse_ws(ws4_text('Plain.') + HARD).graphics == []


def test_inset_graphic_placeholder_carries_a_pix_span_tag():
    """Round 19 (PIX images RULED IN): an emitter that wants to replace the
    placeholder with a real embedded image needs to find both the span AND
    the resolved index into doc.graphics -- the placeholder text alone
    (identical across documents that reuse a filename) can't disambiguate
    which occurrence it is. Marked exactly like a 0x0F print control's
    display string (pctl<hmi>): one span, tagged 'pix<N>'."""
    block = _ws_block(0x10, br'C:\PIX\FIGURE1.PIX')
    doc = core.parse_ws(b'Before. ' + block + b' After.\r\n')
    tagged = [sp for b in doc.blocks for ln in getattr(b, 'lines', [])
              for sp in ln.spans if any(t.startswith('pix') for t in sp.styles)]
    assert len(tagged) == 1, tagged
    assert tagged[0].text == '[image: FIGURE1.PIX]'
    assert 'pix0' in tagged[0].styles


def test_two_inset_graphics_get_distinct_pix_indices():
    block1 = _ws_block(0x10, br'C:\PIX\ONE.PIX')
    block2 = _ws_block(0x10, br'C:\PIX\TWO.PIX')
    doc = core.parse_ws(b'A. ' + block1 + b' B. ' + block2 + b' C.\r\n')
    assert doc.graphics == [r'C:\PIX\ONE.PIX', r'C:\PIX\TWO.PIX']
    tagged = [sp for b in doc.blocks for ln in getattr(b, 'lines', [])
              for sp in ln.spans if any(t.startswith('pix') for t in sp.styles)]
    idxs = sorted(int(t[3:]) for sp in tagged for t in sp.styles
                  if t.startswith('pix'))
    assert idxs == [0, 1]


# ------------------------------------------- Category C: pass 2

def test_toc_and_index_entries_are_collected_with_a_position():
    """C6/C7. A document that asked for a table of contents produced none and said
    nothing about it. The block index is what lets a consumer resolve an entry to
    a PAGE after pagination -- the text alone cannot, since two chapters can share
    a title. It points FORWARD, at the block the entry describes."""
    doc = core.parse_ws(b'.tc Chapter One\r\nBody.\r\n.tc2 A Section\r\nMore.\r\n'
                        b'.ix wordstar\r\nEnd.\r\n')
    assert doc.toc_entries == [(1, 'Chapter One', 0), (2, 'A Section', 1)]
    assert doc.index_entries == [('wordstar', 1)]


def test_line_numbering_interval_is_read_and_zero_turns_it_off():
    """C11."""
    assert core.parse_ws(b'.l# 5\r\nT.\r\n').meta['line_numbering'] == 5
    assert core.parse_ws(b'.l# 0\r\nT.\r\n').meta['line_numbering'] is None


def test_pe_and_cv_are_recorded_rather_than_silently_dropped():
    """C4/C13. `.pe` asks for endnotes HERE, not at the document end; `.cv` retypes
    notes mid-document. Acting on either is a further pass -- not pretending the
    command was absent is this one."""
    fmt = core.parse_ws(b'.pe\r\n.cv 3 4\r\nT.\r\n').meta['formatting']
    assert fmt['endnotes_here'] is True
    assert fmt['convert_notes'] == ['3 4']


def test_columns_are_per_block_and_render_in_html():
    """C5. The archive writes `.co2, 0.3"`, `.CO3,  .20"` and `.co1` (one column =
    off). CSS does columns properly, so HTML is the one format that can honour
    `.co` rather than merely record it."""
    from ctrlkd.emit import emit_html
    doc = core.parse_ws(b'.co2, 0.3"\r\nTwo columns.\r\n.co1\r\nBack to one.\r\n')
    assert [(b.columns, b.column_gutter) for b in doc.blocks] == [(2, 3.0), (1, 3.0)]
    doc.meta['variant'] = 'ws4'
    html = emit_html(doc, mode='modern')
    assert 'column-count:2' in html
    assert 'column-gap:0.30in' in html
    # one column is not a column layout
    assert html.count('column-count') == 1


def test_colour_and_font_changes_are_recorded():
    """C2/C3. Neither was ever at risk of losing TEXT, but both were invisible: a
    document that coloured a passage or set 9pt type rendered identically to one
    that did not. Font height is 1/20 point -- 0x00B4 = 180 = 9pt, which is what
    the archive's own blocks carry."""
    colour = _ws_block(0x01, bytes([0x08, 0x04]))          # colour 8, previous 4
    # WSFORMAT.TXT type 2: width HMI (1/1800in), height VMI (1/1440in), typestyle,
    # then the previous triple. WIDTH FIRST -- this was read swapped until
    # 2026-08-04, and survived because 1/1440in IS 1/20pt (1440/72 = 20), so the
    # WIDTH word read as 20ths-of-a-point gave plausible sizes off the wrong field.
    font = _ws_block(0x02,
                     (180).to_bytes(2, 'little')            # width  180/1800in = 10 CPI
                     + (240).to_bytes(2, 'little')          # height 240/1440in = 12pt
                     + (0x8000 | 0x0400).to_bytes(2, 'little')   # proportional, serif
                     + b'\x00' * 6)
    doc = core.parse_ws(b'Plain ' + colour + b'coloured ' + font + b'and sized.\r\n')
    assert [(c, prev) for _, c, prev in doc.colours] == [(8, 4)]
    f = doc.fonts[0]
    assert f['points'] == 12.0
    assert f['cpi'] == 10.0
    assert f['proportional'] is True
    assert f['generic_style'] == 'serif'
    assert f['symbol_map'] == 'cp437'


def test_print_file_includes_keep_their_filename():
    """The archive's `%F"PLEAD.PS"`: like an inset graphic, the block holds a
    FILENAME and was dropped whole."""
    from ctrlkd.emit import emit_text
    doc = core.parse_ws(b'Before ' + _ws_block(0x0F, b'\x00\x00\x00%F"PLEAD.PS"')
                        + b' after.\r\n')
    assert doc.includes == ['PLEAD.PS']
    assert '[include: PLEAD.PS]' in emit_text(doc, mode='printed')


def test_a_print_block_with_no_filename_stays_a_reported_unknown():
    """Consuming it silently would be WORSE than the bug being fixed: it turns a
    reported unknown into an unreported one. Most 0x0F blocks are PostScript
    preambles with no `%F` at all."""
    doc = core.parse_ws(b'T ' + _ws_block(0x0F, b'\x00\x00\x00/bw 7 inch def') + b'.\r\n')
    assert doc.includes == []
    assert [u.cmd for u in doc.unknown_blocks] == [0x0F]


def test_printer_driver_name_is_reported_without_its_record_tag():
    """Provenance: it explains why a file's measurements look the way they do.
    The byte before the name is a record tag, not part of it (`pLASERJET`)."""
    doc = core.parse_ws(_ws_block(0x00, b'pLASERJET\x00\x00\x00\x80') + b'T.\r\n')
    assert doc.meta['printer_driver'] == 'LASERJET'


def test_every_paragraph_style_survives_not_just_the_three_headings():
    """C1. A 0x11 block is four LE16 handles; word 0's low byte is the 0-based
    library SLOT (deleted slots counted), its high byte the 0x02 pool tag.
    Slot numbers carry no heading semantics -- the corpus's own NOVEL.WS has
    real H1/H2/H3 styles at slots 4/10/8 while the old {0x05,0x02,0x03} map
    promoted its footer style to a heading. Without a resolvable library the
    slot is still recorded; heading requires the resolved NAME."""
    def styled(slot):
        blk = _ws_block(0x11, bytes([slot, 2, 1, 2, 2, 3, 1, 2]))
        return core.parse_ws(blk + b'Styled text.\r\n').blocks[0]

    for sid in (0x05, 0x06, 0x0F, 0x19):
        b = styled(sid)
        assert b.heading == 0, 'no library to resolve against => no heading'
        assert b.style_id == sid, 'but WHICH slot must still be known'
        assert ''.join(s.text for s in b.lines[0].spans) == 'Styled text.'
    # a 0x03xx handle names an editing-temp style that was never written to
    # the file -- unresolvable BY DESIGN, must stay unstyled, never guessed
    tmp = core.parse_ws(_ws_block(0x11, bytes([5, 3, 1, 2, 2, 3, 1, 2]))
                        + b'Styled text.\r\n').blocks[0]
    assert tmp.style_id is None and tmp.heading == 0


def test_note_numbering_mode_is_read_not_just_the_start_value():
    """C12. A numeric argument sets the START value; the keyword forms say how
    numbering RUNS. A document that restarts per page numbered straight through --
    a visible difference on paper, not a diagnostic-only one."""
    meta = core.parse_ws(b'.f# page\r\n.e# continuous\r\n.f# 7\r\nT.\r\n').meta
    assert meta['footnote_number_mode'] == 'page'
    assert meta['endnote_number_mode'] == 'continuous'
    assert meta['footnote_number_start'] == 7          # start still read
    assert 'footnote_number_mode' not in core.parse_ws(b'.f# 3\r\nT.\r\n').meta


def test_shift_jis_is_a_mode_toggle_not_a_text_container():
    """C15, corrected against WSFORMAT.TXT:

        "17h Japanese Font Shift-In/Shift-Out
         Byte: Shift-In (to Japanese) = 1, Shift-Out (Back to Normal) = 0."

    A ONE-BYTE MODE TOGGLE. The Japanese bytes live in the ordinary stream
    BETWEEN a shift-in and its shift-out. This was first implemented as if the
    block held the text itself, which would have injected a placeholder where a
    marker belongs and left the real Japanese to be mangled by the cp437 decoder.

    The run is lifted out and replaced by a placeholder: nothing is lost, and no
    mojibake is presented as text."""
    jp = bytes([0x82, 0xA0, 0x82, 0xA2])
    doc = core.parse_ws(b'Before ' + _ws_block(0x17, b'\x01') + jp
                        + _ws_block(0x17, b'\x00') + b' after.\r\n')
    assert doc.shift_runs == [(7, jp)], doc.shift_runs
    text = ''.join(s.text for s in doc.blocks[0].lines[0].spans)
    assert text == 'Before [shift-jis: 4 bytes] after.', text


def test_an_unterminated_shift_in_runs_to_the_end():
    """The text is Japanese from there on; dropping the run would lose that."""
    doc = core.parse_ws(b'Some ordinary English text here. '
                        + _ws_block(0x17, b'\x01') + bytes([0x82, 0xA0]) + b'\r\n')
    assert len(doc.shift_runs) == 1
    assert doc.shift_runs[0][1].startswith(bytes([0x82, 0xA0]))


def test_the_escape_byte_cannot_fire_inside_a_japanese_run():
    """WSFORMAT.TXT on 17h: "When shifted in, WordStar no longer uses the 1Bh/1Ch
    wrap characters and interprets characters using the Asian Character Standard".

    `_decode_spans` treats 1Bh as the extended-character escape UNCONDITIONALLY,
    so a 1Bh inside a Japanese run would be read as an escape and would swallow
    the byte after it. Lifting the run out before decoding is what makes that
    impossible -- a correctness property, not tidiness."""
    jp = bytes([0x1B, 0x41, 0x82, 0xA0])          # a 1Bh that must NOT act as an escape
    doc = core.parse_ws(b'Some ordinary English text here. '
                        + _ws_block(0x17, b'\x01') + jp
                        + _ws_block(0x17, b'\x00') + b' tail.\r\n')
    assert doc.shift_runs == [(33, jp)], doc.shift_runs
    text = ''.join(s.text for s in doc.blocks[0].lines[0].spans)
    assert '[shift-jis: 4 bytes]' in text
    assert text.endswith(' tail.'), text          # nothing swallowed past the run


def test_fi_file_insert_leaves_a_trace():
    """WSFORMAT.TXT: ".FI  File insert.  Prints the specified file at that point in
    the document."

    A whole file the document composes itself from, rendering as NOTHING -- the
    filename sat in the dot_commands diagnostic and no emitter said a word. The
    same class already fixed for inset graphics (type 0x10) and the printer's own
    `%F"NAME"` includes (type 0x0F); this one was missed because it is a dot
    command rather than a block.

    The file is NOT read: it may not exist, and the spec allows it to be a Lotus
    worksheet. Saying a file belongs here is the honest half."""
    from ctrlkd.emit import emit_text
    doc = core.parse_ws(b'Body one.\r\n.fi CHAPTER2.WS\r\nBody two.\r\n')
    assert doc.includes == ['CHAPTER2.WS']
    # and it lands BETWEEN the paragraphs, not at the front of the document
    assert emit_text(doc, mode='printed') == 'Body one.\n[insert: CHAPTER2.WS]\nBody two.\n'


def test_ig_and_double_dot_comments_never_print():
    """WSFORMAT.TXT: ".IG or..  Ignore.  The text on the remainder of the line is
    treated as an unprinted comment." Verified rather than assumed -- both forms
    are dropped by the general dot-line rule, and this pins that they stay so."""
    from ctrlkd.emit import emit_text
    for src in (b'One.\r\n.ig hidden note\r\nTwo.\r\n',
                b'One.\r\n.. hidden note\r\nTwo.\r\n'):
        text = emit_text(core.parse_ws(src), mode='printed')
        assert 'hidden' not in text, text
        assert 'One.' in text and 'Two.' in text


def test_a_literal_form_feed_breaks_the_page_in_a_ws_document():
    """WSFORMAT.TXT: "0Ch ^L  Form Feed.  At print time causes page to be ejected."

    `parse_printstream` had always honoured it; `parse_ws` did not, so a WS
    document carrying ^L had its two pages run together into ONE paragraph and the
    only trace was an "unknown code 0x0c" line in --diagnose. The break was lost.

    Found by diffing all 32 low-order control codes against the spec -- a surface
    that had never been checked, one code at a time, against the document that
    defines it."""
    doc = core.parse_ws(b'Page one text here with plenty of ordinary prose.'
                        b'\x0cPage two text here also with prose.\r\n')
    assert [b.kind for b in doc.blocks] == ['para', 'pagebreak', 'para']
    assert doc.meta['unknown_codes'] == {}, 'a handled code must not be reported unknown'
    # and the two parse paths now agree, which they did not before
    ps = core.parse_printstream(b'Page one text here with plenty of ordinary prose.'
                                b'\x0cPage two text here also with prose.\r\n')
    assert [b.kind for b in ps.blocks] == [b.kind for b in doc.blocks]


def test_real_control_codes_are_not_mistaken_for_structure():
    """The sentinels were IN-BAND BYTES, and every byte available for one is a
    real WordStar control code:

        SENT_FNREF    0x00 = ^@ fix print position   (2328 in 5 archive docs)
        SENT_SOFTPAGE 0x0B = ^K index marker         (21 in 3)
        SENT_HEADING  0x11 = ^Q custom print control (37 in 5)

    A literal ^K produced a page break the author never wrote. The 0x00 choice
    was made on 2026-08-03 with the reasoning "NUL is not text in a WordStar
    body" -- the spec says otherwise, and it moved the clash from a rare byte
    onto a common one.

    Marks now travel as OFFSETS, the pattern `tab_at` already used and whose own
    comment said "that lesson is cheap to apply here". It was not applied
    backwards until now.
    """
    wrapper = _ws_block(0x00)
    for byte in (0x00, 0x0B, 0x11):
        doc = core.parse_ws(wrapper + b'Ordinary prose here, plenty of it. '
                            + bytes([byte]) + b'More prose follows on.\r\n')
        assert [b.kind for b in doc.blocks] == ['para'], f'{byte:#04x} invented a block'
        assert doc.blocks[0].heading == 0, f'{byte:#04x} invented a heading'
        assert not any('fnref' in s.styles for l in doc.iter_lines() for s in l.spans), \
            f'{byte:#04x} invented a note reference'


def test_real_structure_still_resolves_after_the_sentinel_removal():
    """The other half: removing the sentinels must not lose the structure they
    carried. NOTES.TST is real WordStar output with four known note kinds."""
    import os
    root = os.environ.get('CTRLKD_PRIVATE_FIXTURES')
    if not root:
        return                      # private fixtures opt in via env var; skip if absent
    p = os.path.join(root, 'NOTES.TST')
    if not os.path.exists(p):
        return
    doc = core.parse_ws(open(p, 'rb').read())
    noncomment = [n.kind for n in doc.notes if n.kind != 'comment']
    assert noncomment[:4] == ['footnote', 'footnote', 'endnote', 'endnote']
    from ctrlkd.emit import _annotated_notes, _ref_pairs
    pairs = _ref_pairs(_annotated_notes(doc))
    noncomment_refs = sum(
        1 for l in doc.iter_lines() for s in l.spans
        if 'fnref' in s.styles and s.text.isdigit()
        and 0 < int(s.text) <= len(pairs)
        and pairs[int(s.text) - 1][0].kind != 'comment')
    assert noncomment_refs == 6, noncomment_refs   # the four real note kinds;
                                                   # dot-line comments now also
                                                   # carry marks (2026-08-06)


def _real_fixture(name):
    # Private fixture corpus lives OUTSIDE the repo; runners that have it
    # export CTRLKD_PRIVATE_FIXTURES=<dir>. Everyone else skips cleanly.
    import os
    root = os.environ.get('CTRLKD_PRIVATE_FIXTURES')
    if not root:
        return None
    p = os.path.join(root, name)
    return open(p, 'rb').read() if os.path.exists(p) else None


def test_attrib_tst_known_answers():
    """-ATTRIB.TST is MicroPro's own attribute demo: each label is set in the
    attribute it names. A known-answer check of every toggle pair at once."""
    raw = _real_fixture('-ATTRIB.TST')
    if raw is None:
        return                      # fixture lives outside the repo
    doc = core.parse_ws(raw)
    # first span of each demo line, in the file's own order (labels carry
    # trailing hex annotations inside the same styled span)
    first = [(ln.spans[0].text, ln.spans[0].styles)
             for ln in doc.iter_lines() if ln.spans]
    expect = [('regular', set()), ('Bold', {'b'}), ('Italics', {'i'}),
              ('Bold Italics', {'b', 'i'}), ('Bold Underline', {'b', 'u'}),
              ('Superscript', {'sup'}), ('Subscript', {'sub'}),
              ('strikeout', {'strike'})]
    for (text, styles), (label, want) in zip(first, expect):
        assert text.startswith(label), (text, label)
        assert set(styles) == want, (label, styles)


def test_sub_supe_tst_known_answers():
    """SUB-SUPE.TST: C22 sub/superscript demo -- and its prose carries real
    accented characters as <1B xx 1C> wrapped extended chars, the corpus's
    one known-answer for that path."""
    raw = _real_fixture('SUB-SUPE.TST')
    if raw is None:
        return
    doc = core.parse_ws(raw)
    txt = emit.emit_text(doc, mode='printed')
    for probe in ('Élisabeth', 'voilà', 'naïve', '¡Por favor!'):
        assert probe in txt, probe
    spans = [s for ln in doc.iter_lines() for s in ln.spans]
    # known answer counts WordStar's own ^T toggles; reference marks also
    # carry 'sup' (comment marks included since 2026-08-06) and are excluded
    assert sum(1 for s in spans
               if 'sup' in s.styles and 'fnref' not in s.styles) == 23
    assert sum(1 for s in spans if 'sub' in s.styles) == 30


def test_ps_tst_known_answers():
    """PS.TST: the proportional-spacing font sampler (C19)."""
    raw = _real_fixture('PS.TST')
    if raw is None:
        return
    doc = core.parse_ws(raw)
    txt = emit.emit_text(doc, mode='printed')
    for face in ('Arial', 'Bookman', 'Courier'):
        assert face in txt
    spans = [s for ln in doc.iter_lines() for s in ln.spans]
    assert sum(1 for s in spans if 'b' in s.styles) == 30
    assert sum(1 for s in spans if 'i' in s.styles) == 30


def test_header_sequence_states_the_release_instead_of_guessing_it():
    """WSFORMAT.TXT, type 0 Header: "Byte: version number in BCD (50h for Release
    5.0, 55h for Release 5.5, 60h for Release 6.0)", then a 9-byte driver name,
    2 reserved, and a 32-bit pointer to the file's style library.

    This block was read as nothing but a driver name. The version byte is the
    more valuable field: `detect` INFERS ws4-vs-ws5+ from byte statistics, and
    the file says its release outright. 78 archive documents declare 7.0 and
    3 declare 6.0. The style-library pointer is what C1 proper needs."""
    body = bytes([0x70]) + b'LASERJET\x00' + b'\x00\x00' \
        + (0x1234).to_bytes(2, 'little') + (0x0001).to_bytes(2, 'little')
    doc = core.parse_ws(_ws_block(0x00, body)
                        + b'Body text, with enough ordinary prose to detect.\r\n')
    h = doc.meta['ws_header']
    assert h['release'] == '7.0'
    assert h['style_library_offset'] == 0x00011234


def test_font_block_reads_width_before_height():
    """The trap that hid a swapped field for a day: 1/1440in IS 1/20 point exactly
    (1440/72 = 20), so reading the WIDTH word as 20ths-of-a-point yields sizes
    that look like real type -- 9pt, 8pt, 11pt across 862 archive blocks. Those
    numbers were cited as confirming the reading. They were the right arithmetic
    on the wrong word.

    Read correctly the same corpus gives 12pt for 749 of those blocks, with 10
    CPI, which is what a 1992 document actually looks like."""
    font = _ws_block(0x02, (180).to_bytes(2, 'little') + (240).to_bytes(2, 'little')
                     + (0).to_bytes(2, 'little') + b'\x00' * 6)
    f = core.parse_ws(b'Text ' + font + b' more text here for detection.\r\n').fonts[0]
    assert f['width_1800'] == 180 and f['cpi'] == 10.0
    assert f['height_1440'] == 240 and f['points'] == 12.0


def test_user_print_control_is_parsed_not_scanned():
    """WSFORMAT.TXT, "0Fh User print control":

        Word:  number of hmis this sequence uses on the printed page
        Byte:  number of characters used for screen display
        Text:  the display string itself
        "The remaining bytes ... will be sent directly to the printer."

    This block used to be scanned for printable bytes looking for `%F"NAME"`,
    ignoring the structure. The DISPLAY STRING is real content -- what WordStar
    shows on screen where the control sits -- and three archive blocks carry 70
    characters of it. The file reference is one thing INSIDE the printer payload,
    not the payload itself."""
    from ctrlkd.emit import emit_text

    # a display string, no file reference
    body = (0).to_bytes(2, 'little') + bytes([7]) + b'[LOGO] ' + b'\x1b*p0002x'
    doc = core.parse_ws(b'Before ' + _ws_block(0x0F, body) + b' after.\r\n')
    # Round 3 (2026-08-06): the paper never showed the display string --
    # printed pads the control's declared HMI width instead (here 0)
    assert '[LOGO]' not in emit_text(doc, mode='printed')
    assert 'Before  after.' in emit_text(doc, mode='printed')
    assert doc.includes == []

    # a file reference inside the printer payload
    body = (0).to_bytes(2, 'little') + bytes([0]) + b'%F"PLEAD.PS"'
    doc = core.parse_ws(b'Before ' + _ws_block(0x0F, body) + b' after.\r\n')
    assert doc.includes == ['PLEAD.PS']
    assert '[include: PLEAD.PS]' in emit_text(doc, mode='printed')

    # neither: pure printer bytes stay a REPORTED unknown
    body = (0).to_bytes(2, 'little') + bytes([0]) + b'\x1b*c2370a'
    doc = core.parse_ws(b'T ' + _ws_block(0x0F, body) + b' more text here.\r\n')
    assert [u.cmd for u in doc.unknown_blocks] == [0x0F]


def test_ws5_soft_returns_always_wrap_in_modern():
    # The would-it-have-fit heuristic is a WS4 fixed-pitch inference; WS5+
    # documents use proportional fonts where byte length says nothing about
    # printed width, and a real story's modern RTF carried 204 spurious
    # \line breaks (found by Jon reading the export). In WS5+, a surviving
    # soft return IS wrap by construction.
    SOFT = b'\x8d\x0a'
    data = (ws7_block(0x00) +
            b'     Short line' + SOFT + b'even though the next word fits.' + HARD +
            b'     Second paragraph here.' + HARD)
    doc = core.parse_ws(data)
    from ctrlkd.core import merged_lines
    assert [len(merged_lines(b)) for b in doc.blocks] == [2]
    assert merged_lines(doc.blocks[0])[0].text() == (
        '     Short line even though the next word fits.')
    rtf = emit.emit_rtf(doc, mode='modern')
    assert '\\line' not in rtf.split('Short')[1].split('fits.')[0]  # no break inside the wrap
    assert 'Short line even though' in emit.emit_text(doc, mode='modern')


def test_font_changes_render_as_runs():
    # Jon's export review: every RTF was Times New Roman -- doc.fonts was
    # recorded and never rendered. A font block is a run boundary: following
    # spans carry fontN, RTF gets a real fonttbl entry + \fN\fs, HTML gets
    # a class + generated CSS from the block's own words. Typestyle 3 is
    # 'Courier' in the spec's table; height 280 VMI = 14pt.
    font = ws7_block(0x02, (180).to_bytes(2, 'little') + (280).to_bytes(2, 'little')
                     + (3).to_bytes(2, 'little') + bytes(6))
    data = (ws7_block(0x00) + b'Before the change. ' + font +
            b'After the change.' + HARD)
    doc = core.parse_ws(data)
    spans = [s for b in doc.blocks for ln in b.lines for s in ln.spans]
    tagged = [s for s in spans if any(t.startswith('font') for t in s.styles)]
    assert tagged and 'After the change.' in ''.join(s.text for s in tagged)
    assert not any(t.startswith('font') for s in spans for t in s.styles
                   if 'Before' in s.text)
    rtf = emit.emit_rtf(doc, mode='modern')
    assert '{\\f2 Courier New;}' in rtf   # modern primary; falt only when a SECOND modern alt exists (era names are never the falt -- Jon's ruling)
    assert '\\f2\\fs28 ' in rtf                       # 14pt = \fs28
    h = emit.emit_html(doc, mode='modern')
    assert "class=\"ws-font-0\"" in h
    # CSS stack: original first (pass-through), modern alternate, then the
    # terminal generic -- round 9: 'Courier' has NO proportional bit set
    # here (style_bits defaults to 0 above), so the honest terminal is CSS
    # `monospace`, not the generic-style bits' incidental 'sans' reading
    # (typestyle 3's raw word sets no generic-style bits either -- they
    # only matter for a genuinely proportional record).
    assert "font-family:'Courier', 'Courier New', monospace" in h
    assert 'font-size:14pt' in h
    assert 'ws-font-0' not in emit.emit_html(doc, mode='modern', styles=False).split('<body>')[0]


def test_symbol_and_dingbat_fonts_transliterate_to_unicode():
    # A byte in Symbol/ZapfDingbats is a GLYPH INDEX, not styled text:
    # 'a' in Symbol IS alpha; '!' in Dingbats IS U+2701 (Unicode's 2700
    # block is ITC Zapf Dingbats by name and order). Transliterated at
    # decode time, the output needs no font at all. Typestyle 41=Symbol,
    # 34... use names via table: Symbol=41? -- built from the real table:
    from ctrlkd.typestyles import TYPESTYLE_NAMES
    sym_n = next(k for k, v in TYPESTYLE_NAMES.items() if v.lower().startswith('symbol'))
    ding_n = next(k for k, v in TYPESTYLE_NAMES.items() if 'dingbat' in v.lower())
    def font(n):
        return ws7_block(0x02, (180).to_bytes(2, 'little') + (240).to_bytes(2, 'little')
                         + n.to_bytes(2, 'little') + bytes(6))
    data = (ws7_block(0x00) +
            b'Plain prose padding so the detector reads this as a document.\r\n' +
            b'Plain. ' + font(sym_n) + b'abG ' + font(ding_n) + b'!"#' + HARD +
            b'And a closing line of ordinary prose keeps the ratio honest.\r\n')
    doc = core.parse_ws(data)
    assert doc.meta['variant'] == 'ws5+'
    txt = emit.emit_text(doc, mode='printed')
    assert 'αβΓ' in txt                    # Symbol run -> Greek
    assert '✁✂✃' in txt     # Dingbats run -> U+2701..
    assert 'Plain. ' in txt                # untouched outside the runs


def test_fonts_target_selects_primaries_and_generic_coverage():
    # Jon's ruling: --fonts {office,mac,google}. mac gets Cocoa-native
    # primaries (Futura for Avant Garde); google gets Docs' chancery
    # (Dancing Script); an UNMAPPED family lands on the target's generic
    # primary from the font block's own style bits -- every run a usable
    # face, era names never the falt.
    from ctrlkd.typestyles import TYPESTYLE_NAMES
    ag = next(k for k, v in TYPESTYLE_NAMES.items() if v.lower().startswith('avant garde'))
    zc = next(k for k, v in TYPESTYLE_NAMES.items() if v.lower().startswith('zapfchancery'))
    # round 9: Avant Garde and Zapf Chancery are genuinely proportional
    # display/script faces -- the proportional bit (0x8000) is part of a
    # realistic record for either, and now decisive for family selection
    # (a real WordStar file naming these WOULD set it), so the default
    # here is no longer bit-less the way it could be before that mattered.
    def font(n, style_bits=0x8000):
        ts = (n & 0x01FF) | style_bits
        return ws7_block(0x02, (180).to_bytes(2, 'little') + (240).to_bytes(2, 'little')
                         + ts.to_bytes(2, 'little') + bytes(6))
    data = (ws7_block(0x00) +
            b'Prose padding for detection, a perfectly ordinary sentence.\r\n' +
            font(ag) + b'Geometric. ' + font(zc) + b'Scripted.' + HARD +
            b'Closing prose line keeps the byte ratio looking like text.\r\n')
    doc = core.parse_ws(data)
    office = emit.emit_rtf(doc, mode='modern')
    assert '{\\f2 Century Gothic{\\*\\falt ITC Avant Garde Gothic};}' in office
    mac = emit.emit_rtf(doc, mode='modern', fonts_target='mac')
    assert '{\\f2 Futura{\\*\\falt Century Gothic};}' in mac
    goog = emit.emit_rtf(doc, mode='modern', fonts_target='google')
    assert 'Dancing Script' in goog


def test_linux_target_uses_urw_base35_clones():
    # The URW base-35 set (fonts-urw-base35, Ghostscript heritage) is free
    # metric-compatible clones of EXACTLY this era's faces: URW Gothic IS
    # Avant Garde, Z003 IS Zapf Chancery. The most faithful target, libre.
    from ctrlkd.typestyles import TYPESTYLE_NAMES
    ag = next(k for k, v in TYPESTYLE_NAMES.items() if v.lower().startswith('avant garde'))
    zc = next(k for k, v in TYPESTYLE_NAMES.items() if v.lower().startswith('zapfchancery'))
    # round 9: proportional bit set -- see the same note in
    # test_fonts_target_selects_primaries_and_generic_coverage.
    def font(n):
        return ws7_block(0x02, (180).to_bytes(2, 'little') + (240).to_bytes(2, 'little')
                         + ((n & 0x01FF) | 0x8000).to_bytes(2, 'little') + bytes(6))
    data = (ws7_block(0x00) +
            b'Prose padding for detection, a perfectly ordinary sentence.\r\n' +
            font(ag) + b'Geometric. ' + font(zc) + b'Scripted.' + HARD +
            b'Closing prose line keeps the byte ratio looking like text.\r\n')
    doc = core.parse_ws(data)
    rtf = emit.emit_rtf(doc, mode='modern', fonts_target='linux')
    # falt is guaranteed-tier per the 2026-08-05 ruled table (DejaVu rides
    # fontconfig itself; a Microsoft name is useless on a Ghostscript-less box)
    assert '{\\f2 URW Gothic{\\*\\falt DejaVu Sans};}' in rtf
    assert 'Z003' in rtf


def test_ws4_alternate_font_flag_is_stored_not_lost():
    # Jon, 2026-08-04: "Store that ws4 font switch flag. Don't lose it."
    # ^PA (0x01) / ^PN (0x0E) is the ONLY typeface signal a WS4 file can
    # carry -- the face itself lived in the printer hardware. Preserved as
    # the 'altfont' span tag; deliberately unrendered until a use exists.
    data = ws4_text('Pica here') + b' ' + bytes([0x01]) + ws4_text('elite here') \
        + bytes([0x0E]) + b' ' + ws4_text('pica again.') + HARD + make_prose()
    doc = core.parse_ws(data)
    spans = [s for b in doc.blocks for ln in b.lines for s in ln.spans]
    alt = [s.text for s in spans if 'altfont' in s.styles]
    assert alt == ['elite here']
    assert not any('altfont' in s.styles for s in spans if 'pica' in s.text)
    d2 = core.parse_ws(data)
    assert '0x01' not in d2.meta['unknown_codes']    # no longer noise


# ------------------------------------------------- printed-mode base-14 fonts
#
# Jon's ruling, 2026-08-04: a PRINTED-mode PDF of a WS5+ document renders
# WordStar's exact line breaks (it always did) PLUS the fonts the document
# chose, through the PDF base-14 built-ins -- no embedding, no dependencies.
# Modern mode stays Courier-only typewriter setting. WS4 files and print
# streams carry no font blocks and are therefore Courier automatically.

def _font_block(number, points=12.0, style_bits=0, width=180):
    """One WS5+ font block: width word (HMI, 1/1800in -- the per-character
    advance WordStar laid the document out on; 180 = 10 CPI, the default
    pica), height word (VMI = points*20), typestyle word. Style bits ride in
    the typestyle word's high half."""
    ts = (number & 0x01FF) | style_bits
    return ws7_block(0x02, round(width).to_bytes(2, 'little')
                     + round(points * 20).to_bytes(2, 'little')
                     + ts.to_bytes(2, 'little') + bytes(6))


def _helv_typestyle():
    """A typestyle number the base-14 mapping resolves to Helvetica."""
    from ctrlkd.typestyles import TYPESTYLE_NAMES
    return next(k for k, v in TYPESTYLE_NAMES.items() if v.lower().startswith('helv'))


_SHOW_RE = (rb'/(F\d+) (\d+) Tf -?\d+ Ts (?:([\d.]+) Tz )?'
            rb'(-?[\d.]+) (-?[\d.]+) Td \(((?:\\.|[^)\\])*)\) Tj')


def _content_text(pdf):
    """The content streams' text-showing operators as (font, size, text).
    Every span is its own text object at an absolute x since printed mode
    started positioning on WordStar's own HMI grid; the Tz operator between
    Ts and Td is optional (it is written only when the scaling CHANGES)."""
    return [(m[0].decode(), int(m[1]), m[5]) for m in re.findall(_SHOW_RE, pdf)]


def _content_spans(pdf):
    """(font, size, tz-or-None, x, y, text) for every span shown."""
    return [(m[0].decode(), int(m[1]),
             float(m[2]) if m[2] else None, float(m[3]), float(m[4]), m[5])
            for m in re.findall(_SHOW_RE, pdf)]


def _basefonts(pdf):
    """{'F1': b'Courier', ...} -- resolving the resource dict's indirect
    references to the font objects they point at."""
    objs = dict(re.findall(rb'(\d+) 0 obj\n<< /Type /Font /Subtype /Type1 '
                           rb'/BaseFont /([^\s/>]+)(?: /Encoding'
                           rb' /WinAnsiEncoding)? >>', pdf))
    return {n.decode(): objs[num]
            for n, num in re.findall(rb'/(F\d+) (\d+) 0 R', pdf)}


def test_pdf_fontless_documents_are_byte_identical_to_pre_fonts_output():
    """THE regression that guards the whole feature: a document with no font
    runs -- every WS4 file, every print stream, and most WS5+ documents -- must
    come out of emit_pdf byte for byte across unrelated feature work. First
    pinned at a2cad03 (pre-font emitter); re-pinned ONCE on 2026-08-05 when
    /Encoding /WinAnsiEncoding was added to every text font object -- a
    deliberate, global, single-line change to the font dictionaries (cp1252
    strings need the declared encoding; without it the base-14 built-in
    StandardEncoding renders curly quotes and dashes as the wrong glyphs).
    Nothing else about the fonts/colour/graphics work may perturb a Courier
    page, including the object numbering (which is why the Courier four are
    always emitted, used or not -- see pdf.FontRes).

    Re-pinned a SECOND time 2026-08-20 (round 26 wave 3, PRINTED hash only --
    modern is untouched): _printed_top now folds `.hm` into a headerless
    document's top-of-text offset (WS7 ground truth, see _printed_top's own
    docstring), moving this fixture's body down 24pt. A real, evidenced,
    deliberate change to Printed geometry, not incidental."""
    import hashlib
    from ctrlkd.pdf import emit_pdf

    def digest(doc, mode):
        return hashlib.sha256(emit_pdf(doc, mode)).hexdigest()

    styled = (b'Plain ' + b'\x02bold\x02 ' + b'\x13under\x13 '
              + b'and (word) here.' + HARD
              + b'More ordinary prose for the detector to chew on.' + HARD)
    stream = b'Line one of printed page\r\nLine two\r\nLine three\r\n\x1a'
    assert digest(core.parse_ws(make_prose()), 'printed') == \
        'a98671821a5692e81d81567b48d1cd9d768ea237a8efefcd6ffdefc8019c46ff'
    assert digest(core.parse_ws(make_prose()), 'modern') == \
        'eb8bc918916d3bbb0b274e203c1c3f03b9008e6f6755cc67c6100a2f30705950'
    assert digest(core.parse_ws(styled), 'printed') == \
        'e0e54d1399a799a5120fd075d30993c7ca43b90c5e4aa152114330990cedb488'
    assert digest(core.parse_printstream(stream), 'printed') == \
        '6d6555d63a003a276e67c8291ab31b653cc526e4ec47bf6f6cc5da50849d7e98'


def test_pdf_printed_renders_the_documents_own_font_and_size():
    """Typestyle 4 is 'Helv' with the block's own generic bits saying sans, at
    14pt (height word 280 VMI = 14 points). Printed mode is a facsimile: it
    sets that run in Helvetica at 14, from the file's own words. Modern mode
    is Courier by ruling and must show neither. Proportional bit set (round
    9): a real 'Helv' record is genuinely proportional, and that flag is
    now what decides Helvetica vs Courier -- not the name alone."""
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.'
            + HARD + b'Before. ' + _font_block(4, 14.0, style_bits=0x8000) + b'After.' + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.'
            + HARD)
    doc = core.parse_ws(data)
    assert doc.meta['variant'] == 'ws5+' and doc.fonts

    pdf = emit_pdf(doc, mode='printed')
    assert b'/Filter' not in pdf                  # streams are uncompressed:
                                                  # the text below is readable
    fonts = _basefonts(pdf)
    assert b'Helvetica' in fonts.values()
    helv = next(n for n, b in fonts.items() if b == b'Helvetica')
    assert fonts['F1'] == b'Courier'              # the four are still F1..F4
    shown = _content_text(pdf)
    assert (helv, 14, b'After.') in shown         # the block's own points
    assert any(f == 'F1' and sz == 12 and b'Before.' in t for f, sz, t in shown)

    # Modern is the printed form of the Modern RTF (ruling 2026-08-05):
    # it CARRIES the document's fonts now -- the Courier-only Modern died
    # with the WS4 lens. Fontless text reads in Times at the sophisticated
    # size instead of Courier.
    modern = emit_pdf(doc, mode='modern')
    assert b'Helvetica' in modern
    m_shown = _content_text(modern)
    assert any(sz == 14 and b'After.' in t for f, sz, t in m_shown)
    assert any(b'Times-Roman' in modern.split(b'/BaseFont /')[i][:12]
               for i in range(1, modern.count(b'/BaseFont /') + 1))


def test_lint_no_proportional_face_ever_selected_for_a_proportional_false_record():
    """Round 9, Jon's ruling, tier-1 evidence: `entry['proportional']` is
    the AUTHORITY on whether a font block is fixed-pitch, and a False
    record renders as the fixed-pitch face at its own declared pitch and
    size -- regardless of what its typestyle NAME says. Root cause (SCRIPT
    .WS, Jon's field review, "crazy fat"): typestyles 103/104 ("NPS
    SansSer Qual"/"NPS Serif Qual" -- WSFORMAT's generic Non-PostScript
    letter-quality categories, not real PostScript faces) were falling
    through pdf.py's NAME-based MONO_FAMILIES check to Helvetica/Times --
    wrong weight AND wrong (proportional) advance widths, since the
    existing HMI/Tz grid machinery already renders proportional=False
    content at its true pitch and only base-14 family selection was blind
    to the flag.

    This is the PERMANENT gate: for EVERY typestyle name in the spec's own
    245-entry table (mono-sounding or not -- the point is the flag
    overrides the name in both directions), a proportional=False record
    must resolve to a genuinely fixed-pitch face in all three consumers --
    PDF's base-14 (never Times/Helvetica/Symbol/ZapfDingbats), RTF's
    fonttbl primary (never a proportional name), and HTML's CSS stack
    terminal (never sans-serif/serif/cursive/fantasy). A record that DOES
    carry proportional=True is untouched by this gate -- name-based
    resolution for a genuinely proportional face is unaffected."""
    from ctrlkd.pdf import _pdf_family
    from ctrlkd.fontmap import rtf_fonts, font_stack
    from ctrlkd.typestyles import TYPESTYLE_NAMES
    from ctrlkd.emit import _font_family
    PROPORTIONAL_BASE14 = {'Times', 'Helvetica', 'Symbol', 'ZapfDingbats'}
    PROPORTIONAL_CSS_GENERIC = {'sans-serif', 'serif', 'cursive', 'fantasy'}
    from ctrlkd.symbolmap import font_translit_kind
    checked = 0
    for number, name in TYPESTYLE_NAMES.items():
        entry = core._font_entry(180, 240, (number & 0x01FF), None)
        assert entry['proportional'] is False        # sanity: no style bits set
        # Symbol/ZapfDingbats typestyles are exempt from every check below:
        # `_pdf_family` picks them FIRST, decisively, ahead of (and
        # unrelated to) the proportional check -- a byte set in one of
        # these is a GLYPH INDEX, not prose, transliterated to Unicode at
        # parse time, and correctly reproduced via the exact base-14
        # Symbol/ZapfDingbats face regardless of any pitch flag.
        if font_translit_kind(entry) in ('math', 'symbols'):
            continue
        fam = _font_family(name)
        pdf_fam = _pdf_family(entry)
        assert pdf_fam not in PROPORTIONAL_BASE14, (number, name, pdf_fam)
        primary, _falt = rtf_fonts(fam, entry.get('generic_style'), 'office',
                                   entry.get('proportional'))
        assert primary not in ('Times New Roman', 'Arial', 'Century Gothic',
                               'Monotype Corsiva', 'Impact'), (number, name, primary)
        stack = font_stack(fam, entry.get('generic_style'), entry.get('proportional'))
        assert stack[-1] not in PROPORTIONAL_CSS_GENERIC, (number, name, stack)
        checked += 1
    assert checked > 200                              # the gate actually ran the table


def test_pdf_symbol_run_sets_the_symbol_face_with_its_own_bytes():
    """A Symbol/ZapfDingbats byte is a glyph index, transliterated to Unicode
    at parse time so text formats need no font. PDF is the one consumer that
    HAS the font -- Symbol and ZapfDingbats are in the base-14 set -- so the
    transliteration is undone and the original codes go back on the page:
    'a' with /Symbol selected IS alpha, in any viewer, with nothing embedded."""
    from ctrlkd.pdf import emit_pdf
    from ctrlkd.typestyles import TYPESTYLE_NAMES
    sym_n = next(k for k, v in TYPESTYLE_NAMES.items() if v.lower().startswith('symbol'))
    ding_n = next(k for k, v in TYPESTYLE_NAMES.items() if 'dingbat' in v.lower())
    data = (ws7_block(0x00) +
            b'Plain prose padding so the detector reads this as a document.'
            + HARD + b'Greek: ' + _font_block(sym_n) + b'abG' +
            _font_block(ding_n) + b'!"#' + HARD +
            b'And a closing line of ordinary prose keeps the ratio honest.'
            + HARD)
    doc = core.parse_ws(data)
    txt = emit.emit_text(doc, mode='printed')
    assert 'αβΓ' in txt and '✁✂✃' in txt          # text output: still Unicode

    pdf = emit_pdf(doc, mode='printed')
    fonts = _basefonts(pdf)
    assert b'Symbol' in fonts.values() and b'ZapfDingbats' in fonts.values()
    sym = next(n for n, b in fonts.items() if b == b'Symbol')
    ding = next(n for n, b in fonts.items() if b == b'ZapfDingbats')
    shown = _content_text(pdf)
    assert (sym, 12, b'abG') in shown             # alpha is back to 0x61 'a'
    assert (ding, 12, b'!\\"#') in shown or (ding, 12, b'!"#') in shown


def test_pdf_cp437_greek_in_plain_courier_routes_through_symbol_face():
    """b26 fix: cp437 puts Greek/math at 0xE0-0xEE with NO font block
    declaring Symbol at all -- plain WS4/WS7 body text, the "screen chart"
    case (jon_vault's -SCREEN.pcl + .measurements.json: real WS7 prints the
    line αßΓπΣσµτΦΘΩδφε cleanly). Printed PDF's text path (_esc,
    cp1252-encode-with-replace) has no Greek at all, so before this fix
    every one of those 14 characters became '?'. Only the 12 that cp1252
    truly cannot carry route to Symbol -- ß (sharp s) and µ (micro sign)
    are genuine cp1252 characters in their own right (not this bug) and
    stay on the plain Courier face."""
    from ctrlkd.pdf import emit_pdf
    line = 'αßΓπΣσµτΦΘΩδφε'
    data = (ws7_block(0x00)
            + b'Plain prose padding so the detector reads this as a document.'
            + HARD + line.encode('cp437') + HARD
            + b'And a closing line of ordinary prose keeps the ratio honest.'
            + HARD)
    doc = core.parse_ws(data)
    txt = emit.emit_text(doc, mode='printed')
    assert line in txt                             # text formats: untouched

    pdf = emit_pdf(doc, mode='printed')
    fonts = _basefonts(pdf)
    assert b'Symbol' in fonts.values()
    sym = next(n for n, b in fonts.items() if b == b'Symbol')
    cour = next(n for n, b in fonts.items() if b == b'Courier')
    shown = _content_text(pdf)
    assert not any(b'?' in text for _, _, text in shown)  # the whole point
    # split exactly at the cp1252-representable ß/µ, same order as the source
    assert (sym, 12, b'a') in shown
    assert (cour, 12, b'\xdf') in shown             # ss (sharp s) -- cp1252, untouched
    assert (sym, 12, b'GpSs') in shown
    assert (cour, 12, b'\xb5') in shown             # micro sign -- cp1252, untouched
    assert (sym, 12, b'tFQWdfe') in shown

    # Modern PDF and both RTF modes are untouched -- this fix is Printed
    # PDF only (pdf.py's _line_ops_printed, never shared with Modern/RTF).
    pdf_modern = emit_pdf(doc, mode='modern')
    assert b'Symbol' not in _basefonts(pdf_modern).values()
    r_printed = emit.emit_rtf(doc, mode='printed')
    r_modern = emit.emit_rtf(doc, mode='modern')
    # RTF was never routed through cp1252 at all (\uNNNN? unicode escapes,
    # this fix's pdf.py never touched) -- alpha/Gamma/Sigma/Omega present
    # either as \u945/\u915/\u931/\u937 escapes.
    assert '\\u945' in r_printed and '\\u915' in r_printed
    assert '\\u945' in r_modern and '\\u915' in r_modern


def test_pdf_symbol_run_styling_is_synthesized_bold_italic_bold_italic():
    """Finding 1 (b26-print-fidelity-2): Symbol has ONE cut in the base-14
    set, so a b/i span routed there used to lose its styling silently --
    but real WS7 prints all four (plain/bold/italic/bold-italic) visibly
    distinct (measured: -SCREEN.pcl offset 2767, the Greek sample line's
    four `ESC(s...T` groups carry style=0/1 and weight=0/3 flags on the
    SAME typeface/height/pitch, and the four runs measure the SAME 108pt
    advance for 14 glyphs regardless of style -- the driver styled the
    glyph, never the advance). Pinned here bit-for-bit: bold adds `2 Tr`
    (fill+stroke) with a stroke width proportional to size before Ts;
    italic swaps Td for a sheared Tm (~12 degrees) at the SAME (x, y) Td
    would have used; bold-italic does both. An unstyled Symbol run keeps
    its pre-existing Td-only op, untouched."""
    from ctrlkd.pdf import emit_pdf
    line = 'αΓπ'.encode('cp437')          # cp437 Greek, no font block --
                                           # the -SCREEN.WS fallback path
    data = (ws7_block(0x00)
            + b'Plain prose padding so the detector reads this as a document.'
            + HARD + line + HARD
            + b'\x02' + line + b'\x02' + HARD             # bold
            + b'\x19' + line + b'\x19' + HARD             # italic
            + b'\x02\x19' + line + b'\x02\x19' + HARD     # bold-italic
            + b'And a closing line of ordinary prose keeps the ratio honest.'
            + HARD)
    doc = core.parse_ws(data)
    pdf = emit_pdf(doc, mode='printed')
    ops = [m.group(0) for m in re.finditer(rb'BT /F\d+.*?Tj ET', pdf)
          if b'aGp' in m.group(0)]
    assert len(ops) == 4
    plain, bold, italic, bold_italic = ops
    font = re.match(rb'BT /(F\d+)', plain).group(1)
    # plain: untouched, the pre-existing Td-only shape (no Tr/w/Tm at all)
    assert re.fullmatch(
        rb'BT /' + font + rb' 12 Tf 0 Ts (?:[\d.]+ Tz )?'
        rb'-?[\d.]+ -?[\d.]+ Td \(aGp\) Tj ET', plain)
    # bold: 2 Tr (fill+stroke) + a stroke width before Ts, same Td shape
    assert re.fullmatch(
        rb'BT /' + font + rb' 12 Tf (?:[\d.]+ Tz )?2 Tr 0\.48 w 0 Ts '
        rb'-?[\d.]+ -?[\d.]+ Td \(aGp\) Tj ET', bold)
    # italic: Td replaced by a sheared Tm, tan(12deg) ~= 0.2126, no Tr/w
    assert re.fullmatch(
        rb'BT /' + font + rb' 12 Tf (?:[\d.]+ Tz )?0 Ts '
        rb'1 0 0\.2126 1 -?[\d.]+ -?[\d.]+ Tm \(aGp\) Tj ET', italic)
    # bold-italic: both -- stroke AND shear
    assert re.fullmatch(
        rb'BT /' + font + rb' 12 Tf (?:[\d.]+ Tz )?2 Tr 0\.48 w 0 Ts '
        rb'1 0 0\.2126 1 -?[\d.]+ -?[\d.]+ Tm \(aGp\) Tj ET', bold_italic)
    # the three styled runs land at the SAME x the plain run did (styling
    # changes only how the glyph paints, never the run's own position)
    plain_xy = re.search(rb'(-?[\d.]+) (-?[\d.]+) Td', plain).groups()
    bold_xy = re.search(rb'(-?[\d.]+) (-?[\d.]+) Td', bold).groups()
    italic_xy = re.search(rb'1 0 0\.2126 1 (-?[\d.]+) (-?[\d.]+) Tm', italic).groups()
    assert bold_xy[0] == plain_xy[0]
    assert italic_xy[0] == plain_xy[0]


def test_pdf_symbol_run_styling_is_printed_only():
    """The synthesis lives in pdf.py's Printed-only `_line_ops_printed`
    (never shared with Modern, which routes through `_modern_w`/its own
    token font instead -- see BASE14[family] call sites) and never fires
    for a Symbol run with no b/i styling (byte-identical requirement)."""
    from ctrlkd.pdf import emit_pdf
    line = 'αΓπ'.encode('cp437')
    data = (ws7_block(0x00)
            + b'Plain prose padding so the detector reads this as a document.'
            + HARD + b'\x02' + line + b'\x02' + HARD
            + b'And a closing line of ordinary prose keeps the ratio honest.'
            + HARD)
    doc = core.parse_ws(data)
    pdf_printed = emit_pdf(doc, mode='printed')
    assert b'2 Tr' in pdf_printed and b'Tm (aGp) Tj' not in pdf_printed
    pdf_modern = emit_pdf(doc, mode='modern')
    assert b'2 Tr' not in pdf_modern


def test_pdf_courier_beats_the_generic_bits_that_call_it_serif():
    """The trap this ordering exists for: the spec's own font block for
    Courier declares generic_style 'serif' -- honest typography (it is a slab
    serif) and true of 48 of the 121 font blocks in the reference corpus.
    Reading the generic bits before the fixed-pitch names would have set every
    Courier run in Times, the one substitution a typescript facsimile must
    never make. Pica/Elite/LinePrinter go the same way."""
    from ctrlkd.pdf import _pdf_family
    assert _pdf_family({'typestyle_name': 'Courier', 'generic_style': 'serif'}) == 'Courier'
    assert _pdf_family({'typestyle_name': 'Pica', 'generic_style': 'serif'}) == 'Courier'
    assert _pdf_family({'typestyle_name': 'LinePrinter', 'generic_style': 'sans'}) == 'Courier'
    # everything else resolves by the strict serif/sans/mono split (Jon's
    # amendment: no special flavouring for faces we cannot truly represent)
    assert _pdf_family({'typestyle_name': 'Garamond', 'generic_style': 'serif'}) == 'Times'
    assert _pdf_family({'typestyle_name': 'Univers', 'generic_style': 'sans'}) == 'Helvetica'
    assert _pdf_family({'typestyle_name': 'ZapfChancery', 'generic_style': 'script'}) == 'Times'
    assert _pdf_family({'typestyle_name': 'Univ. Roman', 'generic_style': 'display'}) == 'Helvetica'
    assert _pdf_family({'typestyle_name': None, 'generic_style': None}) == 'Courier'
    assert _pdf_family(None) == 'Courier'


def test_symbol_untransliteration_round_trips():
    """The reverse maps are the forward maps read backwards, and the pair has
    to survive the trip: transliterate then untransliterate is identity for
    every byte the faces carry. Characters neither face has degrade to '?',
    the same way the rest of the PDF emitter degrades what it cannot write."""
    from ctrlkd.symbolmap import transliterate, untransliterate
    greek = 'ABCDE abcde 12345 !@#$%'
    assert untransliterate(transliterate(greek, 'math'), 'math') == greek
    dings = '!"#$% ABCDE abcde'
    assert untransliterate(transliterate(dings, 'symbols'), 'symbols') == dings
    assert transliterate('a', 'math') == 'α'
    assert untransliterate('α', 'math') == 'a'          # back to 0x61
    assert untransliterate('♣', 'symbols') == '\xa8'    # the cross-block four
    assert untransliterate('é', 'math') == '?'          # no such glyph there


# ------------------------------------- printed mode on the document's own grid
#
# Jon's ruling, 2026-08-05: "Printed that ignores fonts can't call itself
# Printed." A WS5+ printed PDF must honour the file's own layout arithmetic --
# `.lh` as running state (vertical), the font blocks' HMI advances (horizontal),
# and Tz width-matching so a proportional face lands on that horizontal grid.

def test_lh_is_stateful_each_line_keeps_the_lead_it_was_set_at():
    """`.lh` applies from where it appears, like `.oc` and `.lm` -- it is not a
    once-per-document page property. The page dict still resolves the FIRST
    occurrence (that is the document default, and what capacity is computed
    at); every line additionally carries the lead in force where IT sat.

    Before this, a document that switched leading around its headings had all
    of it collapsed onto one value, which is how 72pt banners came to be
    stacked on a 14pt lead."""
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) +
            b'.lh 8' + HARD +
            b'Prose padding so the detector reads this as a document, plainly.' + HARD +
            b'.lh 16' + HARD +
            b'A tall line that must sit on its own sixteen forty-eighths lead.' + HARD +
            b'.lh 8' + HARD +
            b'Back to six lines per inch for the rest of this small document.' + HARD)
    doc = core.parse_ws(data)
    assert doc.meta['variant'] == 'ws5+'
    lines = [ln for b in doc.blocks for ln in b.lines]
    # first-wins page default is 8; only the line set at 16 carries a lead
    assert doc.meta['page']['lh_48'] == 8.0
    assert doc.meta['page']['lh_varies'] is True
    assert [ln.lead_48 for ln in lines] == [None, 16.0, None]

    # ...and the PDF advances by it. `.lh 16` = 16/48in = 24pt; the default
    # `.lh 8` = 12pt. A lead is the space ABOVE its own line (it is a printer
    # VMI: the feed onto the line uses the value set before it), so the gap
    # from line 1 to line 2 is the TALL line's 24pt and the gap from 2 to 3 is
    # the 12pt the file went back to.
    ys = [y for _f, _sz, _tz, _x, y, _t in _content_spans(emit_pdf(doc, 'printed'))]
    assert ys[0] - ys[1] == 24.0
    assert ys[1] - ys[2] == 12.0

    # PAGE CAPACITY deliberately stays on the document default -- 66-3-8 lines
    # at .lh 8 = 55. Whether WordStar recomputed lines-per-page as `.lh`
    # changed is UNMEASURED (register open question #15), and every way of
    # guessing repaginates real documents on an assumption. See pdf._printed_cap.
    assert doc.meta['page']['text_lines'] == 55


def test_lh_before_the_first_one_is_wordstars_own_default_not_the_files():
    """The document default is the FIRST `.lh`, so a file that sets `.lh 16`
    after some text does not back-date it: those earlier lines really printed
    at WordStar's own 8/48, and they say so explicitly."""
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.' + HARD +
            b'.lh 16' + HARD +
            b'A second line, now at sixteen forty-eighths of an inch of lead.' + HARD)
    doc = core.parse_ws(data)
    lines = [ln for b in doc.blocks for ln in b.lines]
    assert doc.meta['page']['lh_48'] == 16.0            # first occurrence wins
    assert [ln.lead_48 for ln in lines] == [8.0, None]  # 8.0 is stated, not assumed


def test_printed_x_comes_from_wordstars_own_hmi_arithmetic():
    """Each span starts where WordStar's own per-character advance puts it:
    the characters before it, each at its run's HMI width (1/1800in). 1800 HMI
    is one inch is 72 points, so a run declaring 1800 advances 72pt per
    character and the span after two of them starts 144pt along."""
    from ctrlkd.pdf import emit_pdf, _printed_left, _printed_size
    helv = _helv_typestyle()
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.' + HARD +
            _font_block(helv, 72.0, width=1800) + b'AA' +
            _font_block(helv, 12.0, width=180) + b'B' + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.' + HARD)
    doc = core.parse_ws(data)
    left = _printed_left(doc, _printed_size(doc))
    spans = _content_spans(emit_pdf(doc, 'printed'))
    aa = next(s for s in spans if s[5] == b'AA')
    b = next(s for s in spans if s[5] == b'B')
    assert aa[3] == round(left, 1)                       # first span at the margin
    assert b[3] == round(left + 2 * 72.0, 1)             # 2 chars x 1800 HMI


def test_tz_matches_a_proportional_span_to_the_hmi_grid():
    """Times/Helvetica do not set a word in the width WordStar reserved for
    it, so a genuinely proportional span (round 9: `proportional=True` is
    what puts it on this path at all -- see pdf._pdf_family) is scaled
    horizontally (Tz) until it does. Round 9 also surfaced that the scale
    is FACE-CONSTANT (`_face_tz`), not a per-span exact match -- one
    percentage per (face, pitch, size), chosen so the face's AVERAGE
    lowercase character lands on the document's own HMI grid, so a lone
    wide glyph is never crushed (Jon's ruling, 2026-08-05: "a lone (c)
    squeezed to 70% is not a circle"). Computed, never tabulated here."""
    from ctrlkd.pdf import emit_pdf, _printed_left, _face_tz
    helv = _helv_typestyle()
    # round 9: proportional bit set -- a real 'Helv' record IS proportional,
    # and that flag now decides Helvetica vs Courier (see pdf._pdf_family).
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.' + HARD +
            _font_block(helv, 12.0, width=180, style_bits=0x8000) + b'AAAA' + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.' + HARD)
    doc = core.parse_ws(data)
    span = next(s for s in _content_spans(emit_pdf(doc, 'printed')) if s[5] == b'AAAA')
    expected = _face_tz('Helvetica', 180 / 25.0, 12)     # 180 HMI = 7.2pt pitch
    assert span[2] == expected
    assert 100.0 < span[2] < 250.0       # Helvetica's AVERAGE lowercase glyph is
                                          # NARROWER than WordStar's 10-CPI cell, so
                                          # the constant STRETCHES it to the grid,
                                          # not squeezes it (contrast a single "AAAA"
                                          # span's own wide caps, irrelevant here --
                                          # the scale is the face's, not the span's)


def test_tz_is_100_for_courier_by_arithmetic_not_by_special_case():
    """Courier is 600/1000 em and the fontless pitch is 0.6 em by derivation
    from `.cw`, so the ratio comes out exactly 100 and NO Tz operator is
    written at all. Nothing in the emitter tests for Courier to make this
    happen -- it falls out of the same arithmetic every other face goes
    through, which is the point: if the metrics and the grid ever disagreed
    for Courier we would want to see it, not hide it."""
    from ctrlkd.pdf import emit_pdf, _tz_scale
    from ctrlkd.typestyles import TYPESTYLE_NAMES
    cour = next(k for k, v in TYPESTYLE_NAMES.items() if v.lower().startswith('courier'))
    assert _tz_scale('Hello', 'Courier', 12, 5 * 180 / 25.0) == (None, 5 * 7.2)
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.' + HARD +
            _font_block(cour, 12.0, width=180) + b'Typescript.' + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.' + HARD)
    pdf = emit_pdf(core.parse_ws(data), 'printed')
    assert b' Tz' not in pdf


def test_tz_clamp_falls_back_to_the_natural_advance():
    """A ratio outside [40, 250] means the file's HMI and the substituted
    base-14 face disagree pathologically -- a typestyle we can only
    approximate, a printer pitch with nothing to do with the face it
    resolved to. Scaling to obey it would produce glyphs stretched past
    legibility in the name of fidelity, so the span keeps its natural
    advance instead and the following span moves with it.

    Round 9: this is `_tz_scale`'s OWN per-span clamp, exercised through
    the real pdf.py pipeline via a record with `proportional=False` (style
    _bits left at the default 0 -- unlike the OTHER Tz tests, this one
    deliberately does NOT set 0x8000). A genuinely proportional record
    (Helv with the bit set) never reaches `_tz_scale` at all any more --
    see `_line_ops_printed`'s own proportional branch, which routes to the
    face-constant `_face_tz` instead and has no natural-advance fallback of
    its own (it clamps to a constant scale, it does not give up). The
    still-real, still-reachable mismatch this test demonstrates is a
    proportional=False record (typestyle number irrelevant -- the name
    plays no part once the bit says False) whose OWN declared HMI is
    absurd relative to Courier's real metrics, e.g. a 1-inch-per-character
    pitch: even Courier's arithmetic disagrees with that pathologically."""
    from ctrlkd.pdf import emit_pdf, _tz_scale, _printed_left, TZ_MIN, TZ_MAX
    from ctrlkd.afm import string_width_pt
    helv = _helv_typestyle()
    # in range -> scaled to the grid; out of range -> natural, no operator
    assert _tz_scale('AA', 'Helvetica', 12, 40.0)[0] is not None
    assert _tz_scale('AA', 'Helvetica', 12, 400.0) == (
        None, string_width_pt('AA', 'Helvetica', 12))
    assert _tz_scale('AA', 'Helvetica', 12, 0.1) == (
        None, string_width_pt('AA', 'Helvetica', 12))
    assert TZ_MIN == 40.0 and TZ_MAX == 250.0

    # 1800 HMI at 12pt asks for 72pt per character where Courier sets ~7.2
    # -- a 900% stretch. The span is left alone and the next one follows it
    # at its NATURAL width, not on the abandoned grid. `helv`'s typestyle
    # NUMBER is reused only for convenience (it exists in the table); the
    # proportional bit is what matters, and it is False here (the default),
    # so `_pdf_family` selects Courier regardless of the "Helv" name.
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.' + HARD +
            _font_block(helv, 12.0, width=1800) + b'AA' +
            _font_block(helv, 12.0, width=180) + b'B' + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.' + HARD)
    doc = core.parse_ws(data)
    left = _printed_left(doc, 12)
    spans = _content_spans(emit_pdf(doc, 'printed'))
    aa = next(s for s in spans if s[5] == b'AA')
    b = next(s for s in spans if s[5] == b'B')
    assert aa[2] is None                                  # no scaling written
    assert b[3] == round(left + string_width_pt('AA', 'Courier', 12), 1)


def test_tz_is_written_only_when_it_changes_because_it_is_text_state():
    """Tz survives ET: it is text state, not a property of one text object. An
    85 set on a banner would silently scale every following span in the same
    content stream, so the operator is written on CHANGE only -- which is also
    why a document that never needs it emits none (see the byte-identity
    digests).

    Round 9: for a genuinely proportional record, Tz is FACE-CONSTANT
    (`_face_tz`, keyed on face+pitch+size) -- two spans in the SAME font
    block get the identical value regardless of which characters they
    hold (unlike the old per-span `_tz_scale` model this test originally
    exercised, where a caps-heavy span and a lowercase span could differ).
    "Changes" now genuinely means the (face, pitch, size) key changed --
    demonstrated here with a second font block at a DIFFERENT declared
    pitch, still Helv, still proportional."""
    from ctrlkd.pdf import emit_pdf
    helv = _helv_typestyle()
    # round 9: proportional bit set, as above.
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.' + HARD +
            _font_block(helv, 12.0, width=180, style_bits=0x8000) + b'Wide' +
            _font_block(helv, 12.0, width=180, style_bits=0x8000) + b'Wide' + HARD +
            _font_block(helv, 12.0, width=240, style_bits=0x8000) + b'Different' + HARD)
    spans = _content_spans(emit_pdf(core.parse_ws(data), 'printed'))
    scaled = [s for s in spans if s[5] == b'Wide']
    assert len(scaled) == 2
    assert scaled[0][2] is not None                       # first sets the scaling
    assert scaled[1][2] is None                           # same (face, pitch, size)
                                                            # key: nothing to say
    # ...and the next span at a DIFFERENT declared pitch (240 vs 180 HMI)
    # gets its own face-constant Tz, written out rather than inherited.
    different = next(s for s in spans if s[5] == b'Different')
    assert different[2] is not None and different[2] != scaled[0][2]


def test_leading_tab_indent_measures_in_print_columns_not_the_font():
    """WordStar expands a tab to its stop in 10-CPI PRINT COLUMNS (`.tb` and
    `.lm` are specified there, and core._tab_columns converts the tab's HMI
    size to columns before emitting the padding). Run that padding at a 72pt
    display font's own advance instead and a one-column offset becomes a
    six-inch one -- which is exactly how the archive's banner document, which
    tabs to 1.39in and then 1.4in to print a word twice with a 0.1in shadow,
    threw its second copy off the right edge of the paper."""
    from ctrlkd.pdf import emit_pdf, _printed_left
    helv = _helv_typestyle()
    tab = ws7_block(0x09, (2502).to_bytes(2, 'little') * 2 + b' \r')   # 1.39in
    # 0x8000: the proportional bit -- the evidence font (the archive banner's
    # Antique Olive) is proportional, and the document-column indent rule is
    # scoped to proportional runs (a fixed-pitch font's spaces advance at its
    # own pitch: LJ6DTP's PC-8 chart border, 2026-08-05)
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.' + HARD +
            _font_block(helv, 72.0, width=1064, style_bits=0x8000) + tab + b'X' + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.' + HARD)
    doc = core.parse_ws(data)
    left = _printed_left(doc, 12)
    x = next(s[3] for s in _content_spans(emit_pdf(doc, 'printed')) if s[5] == b'X')
    assert x == round(left + 14 * 12 * 0.6, 1)     # 14 columns at 10 CPI, not
                                                    # 14 x the 72pt font's 42.6pt


# ---- the wholesale-defaults batch (CLI-Defaults-Audit, all ruled 2026-08-05)

def _run_cli_defaults(tmp_path, args, name='DOC.WS', data=None):
    from ctrlkd import cli
    import io, contextlib
    src = tmp_path / name
    src.write_bytes(data if data is not None else make_prose())
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        cli.main([str(src)] + args)
    return src, err.getvalue()

def test_bare_invocation_is_modern_rtf(tmp_path):
    # THE ruling: "the converter is about bringing the old docs to a modern
    # audience" -- no flags means Modern RTF, Georgia 14 body, modern page.
    src, _ = _run_cli_defaults(tmp_path, [])
    out = (tmp_path / 'DOC.rtf').read_text()
    assert out.startswith(r'{\rtf1')
    assert r'{\f0 Georgia{\*\falt Times New Roman};}' in out
    assert r'\f0\fs28' in out                       # the cozy-book 14pt
    assert r'\paperw12240' in out and r'\margl1440' in out

def test_printed_mode_defaults_to_pdf(tmp_path):
    src, _ = _run_cli_defaults(tmp_path, ['--mode', 'printed'])
    pdf = (tmp_path / 'DOC.pdf').read_bytes()
    assert pdf.startswith(b'%PDF-1.4')

def test_page_settings_presets(tmp_path):
    # sawyer: the DEFAULT.PAT machine (mt ~0.83in -> margt 1195/1440*1440
    # twips = 1195... in lines*240: 4.979*240 = 1195); default: factory page.
    _run_cli_defaults(tmp_path, ['--mode', 'printed', '-t', 'rtf',
                        '--page-settings', 'sawyer'])
    rtf = (tmp_path / 'DOC.rtf').read_text()
    assert r'\margt1195' in rtf and r'\margb1440' in rtf and r'\margl1008' in rtf
    _run_cli_defaults(tmp_path, ['--mode', 'printed', '-t', 'rtf',
                        '--page-settings', 'default'])
    rtf = (tmp_path / 'DOC.rtf').read_text()
    assert r'\margt720' in rtf and r'\margb1920' in rtf     # factory 0.5/1.33in

def test_force_flag_is_accepted(tmp_path):
    _run_cli_defaults(tmp_path, ['--force'])
    assert (tmp_path / 'DOC.rtf').exists()

def test_forced_printed_notice_on_explicit_modern(tmp_path):
    # D5: a print stream cannot reflow; an EXPLICIT --mode modern gets one
    # stderr line saying so. The default (no --mode) stays quiet.
    stream = b'Line one of a printed page\r\nLine two of it\r\n\x1a'
    _, err = _run_cli_defaults(tmp_path, ['--mode', 'modern', '-t', 'text'],
                      name='CAP.PRN', data=stream)
    assert 'modern reflow is not possible' in err
    _, err = _run_cli_defaults(tmp_path, ['-t', 'text'], name='CAP2.PRN', data=stream)
    assert 'modern reflow' not in err

def test_modern_pdf_is_the_printed_modern_rtf():
    # Ruling: one content model for Modern; PDF is its paper form. Document
    # fonts carried (base-14 mapped), fontless body Times 14, footnotes at
    # the page bottom behind the 20-dash separator.
    from ctrlkd.pdf import emit_pdf
    pdf = emit_pdf(core.parse_ws(make_prose()), 'modern')
    assert b'/BaseFont /Times-Roman' in pdf
    assert b' 14 Tf' in pdf                        # sophisticated size
    assert b'/BaseFont /Courier' in pdf            # the four are still emitted
    assert b'Tf 0 Ts' in pdf
    helv = _helv_typestyle()
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.'
            + HARD + _font_block(helv, 18.0, width=250, style_bits=0x8000)
            + b'Styled in a real face.' + HARD)
    pdf2 = emit_pdf(core.parse_ws(data), 'modern')
    assert b'/BaseFont /Helvetica' in pdf2
    assert b'/F5 18 Tf' in pdf2 or b' 18 Tf' in pdf2

def test_modern_pdf_page_bottom_footnotes():
    from ctrlkd.pdf import emit_pdf
    note = ws7_note(0x03, b'A note that lands at the page bottom.', number=0)
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.'
            + HARD + b'The referenced line' + note + b' continues after.'
            + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.'
            + HARD)
    doc = core.parse_ws(data)
    assert doc.notes
    pdf = emit_pdf(doc, 'modern')
    assert b'--------------------' in pdf          # the 20-dash separator
    # note text renders word-per-op; check words, and that they sit BELOW
    # the body (page-bottom = smaller y than every body line)
    assert b'(bottom.)' in pdf
    import re as _re2
    ys = [(float(m.group(1)), m.group(2))
          for m in _re2.finditer(rb'[\d.]+ ([\d.]+) Td \((.*?)\) Tj', pdf)]
    note_y = next(y for y, t in ys if t == b'bottom.')
    body_y = next(y for y, t in ys if b'referenced' in t)
    assert note_y < body_y


# ====================== Modern layout rulings (2026-08-06) ==================
#
# Jon's second Modern review round, all six rulings: endnotes to the document
# end, block margins honored, editor-time alignment de-duplicated, only the
# author's blank lines make space, running heads kept, and driver character
# substitutions are content. The printed digests above must NOT move.

def _td_ops6(pdf):
    """(x, y, text) for every one-word show op, in stream order."""
    return [(float(m.group(1)), float(m.group(2)), m.group(3))
            for m in re.finditer(
                rb'([\d.-]+) ([\d.-]+) Td \(((?:\\.|[^)\\])*)\) Tj', pdf)]


def test_modern_pdf_endnotes_collect_at_document_end():
    """Ruling 1: Word sends \\ftnalt notes to the back, and Modern PDF is the
    printed Modern RTF -- so endnotes flow after the last body line (never
    the page-bottom footnote area), inline-marked in Word's own lowercase
    roman so footnote [1] and endnote [i] cannot collide."""
    from ctrlkd.pdf import emit_pdf
    note = ws7_note(0x04, b'The endnote text itself.', number=0)
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.'
            + HARD + b'The referenced line' + note + b' continues after.'
            + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.'
            + HARD)
    doc = core.parse_ws(data)
    pdf = emit_pdf(doc, 'modern')
    ops = _td_ops6(pdf)
    assert any(t == b'i' for _, _, t in ops)          # inline roman marker
    label_y = next(y for _, y, t in ops if t == b'[i]')
    last_body_y = next(y for _, y, t in ops if t == b'honest.')
    assert 0 < last_body_y - label_y < 80             # flows just below body
    assert label_y > 300                              # not bottom-anchored


def test_modern_outputs_all_carry_the_footnote_marker_and_text():
    # b26 notes wave, Fix 1 (field-reported): "Modern outputs omit the
    # footnote text entirely." Cross-format pin, oracle-shaped (-SCREEN.WS:
    # inline superscript marker + the note text surviving somewhere in the
    # document) -- every Modern emitter must carry BOTH the inline marker
    # and the footnote's own text for a plain footnote-bearing document.
    # Each emitter's own convention for WHERE the text lands differs (text/
    # markdown/HTML/RTF: a trailing Footnotes section or a real Word
    # footnote destination; PDF: the page-bottom area, same as Printed) --
    # this test follows each emitter's own documented shape rather than
    # inventing one, per the fix's own instruction to read existing
    # convention first. All six assertions already pass against current
    # main (no production change was needed for this one) -- this is
    # regression coverage, not a fail-first pin.
    from ctrlkd.pdf import emit_pdf
    note = ws7_note(0x03, b'The footnote text itself.', number=0)
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.'
            + HARD + b'The referenced line' + note + b' continues after.'
            + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.'
            + HARD)
    doc = core.parse_ws(data)
    t = emit.emit_text(doc, mode='modern')
    assert '[1]' in t and 'The footnote text itself.' in t
    md = emit.emit_markdown(doc, mode='modern')
    assert '[^1]' in md and '[^1]: The footnote text itself.' in md
    h = emit.emit_html(doc, mode='modern')
    assert 'role="doc-noteref"' in h and 'The footnote text itself.' in h
    assert 'role="doc-endnotes"' in h                 # the Footnotes section itself
    r = emit.emit_rtf(doc, mode='modern')
    assert r.count(r'\*\footnote') >= 1 and 'The footnote text itself.' in r
    pdf = emit_pdf(doc, 'modern')
    words = re.findall(rb'\(((?:\\.|[^)\\])*)\)\s*Tj', pdf)
    joined = b' '.join(words)
    assert b'footnote' in joined and b'itself.' in joined  # note area text present
    assert any(w == b'1' for w in words)               # inline superscript marker


def test_modern_pdf_block_margins_indent_and_narrow_the_measure():
    """Ruling 2: a block's own .lm/.rm are the document's explicit choices
    and win in Modern exactly as its fonts do. WordStar's stamped .lm spaces
    come off the front so the indent isn't applied twice."""
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) +
            b'Full width prose before the quotation, ordinary and plain.'
            + HARD + b'.lm 8' + HARD + b'.rm 58' + HARD +
            b'       An indented quotation, with enough words in it that the '
            b'line has to wrap inside its own narrowed measure to pass.'
            + HARD + b'.lm 1' + HARD + b'.rm 65' + HARD +
            b'Back to the full measure after the quotation ends here.' + HARD)
    doc = core.parse_ws(data)
    pdf = emit_pdf(doc, 'modern')
    ops = _td_ops6(pdf)
    x_quote = next(x for x, _, t in ops if t == b'An')
    x_back = next(x for x, _, t in ops if t == b'Back')
    assert abs(x_quote - (72 + 7 * 7.2)) < 0.1        # .lm 8 = 7 columns in
    assert abs(x_back - 72) < 0.1


def test_modern_alignment_tag_strips_the_spaces_that_implemented_it():
    """Ruling 3: WordStar 5+ aligned at EDITOR time -- the file carries both
    the tag and the spaces that implemented it. The spaces come off and the
    tag does the work; the visible text lands dead center of the measure."""
    from ctrlkd.pdf import emit_pdf
    from ctrlkd.afm import string_width_pt
    data = (ws7_block(0x00) +
            b'Padding prose line one, entirely ordinary text, for balance.'
            + HARD + b'.oc on' + HARD +
            b'                    Centered Headline' + HARD +
            b'.oc off' + HARD +
            b'More plain prose to close the document, again fully ordinary.'
            + HARD)
    doc = core.parse_ws(data)
    pdf = emit_pdf(doc, 'modern')
    ops = _td_ops6(pdf)
    x = next(x for x, _, t in ops if t == b'Centered')
    w = string_width_pt('Centered Headline', 'Times-Roman', 14)
    assert abs(x - (72 + (468 - w) / 2)) < 0.5


def test_modern_dot_command_block_split_invents_no_blank():
    """Ruling 4: command codes are invisible -- a block boundary made by a
    dot command adds no space; the author's own blank line still does."""
    from ctrlkd.pdf import emit_pdf

    def gap(mid):
        doc = core.parse_ws(
            ws7_block(0x00) +
            b'First paragraph line of plain prose, long enough to matter.'
            + HARD + mid +
            b'Second paragraph line of plain prose, also long enough.' + HARD)
        ops = _td_ops6(emit_pdf(doc, 'modern'))
        y1 = next(y for _, y, t in ops if t == b'First')
        y2 = next(y for _, y, t in ops if t == b'Second')
        return y1 - y2

    assert abs(gap(b'.cp 4' + HARD) - 16.8) < 0.1     # dot command: one lead
    assert abs(gap(HARD) - 33.6) < 0.1                # author blank: two


def test_modern_running_heads_replay_with_page_numbers():
    """Ruling 5: Modern keeps headers. They replay per page (state in force
    when the page takes content), live in the top margin zone, and WordStar's
    # token becomes the page number."""
    from ctrlkd.pdf import emit_pdf
    doc = core.parse_ws(
        ws7_block(0x00) + b'.he Chapter / #' + HARD +
        b'Page one prose, plain and ordinary, enough for the detector.'
        + HARD + b'.pa' + HARD +
        b'Page two prose, also plain and ordinary, and long enough too.'
        + HARD)
    pdf = emit_pdf(doc, 'modern')
    streams = re.findall(rb'stream\r?\n(.*?)endstream', pdf, re.S)
    assert len(streams) >= 2
    for pi, s in enumerate(streams[:2]):
        ops = _td_ops6(s)
        assert any(t == b'Chapter' and y > 720 for _, y, t in ops)
        assert any(t == str(pi + 1).encode() and y > 720 for _, y, t in ops)


def test_modern_rtf_carries_running_heads_and_strips_align_spaces():
    """Rulings 3 and 5 on the RTF side: a real \\header destination with
    Word's own \\chpgn page number, and center/right paragraphs shed the
    spaces that implemented their alignment."""
    doc = core.parse_ws(ws7_block(0x00) + b'.he Chapter / #' + HARD +
                        b'.oc on' + HARD +
                        b'          A Centered Title' + HARD +
                        b'.oc off' + HARD +
                        b'Plain closing prose, quite ordinary and long.' + HARD)
    rtf = emit.emit_rtf(doc, 'modern')
    assert r'{\header \pard\plain \f0\fs22 {Chapter / {\chpgn }}\par}' in rtf
    assert 'A Centered Title' in rtf
    assert '  A Centered Title' not in rtf            # the tag does the work


def test_modern_rtf_dot_command_split_invents_no_par():
    """Ruling 4 on the RTF side: \\par count between paragraphs follows the
    author's blank lines, never the block structure."""
    def rtf_for(mid):
        doc = core.parse_ws(
            ws7_block(0x00) +
            b'First paragraph line of plain prose, long enough to matter.'
            + HARD + mid +
            b'Second paragraph line of plain prose, also long enough.' + HARD)
        return emit.emit_rtf(doc, 'modern')

    tight = rtf_for(b'.cp 4' + HARD)
    seg = tight[tight.find('matter.'):tight.find('Second')]
    assert seg.count(r'\par') == 1
    spaced = rtf_for(HARD)
    seg = spaced[spaced.find('matter.'):spaced.find('Second')]
    assert seg.count(r'\par') == 2


def test_modern_applies_lj6dtp_character_substitutions():
    """Ruling 7: the driver's patched slots are CONTENT -- an em dash is an
    em dash in any century -- so Modern applies them (proportional faces
    only, the driver's own rule). The page art stays print-time."""
    from ctrlkd.pdf import emit_pdf
    prop = _font_block(_helv_typestyle(), 12.0, style_bits=0x8000)
    data = (_ws_block(0x00, b'pLJ6DTP\x00\x00\x00\x80') +
            prop + b'word_word' + HARD +
            b'Plain padding prose, ordinary and long enough to balance it.'
            + HARD)
    doc = core.parse_ws(data)
    assert doc.meta['printer_driver'] == 'LJ6DTP'
    pdf = emit_pdf(doc, 'modern')
    assert b'word\x97word' in pdf                     # '_' -> em dash (cp1252)


def test_note_refs_prefixed_scheme_matches_markdown_labels():
    """Ruling 2026-08-06 (round 2 follow-up): --note-refs prefixed shows the
    Markdown emitter's own labels -- footnotes bare, endnotes e1, annotations
    a1 -- in PDF, RTF, and HTML alike. `word` (the default) stays exactly
    what displayed before: arabic/roman/tags. Ids and structure never move;
    only the visible mark text does."""
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.'
            + HARD + b'One' + ws7_note(0x03, b'Foot text.', number=0)
            + b' two' + ws7_note(0x04, b'End text.', number=0)
            + b' three' + ws7_note_with_tag(0x05, b'Anno text.', number=0)
            + b' done.' + HARD +
            b'A closing line of ordinary prose keeps the byte ratio honest.'
            + HARD)
    doc = core.parse_ws(data)

    pdf = emit_pdf(doc, 'modern', note_refs='prefixed')
    ops = _td_ops6(pdf)
    texts = [t for _, _, t in ops]
    assert b'e1' in texts and b'[e1]' in texts        # endnote, inline + end
    assert b'a1' in texts and b'[a1]' in texts        # annotation likewise
    assert b'i' not in texts                          # no roman under prefixed

    rtf = emit.emit_rtf(doc, 'modern', note_refs='prefixed')
    assert r'{\super e1}' in rtf                      # custom mark, not \chftn
    assert r'{\super a1}' in rtf
    word = emit.emit_rtf(doc, 'modern')
    assert r'{\super e1}' not in word                 # default keeps \chftn

    html = emit.emit_html(doc, 'modern', note_refs='prefixed')
    assert '>e1</a></sup>' in html
    assert 'id="enref1"' in html                      # ids stay structural


# ================= Comments become first-class (2026-08-06) =================
#
# Both WordStar comment forms -- ^ON note blocks and '..'/'.ig' dot lines --
# unify into Note(kind='comment') with `origin` provenance, each emitting a
# reference mark at its position (position, not ink). --comments stays the
# visibility gate; printed is always silent about them.

def test_both_comment_origins_unify_and_refs_stay_aligned():
    data = (ws7_block(0x00) +
            b'.. a disabled command lives here' + HARD +
            b'First line of prose, referencing'
            + ws7_note(0x03, b'The footnote text.', number=0) + b' a note.'
            + HARD + b'.ig the long-form comment syntax' + HARD +
            b'Second line of prose to close the document, quite plainly.'
            + HARD)
    doc = core.parse_ws(data)
    comments = [n for n in doc.notes if n.kind == 'comment']
    assert [c.origin for c in comments] == ['..', '.ig']
    assert comments[0].text == 'a disabled command lives here'
    # the mark BEFORE the footnote must not derail its resolution: the
    # footnote still renders as footnote 1 in every format
    md = emit.emit_markdown(doc, 'modern')
    assert '[^1]' in md and '[^1]: The footnote text.' in md
    from ctrlkd.pdf import emit_pdf
    ops = _td_ops6(emit_pdf(doc, 'modern'))
    assert any(t == b'[1]' for _, _, t in ops)        # page-bottom footnote


def test_comments_hidden_by_default_and_printed_always_silent():
    data = (ws7_block(0x00) +
            b'Visible prose line one, plain and ordinary for the detector.'
            + HARD + b'.. the hidden aside' + HARD +
            b'Visible prose line two, also plain and entirely ordinary.'
            + HARD)
    doc = core.parse_ws(data)
    from ctrlkd.pdf import emit_pdf
    for out in (emit.emit_text(doc, 'modern'), emit.emit_markdown(doc, 'modern'),
                emit.emit_html(doc, 'modern'), emit.emit_rtf(doc, 'modern')):
        assert 'hidden aside' not in out              # gate stays closed
    keep = emit.ALL_NOTE_KINDS
    for out in (emit.emit_text(doc, 'printed', notes=keep),
                emit.emit_rtf(doc, 'printed', notes=keep)):
        assert 'hidden aside' not in out              # printed: never
    assert b'hidden aside' not in emit_pdf(doc, 'printed', notes=keep)


def test_comments_opted_in_render_positioned_with_origin():
    data = (ws7_block(0x00) +
            b'Alpha prose line, plain and ordinary, before the comment.'
            + HARD + b'.. the surfaced aside' + HARD +
            b'Omega prose line, plain and ordinary, after the comment.'
            + HARD)
    doc = core.parse_ws(data)
    keep = emit.ALL_NOTE_KINDS
    from ctrlkd.pdf import emit_pdf
    ops = _td_ops6(emit_pdf(doc, 'modern', notes=keep))
    texts = [t for _, _, t in ops]
    assert b'[c1]' in texts                           # end block, c-labeled
    assert b'c1' not in texts                         # word scheme: markless
    ops = _td_ops6(emit_pdf(doc, 'modern', notes=keep, note_refs='prefixed'))
    assert b'c1' in [t for _, _, t in ops]            # prefixed: visible mark
    md = emit.emit_markdown(doc, 'modern', notes=keep)
    assert '[^c1]' in md and '[^c1]: the surfaced aside' in md
    rtf = emit.emit_rtf(doc, 'modern', notes=keep)
    assert rtf.index('Alpha') < rtf.index('the surfaced aside') < rtf.index('Omega')
    html = emit.emit_html(doc, 'modern', notes=keep)
    assert 'data-note-kind="comment"' in html


def test_dot_comment_before_blank_creates_no_phantom_line():
    """The mark defers to the next CONTENT line: a '..' line followed by the
    author's blank must not close a phantom line holding only the mark --
    printed line structure is identical with and without the comment."""
    from ctrlkd.pdf import emit_pdf
    base = (b'First paragraph line of plain prose, long enough to matter.'
            + HARD + b'%s' + HARD +
            b'Second paragraph line of plain prose, also long enough.' + HARD)
    with_c = core.parse_ws(ws7_block(0x00) +
                           (b'First paragraph line of plain prose, long enough to matter.'
                            + HARD + b'.. noise' + HARD + HARD +
                            b'Second paragraph line of plain prose, also long enough.' + HARD))
    without = core.parse_ws(ws7_block(0x00) +
                            (b'First paragraph line of plain prose, long enough to matter.'
                             + HARD + HARD +
                             b'Second paragraph line of plain prose, also long enough.' + HARD))
    assert emit_pdf(with_c, 'printed') == emit_pdf(without, 'printed')


def test_running_head_toggle_bytes_become_styles_not_glyphs():
    """Round 3 (2026-08-06): LJ6DTP's `.h1` carries raw ^B bold toggles and
    a U+2219 dot; measuring toggles as glyphs made header letters overlap.
    hf_runs interprets them as styles, maps the dot to the cp1252 bullet,
    and a control-bytes-only head (LJ6DTP's `.f1` = two 0x0F bytes) empties
    out entirely."""
    from ctrlkd.emit import hf_runs
    runs = hf_runs('  \x02\x02Title ∙ #\x02 tail')
    assert runs[0] == ('  ', frozenset())            # baked spaces survive
    texts = ''.join(t for t, _ in runs)
    assert '\x02' not in texts and '∙' not in texts and '•' in texts
    assert any('b' in s for _, s in runs)            # bold recognized
    assert hf_runs('\x0f\x0f') == []                 # junk head -> nothing
    # end-to-end: a doc with a toggle-carrying head renders overlap-free
    # (words strictly ordered, no negative advance) in the modern PDF
    from ctrlkd.pdf import emit_pdf
    doc = core.parse_ws(ws7_block(0x00) +
                        b'.he \x02Big Bold Header\x02 / #' + HARD +
                        b'Page one prose, plain and ordinary and long enough.'
                        + HARD + b'.pa' + HARD +
                        b'Page two prose, also plain, ordinary, long enough.'
                        + HARD)
    pdf = emit_pdf(doc, 'modern')
    first = re.search(rb'stream\r?\n(.*?)endstream', pdf, re.S).group(1)
    hdr = [(x, t) for x, y, t in _td_ops6(first) if y > 720]
    words = [t for _, t in hdr]
    assert b'Big' in words and b'\x02Big' not in words
    xs = [x for x, _ in hdr]
    assert xs == sorted(xs)                          # strictly left-to-right


def test_modern_draws_fontless_cp437_square_bullet_as_vector():
    """Round 3 (2026-08-06): -README's list bullets are cp437 0xFE black
    squares in FONTLESS spans -- no cp1252 slot, and the graphics vector
    path used to require a font entry, so they rendered '?'. Modern now
    draws the geometry for fontless spans too; printed keeps its
    fontless-untouched doctrine (digests prove it)."""
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) +
            b'A paragraph of ordinary prose before the bulleted list here.'
            + HARD + b'\xfe First item of the list, plain prose and clear.'
            + HARD +
            b'A closing paragraph of ordinary prose after the list ends.'
            + HARD)
    doc = core.parse_ws(data)
    pdf = emit_pdf(doc, 'modern')
    assert b'(?' not in pdf                       # no mangled bullet
    assert b're f' in pdf                         # a filled vector rect
    ops = _td_ops6(pdf)
    assert any(t == b'First' for _, _, t in ops)  # text continues after it


# ================= The layout façade (task #15, 2026-08-06) =================

def test_modern_flow_is_the_public_semantic_contract():
    """layout.modern_flow is the single implementation of the M-rules,
    consumed by the PDF's measuring adapter, the Mac app's text stack, and
    the `layout` JSON emitter. Items are plain JSON-safe dicts; columns,
    not points -- consumers convert with their own metrics."""
    import json
    from ctrlkd.layout import modern_flow
    data = (ws7_block(0x00) + b'.oc on' + HARD +
            b'     A Centered Heading' + HARD + b'.oc off' + HARD +
            b'.lm 8' + HARD +
            b'       An indented quotation line, plain prose and clear.'
            + HARD + b'.lm 1' + HARD +
            b'Body prose at the full measure'
            + ws7_note(0x03, b'A footnote.', number=0) + b' continues.'
            + HARD)
    doc = core.parse_ws(data)
    sem = modern_flow(doc)
    json.dumps(sem)                                   # JSON-safe throughout
    paras = [i for i in sem['items'] if i['kind'] == 'para']
    centered = next(p for p in paras if p['align'] == 'center')
    assert centered['runs'][0]['text'].startswith('A Centered')  # M3 strip
    quote = next(p for p in paras if p['indent_cols'] == 7)      # M2 margins
    assert quote['runs'][0]['text'].startswith('An indented')    # lm stamp off
    body = next(p for p in paras if any('ref' in r for r in p['runs']))
    assert body['footnotes'] and sem['notes'][body['footnotes'][0][0]][
        'text'] == 'A footnote.'


def test_layout_emitter_serializes_the_viewer_contract():
    """`-t layout`: format/version header, semantic modern flow, printed
    page-lines with soft flags, and the invisible layer -- enough for a
    renderer in any language, no engine linked."""
    import json
    doc = core.parse_ws(ws7_block(0x00) + b'.. a hidden aside' + HARD +
                        b'First line of prose, plain and long enough here.'
                        + HARD +
                        b'Second line of prose, also plain and long enough.'
                        + HARD)
    out = emit.get_emitter('layout')['fn'](doc, 'modern')
    d = json.loads(out)
    assert d['format'] == 'ctrl-kd-layout' and d['version'] == 1
    assert d['meta']['encoding'] == 'cp437'
    assert d['page']['size_name'] == 'Letter'
    assert any(i['kind'] == 'para' for i in d['modern']['items'])
    assert d['printed']['pages'][0]['lines']          # printed layer present
    assert d['invisibles']['notes'][0]['origin'] == '..'
    assert d['invisibles']['dot_positions']           # Show Invisibles anchors
    assert 'layout' in emit.formats()                 # reachable from the CLI


def test_page_settings_size_presets_letter_legal_a4():
    """Ruling 2026-08-06 (task #16): --page-settings size=letter|legal|a4
    fills SILENT files with a named sheet -- the document's own .pl always
    wins. An A4 page narrows the PDF MediaBox and the RTF \\paperw."""
    from ctrlkd.pdf import emit_pdf
    silent = core.parse_ws(ws7_block(0x00) +
                           b'Plain prose line, ordinary and long enough here.'
                           + HARD)
    eff = core.effective_page(silent.meta['page'], {'pl_lines': 70.157})
    assert eff['size_name'] == 'A4' and abs(eff['pw_in'] - 8.268) < 1e-6
    silent.meta['page'] = eff
    pdf = emit_pdf(silent, 'modern')
    assert b'/MediaBox [0 0 595 842]' in pdf
    rtf = emit.emit_rtf(silent, 'modern')
    assert r'\paperw11906' in rtf and r'\paperh16838' in rtf
    # a file DECLARING its length keeps it against any preset
    own = core.parse_ws(ws7_block(0x00) + b'.pl 84' + HARD +
                        b'Plain prose line, ordinary and long enough here.'
                        + HARD)
    eff = core.effective_page(own.meta['page'], {'pl_lines': 70.157})
    assert eff['size_name'] == 'Legal' and eff['pw_in'] == 8.5


def test_tab_stops_are_editor_time_state_carried_not_rendered():
    """.tb (task #19, measured 2026-08-06): the stops are ruler state the
    Tab key resolves against at EDIT time -- type-9 sequences carry their
    own baked positions, and zero archive files pair .tb with a bare 0x09.
    So the stops change no rendered byte; they are stamped per block and
    surface as 'tabs' items in the layout contract for Show Invisibles and
    a future editor."""
    from ctrlkd.layout import modern_flow
    data = (ws7_block(0x00) +
            b'Prose before the stops change, plain and long enough here.'
            + HARD + b'.tb 12 27 41' + HARD +
            b'Prose after the stops change, also plain and long enough.'
            + HARD)
    doc = core.parse_ws(data)
    blocks = [b for b in doc.blocks if b.kind == 'para']
    assert blocks[0].tab_stops is None                # ruler default
    assert blocks[1].tab_stops == [12.0, 27.0, 41.0]  # stateful, per block
    items = modern_flow(doc)['items']
    tabs = [i for i in items if i['kind'] == 'tabs']
    assert tabs and tabs[-1]['stops'] == [12.0, 27.0, 41.0]
    # and the rendered PDF is identical with or without the .tb line
    from ctrlkd.pdf import emit_pdf
    without = core.parse_ws(data.replace(b'.tb 12 27 41' + HARD, b''))
    assert emit_pdf(doc, 'modern') == emit_pdf(without, 'modern')


def test_parse_error_carries_kind_and_detection_evidence():
    """Task #18: refusals explain themselves. ParseError subclasses
    ValueError (existing handlers keep working) and carries a machine-
    readable kind plus the full detection dict, so the app's error alert
    can say WHY a file failed instead of just 'no'."""
    from ctrlkd import ParseError
    with pytest.raises(ParseError) as ei:
        core.parse(b'')
    assert ei.value.kind == 'empty'
    with pytest.raises(ValueError) as ei:            # old handlers still catch
        core.parse(bytes(range(256)) * 8)
    assert getattr(ei.value, 'kind', None) == 'binary'
    assert ei.value.detection.get('reason')          # evidence attached


def test_fontless_box_corners_never_degrade_to_question_marks():
    # Jon's standing guarantee (2026-08-11): NO release -- ctrl-kd, sr,
    # QuickLook, or the Soft Return app -- may render fontless cp437 box
    # corners as '?' in Printed mode (ruling B, 2026-08-10: "the geometry IS
    # the glyph... it could be done in that era"). Mirrors the Swift engine's
    # PDFGraphicsTests pin; the app repo's OracleByteParityTests pins the
    # same bytes downstream. BOX.WS's exact shape: <1B x 1C>-wrapped cp437.
    from ctrlkd.pdf import emit_pdf
    import re as _re
    row = b'\x1b\xda\x1c' + b'\x1b\xc4\x1c' * 8 + b'\x1b\xbf\x1c'
    data = b'.aw off\r\n' + row + b'\r\n' + row + b'\r\n'
    doc = core.parse_ws(data)
    pdf = emit_pdf(doc, 'printed')
    assert b' re f' in pdf, 'box arms must draw as vector fills'
    shown = b''.join(_re.findall(rb'\((.*?)\)\s*Tj', pdf))
    assert b'?' not in shown, 'a ? leaked into printed text ops'


def test_cp437_symbol_glyphs_draw_as_vectors_not_question_marks():
    # Jon's ruling (2026-08-11, extending ruling B): "the card suits, etc.
    # show up everywhere." LJ6DTP p3's "Shows on screen as" column is the
    # literal control-position bytes 02-06/0F/F0 -- era screens showed
    # card suits, the smiley, the sun, and the triple bar. Latin-1 has
    # none of them; before this ruling every one degraded to '?' in the
    # printed PDF. Now they draw as filled vector geometry (SYMBOL_SHAPES
    # in pdf.py). Same <1B x 1C>-wrapped shape the box pin uses.
    from ctrlkd.pdf import emit_pdf
    import re as _re
    symbols = b''.join(b'\x1b%c\x1c' % b for b in (0x02, 0x03, 0x04, 0x05, 0x06, 0x0F, 0xF0))
    data = b'.aw off\r\n' + symbols + b'\r\n'
    doc = core.parse_ws(data)
    pdf = emit_pdf(doc, 'printed')
    assert b' c' in pdf and b' re f' in pdf, 'symbol glyphs must draw as vector fills'
    shown = b''.join(_re.findall(rb'\((.*?)\)\s*Tj', pdf))
    assert b'?' not in shown, 'a ? leaked into printed text ops'


# ---------------------------------------------------- Modern structure rules
#
# The three GENERIC structure rules (Jon's field notes, 2026-08-13):
# def-list/hanging-indent, nested hierarchy (the same mechanism applied
# recursively), and centered lines -- derived purely from a paragraph's own
# column geometry (classify_rows() in layout.py), never keyed to a specific
# file. The real-world source for all three is the Sawyer WS7 archive
# (VERSIONS.WS, CONVERT.WS, STRENGTH.WS); these fixtures build the identical
# shapes byte-by-byte, per this repo's synthetic-fixtures-only rule.

def _modern(data):
    doc = core.parse_ws(data)
    doc.meta['variant'] = 'ws4'          # force the reflow path, not <pre>
    return doc


def test_deflist_ragged_label_widths_share_one_column():
    """Rule 1: a def-list label is a paragraph's own first word glued to
    its description by 2+ spaces -- WordStar has no def-list markup, so an
    author signals it purely by padding labels of different lengths out to
    a shared description column. VERSIONS.WS's 'WS.EXE:'/'WSRJS.EXE:' shape."""
    from ctrlkd.layout import modern_flow
    from ctrlkd.emit import emit_html
    data = (b'.lm 15\r\n' +
            b'A:             short label.' + HARD +
            b'LONGLABEL:     longer label, same column.' + HARD)
    doc = _modern(data)
    items = [i for i in modern_flow(doc)['items'] if i['kind'] == 'para']
    assert [i['structure']['kind'] for i in items] == ['def', 'def']
    assert [i['structure']['label'] for i in items] == ['A:', 'LONGLABEL:']
    assert [i['structure']['body'] for i in items] == \
        ['short label.', 'longer label, same column.']
    html = emit_html(doc, mode='modern')
    assert ('<dl><dt>A:</dt><dd>short label.</dd>'
            '<dt>LONGLABEL:</dt><dd>longer label, same column.</dd></dl>') in html


def test_deflist_single_entry_needs_no_repetition():
    """Edge case: unlike a bullet marker (a bare glyph could just be
    punctuation, so it needs a repeated sibling to be trusted), one
    label+gap+description line alone is already unambiguous."""
    from ctrlkd.layout import modern_flow
    data = b'Note:  a single hanging label, alone in its own document.' + HARD
    doc = _modern(data)
    s = modern_flow(doc)['items'][0]['structure']
    assert s['kind'] == 'def' and s['label'] == 'Note:'
    assert s['body'] == 'a single hanging label, alone in its own document.'


def test_bullet_list_with_nested_deflist():
    """Rule 2: a def-list nested INSIDE a bullet list -- the same column-
    geometry mechanism as rule 1, one level deeper. CONVERT.WS's own
    'Peter Mierau...: WSASC.COM: ...' shape."""
    from ctrlkd.emit import emit_html
    data = (b'.lm 2\r\n'
            b'* First bullet item.' + HARD +
            b'* Second bullet, introduces a sub-list:' + HARD +
            b' LABEL:  nested description.' + HARD +
            b'* Third bullet, back at the outer level.' + HARD)
    doc = _modern(data)
    html = emit_html(doc, mode='modern')
    assert ('<ul><li>First bullet item.</li>'
            '<li>Second bullet, introduces a sub-list:'
            '<dl><dt>LABEL:</dt><dd>nested description.</dd></dl></li>'
            '<li>Third bullet, back at the outer level.</li></ul>') in html


def test_three_level_nesting():
    """Edge case: nesting recurses to arbitrary depth, not just one level
    -- a bullet list containing a nested bullet list containing a nested
    def-list, three columns deep."""
    from ctrlkd.layout import modern_flow
    from ctrlkd.emit import emit_html
    data = (b'.lm 2\r\n'
            b'* Outer bullet one.' + HARD +
            b'* Outer bullet two, introduces inner list:' + HARD +
            b'  # Inner one' + HARD +
            b'  # Inner two, introduces a def-list:' + HARD +
            b'   LABEL:  deepest.' + HARD)
    doc = _modern(data)
    items = [i for i in modern_flow(doc)['items'] if i['kind'] == 'para']
    assert [i['structure']['level'] for i in items] == [1, 1, 2, 2, 3]
    html = emit_html(doc, mode='modern')
    assert ('<ul><li>Outer bullet one.</li>'
            '<li>Outer bullet two, introduces inner list:'
            '<ul><li>Inner one</li>'
            '<li>Inner two, introduces a def-list:'
            '<dl><dt>LABEL:</dt><dd>deepest.</dd></dl></li></ul></li></ul>') in html


def test_centered_by_spaces_detected_and_rendered():
    """Rule 3, encoding finding: STRENGTH.WS's title/author/email carry NO
    .oc tag at all -- centering is leading-space padding only, symmetric
    within the document's own 65-column measure. Structural detection must
    catch this untagged mechanism, which nothing rendered correctly before."""
    from ctrlkd.layout import modern_flow
    from ctrlkd.emit import emit_html
    title = 'A Centered Title'
    pad = (65 - len(title)) // 2
    data = (' ' * pad + title).encode() + HARD
    doc = _modern(data)
    s = modern_flow(doc)['items'][0]['structure']
    assert s['centered'] and s['center_via'] == 'spaces'
    assert s['center_text'] == title
    html = emit_html(doc, mode='modern')
    # round 20 (slate item 4): a centered unit gets tighter internal
    # line-height (VERSE_LINE_HEIGHT) alongside its alignment, same
    # mechanism as a verse-classified unit.
    assert ('<p style="text-align:center;line-height:1.15">'
           'A Centered Title</p>') in html


def test_centered_tag_also_classified_uniformly():
    """The other mechanism named in the field notes ('likely both need
    handling'): a real align=center tag is ALSO exposed as centered=True
    (center_via='tag') for a consumer that wants one uniform signal --
    but the tag's own existing HTML rendering (M3 already strips its
    padding) is left completely alone, so a tagged document's output is
    unchanged by this rule set."""
    from ctrlkd.layout import modern_flow
    doc = _modern(b'.oc on\r\nCentred.\r\n.oc off\r\n')
    s = modern_flow(doc)['items'][0]['structure']
    assert s['centered'] and s['center_via'] == 'tag'


def test_near_centered_but_not_stays_plain():
    """Edge case: a genuinely off-centre indent -- not padded to sit near
    the measure's own midpoint -- must not be misread as a centered line,
    however coincidentally short the paragraph is."""
    from ctrlkd.layout import modern_flow
    data = (b'    Not Quite Centered') + HARD   # ideal pad would be (65-19)//2=23
    doc = _modern(data)
    s = modern_flow(doc)['items'][0]['structure']
    assert not s['centered']


def test_ordinary_multiline_block_stays_one_paragraph():
    """Regression guard: a block with NO list/def/center structure at all
    -- a signature block with several hard-broken lines -- must still
    render as ONE <p> with <br> between lines, exactly as before this rule
    set existed. (The per-row classification needed for rules 1/2 renders
    one merged line at a time; this proves plain lines still coalesce.)"""
    from ctrlkd.emit import emit_html
    data = b'-- Robert J. Sawyer' + HARD + b'   sawyer@sfwriter.com' + HARD
    doc = _modern(data)
    html = emit_html(doc, mode='modern')
    # this <br>-joined shape means the paragraph-assembly heuristic already
    # classified it verse-like (is_verse) -- round 20 (slate item 4) adds
    # the tight line-height that classification now carries.
    assert ('<p style="line-height:1.15">-- Robert J. Sawyer<br>\n'
           '   sawyer@sfwriter.com</p>') in html


def test_ordinary_prose_is_not_swept_into_a_list():
    """False-positive guard: an ordinary sentence must never be read as a
    bullet (needs a repeated marker glyph) or a def-list label (needs a
    2+-space gap right after its very first word)."""
    from ctrlkd.emit import emit_html
    data = b'This is an entirely ordinary sentence, nothing structural here.' + HARD
    doc = _modern(data)
    html = emit_html(doc, mode='modern')
    assert '<ul>' not in html and '<dl>' not in html
    assert html.count('<p>') == 1


def test_printed_left_po_columns_are_pitch_independent():
    """dx experiment 2026-08-20: real WS7 keeps .po at a fixed 7.2pt/column
    at both 10cpi and 12cpi (PCL ESC&aH 576dp identical for .po 8) -- the
    manual's ".CW determines the actual amount of indentation" clause is
    contradicted by measured bytes. Regression: 12cpi (size 10) must not
    shrink the left edge to 48pt."""
    from ctrlkd import pdf as _pdf

    class _Doc:
        meta = {'page': {'po_cols': 8.0}}

    assert abs(_pdf._printed_left(_Doc(), 12) - 57.6) < 1e-9
    assert abs(_pdf._printed_left(_Doc(), 10) - 57.6) < 1e-9
