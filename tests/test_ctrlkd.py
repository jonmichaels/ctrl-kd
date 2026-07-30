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

def ws7_block(cmd, payload=b''):
    body = bytes([cmd]) + payload
    return b'\x1d' + len(body).to_bytes(2, 'little') + body

def ws7_note(text):
    inner = b'\x00' * 17 + b'\x1d' + text + b'\x2c\x00'
    return ws7_block(0x03, inner)

def test_ws7_footnote_extraction_and_ref():
    data = (ws7_block(0x00) + b'Treaties were made.' + ws7_note(b'See the 1868 accords.') +
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
