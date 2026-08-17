"""Modern-reflow overhaul (2026-08-17): paragraph-assembly fixtures plus the
permanent output-quality lint gates Jon's ruling asked for.

Synthetic fixtures are built byte-by-byte, same discipline as
test_ctrlkd.py (whose helper builders are copied in below rather than
imported -- its own guidance). The lint gates additionally run against
every real fixture in CTRLKD_PRIVATE_FIXTURES when that env var is set
(same opt-in pattern as test_ctrlkd.py's `_real_fixture` tests); with no
private fixtures present, the synthetic-only gates still run and the
corpus-driven ones skip cleanly.
"""
import copy
import os
import re

import pytest

from ctrlkd import core, emit

HARD = b'\x0d\x0a'
SOFT = b'\x8d\x0a'


def ws4_word(w):
    """WS4 sets bit 7 on the last character of each word."""
    return w[:-1] + bytes([w[-1] | 0x80])


def ws4_text(s):
    return b' '.join(ws4_word(w.encode()) for w in s.split(' '))


def ws7_block(cmd, content=b''):
    """One WS7 symmetrical sequence -- see test_ctrlkd.py's own copy for the
    field-by-field rationale (WordStar 7.0 file format spec)."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _style_record(left=1800, just=0, right=None, attrs_on=0):
    """Trimmed 102-byte style record -- only the fields this file's tests
    read (left/right margin, justification, attrs-on); everything else
    stays at the project's own 'inherited' sentinels. See test_ctrlkd.py's
    `_style_record` for the full field-by-field version. `right=None`
    keeps the original inherited-margin sentinel (0xFFFE, -2 signed --
    `core.sword_none`'s own "no value" reading); a real int is HMI
    (1800/inch), same unit as `left`. `attrs_on` is the raw WSFORMAT bit
    pattern (strikeout=1, doublestrike=2, underline=8, sub=16, super=32,
    bold=64, italic=128 -- see core.py's own `entry['attrs']` decode)."""
    rec = bytearray(102)
    rec[0:2] = (0xFFFF).to_bytes(2, 'little')
    rec[10:12] = left.to_bytes(2, 'little')
    rec[12:14] = ((right if right is not None else 0xFFFE) & 0xFFFF).to_bytes(2, 'little')
    rec[14:16] = (0xFFFE).to_bytes(2, 'little')
    rec[18] = rec[19] = 0xFF
    for k in range(32):
        rec[20 + 2 * k:22 + 2 * k] = (0xBEEF).to_bytes(2, 'little')
    rec[86] = just % 256
    rec[87] = 1
    rec[88:90] = (0xFFFF).to_bytes(2, 'little')
    rec[90] = 0xFF
    rec[91:93] = attrs_on.to_bytes(2, 'little')
    rec[95] = 0xFF
    return bytes(rec)


def _style_library(entries):
    n = len(entries)
    items, records = b'', b''
    rec_base = 13 + 5 + 33 * n
    for name, has_rec, rec in entries:
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


def _style_handle(slot):
    return ws7_block(0x11, (0x0200 | slot).to_bytes(2, 'little')
                     + (0x0201).to_bytes(2, 'little')
                     + (0x0300).to_bytes(2, 'little')
                     + (0x0201).to_bytes(2, 'little'))


def _doc_with_style(name, rec, body):
    """A parsed Document whose one styled block uses paragraph style
    `name`. Mirrors test_ctrlkd.py's `test_style_record_formatting_applies`
    plumbing, trimmed to what a single-style fixture needs."""
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        (name, True, rec),
    ])
    header = ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
    doc_body = header + _style_handle(2) + body
    base = ((len(doc_body) + 127) // 128) * 128
    data = bytearray(doc_body.ljust(base, b'\x1a')) + lib
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    return core.parse_ws(bytes(data))


# ---------------------------------------------------------------- paragraph
# assembly (rule 2: poems survive; rule 3: no hard breaks inside prose)

def _typed_paragraph_doc(lines):
    """A WS5+ document: one Block, `lines` as hard-return-terminated typed
    paragraphs (manuscript convention -- indentation marks a new paragraph,
    not a blank line)."""
    return core.parse_ws(ws7_block(0x00) + HARD.join(lines) + HARD)


def _para_blocks_doc(block_lines_list):
    """A WS5+ document whose Blocks are BLANK-LINE delimited (the OTHER
    real manuscript convention -- unlike `_typed_paragraph_doc`'s single
    indent-only Block, a blank line closes each Block here, so a normal
    paragraph is already its own Block and typically opens with the
    document's own indent convention on its one line). `block_lines_list`
    is a list of blocks, each itself a list of hard-terminated line
    bytestrings."""
    body = b''
    for lines in block_lines_list:
        body += HARD.join(lines) + HARD + HARD
    return core.parse_ws(ws7_block(0x00) + body)


def test_assemble_paragraphs_short_lines_stay_one_unit():
    """Calibration fixture for PARAGRAPH_JOIN_SLACK (core.py): four
    deliberately short hard-terminated lines -- shaped exactly like
    OLDTIMES.WS's real four-line 'Mikado' quotation (longest real line 43
    of 65 columns) -- must NOT split into separate paragraphs."""
    lines = [
        b'     Line one is short,',
        b'     line two also short --',
        b'     line three fits the pattern --',
        b'     line four closes it.',
    ]
    doc = _typed_paragraph_doc(lines)
    margin = doc.meta.get('margin_estimate') or 65
    units = core.assemble_paragraphs(doc.blocks[0], margin)
    assert len(units) == 1
    assert sum(len(u) for u in units) == 4


def test_assemble_paragraphs_long_indented_lines_each_split():
    """A hard-return line that opens with a typed indent AND runs close to
    the block's own measured margin (WordStar's own wrap point) starts a
    NEW paragraph -- shaped like OLDTIMES's real narrative lines (e.g. its
    58-of-65-column line, which DOES split there)."""
    long = 'x' * 58
    lines = [f'     {long} one'.encode(), f'     {long} two'.encode(),
             f'     {long} three'.encode()]
    doc = _typed_paragraph_doc(lines)
    margin = doc.meta.get('margin_estimate') or 65
    units = core.assemble_paragraphs(doc.blocks[0], margin)
    assert len(units) == 3
    assert all(len(u) == 1 for u in units)


def test_ws4_multi_stanza_poem_survives_with_no_attributes_or_styles():
    """Round 2 (2026-08-17): a WS4 document has NEITHER the WS5+ symmetric-
    block machinery NOR (here) any inline b/i/u toggle -- so the attribute-
    shift signal `looks_like_verse` can use is silent by construction, and
    stanza preservation has to stand on terminal-punctuation/quote-opening
    alone. Two four-line stanzas (separated by the author's own blank
    line, same as a real poem), each line typed-indented, none ending in
    terminal punctuation (the enjambment shape real verse was found to
    have) -- both stanzas must stay a tight single unit."""
    stanza1 = [
        'Winter light upon the pane',
        'shadows learning how to fall',
        'something waits beyond the rain',
        'patient at the garden wall',
    ]
    stanza2 = [
        'Morning comes without a sound',
        'grey and folded like a page',
        'footsteps circling worn ground',
        'marking time against the age',
    ]
    body = b''
    for stanza in (stanza1, stanza2):
        for line in stanza:
            body += b'     ' + ws4_text(line) + HARD
        body += HARD                    # the author's own blank line
    assert core.detect(body)['variant'] == 'ws4'
    doc = core.parse_ws(body)
    stanza_blocks = [b for b in doc.blocks if b.kind == 'para' and b.lines]
    assert len(stanza_blocks) == 2
    margin = doc.meta.get('margin_estimate') or 65
    for b in stanza_blocks:
        units = core.assemble_paragraphs(b, margin)
        assert len(units) == 1, [l.text() for u in units for l in u]
        assert sum(len(u) for u in units) == 4


def test_ws4_dialogue_run_does_not_false_positive_as_stanza():
    """The companion fixture: six short, typed-indented, hard-terminated
    WS4 lines shaped like rapid dialogue/narrative beats (quote-opening
    and/or terminal punctuation on every line, no attributes available
    either) -- each must become its OWN paragraph, not get glued into a
    false stanza by run-length alone."""
    lines = [
        'Wait.',
        '"Where are you going?"',
        'Nothing here.',
        'He turned around.',
        '"I already told you."',
        'Gone.',
    ]
    body = b''.join(b'     ' + ws4_text(l) + HARD for l in lines)
    assert core.detect(body)['variant'] == 'ws4'
    doc = core.parse_ws(body)
    margin = doc.meta.get('margin_estimate') or 65
    units = core.assemble_paragraphs(doc.blocks[0], margin)
    assert len(units) == 6, [l.text() for u in units for l in u]
    assert all(len(u) == 1 for u in units)


def _filler(n):
    """`n`-visible-character non-terminal, non-quote-opening filler text --
    a stand-in for a real verse line whose own length happens to fall past
    the shortness pre-filter, without needing (or risking pasting in) real
    corpus text."""
    return ('word ' * ((n // 5) + 3))[:n].rstrip()


def test_ws4_long_line_boxed_in_by_verse_widens_into_the_run():
    """The in-run widening (Jon's ruling, round 2 addendum, 2026-08-17): a
    single line past `threshold` but under the block's own margin, with a
    verified-short verse line immediately before AND after it, still joins
    the stanza -- found against a real personal poem (a 57-of-65-column
    line splitting an otherwise unbroken run in two) and reproduced here
    without the real text."""
    stanza = [
        'shadows learning how to fall',
        'something waits beyond the rain',
        _filler(60),                        # past threshold(55), under margin(65)
        'patient at the garden wall',
        'marking time against the age',
    ]
    body = b''.join(b'     ' + ws4_text(l) + HARD for l in stanza)
    assert core.detect(body)['variant'] == 'ws4'
    doc = core.parse_ws(body)
    margin = doc.meta.get('margin_estimate') or 65
    units = core.assemble_paragraphs(doc.blocks[0], margin)
    assert len(units) == 1, [l.text() for u in units for l in u]
    assert sum(len(u) for u in units) == 5


def test_ws4_long_line_boxed_in_by_dialogue_does_not_widen():
    """Companion/safety-net check: the SAME boxed-in shape, but the
    neighbours are short dialogue (quote-opening, terminal-punctuated)
    rather than verse -- the widened-in long line still has to survive
    `looks_like_verse`'s content verdict on the whole run, so the run
    reads as prose and every line -- including the widened one -- stays
    its own paragraph. Proves the widening is bounded by content, not just
    length: it cannot glue a real prose one-liner to its dialogue
    neighbours."""
    lines = [
        'Wait.',
        '"Where are you going?"',
        _filler(59),
        '"I already told you."',
        'Gone.',
    ]
    body = b''.join(b'     ' + ws4_text(l) + HARD for l in lines)
    assert core.detect(body)['variant'] == 'ws4'
    doc = core.parse_ws(body)
    margin = doc.meta.get('margin_estimate') or 65
    units = core.assemble_paragraphs(doc.blocks[0], margin)
    assert len(units) == 5, [l.text() for u in units for l in u]
    assert all(len(u) == 1 for u in units)


# ------------------------------------------------------- epigraph handling
# (Jon's ruling, closing round, 2026-08-17: convention-outlier detection
# bounded by document position -- see core.paragraph_layout_context and
# assemble_paragraphs's outlier route. Shaped after a private-corpus WS4 story's real
# structure -- a flush-typed verse epigraph opening the document, ordinary
# 5-space-indented prose paragraphs everywhere else -- with synthetic text
# throughout, never the real corpus.)

def test_epigraph_at_document_head_becomes_one_stanza_unit():
    """The private-corpus story's real defect shape: a flush-typed (no per-line indent),
    non-terminal, multi-line epigraph opens the document; every ordinary
    paragraph in the rest of the document opens with the same 5-space
    indent, so the epigraph's own opening line is a convention outlier AND
    sits at the document's head. Acceptance: the epigraph becomes ONE
    preserved stanza unit (all lines kept, internal breaks only); the
    ordinary body paragraphs are each unaffected, still their own units."""
    epigraph = [
        b'the river does not pause to name itself',
        b'nor does the field ask why it opens',
        b'toward whatever light the morning keeps',
    ]
    body1 = [b'     A plain paragraph that behaves exactly as expected here.']
    body2 = [b'     Another ordinary paragraph continues the story further.']
    body3 = [b'     A third paragraph closes out this small fixture nicely.']
    doc = _para_blocks_doc([epigraph, body1, body2, body3])
    convention_indent, head_position = core.paragraph_layout_context(doc)
    assert convention_indent == 5
    margin = doc.meta.get('margin_estimate') or 65
    blocks = [b for b in doc.blocks if b.kind == 'para' and b.lines]

    epigraph_units = core.assemble_paragraphs(
        blocks[0], margin, head_position=head_position.get(id(blocks[0]), False),
        convention_indent=convention_indent)
    assert len(epigraph_units) == 1, [l.text() for u in epigraph_units for l in u]
    assert sum(len(u) for u in epigraph_units) == 3

    for b in blocks[1:]:
        units = core.assemble_paragraphs(
            b, margin, head_position=head_position.get(id(b), False),
            convention_indent=convention_indent)
        assert len(units) == 1 and len(units[0]) == 1, [l.text() for u in units for l in u]

    # acceptance, restated across all four Modern formats: 3 source lines
    # -> 1 unit with internal breaks only, everywhere.
    h = emit.emit_html(doc, mode='modern')
    r = emit.emit_rtf(doc, mode='modern')
    md = emit.emit_markdown(doc, mode='modern')
    t = emit.emit_text(doc, mode='modern')
    assert h.count('<p') == 4 and h.count('<br>') == 2      # epigraph + 3 body paras
    assert r.count(r'\line') == 2
    assert md.count('\n\n') == 3
    assert t.count('\n\n') == 3


def test_epigraph_after_chapter_heading_becomes_one_stanza_unit():
    """The positional variant: the same flush-typed epigraph shape, but
    placed mid-document immediately after a heading-classified block (a
    chapter title) instead of at the document's own head. The heading
    reopens the front-matter window for what follows, so the epigraph
    still gets the whole-block verse route; body paragraphs before AND
    after are unaffected."""
    body1 = [b'     A plain paragraph that behaves exactly as expected here.']
    body2 = [b'     Another ordinary paragraph continues the story further.']
    chapter_heading = [b'     Chapter Two']
    chapter_epigraph = [
        b'the river does not pause to name itself',
        b'nor does the field ask why it opens',
        b'toward whatever light the morning keeps',
    ]
    body3 = [b'     A third paragraph closes out this small fixture nicely.']
    doc = _para_blocks_doc([body1, body2, chapter_heading, chapter_epigraph, body3])
    blocks = [b for b in doc.blocks if b.kind == 'para' and b.lines]
    blocks[2].heading = 1              # force heading classification (Chapter Two)

    convention_indent, head_position = core.paragraph_layout_context(doc)
    margin = doc.meta.get('margin_estimate') or 65
    assert head_position.get(id(blocks[3])) is True   # epigraph reopened by the heading

    epigraph_units = core.assemble_paragraphs(
        blocks[3], margin, head_position=head_position.get(id(blocks[3]), False),
        convention_indent=convention_indent)
    assert len(epigraph_units) == 1, [l.text() for u in epigraph_units for l in u]
    assert sum(len(u) for u in epigraph_units) == 3

    for b in (blocks[0], blocks[1], blocks[4]):
        units = core.assemble_paragraphs(
            b, margin, head_position=head_position.get(id(b), False),
            convention_indent=convention_indent)
        assert len(units) == 1 and len(units[0]) == 1


def test_convention_outlier_mid_body_stays_conservative_unless_overwhelming():
    """The safety net: a convention-outlier block deep in mid-body prose
    (neither at the document's head nor after a heading/section boundary)
    must NOT get the whole-block verse route just because it happens to
    open flush -- unless the verse signal is overwhelming (not one line in
    the whole block ends as a finished sentence). Two mid-body blocks,
    same flush-then-indented shape (the real epigraph's own [3, 2] shape,
    reused mid-document instead of at the head):

    - terminally-punctuated throughout (ordinary narrative that merely
      forgot its indent) -- stays split, same shape phase 1 already gives
      it ([3, 2]), NOT swept into one stanza just because it's an outlier.
    - zero terminal punctuation anywhere (decisive enjambment) -- DOES
      still merge into one unit, proving the override isn't disabled
      outright for mid-body, only raised to a much higher bar."""
    body1 = [b'     A plain paragraph that behaves exactly as expected here.']
    body2 = [b'     Another ordinary paragraph continues the story further.']
    body3 = [b'     A third paragraph closes out this small fixture nicely.']
    midbody_conservative = [
        b'Quiet now, she said firmly.',
        b'Nobody answered at all.',
        b'Then footsteps came again outside.',
        b'     He turned back toward the door slowly.',
        b'It was already too late for that.',
    ]
    midbody_strong_override = [
        b'the wind keeps turning without a name',
        b'and nothing answers from the field',
        b'until the light comes back again',
        b'     circling slowly toward the door',
        b'waiting for whatever comes next',
    ]
    doc = _para_blocks_doc([body1, body2, midbody_conservative, body3,
                            midbody_strong_override])
    convention_indent, head_position = core.paragraph_layout_context(doc)
    margin = doc.meta.get('margin_estimate') or 65
    blocks = [b for b in doc.blocks if b.kind == 'para' and b.lines]

    conservative_block = blocks[2]
    assert head_position.get(id(conservative_block), False) is False
    units = core.assemble_paragraphs(
        conservative_block, margin,
        head_position=head_position.get(id(conservative_block), False),
        convention_indent=convention_indent)
    assert [len(u) for u in units] == [3, 2], [l.text() for u in units for l in u]

    override_block = blocks[4]
    assert head_position.get(id(override_block), False) is False
    units = core.assemble_paragraphs(
        override_block, margin,
        head_position=head_position.get(id(override_block), False),
        convention_indent=convention_indent)
    assert len(units) == 1, [l.text() for u in units for l in u]
    assert sum(len(u) for u in units) == 5


def test_modern_html_poem_stays_one_paragraph_with_hard_breaks():
    lines = [
        b'     Line one is short,',
        b'     line two also short --',
        b'     line three fits the pattern --',
        b'     line four closes it.',
    ]
    doc = _typed_paragraph_doc(lines)
    h = emit.emit_html(doc, mode='modern')
    assert h.count('<p') == 1
    assert h.count('<br>') == 3
    assert '<pre' not in h


def test_modern_rtf_poem_stays_one_par_with_line_breaks():
    lines = [
        b'     Line one is short,',
        b'     line two also short --',
        b'     line three fits the pattern --',
        b'     line four closes it.',
    ]
    doc = _typed_paragraph_doc(lines)
    r = emit.emit_rtf(doc, mode='modern')
    assert r.count(r'\par') == 1
    assert r.count(r'\line') == 3


def test_modern_markdown_poem_stays_one_paragraph_with_hard_breaks():
    """Companion to the HTML/RTF poem tests, for Markdown: a verified
    stanza still gets a real forced break -- classic Markdown/CommonMark's
    own vocabulary for one, two TRAILING SPACES before the newline (round
    4, 2026-08-17: was a trailing backslash, replaced because some
    renderers show it literally and it's text that never existed in the
    WordStar source either way)."""
    lines = [
        b'     Line one is short,',
        b'     line two also short --',
        b'     line three fits the pattern --',
        b'     line four closes it.',
    ]
    doc = _typed_paragraph_doc(lines)
    md = emit.emit_markdown(doc, mode='modern')
    assert md.count('\n\n') == 0
    assert md.count('  \n') == 3
    assert not any(l.endswith('\\') for l in md.split('\n'))


def test_modern_text_poem_stays_one_paragraph_with_line_breaks():
    """Companion to the HTML/RTF/Markdown poem tests, for Text (round 3b,
    2026-08-17): a verified stanza still gets a real forced break -- a
    bare newline, Text's own paragraph-INTERNAL break -- between each of
    its lines, distinct from the blank-line paragraph separator."""
    lines = [
        b'     Line one is short,',
        b'     line two also short --',
        b'     line three fits the pattern --',
        b'     line four closes it.',
    ]
    doc = _typed_paragraph_doc(lines)
    t = emit.emit_text(doc, mode='modern')
    assert t.count('\n\n') == 0
    assert t.strip().count('\n') == 3


def test_modern_prose_lines_each_get_own_paragraph():
    long = 'x' * 58
    lines = [f'     {long} one'.encode(), f'     {long} two'.encode(),
             f'     {long} three'.encode()]
    doc = _typed_paragraph_doc(lines)
    h = emit.emit_html(doc, mode='modern')
    r = emit.emit_rtf(doc, mode='modern')
    md = emit.emit_markdown(doc, mode='modern')
    t = emit.emit_text(doc, mode='modern')
    assert h.count('<p') == 3 and '<br>' not in h
    assert r.count(r'\par') == 3 and r.count(r'\line') == 0
    assert md.count('\n\n') == 2 and '\\\n' not in md
    assert t.count('\n\n') == 2


def test_modern_non_verse_multiline_unit_flows_in_all_four_formats():
    """Round 3b (2026-08-17): "no hard line breaks inside paragraphs in
    ANY Modern format." Two complete, terminally-punctuated sentences --
    decisively prose by every `looks_like_verse` signal -- shaped as a
    BARE phase-1 flush-continuation unit (line 0 indented starts it, line
    1 flush continues it): this never even reaches phase 2's verse check
    inside `assemble_paragraphs` (multi-line already, so phase 2 skips
    it), which is exactly why each emitter has to re-derive the verdict
    itself at render time. Real evidence this shape exists: the private-corpus story's own
    title block and one other body unit, found when this fix was first
    applied to HTML alone and only later made uniform. All four formats
    must flow it as ONE paragraph with NO forced break of any kind --
    <br>, \\line, a trailing-backslash break, or a bare newline."""
    lines = [
        b'     Fenn walked slowly to the door and stopped there for a moment.',
        b'He turned the handle very carefully and stepped outside into the cold.',
    ]
    doc = _typed_paragraph_doc(lines)
    margin = doc.meta.get('margin_estimate') or 65
    units = core.assemble_paragraphs(doc.blocks[0], margin)
    assert len(units) == 1 and len(units[0]) == 2          # one bare 2-line unit
    dominant = core.block_dominant_styles(core.merged_lines(doc.blocks[0]))
    assert not core.looks_like_verse(units[0], dominant)    # decisively prose

    h = emit.emit_html(doc, mode='modern')
    r = emit.emit_rtf(doc, mode='modern')
    md = emit.emit_markdown(doc, mode='modern')
    t = emit.emit_text(doc, mode='modern')
    assert h.count('<p') == 1 and '<br>' not in h
    assert r.count(r'\par') == 1 and r'\line' not in r
    assert md.count('\n\n') == 0 and '\\\n' not in md
    assert t.strip().count('\n') == 0                       # one flowed line, no break


def test_modern_first_line_indent_becomes_property_not_literal_spaces():
    """Rule B/C: no literal leading indent whitespace opening a Modern
    paragraph -- it becomes \\fi (RTF) / text-indent (HTML)."""
    doc = _typed_paragraph_doc([b'     Indented paragraph text here, fine.'])
    h = emit.emit_html(doc, mode='modern')
    r = emit.emit_rtf(doc, mode='modern')
    assert 'text-indent:5ch' in h
    assert not re.search(r'<p[^>]*>\s{2,}', h)
    assert r'\fi720' in r                      # 5 cols * 144 twips/col
    assert not re.search(r'\\par [^{}]*\{[^{}]*  ', r)


def test_modern_markdown_drops_first_line_indent():
    doc = _typed_paragraph_doc([b'     Indented paragraph text here, fine.'])
    md = emit.emit_markdown(doc, mode='modern')
    assert not md.startswith('     ')
    assert md.lstrip('\n').startswith('Indented')


def test_modern_quote_style_gets_blockquote_prefix_in_markdown():
    rec = _style_record(left=1260, just=0)
    body = b'A quoted passage of reasonable length for testing purposes.' + HARD
    doc = _doc_with_style('Double-Indented Quote', rec, body)
    assert doc.blocks[-1].style_name == 'Double-Indented Quote'
    md = emit.emit_markdown(doc, mode='modern')
    assert any(l.startswith('> ') for l in md.split('\n'))


# ---------------------------------------------------------------- lint gates
# (item G: permanent pytest tests, run against real fixture conversions)

def _ir_bad_adjacent_spans(doc):
    """Adjacent, byte-identical-style spans surviving in the IR itself
    (lint gate 1) -- the precise form of the check. A RENDERED-text version
    (grep the RTF/HTML for two touching same-attribute runs) sounds more
    direct but isn't: it false-positives on two entirely separate, benign
    mechanisms a real corpus exercises --

      * an invisible note reference (a WordStar comment, excluded from
        `notes=` by default) renders to '', leaving what LOOKS like two
        touching runs in the OUTPUT even though the IR correctly keeps
        them apart (never merge across a fnref span -- a different note
        selection could render real content there);
      * distinct font-block indices in the SOURCE that fontmap.rtf_fonts
        happens to resolve to the same target face (\\f7, say) render
        identically without being the same style at the IR level.

    Testing the IR directly -- exactly what core.merged_lines()/
    coalesce_spans() promise -- sidesteps both. `merged_lines()` already
    calls coalesce_spans() internally, so this is a regression trip-wire
    (it must stay empty), not a search for new problems."""
    bad = []
    for b in doc.blocks:
        for line in core.merged_lines(b):
            spans = line.spans
            for i in range(len(spans) - 1):
                a, c = spans[i], spans[i + 1]
                if a.styles == c.styles and 'fnref' not in a.styles:
                    bad.append((a.text[:24], c.text[:24]))
    return bad


def _ir_bad_paragraph_indent_opens(doc):
    """Every Modern paragraph unit's OWN first line, after
    core.split_leading_indent() runs on it, must not still open with a
    literal 2+-space run (lint gate 2). This is the IR-level form of the
    check -- see _ir_bad_adjacent_spans for why: a RENDERED-text version
    (regex the HTML/RTF for a `<p>`/`\\par` that opens with spaces) sounds
    more direct but has to reliably locate "the paragraph's true first
    line" in output text, and gets fooled by ordinary, correct output
    shapes a real corpus contains -- a unit whose first Line strips down to
    NOTHING (an indent-only blank) renders no opening run at all, so the
    first VISIBLE text a naive scanner finds is actually the unit's second
    or third line, which never went through the first-line indent
    extraction and is legitimately keeping its OWN literal spacing (a
    poem's second verse, a legend's differently-indented rows -- content,
    not a paragraph-start marker, exactly as designed). Checking the
    mechanism directly avoids reconstructing paragraph boundaries from
    text at all."""
    bad = []
    margin = doc.meta.get('margin_estimate') or 65
    for b in doc.blocks:
        if b.kind != 'para' or b.heading:
            continue
        for unit in core.assemble_paragraphs(b, margin):
            _, spans = core.split_leading_indent(list(unit[0].spans))
            if spans and spans[0].text.startswith('  '):
                bad.append((b.style_name, spans[0].text[:40]))
    return bad


def _unit_is_glued(unit, dominant):
    """The predicate at the heart of the tightened gate: does paragraph
    UNIT contain an indented line anywhere but first, and if so, is the
    unit actually a verified stanza (core.looks_like_verse)? Split out from
    `_ir_glued_indented_paragraphs` so the check itself can be regression-
    tested directly against a hand-built unit shape (see
    `test_ir_glued_indented_paragraphs_gate_catches_round1_shape`), not
    only through `assemble_paragraphs`, which no longer produces this
    shape at all now that the fix has landed -- exercising the predicate
    in isolation is what keeps a future weakening of the CHECK itself
    (not the algorithm) from going unnoticed."""
    if len(unit) < 2:
        return False
    interior_indented = any(
        core.line_visible_text(l).startswith('     ')
        for l in unit[1:])
    return interior_indented and not core.looks_like_verse(unit, dominant)


def _ir_glued_indented_paragraphs(doc):
    """The check that SHOULD have caught round 1's real defect and did
    not: `_ir_bad_paragraph_indent_opens` only asks whether a unit's own
    first line still opens with literal spaces after extraction -- true by
    construction, so it passed clean on round-1 output where 43 real
    paragraph-openings across OLDTIMES.rtf were glued onto the TAIL of the
    wrong paragraph as an indented interior `\\line`d line, never becoming
    a unit's first line at all. This asks the actual question via
    `_unit_is_glued`. Proven to fail against round-1's real algorithm (see
    the branch's commit history) before this fix landed."""
    bad = []
    margin = doc.meta.get('margin_estimate') or 65
    for b in doc.blocks:
        if b.kind != 'para' or b.heading:
            continue
        merged = core.merged_lines(b)
        dominant = core.block_dominant_styles(merged)
        for unit in core.assemble_paragraphs(b, margin):
            if _unit_is_glued(unit, dominant):
                bad.append((b.style_name,
                           [core.line_visible_text(l)[:30] for l in unit]))
    return bad


def test_ir_glued_indented_paragraphs_gate_catches_round1_shape():
    """Regression-proof the tightened gate itself (finish-list item 4,
    2026-08-17): reproduce round 1's real defect SHAPE directly -- an
    indented, decisively-prose paragraph-start line glued onto the TAIL of
    a different unit as an interior line, never reaching its own unit at
    all -- and confirm `_unit_is_glued` flags it. Built directly against
    the unit-level predicate rather than through `assemble_paragraphs`,
    which (as of this fix) never produces this shape any more; that's the
    point -- this is a trip-wire on the CHECK, so a future change that
    reintroduces round 1's algorithm still gets caught even though no real
    fixture can exercise it end-to-end any more.

    Companion assertion: the same predicate must NOT flag a genuine
    verified stanza (an indented interior line that IS part of a real
    verse run) -- the gate exists to catch a bypass of the verse check,
    not to veto every indented interior line outright."""
    # Round-1 shape: two complete, terminally-punctuated, unstyled prose
    # sentences -- decisively NOT verse by every looks_like_verse signal --
    # with the second glued in as an indented INTERIOR line of the first's
    # unit instead of starting its own.
    glued_unit = [
        core.Line([core.Span('     Fenn walked to the door and stopped there.',
                             frozenset())]),
        core.Line([core.Span('     He turned the handle very slowly indeed today.',
                             frozenset())]),
    ]
    assert _unit_is_glued(glued_unit, frozenset())

    # Companion: a real 2-line stanza (short, non-terminal, enjambed) with
    # its second line indented -- must NOT be flagged; that shape is
    # legitimate verse, not round 1's defect.
    verse_unit = [
        core.Line([core.Span('     Winter light upon the pane', frozenset())]),
        core.Line([core.Span('     shadows learning how to fall', frozenset())]),
    ]
    assert not _unit_is_glued(verse_unit, frozenset())


def _html_bad_geometry(h):
    """Round 3 (2026-08-17): Modern HTML must carry NO page-width opinion
    of its own -- neither WS-absolute geometry (the original defect: a
    quote paragraph's own `margin-right:5.8in` alone exceeded the reading
    column and broke wrapping in a real browser) NOR our own former
    `max-width`/measure convention (Jon's round-3 addendum: width belongs
    to the reader's own window, full stop, in Modern AND Native alike).
    Flags any `max-width`/bare `width` CSS property anywhere, and any
    `margin-left`/`margin-right` expressed in inches over 1in (the
    blockquote structural inset is a flat em value, never inches, so this
    never fires on legitimate quote styling)."""
    bad = []
    if re.search(r'(?<![-\w])max-width\s*:', h):
        bad.append('max-width declared')
    if re.search(r'(?<![-\w])width\s*:', h):
        bad.append('width declared')
    for m in re.finditer(r'margin-(left|right)\s*:\s*([\d.]+)in', h):
        if float(m.group(2)) > 1.0:
            bad.append(f'margin-{m.group(1)}:{m.group(2)}in')
    return bad


def _rtf_bad_geometry(r):
    """Round 3: Modern RTF's stylesheet must carry no `\\li`/`\\ri` over
    1440 twips (1in) -- ordinary styles lose page geometry outright (no
    \\li/\\ri at all); a quote style's own override is a flat 720-twip
    (0.5in) inset (`_RTF_MODERN_QUOTE_INSET`), comfortably under this
    bound. Scoped to the `\\stylesheet` group specifically (see
    `_rtf_body_only`'s docstring for the correct `\\paperw` boundary --
    an earlier version of this lookahead used `{\\f0`, which sits BEFORE
    `\\stylesheet` in `emit_rtf`'s own output order, so it silently never
    matched at all and this check spent the whole round validating an
    empty string)."""
    m = re.search(r'\{\\stylesheet.*?\}(?=\\paperw)', r, re.S)
    sheet = m.group(0) if m else ''
    bad = []
    for mm in re.finditer(r'\\(li|ri)(\d+)', sheet):
        if int(mm.group(2)) > 1440:
            bad.append(f'\\{mm.group(1)}{mm.group(2)}')
    return bad


def _md_deep_indent_lines(md):
    """Round 3 (+ Jon's follow-up Markdown note): no CONTENT line in
    Modern Markdown may open with 4+ literal spaces -- CommonMark reads
    that as an indented code block, and it's also simply meaningless in
    Markdown (no first-line-indent concept, no verse-indent concept). This
    is the general form of the hazard class; it covers verse/stanza lines
    (uniformly flush per the follow-up ruling) the same way it covers a
    centred block's stripped padding -- one check, not a special case per
    content type."""
    return [l for l in md.split('\n') if l[:4] == '    ']


def _md_trailing_backslash_lines(md):
    """Round 4 (2026-08-17): no line in Modern Markdown may end with a
    literal backslash -- that was the OLD hard-break marker, replaced with
    two trailing spaces (classic Markdown/CommonMark) because Jon found
    some renderers show a trailing backslash literally, and it's text
    that never existed in the WordStar source either way."""
    return [l for l in md.split('\n') if l.endswith('\\')]


def _html_adjacent_blockquotes(h):
    """Round 4 (2026-08-17): no `</blockquote>` may be immediately
    followed by a `<blockquote>` across only whitespace -- that shape is
    exactly the round-3 defect (one <blockquote> per paragraph UNIT
    instead of per CONSECUTIVE quote-style run), which rendered a real
    multi-paragraph quotation as a stack of separately bordered, gapped
    boxes instead of one continuous quote block."""
    return re.findall(r'</blockquote>\s*<blockquote>', h)


def _html_blockquote_indent_variance(h):
    """Round 4: every <p>'s own `text-indent` INSIDE one <blockquote> must
    be the same value -- the group's own first paragraph sets it (see
    `emit_html`'s `quote_indent_cols`), reused for every paragraph in the
    group rather than each one's own (source-inconsistent) raw column
    count. Returns blockquotes with more than one distinct value found."""
    bad = []
    for bq in re.findall(r'<blockquote>(.*?)</blockquote>', h, re.S):
        indents = set(re.findall(r'text-indent:(\d+)ch', bq))
        if len(indents) > 1:
            bad.append(indents)
    return bad


def _rtf_body_only(r):
    """`r` with the `\\fonttbl` AND `\\stylesheet` groups removed --
    state-replay checks (`_rtf_state_issues`, `_rtf_missing_run_attrs`)
    must scan only the BODY's own direct-formatting/text runs. Two
    real false-positive sources found removing each:

    - `\\stylesheet` legitimately contains the same `\\li`/`\\ri`/`\\b`/
      `\\i` control words for an entirely different reason (Word's named-
      style definitions) and corrupts a naive token replay if left in.
      Emitted right after `\\fonttbl` (BEFORE `{\\f0` in `_rtf_stylesheet`'s
      own document position -- not after it, which a first attempt at
      this lookahead got backwards and silently matched nothing at all)
      and always immediately precedes `emit_rtf`'s own page-setup block,
      which always opens with the fixed `\\paperw` token -- an
      unambiguous boundary.
    - `\\fonttbl` itself holds literal FONT NAME strings in braces (e.g.
      `{\\f1 Courier New;}`) that read as plausible "runs" to a naive
      brace-group scan -- found for real (MARKUP.WS): the paragraph-split
      regex's own FIRST chunk (everything before the first real `\\par`)
      still included the whole preamble, so a font name's own braces got
      swept in as if they belonged to the first paragraph's \\sN run and
      flagged missing attributes that were never real runs at all."""
    body = re.sub(r'\{\\fonttbl.*?\}(?=\{\\stylesheet|\\paperw)', '', r, flags=re.S)
    return re.sub(r'\{\\stylesheet.*?\}(?=\\paperw)', '', body, flags=re.S)


def _rtf_state_issues(r, doc, printed=False):
    """Replay Modern RTF's own body -- direct-formatting tokens ONLY, the
    `\\stylesheet` group entirely excluded from what's read (round 5's
    absolute ruling, 2026-08-17: DIRECT FORMATTING IS THE ONLY RENDERING
    MECHANISM IN RTF -- Jon opened a delivered file in Word ITSELF and
    found style-declared bold invisible there too, which kills any
    reader-specific "stylesheet is fine for X" premise outright; the RTF
    spec's own `\\sN` is nominal, a style-pane label, and no reader is
    obliged to apply `\\stylesheet` on load). Tracks li/ri/fi as direct-
    formatting state, token by token, and flags two hazards:

    - a paragraph referencing a stylesheet style (`\\sN`) whose style-
      table margins (`_rtf_style_margins` -- the DATA, never the
      rendered `\\stylesheet` text) don't match the direct state active
      at that point.
    - a quote-classified paragraph's own `\\fi` outside a sane bound
      (1440 twips/1in) -- scoped to quote styles specifically; an
      ordinary body paragraph's own (potentially large, genuinely typed)
      indent is real content no round has touched or verified."""
    margins = {e['slot']: emit._rtf_style_margins(e, printed)
              for e in doc.styles if 'attrs_on' in e}
    quote_slots = {e['slot'] for e in doc.styles
                   if 'attrs_on' in e and emit._is_quote_name(e.get('name'))}
    body = _rtf_body_only(r)
    tokens = re.findall(r'\\li(-?\d+)|\\ri(-?\d+)|\\fi(-?\d+)|\\s(\d+) ', body)
    li = ri = fi = 0
    bad = []
    for li_t, ri_t, fi_t, s_t in tokens:
        if li_t:
            li = int(li_t)
        if ri_t:
            ri = int(ri_t)
        if fi_t:
            fi = int(fi_t)
        if s_t:
            slot = int(s_t) - 1
            if slot in margins:
                exp = margins[slot]
                if (li, ri) != exp:
                    bad.append(f'\\s{s_t}: direct(li={li},ri={ri}) != style{exp}')
                if slot in quote_slots and abs(fi) > 1440:
                    bad.append(f'\\s{s_t}: fi={fi} exceeds 1440-twip bound')
    return bad


_RTF_ATTR_CTL = {'b': r'\b ', 'i': r'\i ', 'u': r'\ul ', 'sup': r'\super ',
                 'sub': r'\sub ', 'strike': r'\strike '}


def _rtf_missing_run_attrs(r, doc):
    """Round 5 (2026-08-17): every RUN inside a paragraph that references a
    stylesheet style must carry that style's OWN declared character
    attributes (b/i/u/strike/sub/sup) as direct control words -- not just
    inherited from `\\sN`, which is nominal per the RTF spec and which
    Word itself was found to ignore on load. Scans `\\par`-delimited
    paragraphs for an `\\sN` tag, then checks every text-carrying brace
    run within that paragraph for the style's full attribute set (from
    `doc.styles`, the DATA -- never the rendered `\\stylesheet` text).
    A run with no letters (a bare control group) isn't a character run
    and is skipped. A run that IS a footnote/endnote/annotation/comment
    DESTINATION (RTF's own `\\*` "skip if unrecognised" marker, or one of
    the specific note control words) is ALSO skipped -- found for real
    (NOVEL.WS): a comment's own `{\\*\\annotation ...}` text is
    independent note content with its own formatting reset
    (`\\pard\\plain\\fs24`), not a run that inherits the ENCLOSING
    paragraph's style, and flagging it for missing the paragraph's bold
    would be demanding a comment popup match body text it was never
    part of."""
    style_attrs = {e['slot']: e.get('attrs', frozenset())
                   for e in doc.styles if 'attrs_on' in e}
    body = _rtf_body_only(r)
    bad = []
    for para in re.split(r'(?<=\\par )', body):
        m = re.search(r'\\s(\d+) ', para)
        if not m:
            continue
        attrs = style_attrs.get(int(m.group(1)) - 1, frozenset())
        needed = [a for a in attrs if a in _RTF_ATTR_CTL]
        if not needed:
            continue
        for run in re.findall(r'\{([^{}]*)\}', para):
            if not re.search(r'[A-Za-z]', run):
                continue
            if '\\*\\' in run or any(c in run for c in
                                    (r'\chftn', r'\chatn', r'\atnid',
                                     r'\footnote', r'\annotation')):
                continue
            missing = [a for a in needed if _RTF_ATTR_CTL[a] not in run]
            if missing:
                bad.append((m.group(1), missing, run[:40]))
    return bad


_ATTR_SET = frozenset({'b', 'i', 'u', 'strike', 'sub', 'sup'})

# The attribute-mapping table this whole audit (round 5, 2026-08-17)
# landed on -- one entry per format, one marker (or tuple of acceptable
# markers) per attribute. Native HTML shares Modern HTML's own `_TAG`
# table (run-level rendering is identical; only page geometry differs,
# per round 3/4's own printed-vs-modern split) so it is not listed
# separately. Text has NO markers at all -- see `emit_text`'s own RULED
# EXCLUSION docstring -- so it is intentionally absent from this table
# rather than mapped to an empty tuple.
_ATTR_MARKERS = {
    'html': {'b': ('<strong', 'font-weight:bold'),
             'i': ('<em', 'font-style:italic'),
             'u': ('<u>',),
             'strike': ('<s>', 'text-decoration:line-through'),
             'sub': ('<sub', 'vertical-align:sub'),
             'sup': ('<sup', 'vertical-align:super')},
    'rtf': {a: (ctl,) for a, ctl in _RTF_ATTR_CTL.items()},
    'markdown': {'b': ('**',), 'i': ('*',), 'strike': ('~~',),
                 'u': ('<u>',), 'sub': ('<sub>',), 'sup': ('<sup>',)},
}


def _effective_attrs_present(doc):
    """Every character attribute (b/i/u/strike/sub/sup) EFFECTIVELY
    present anywhere in the document -- style-declared OR run-toggled,
    merged via `core.effective_span_styles` (round 5's own fix) -- the
    source-of-truth set the attribute-mapping lint checks each format's
    output against.

    A note-REFERENCE marker (`fnref`) is excluded (found for real,
    NOTES.TST): WordStar raises a footnote/endnote reference number with
    its own `sup`, but that `sup` never reaches the general attribute
    path in ANY format -- HTML/RTF wrap the reference in their OWN
    dedicated superscript markup regardless of the span's styles, and
    Markdown's `[^label]` carries the same meaning natively with no
    wrapping at all. Checking for it here would demand a marker no
    format's own (correct, intentional) note-reference handling ever
    produces."""
    present = set()
    for b in doc.blocks:
        if b.kind != 'para' or not b.lines:
            continue
        for line in b.lines:
            for sp in line.spans:
                if 'fnref' in sp.styles:
                    continue
                present |= (core.effective_span_styles(sp, b) & _ATTR_SET)
    return present


def _missing_attr_markers(rendered, fmt, attrs_present):
    """Attributes in `attrs_present` with NONE of their mapped markers
    (`_ATTR_MARKERS[fmt]`) anywhere in `rendered` -- the fail-first half
    of the round-5 audit: every attribute a real fixture's sources
    declare must show up, per the mapping table, in every format that
    isn't a RULED exclusion."""
    table = _ATTR_MARKERS[fmt]
    body = _rtf_body_only(rendered) if fmt == 'rtf' else rendered
    return [a for a in sorted(attrs_present)
            if a in table and not any(m in body for m in table[a])]


def _wrap_off_issues(doc):
    """Round 7 (2026-08-17): every wrap=off (`.aw off`) block must
    assemble into EXACTLY ONE paragraph unit containing ALL of its own
    merged lines -- Register C23, "a reflowing consumer must NOT re-wrap
    them or the layout is destroyed." Checked directly against the
    MODEL (`core.assemble_paragraphs`'s own return value), not rendered
    text, so it catches the core regression regardless of any single
    format's own rendering quirks."""
    margin = doc.meta.get('margin_estimate') or 65
    ci, hp = core.paragraph_layout_context(doc)
    bad = []
    for b in doc.blocks:
        if b.kind != 'para' or not b.lines or b.wrap is not False:
            continue
        merged = core.merged_lines(b)
        units = core.assemble_paragraphs(b, margin, head_position=hp.get(id(b), False),
                                         convention_indent=ci)
        if len(units) != 1 or sum(len(u) for u in units) != len(merged):
            bad.append((b.style_name, len(merged), [len(u) for u in units]))
    return bad


def _wrap_off_rendering_issues(doc):
    """Round 7: a MULTI-line wrap=off block renders as one structural
    paragraph with a forced break between every line, in HTML and RTF --
    the two formats with unambiguous structural markup for "paragraph"
    (`<p>`/`\\par`) versus "forced break" (`<br>`/`\\line`). Markdown and
    Text are deliberately not asserted here at the same per-line-break
    precision: a genuinely BLANK line inside a hand-positioned block
    (found for real, MARKUP.WS -- a spacer row in the middle of a
    10-line table-ish block) renders as an empty string, and a plain-text
    join has no way to say "that blank was CONTENT, not a paragraph
    separator" -- an inherent limitation of those two formats' own
    vocabulary, not something this round introduces or can fix. RTF's own
    `\\par` count allows >= 1 rather than == 1: a block's own TRAILING
    author blank lines still echo as extra bare `\\par`s (pre-existing,
    unrelated mechanism -- `trailing_blank_lines`), which is correct and
    not a paragraph split; `\\line` count, unaffected by that mechanism,
    is the precise signal."""
    bad = []
    for b in doc.blocks:
        if b.kind != 'para' or not b.lines or b.wrap is not False:
            continue
        merged = core.merged_lines(b)
        if len(merged) < 2:
            continue
        mini = copy.copy(doc)
        mini.blocks = [b]
        expected = len(merged) - 1
        h = emit.emit_html(mini, mode='modern')
        if h.count('<p') != 1 or h.count('<br>') != expected:
            bad.append(('html', h.count('<p'), h.count('<br>'), expected))
        r = emit.emit_rtf(mini, mode='modern')
        if r.count(r'\par') < 1 or r.count(r'\line') != expected:
            bad.append(('rtf', r.count(r'\par'), r.count(r'\line'), expected))
    return bad


def _assert_lint_gates(name, doc):
    # Rendering all four Modern formats here is also the corpus smoke test
    # (item I): every real fixture must convert without crashing, whether
    # or not a structural gate below has anything to say about its output.
    h = emit.emit_html(doc, mode='modern', notes=emit.ALL_NOTE_KINDS)
    r = emit.emit_rtf(doc, mode='modern', notes=emit.ALL_NOTE_KINDS)
    md = emit.emit_markdown(doc, mode='modern', notes=emit.ALL_NOTE_KINDS)
    emit.emit_text(doc, mode='modern', notes=emit.ALL_NOTE_KINDS)

    # 7. Modern HTML carries no page-width opinion (round 3 + addendum)
    assert not _html_bad_geometry(h), (name, 'html page-width/geometry leak',
                                       _html_bad_geometry(h))
    # 8. Modern RTF stylesheet carries no geometry over 1in
    assert not _rtf_bad_geometry(r), (name, 'rtf geometry over 1in',
                                      _rtf_bad_geometry(r))
    # 9. Modern Markdown has no 4+-space-opening content line (verse included)
    assert not _md_deep_indent_lines(md), (name, 'markdown deep indent',
                                           _md_deep_indent_lines(md)[:5])
    # 10. Modern Markdown has no trailing-backslash hard break (round 4)
    assert not _md_trailing_backslash_lines(md), \
        (name, 'markdown trailing backslash', _md_trailing_backslash_lines(md)[:5])
    # 11. no adjacent sibling <blockquote>s in Modern HTML (round 4)
    assert not _html_adjacent_blockquotes(h), (name, 'adjacent blockquotes')
    # 12. uniform text-indent across every <p> inside one <blockquote> (round 4)
    assert not _html_blockquote_indent_variance(h), \
        (name, 'blockquote text-indent variance', _html_blockquote_indent_variance(h))
    # 13. Modern RTF: every styled paragraph carries its style's li/ri as
    #     DIRECT tokens (not stylesheet-only), and no quote paragraph's own
    #     \fi exceeds a sane bound (round 4)
    assert not _rtf_state_issues(r, doc, printed=False), \
        (name, 'rtf direct-formatting gap', _rtf_state_issues(r, doc, printed=False))
    # 14. every RUN referencing a styled paragraph carries that style's
    #     OWN declared character attrs as direct tokens (round 5)
    assert not _rtf_missing_run_attrs(r, doc), \
        (name, 'rtf run missing style attr', _rtf_missing_run_attrs(r, doc)[:5])
    # 15. attribute-mapping audit (round 5): every b/i/u/strike/sub/sup
    #     effectively present anywhere in the document shows up, per the
    #     ruled mapping table, in HTML/RTF/Markdown output (Text is a
    #     RULED exclusion -- see emit_text's own docstring -- so it is
    #     deliberately not checked here)
    attrs_present = _effective_attrs_present(doc)
    if attrs_present:
        for fmt, rendered in (('html', h), ('rtf', r), ('markdown', md)):
            missing = _missing_attr_markers(rendered, fmt, attrs_present)
            assert not missing, (name, fmt, 'attribute mapping missing', missing)
    # 18. wrap=off (.aw off) blocks assemble into ONE preserved unit,
    #     every line kept -- Register C23 (round 7)
    assert not _wrap_off_issues(doc), (name, 'wrap=off split', _wrap_off_issues(doc))
    assert not _wrap_off_rendering_issues(doc), \
        (name, 'wrap=off rendering', _wrap_off_rendering_issues(doc))

    # 1. no un-coalesced adjacent runs (IR-level -- see _ir_bad_adjacent_spans)
    assert not _ir_bad_adjacent_spans(doc), (name, 'un-coalesced adjacent spans')

    # 2. no literal multi-space indent opening a Modern paragraph
    #    (Markdown drops it entirely; HTML/RTF use a real indent property)
    assert not _ir_bad_paragraph_indent_opens(doc), (name, 'paragraph-opening indent')
    # 2b. tightened (round 2): no indented line glued mid-paragraph unless
    #     the whole unit is a verified stanza -- this is the check that
    #     should have caught round 1's real defect (43 glued paragraph
    #     opens in OLDTIMES.rtf alone) and, with gate 2 alone, did not.
    assert not _ir_glued_indented_paragraphs(doc), (name, 'indented line glued mid-paragraph')

    # 3. no <pre> in Modern HTML for a non-columnar, non-printstream document
    if doc.meta.get('variant') != 'printstream' and not doc.meta.get('columnar'):
        assert '<pre' not in h, (name, 'modern html used <pre>')

    # 4. no internal WordStar wire-format leaking into public CSS
    assert '--ws-typestyle' not in h, (name, 'ws-typestyle leak')

    # 6. heading text carries no leading alignment padding (double-centering)
    for hm in re.finditer(r'<h[1-3][^>]*>(.*?)</h[1-3]>', h, re.S):
        assert not re.match(r'\s|&nbsp;', hm.group(1)), \
            (name, 'heading leading alignment padding', hm.group(0)[:80])


def test_lint_gates_on_double_centered_heading_synthetic_regression():
    """Direct regression test for defect (b): a centered heading used to
    keep its baked centering spaces as visible &nbsp; runs on top of the
    CSS that already centers it."""
    rec = _style_record(left=0, just=(-2) % 256)     # right/centre-ish record unused here
    # A centered heading is style-independent in this codebase (b.heading +
    # b.align both come from dot-command/style state); build directly via
    # `.oc on` + a heading-level style name so b.heading resolves.
    data = (ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
            + b'.oc on\r\n' + b'     Title Text Here' + HARD + b'.oc off\r\n')
    doc = core.parse_ws(data)
    doc.blocks[0].heading = 1              # force heading classification
    h = emit.emit_html(doc, mode='modern')
    _assert_lint_gates('synthetic-centered-heading', doc)


def test_round3_geometry_normalization_and_quote_distinction():
    """Direct regression test for the round-3 defect (2026-08-17): Jon's
    real bug report was a browser rendering a quote paragraph one word per
    line because `margin-left`+`margin-right:5.8in` (this style's own
    WS4-absolute geometry, straight off an 8.5in page) exceeded the
    reading column. Reproduces that exact geometry (5.8in each side) on a
    synthetic 'Double-Indented Quote' style alongside an ordinary body
    paragraph, and checks all four Modern formats: quotes read as visibly
    distinct from body, and NONE of the WS-absolute geometry survives."""
    quote_rec = _style_record(left=10440, right=10440, just=0)   # 5.8in each side
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        ('Double-Indented Quote', True, quote_rec),
    ])
    header = ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
    body = (header
            + b'     An ordinary body paragraph with plenty of text in it.' + HARD
            + _style_handle(2)
            + b'A quoted passage that must read as visibly different from body.' + HARD
            + _style_handle(1)
            + b'     Back to an ordinary body paragraph to close things out.' + HARD)
    base = ((len(body) + 127) // 128) * 128
    data = bytearray(body.ljust(base, b'\x1a')) + lib
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    doc = core.parse_ws(bytes(data))
    _assert_lint_gates('synthetic-quote-geometry', doc)

    h = emit.emit_html(doc, mode='modern')
    r = emit.emit_rtf(doc, mode='modern')
    t = emit.emit_text(doc, mode='modern')
    md = emit.emit_markdown(doc, mode='modern')

    # HTML: quote wrapped in a real <blockquote>; no inch geometry anywhere
    assert '<blockquote>' in h and '</blockquote>' in h
    assert '5.8' not in h and 'in;' not in h and 'in"' not in h
    assert not _html_bad_geometry(h)

    # RTF: quote style gets the flat 720-twip inset; body style gets none
    assert r'\li720\ri720' in r
    assert not _rtf_bad_geometry(r)

    # Text: quote block uniform 4-space indent, distinct from body's
    # 5-space-first-line scheme
    quote_line = next(l for l in t.split('\n') if 'quoted passage' in l)
    assert quote_line.startswith('    ') and not quote_line.startswith('     ')

    # Markdown: '>' prefix on the quote, not on body; no deep indent anywhere
    assert any(l.startswith('> ') for l in md.split('\n'))
    assert not _md_deep_indent_lines(md)


def test_round4_quote_group_merges_across_styles_and_units():
    """Direct regression test for round 4 (2026-08-17): consecutive
    quote-classified paragraphs are ONE quote block, whether the
    "consecutive" comes from multiple typed paragraphs inside a single
    indent-only-convention WordStar Block (OLDTIMES's real shape: 5 units,
    was 5 separate bordered <blockquote>s) OR from two DIFFERENT quote
    STYLE NAMES back to back with nothing between them (NOVEL.WS's real
    shape: 'MS Quote Introductory' immediately followed by 'MS Quote
    Credit', an epigraph and its own attribution line -- grouping by exact
    style name alone missed this and still produced adjacent boxes).
    Also covers the "absolute where it must be relative" first-line-indent
    fix: the two typed quote paragraphs open at deliberately DIFFERENT raw
    columns (6 and 9), same shape as OLDTIMES's real 7-vs-12 inconsistency."""
    quote_rec = _style_record(left=1260, just=0)
    credit_rec = _style_record(left=1260, just=0)
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        ('Double-Indented Quote', True, quote_rec),
        ('MS Quote Credit', True, credit_rec),
    ])
    header = ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
    body = (header
            + _style_handle(2)
            + b'      First quoted paragraph carries real sentence text.' + HARD
            + b'         Second quoted paragraph typed at a different depth.' + HARD
            + HARD
            + _style_handle(3)
            + b'     Attribution credit line follows immediately after.' + HARD
            + HARD
            + _style_handle(1)
            + b'     An ordinary body paragraph comes after the quote group.' + HARD)
    base = ((len(body) + 127) // 128) * 128
    data = bytearray(body.ljust(base, b'\x1a')) + lib
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    doc = core.parse_ws(bytes(data))

    h = emit.emit_html(doc, mode='modern')
    r = emit.emit_rtf(doc, mode='modern')

    # HTML: ONE <blockquote> spans BOTH quote styles, containing all 3
    # quote paragraphs, all sharing the SAME text-indent -- the group's
    # own first paragraph's value, not each one's own raw column count.
    # The trailing body paragraph is NOT inside it.
    assert h.count('<blockquote') == 1, h
    bq = re.search(r'<blockquote>(.*?)</blockquote>', h, re.S).group(1)
    assert bq.count('<p') == 3
    indents = set(re.findall(r'text-indent:(\d+)ch', bq))
    assert len(indents) == 1, indents
    assert not _html_adjacent_blockquotes(h)
    assert not _html_blockquote_indent_variance(h)

    # RTF: every quote paragraph carries direct \li720\ri720 (round 4:
    # not stylesheet-only -- a reader that ignores \stylesheet entirely
    # still renders the inset), and the trailing body paragraph resets
    # both back to 0. No gap gets introduced between the two DIFFERENT
    # quote styles either.
    assert not _rtf_state_issues(r, doc, printed=False)
    assert r.count(r'\li720\ri720') >= 1


def test_round5_style_level_bold_reaches_markdown_and_rtf_runs():
    """Direct regression test for round 5 (2026-08-17): OLDTIMES's real
    'Award Citation' style declares bold+italic
    ({\\s7\\qc\\b\\i\\fs24}), but its own spans only re-toggle italic
    inline -- the bold lives ENTIRELY in the style. HTML rendered it
    correctly by accident (a completely different, paragraph-level CSS-
    class path); RTF and Markdown -- both of which render CHARACTER RUNS
    off `span.styles` -- silently dropped the style-level bold in lockstep,
    which is what pointed at one shared resolution gap rather than two
    unrelated bugs. Reproduces the exact shape: a style with attrs
    bold+italic, a paragraph whose ONE span only carries an inline italic
    toggle, never bold."""
    rec = _style_record(just=(-1) % 256, attrs_on=0b11000000)   # bold + italic, centered
    lib = _style_library([
        ('WordStar Defaults', False, None),
        ('WordStar Defaults', False, None),
        ('Award Citation', True, rec),
    ])
    header = ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
    # \x19 toggles italic on/off around the text -- the style ALONE
    # supplies bold, exactly as OLDTIMES's own spans do.
    body = (header + _style_handle(2)
            + b'\x19Honored for outstanding service to the community.\x19' + HARD)
    base = ((len(body) + 127) // 128) * 128
    data = bytearray(body.ljust(base, b'\x1a')) + lib
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    doc = core.parse_ws(bytes(data))
    assert doc.blocks[0].style_attrs == frozenset({'b', 'i'})

    h = emit.emit_html(doc, mode='modern')
    r = emit.emit_rtf(doc, mode='modern')
    md = emit.emit_markdown(doc, mode='modern')

    assert 'font-weight:bold' in h and 'font-style:italic' in h   # unaffected (CSS path)
    assert not _rtf_missing_run_attrs(r, doc)
    assert r'\b \i ' in r or r'\i \b ' in r
    assert '***Honored' in md


def test_round7_wrap_off_block_never_splits_in_any_modern_format():
    """Direct regression test for round 7 (2026-08-17): a REGRESSION the
    register re-audit found in this whole overhaul -- `.aw off`
    (`Block.wrap = False`) was honored before `assemble_paragraphs`
    existed (Modern simply never reflowed anything back then), but the
    new paragraph-assembly path never learned to check it, so a hand-
    positioned block could get torn apart at its own column headers. The
    classic case: a small table, one row typed flush (its own header)
    then a row typed with a stray 5-space indent -- phase 1's own
    "indent starts a new paragraph" rule (correct for ordinary prose)
    would otherwise split the header from the rows it's paired with.
    Proven against the PRE-fix algorithm (this exact fixture, run through
    the branch's own base commit): units == [1, 2], a real split. Fixed:
    the whole block is ONE preserved unit, every line kept, in all four
    Modern formats -- Register C23, same family as verse (deliberate line
    positions survive)."""
    doc = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
        + b'.aw off' + HARD
        + b'Name          Score' + HARD
        + b'     Alice          95' + HARD
        + b'Bob             87' + HARD)
    assert doc.blocks[0].wrap is False
    margin = doc.meta.get('margin_estimate') or 65
    units = core.assemble_paragraphs(doc.blocks[0], margin)
    assert len(units) == 1 and sum(len(u) for u in units) == 3, \
        [len(u) for u in units]
    assert not _wrap_off_issues(doc)
    assert not _wrap_off_rendering_issues(doc)

    h = emit.emit_html(doc, mode='modern')
    r = emit.emit_rtf(doc, mode='modern')
    md = emit.emit_markdown(doc, mode='modern')
    t = emit.emit_text(doc, mode='modern')
    assert h.count('<p') == 1 and h.count('<br>') == 2
    assert r.count(r'\par') == 1 and r.count(r'\line') == 2
    assert md.count('\n\n') == 0 and md.count('  \n') == 2
    assert t.count('\n\n') == 0 and t.strip().count('\n') == 2


def _iter_private_fixtures():
    root = os.environ.get('CTRLKD_PRIVATE_FIXTURES')
    if not root:
        return
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        try:
            data = open(path, 'rb').read()
            d = core.detect(data)
            if d['variant'] in ('binary',):
                continue
            doc = core.parse_ws(data) if d['variant'] != 'printstream' \
                else core.parse_printstream(data)
        except Exception:
            continue
        yield name, doc


def test_lint_gates_over_private_corpus():
    root = os.environ.get('CTRLKD_PRIVATE_FIXTURES')
    if not root:
        return                          # private fixtures opt in via env var
    fixtures = list(_iter_private_fixtures())
    if not fixtures:
        return
    for name, doc in fixtures:
        _assert_lint_gates(name, doc)


def test_lint_par_line_ratio_advisory_report():
    """Gate 5 (advisory, never fails): for a prose-heavy document, \\par
    should not be drastically outnumbered by \\line -- the inverse of the
    pre-overhaul OLDTIMES numbers (39 \\par vs 182 \\line). Reported, not
    asserted, per the poem-ambiguity caveat (section 1b)."""
    root = os.environ.get('CTRLKD_PRIVATE_FIXTURES')
    if not root:
        return
    for name, doc in _iter_private_fixtures():
        units = sum(len(core.assemble_paragraphs(b, doc.meta.get('margin_estimate') or 65))
                    for b in doc.blocks if b.kind == 'para')
        if units <= 20:
            continue
        r = emit.emit_rtf(doc, mode='modern')
        pars, lines = r.count(r'\par'), r.count(r'\line')
        print(f'{name}: {pars} \\par / {lines} \\line ({units} paragraph units)')
