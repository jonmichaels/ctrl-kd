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
    seps = [s for _, s in lines]
    assert seps == ['wrap', 'wrap', 'para', 'eof']

def test_poem_lines_kept():
    # short lines ending in SOFT returns where the next word would have fit:
    # deliberate breaks (the wrap test), stanza gap = soft+hard run -> para
    poem = (b'     A short poem line,' + SOFT +
            b'     another short line.' + SOFT + HARD + SOFT +
            b'     Second stanza opens,' + SOFT +
            b'     and closes.' + HARD)
    lines, _ = core.lines_pass(poem)
    assert [s for _, s in lines] == ['line', 'para', 'line', 'eof']

def test_wrap_boundary_is_strict():
    # word landing EXACTLY at the margin: WS4 still wrapped -> join, not break
    l1 = (' ' * 5 + 'a' * 52).encode()              # len 57
    lines, margin = core.lines_pass(l1 + SOFT + b'mother.' + HARD)
    assert margin == 65
    assert lines[0][1] == 'wrap'                    # 57 + 1 + 7 == 65: not < 65

def test_single_hard_is_line_break():
    data = b'Jon Michaels' + SOFT + b'March 6, 1992' + SOFT + HARD + SOFT + b'Body text.' + HARD
    lines, _ = core.lines_pass(data)
    assert [s for _, s in lines] == ['line', 'para', 'eof']

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
    md = emit.emit_markdown(core.parse_ws(data))
    assert '**Bold**' in md and '*ital*' in md

def test_emit_html_poem_breaks():
    poem = b'     line one,' + SOFT + b'     line two.' + HARD
    h = emit.emit_html(core.parse_ws(poem))
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
    data = (ws7_block(0x00) + b'Treaties were made.' +
            ws7_note(0x03, b'See the 1868 accords.') +
            b' More text follows here.' + HARD)
    doc = core.parse_ws(data)
    assert doc.meta['variant'] == 'ws5+'
    assert len(doc.footnotes) == 1
    assert ''.join(s.text for s in doc.footnotes[0]) == 'See the 1868 accords.'
    spans = doc.blocks[0].lines[0].spans
    ref = [s for s in spans if 'fnref' in s.styles]
    assert ref and ref[0].text == '1' and 'sup' in ref[0].styles
    md = emit.emit_markdown(doc)
    assert '[^1]' in md and '[^1]: See the 1868 accords.' in md

def test_ws7_heading_and_softpage():
    data = (ws7_block(0x00) + ws7_block(0x11, bytes([0x02])) + b'Chapter One' + HARD + HARD +
            b'Body text of the chapter.' + HARD + ws7_block(0x0B) + b'Next page text.' + HARD)
    doc = core.parse_ws(data)
    heads = [b for b in doc.blocks if b.heading]
    assert heads and heads[0].heading == 2
    assert heads[0].lines[0].text().strip() == 'Chapter One'
    assert any(b.kind == 'softpage' for b in doc.blocks)
    md = emit.emit_markdown(doc)
    assert '## Chapter One' in md
    h = emit.emit_html(doc)
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
