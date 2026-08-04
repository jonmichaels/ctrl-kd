"""ctrl-kd tests — all fixtures are SYNTHETIC, built byte-by-byte here.

They encode real WordStar behaviors verified against a 1987-92 corpus during
development (that corpus is personal and is not shipped).
"""
import pytest
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
    poem = b'     line one,' + SOFT + b'     line two.' + HARD
    h = emit.emit_html(core.parse_ws(poem), mode='modern')
    assert '<br>' in h and '<p>' in h

def test_emit_html_printed_pre():
    data = b'A    B    C\r\nD    E    F\r\n'
    h = emit.emit_html(core.parse_printstream(data), 'printed')
    assert '<pre>' in h and 'A    B    C' in h

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

def test_ws7_heading_and_softpage():
    data = (ws7_block(0x00) + ws7_block(0x11, bytes([0x02])) + b'Chapter One' + HARD + HARD +
            b'Body text of the chapter.' + HARD + ws7_block(0x0B) + b'Next page text.' + HARD)
    doc = core.parse_ws(data)
    heads = [b for b in doc.blocks if b.heading]
    assert heads and heads[0].heading == 2
    assert heads[0].lines[0].text().strip() == 'Chapter One'
    assert any(b.kind == 'softpage' for b in doc.blocks)
    md = emit.emit_markdown(doc, mode='modern')
    assert '## Chapter One' in md
    h = emit.emit_html(doc, mode='modern')
    assert '<h2>Chapter One</h2>' in h

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
    assert [r.text for r in refs] == ['1', '2', '3']       # comment got no ref
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
    data = (ws7_block(0x00) + ws7_block(0x11, bytes([0x02])) + b'Chapter One' + HARD + HARD +
            b'Body text here.' + HARD)
    pages = _doc_to_pagelines(core.parse_ws(data), False)
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
    t = emit.emit_text(four_kind_doc, notes=ALL_NOTE_KINDS)
    assert 'Comments:\n[1] Comment text.' in t

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
    h = emit.emit_html(four_kind_doc, notes=ALL_NOTE_KINDS)
    assert 'Comment text.' in h
    assert '<h2 id="comments-label">Comments</h2>' in h
    # comments have no inline reference to link back to
    assert 'cmref' not in h

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
    r = emit.emit_rtf(four_kind_doc, notes=ALL_NOTE_KINDS)
    assert r'\*\annotation' in r and r'\chatn' in r and r'\atnid' in r
    assert 'Comment text.' in r
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
    far = core.parse_ws(b'.PL 70' + HARD + b'x' + HARD)        # 11.667in: > 0.25 from Letter
    assert far.meta['page']['size_name'] == 'Custom'
    assert far.meta['page']['height_in'] == pytest.approx(70 / 6)   # raw geometry honoured

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
    # the default .mt 3 IS the 36pt top this emitter always used; a bigger
    # .mt moves the text start down in real points (1 line = 12pt at 6 LPI)
    from ctrlkd.pdf import _printed_top
    assert _printed_top(core.parse_ws(b'x' + HARD)) == 36
    assert _printed_top(core.parse_ws(b'.MT 6' + HARD + b'x' + HARD)) == 72

def test_pdf_printed_lead_follows_lh():
    # .lh 8 IS the 12pt lead; .lh 16 prints double-spaced at 24pt
    from ctrlkd.pdf import _printed_lead
    assert _printed_lead(core.parse_ws(b'x' + HARD)) == 12.0
    assert _printed_lead(core.parse_ws(b'.LH 16' + HARD + b'x' + HARD)) == 24.0

def test_pdf_output_bytes_carry_mt_top_and_lh_lead():
    # end-to-end: the geometry must reach the CONTENT STREAM, not just the
    # helpers -- .mt 6 starts text at 72pt from the top, .lh 16 spaces
    # baselines 24pt apart. Read the Td y-coordinates back out of the bytes.
    import re
    from ctrlkd.pdf import emit_pdf
    data = (b'.MT 6' + HARD + b'.LH 16' + HARD +
            b'Line one.' + HARD + b'Line two.' + HARD + b'Line three.' + HARD)
    pdf = emit_pdf(core.parse_ws(data), mode='printed')
    ys = [float(m) for m in re.findall(rb'[\d.]+ ([\d.]+) Td', pdf)]
    assert ys[0] == 792 - 72 - 12                  # top from .mt, not fixed 36
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
    assert _printed_left(d_default, 12) == pytest.approx(8 * 12 * 0.6)   # 57.6
    d_elite = core.parse_ws(b'.CW 10' + HARD + b'.PO 12' + HARD + b'x' + HARD)
    assert _printed_size(d_elite) == 10
    assert _printed_left(d_elite, 10) == pytest.approx(12 * 10 * 0.6)    # 72.0

