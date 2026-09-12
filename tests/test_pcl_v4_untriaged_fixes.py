"""Three mechanisms traced out of the ws7-prints/v4 untriaged set, 2026-09-12
(research/2026-09-12_pcl-v4-untriaged-triage.md in the vault). Every one is
MEASURED against real WordStar 7 output -- the PRISTINE.EXE captures in the
private corpus -- not inferred; the synthetic fixtures here reproduce the
same shapes so the rules stay covered without the corpus.

  A. A `.fo` whose text is EMPTY still puts footers in use, and a footer in
     use silences WordStar's automatic bottom-of-page number. Real WS7
     prints no number on any page of `sawyer/LSRBOX/LSRBOX.WS` (a bare
     `.fo`, no `.op`/`.pn`/`.pg` anywhere) or of four HOLYMAC macro
     documents. ctrl-kd printed one on every page of all of them.

  B. A document whose entire body is one note block -- no body text, no
     line terminator after the block -- rendered as a completely BLANK
     page. All 19 of the Sawyer archive's TAGS/ annotation files are that
     shape, and WS7 prints all of them.

  C. A note's own hard returns print. WordStar stores the note's marker
     INLINE in that text, so a note whose text opens with a return carries
     its marker on the SECOND line (`sawyer/TAGS/WHEN`), not the first
     (`sawyer/TAGS/WHY`), and a note ending in a blank line reserves that
     line (`sawyer/TAGS/SIMPLIFY`).
"""
import re

from ctrlkd import core, pdf


HARD = b'\x0d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def ws7_annotation(text, tag, line_count=1, lead_break=False):
    """An annotation block shaped exactly like the TAGS/ files: a nested
    sequence carrying the display tag, then the note's own text. With
    `lead_break`, a hard return is stored BEFORE the nested tag sequence --
    `sawyer/TAGS/WHEN`'s own shape."""
    inner = ws7_block(0x05, b'\x00\x00\x00\x00\x05' + tag)
    body = (HARD if lead_break else b'') + inner + text
    content = (line_count.to_bytes(2, 'little') + (0x8000 + 9).to_bytes(2, 'little')
               + b'\x05' + body)
    return ws7_block(0x05, content)


def _pdf_text(data):
    return b'\n'.join(re.findall(rb'\((.*?)\)\s*Tj', data, re.S)).decode('latin-1')


# ---------------------------------------------------------------- mechanism A
def _ws(src):
    """Parse as a WordStar DOCUMENT. A minimal plain-ASCII dot-command
    replica auto-detects as `printstream` (fidelity_gate.py's own CAVEAT
    records the same trap), which never reads dot commands at all."""
    return core.parse_ws(src)


def test_empty_fo_suppresses_the_automatic_page_number():
    """`.fo` with nothing after it is a footer, and a footer in use silences
    the automatic number -- measured on `sawyer/LSRBOX/LSRBOX.WS`, which
    carries a bare `.fo` and no `.op`/`.pn`/`.pg` at all, and on which real
    WS7 prints no bottom-of-page number on any of its 7 pages."""
    body = HARD.join([b'line %d' % n for n in range(1, 150)])
    with_fo = _ws(b'.fo' + HARD + body)
    without = _ws(body)
    assert len(with_fo.footers) == 1 and not any(with_fo.footers.values()), (
        'a bare .fo is a footer with no text')
    # The document with no `.fo` keeps WordStar's stock automatic number.
    assert re.search(r'^\s*2\s*$', _pdf_text(pdf.emit_pdf(without, mode='printed')),
                     re.M), 'stock automatic page number should still print'
    # The one with a bare `.fo` has none.
    assert not re.search(r'^\s*2\s*$', _pdf_text(pdf.emit_pdf(with_fo, mode='printed')),
                         re.M), 'a bare .fo must silence the automatic page number'


def test_pn_after_op_does_not_resurrect_the_number_through_a_footer():
    """The HOLYMAC shape: `.op`, then a bare `.fo`, then `.pn` -- `.pn` is
    an "on" checkpoint for the automatic number, but the footer is what
    decides here, and real WS7 prints no number on any page of 4MAC2/
    4MAC3/7MAC2/7MAC3."""
    body = HARD.join([b'line %d' % n for n in range(1, 150)])
    doc = _ws(b'.op' + HARD + b'.fo' + HARD + b'.pn251' + HARD + body)
    text = _pdf_text(pdf.emit_pdf(doc, mode='printed'))
    assert not re.search(r'^\s*25[12]\s*$', text, re.M)


# ---------------------------------------------------------------- mechanism B
def test_note_only_document_still_renders():
    """A file that is one annotation block and nothing after it -- no body
    text, no terminator. It used to produce zero blocks and a blank page."""
    data = ws7_annotation(HARD + b'Why?' + HARD, b'[Why?]', line_count=2)
    doc = core.parse(data + b'\x1a' * 87)
    assert len(doc.blocks) == 1, 'the note reference is the document body'
    assert len(doc.notes) == 1 and doc.notes[0].kind == 'annotation'
    text = _pdf_text(pdf.emit_pdf(doc, mode='printed'))
    assert '[Why?]' in text and 'Why?' in text


def test_trailing_eof_line_without_marks_is_still_dropped():
    """The blank-tail rule this narrows, unchanged: a file ending in blank
    lines before its ^Z still loses them."""
    kept = core.parse_ws(b'one' + HARD + b'two' + HARD + b'\x1a' * 40)
    texts = [''.join(s.text for s in ln.spans).strip()
             for b in kept.blocks for ln in b.lines]
    # Exactly the two real lines: the zero-length, unterminated tail after
    # the last return carries no marks, so it is still not a line.
    assert texts == ['one', 'two'], texts


# ---------------------------------------------------------------- mechanism C
def test_note_keeps_its_own_physical_lines():
    """`sawyer/TAGS/SIMPLIFY`'s shape: text, then a blank line the author
    typed. Exactly one trailing element -- the block's own terminator --
    is dropped, so `text_lines` matches WordStar's stored `line_count`."""
    doc = core.parse(ws7_annotation(HARD + b'Simplify' + HARD + HARD,
                                    b'[Simplify]', line_count=3) + b'\x1a')
    note = doc.notes[0]
    assert note.text_lines == ('', 'Simplify', '')
    assert len(note.text_lines) == note.line_count
    assert note.text == 'Simplify', 'the flowed form is unchanged'
    assert note.tag_line == 0


def test_note_marker_sits_on_the_line_it_is_stored_on():
    """`sawyer/TAGS/WHEN`'s shape: a hard return BEFORE the nested tag
    sequence, so the tag prints on the note area's SECOND line."""
    doc = core.parse(ws7_annotation(HARD + b'When?' + HARD, b'[When?]',
                                    line_count=3, lead_break=True) + b'\x1a')
    note = doc.notes[0]
    assert note.text_lines == ('', '', 'When?')
    assert note.tag_line == 1


def test_note_wrap_places_the_marker_on_its_own_line():
    """The renderer half of the same rule, with no corpus involved."""
    lines = pdf._note_wrap('[When?] ', ['', '', 'When?'], 65, tag_line=1)
    flat = [''.join(t for t, _ in row) for row in lines]
    assert flat[0] == ''
    assert flat[1].startswith('[When?]')
    assert flat[2] == 'When?'