def test_pdf_output_bytes_carry_po_left_and_cw_size():
    # end-to-end: x-coordinates and Tf size come from the file's own .po/.cw
    import re
    from ctrlkd.pdf import emit_pdf
    data = (b'.PO 12' + HARD + b'.CW 10' + HARD + b'Line one.' + HARD)
    pdf = emit_pdf(core.parse_ws(data), mode='printed')
    m = re.search(rb'/F1 (\d+) Tf \d+ Ts ([\d.]+) [\d.]+ Td', pdf)
    assert m and m.group(1) == b'10'               # elite type size
    assert m.group(2) == b'72.0'                   # 12 cols x 10pt x 0.6em

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
    # tab type ']' with size 4500 HMI (4500/144 = 31.25 -> 31 columns).
    data = ws7_block(0x00) + _ws7_tab(4500, ord(']')) + b'Indented.' + HARD
    doc = core.parse_ws(data)
    text = doc.blocks[0].lines[0].text()
    assert text.startswith(' ' * 31)
    assert text.strip() == 'Indented.'

def test_ws7_tab_dot_leader_repeats_leader_character():
    # spec: "Other character such as '.' or '*' are used for dot leaders."
    # A leading "Row" keeps the expanded leader dots from starting the
    # physical line -- a line literally starting with '.' is (correctly,
    # pre-existing behaviour, unrelated to this fix) read as a dot command.
    data = ws7_block(0x00) + b'Row' + _ws7_tab(720, ord('.')) + b'Contents' + HARD  # 720/144=5
    doc = core.parse_ws(data)
    text = doc.blocks[0].lines[0].text()
    assert '.' * 5 in text
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
    for b in (0x01, 0x1C, 0x1D, 0x1E, 0x1F):
        data = b'A' + bytes([0x1B, b]) + b'B' + HARD
        doc = core.parse_ws(data)
        assert doc.meta['variant'] == 'binary'
        text = ''.join(s.text for s in doc.blocks[0].lines[0].spans)
        assert text == 'A' + chr(b) + 'B', f'escaped {b:#04x} was not passed through'


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
    """Placement MEASURED on WordStar 4 (2026-08-03): header on page line 0,
    body starting at line 3 (.mt), 55 body lines, footer on line 60
    (.pl - .mb + .fm). Asserted in lines, not points, so it stays readable."""
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
    assert txt[0] == 3, f'body should start at .mt 3, got {txt[0]}'
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
    assert '<p style="text-align:center">' in html
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
    assert [(b.left_margin, b.right_margin, b.para_margin) for b in doc.blocks] == [
        (5.0, 60.0, None), (5.0, 60.0, 4.0)]
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
    """C1. Three style IDs were mapped to heading levels and EVERY OTHER STYLE WAS
    DROPPED -- silently, so a styled paragraph became an unstyled one with nothing
    to say a style had been applied. The WS7 archive uses at least twelve distinct
    IDs, and 0x06 alone appears 60 times: more often than two of the three that
    were mapped."""
    def styled(style_id):
        blk = _ws_block(0x11, bytes([style_id, 2, 1, 2, 2, 3, 1, 2]))
        return core.parse_ws(blk + b'Styled text.\r\n').blocks[0]

    known = styled(0x05)
    assert (known.heading, known.style_id) == (1, 5)
    # the ones that used to vanish
    for sid in (0x06, 0x0F, 0x19):
        b = styled(sid)
        assert b.heading == 0, 'not one of the three known headings'
        assert b.style_id == sid, 'but WHICH style must still be known'
        assert ''.join(s.text for s in b.lines[0].spans) == 'Styled text.'


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
    p = os.path.expanduser('~/vaults/claude_memory/workbench/chonky/fixtures-ws5/NOTES.TST')
    if not os.path.exists(p):
        return                      # fixture lives outside the repo; skip if absent
    doc = core.parse_ws(open(p, 'rb').read())
    assert [n.kind for n in doc.notes[:4]] == ['footnote', 'footnote', 'endnote', 'endnote']
    refs = sum(1 for l in doc.iter_lines() for s in l.spans if 'fnref' in s.styles)
    assert refs == 6, refs          # four kinds, comments never referenced inline


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
