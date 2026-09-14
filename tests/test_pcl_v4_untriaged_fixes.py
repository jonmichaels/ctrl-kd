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

import pytest

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


# ---------------------------------------------------------------- mechanism D
def test_column_width_is_the_rm_itself_not_rm_minus_po():
    """`.co` newspaper columns: `.rm` IS the column's own width, measured
    from the `.po` origin -- nothing is subtracted.

    MEASURED against real WS7 (ws7-prints/v4, PRISTINE.EXE) on
    `sawyer/REF/WINGDING.CHT` (`.po .3"`, `.rm .88"`, `.co5, .75"`):
    column origins 21.6 / 138.9 / 256.3 / 373.6 / 491.0 pt, i.e. a pitch of
    63.36 + 54 = 117.36pt. Subtracting `.po` gave a pitch of 95.76 and put
    every column after the first 21.6pt per column too far left, printing
    them on top of column 1 (`sawyer/REVIEW.DOC` page 1 was unreadable).
    `sawyer/REF/SYMBOL.CHT`, the document planning #227's research checked
    against, has `.po .0"` -- both formulas agree there, which is why the
    subtraction survived."""
    from ctrlkd import pdf as pdfmod
    body = HARD.join([b'word%d' % n for n in range(1, 60)])
    src = b'.po .3"' + HARD + b'.rm .88"' + HARD + b'.co5,  .75"' + HARD + body
    doc = core.parse_ws(src)
    pages = pdfmod._doc_to_pagelines(doc, True)
    lefts = sorted({round(ln.left, 2) for pg in pages for ln in pg
                    if getattr(ln, 'left', None) is not None})
    assert len(lefts) >= 2, lefts
    # 21.6 + i * (63.36 + 54) -- the pitch WS7 measures, per column.
    expected = [round(21.6 + i * 117.36, 2) for i in range(len(lefts))]
    assert lefts == pytest.approx(expected, abs=0.05), lefts


def test_column_width_unchanged_when_po_is_zero():
    """`sawyer/REF/SYMBOL.CHT`'s shape -- the one the old formula agreed
    with. Guards the fix against 'well, it moved everything'."""
    from ctrlkd import pdf as pdfmod
    body = HARD.join([b'word%d' % n for n in range(1, 60)])
    src = b'.po .0"' + HARD + b'.rm .78"' + HARD + b'.co5,  .4i' + HARD + body
    doc = core.parse_ws(src)
    pages = pdfmod._doc_to_pagelines(doc, True)
    lefts = sorted({round(ln.left, 2) for pg in pages for ln in pg
                    if getattr(ln, 'left', None) is not None})
    assert len(lefts) >= 2, lefts
    expected = [round(0.0 + i * (56.16 + 28.8), 2) for i in range(len(lefts))]
    assert lefts == pytest.approx(expected, abs=0.05), lefts


# --------------------------------------------- mechanism D (long tail, 09-12)
def _centre_tab(abs_hmi, run_hmi=None):
    """A WS5+ type-9 TAB block -- WordStar's own encoding of a centred
    line's leading padding. content[0:2] is the run's width, content[2:4]
    the ABSOLUTE stop in HMIs, content[4] the fill character."""
    import struct
    run = abs_hmi if run_hmi is None else run_hmi
    return ws7_block(0x09, struct.pack('<HH', run, abs_hmi) + b'\x20\x11')


def _centred_line_x(text, abs_hmi):
    from ctrlkd import pdf as pdfmod
    src = (b'.oc on' + HARD + _centre_tab(abs_hmi) + text + HARD)
    doc = core.parse_ws(src)
    pages = pdfmod._doc_to_pagelines(doc, True)
    line = next(ln for pg in pages for ln in pg
                if any(seg[0].strip() for seg in ln))
    tag = next(t for t in line[0][1] if t.startswith('tabhmi'))
    return int(tag[6:]) / 180.0


def test_centred_line_ignores_its_own_trailing_blanks():
    """A `.oc on` line is re-centred at PRINT time on its ink alone.

    MEASURED against real WS7 (ws7-prints/v4, PRISTINE.EXE) on
    `sawyer/PLAYBILL.DOC`, whose 12 centred lines each carry their own
    type-9 centring tab. The three lines whose stored text ends in blanks
    are exactly the three WS7 prints somewhere other than the stored tab:
    `A gala opening night with the ` at column 18 (file: 17.5),
    `City ... special season ` at 4.5 (file: 4), `for Theatre in the
    Park.  ` at 20.5 (file: 19.5). The editor counted the trailing blanks
    when it centred; the printer does not. All 12 land on
    `(65 - ink) / 2`."""
    # 29 characters of ink, one trailing blank: (65 - 29) / 2 = 18.0
    assert _centred_line_x(b'A gala opening night with the ', 3150) == 18.0
    # 24 characters of ink, two trailing blanks: (65 - 24) / 2 = 20.5
    assert _centred_line_x(b'for Theatre in the Park.  ', 3510) == 20.5


def test_centred_line_with_no_trailing_blanks_keeps_its_stored_tab():
    """The other nine PLAYBILL lines: the editor's own arithmetic already
    agrees with the printer's, and nothing moves."""
    # 24 characters of ink, no trailing blank -- the file's 3690 (20.5) is
    # already `(65 - 24) / 2`.
    assert _centred_line_x(b'TENTH ANNIVERSARY SEASON', 3690) == 20.5
    # 19 characters: (65 - 19) / 2 = 23.0, the file's own 4140.
    assert _centred_line_x(b'THEATRE IN THE PARK', 4140) == 23.0


def test_oni_index_entry_prints_nothing_but_keeps_its_row():
    """A ^ONI index ENTRY (a type-0x0E symmetrical block) belongs to the
    index file, not to the page.

    MEASURED against real WS7 (ws7-prints/v4, PRISTINE.EXE) on
    `sawyer/REF/-INDEX.HOW`, whose own prose introduces two of them with
    "^ONI command -- which creates a symmetrical sequence such as
    these:". WS7 spends both rows (its "as these:" line sits at 348.0pt
    and the next printed line, "Using .ix", at 408.0pt -- five 12pt rows
    apart, exactly the blank/entry/entry/blank the file stores) and puts
    NO INK on either. ctrl-kd printed both phrases.

    Printed only: the phrase stays in the IR, tagged `ixentry`, so every
    text/Markdown/HTML/RTF consumer keeps it."""
    from ctrlkd import pdf as pdfmod
    src = (b'before' + HARD + ws7_block(0x0E, b'Sawyer\\, Robert J.')
           + HARD + b'after' + HARD)
    doc = core.parse_ws(src)
    tagged = [s for b in doc.blocks for l in b.lines for s in l.spans
              if 'ixentry' in s.styles]
    assert [s.text for s in tagged] == ['Sawyer\\, Robert J.']
    printed = pdfmod._doc_to_pagelines(doc, True)
    drawn = [seg[0] for pg in printed for ln in pg for seg in ln]
    assert 'Sawyer\\, Robert J.' not in drawn, drawn
    assert 'before' in drawn and 'after' in drawn
    # the entry's own row is still spent: three lines, not two
    rows = [ln for pg in printed for ln in pg]
    assert len(rows) >= 3, rows
    modern = pdfmod._doc_to_pagelines(doc, False)
    kept = [seg[0] for pg in modern for ln in pg for seg in ln]
    assert any('Sawyer' in t for t in kept), kept


def test_column_under_a_prefix_never_overflows_the_text_bottom():
    """A column group shares one top -- in the NOTE-BEARING paginator too.

    `_doc_to_pagelines`'s own main loop already charges a columnar group's
    shared non-columnar PREFIX against every column of the group except
    the first; `_paginate_printed_notes` -- the paginator every document
    with a footnote/endnote/annotation takes instead -- did not, so a
    later column kept a whole page's capacity while starting BELOW the
    page top and ran off the bottom of the sheet.

    MEASURED against real WS7 (ws7-prints/v4, PRISTINE.EXE) on
    `sawyer/PRINT.TST` page 2 -- `.co3, .20"` under a "Paragraph Styles"
    prefix. WS7 opens all three columns at 288.0pt and, with a text
    bottom of 720.0pt (`.mt 1"`/`.mb 1"`/`.pl 11"`) at a 12pt lead, gives
    each 36 rows: column 1 holds 15 and ends on its own `.cb`, column 2
    holds 21 and ends on `.cc 19`, column 3 holds 23. This engine gave
    column 2 the full 54-row page, never reached the `.cc`, and placed 51
    lines from y 286 down to y 884 -- past the text bottom, past the
    sheet (792), through the page number at 756 -- leaving column 3
    empty."""
    from ctrlkd import pdf as pdfmod
    prefix = HARD.join([b'prefix line %d' % n for n in range(1, 16)])
    body = HARD.join([b'body word %d' % n for n in range(1, 140)])
    src = (b'.mt 1"' + HARD + b'.mb 1"' + HARD + prefix + HARD
           + b'.rm 2"' + HARD + b'.co3,  .2"' + HARD + body + HARD
           + ws7_annotation(b'a note', b'[N]') + HARD)
    doc = core.parse_ws(src)
    pages = pdfmod._doc_to_pagelines(doc, True)
    cols_pages = [pg for pg in pages if getattr(pg, 'columns', None)]
    assert cols_pages, [getattr(pg, 'columns', None) for pg in pages]
    lead = pdfmod._printed_lead(doc)
    for pg in cols_pages:
        top = getattr(pg, 'column_top_offset_pt', 0.0) or 0.0
        by_col = {}
        for pl in pg:
            by_col.setdefault(getattr(pl, 'col', 0), []).append(pl)
        budget = pdfmod._printed_budget_pt(
            doc, pdfmod._printed_cap(doc), lead, None, None, None)
        for ci, rows in by_col.items():
            if ci == 0:
                continue          # column 0 pays the prefix line by line
            spent = sum((getattr(r, 'lead', None) or lead) for r in rows)
            assert top + spent <= budget + lead, (ci, top, spent, budget)


def test_pn_reanchors_the_count_even_when_its_number_repeats():
    """A `.pn` restarts the numbering at the page it appears on, always.

    `_pn_checkpoints` used to drop a checkpoint whose VALUE equalled the
    last one recorded -- a guard that compared against the previous
    checkpoint's number instead of against the number this page would
    otherwise have taken, so every restart to an already-used number was
    thrown away.

    MEASURED against real WS7 (ws7-prints/v4, PRISTINE.EXE) on
    `sawyer/REF/CTRL-K.H1`: five pages numbered 1-5, then a mid-document
    `.pn1`, and WS7 numbers the remaining sheets 6, 7, 8, 9 as pages
    1, 2, 3, 4 -- which is also the parity its own `^K` even-page header
    rule reads."""
    src = HARD.join([b'one', b'.pa', b'two', b'.pa', b'three',
                     b'.pn1', b'four', b'.pa', b'five']) + HARD
    doc = core.parse_ws(src)
    cps = pdf._pn_checkpoints(doc)
    assert len(cps) == 2, cps
    assert cps[0] == (0, 1) and cps[1][1] == 1, cps
    assert cps[1][0] > 0, cps
    pages = pdf._doc_to_pagelines(doc, True)
    numbers = pdf._resolve_page_numbers(cps, pages)
    # the `.pn1` sits on the third page, which it re-anchors to 1
    assert numbers == [1, 2, 1, 2], numbers


def test_ctrl_k_suppresses_header_blanks_on_even_pages():
    """`^K` in a `.h#`/`.f#` line kills the blanks after it -- even pages only.

    WordStar's own file-format document, quoted verbatim inside the corpus
    document that tests it (`sawyer/REF/CTRL-K.H1`): "In a header or footer
    line, on even numbered pages all blanks following the ^K are
    suppressed."

    MEASURED against real WS7 (ws7-prints/v4, PRISTINE.EXE) on that
    document: `.h1 ^K<55 blanks>Header / #` prints at x 453.6pt on an odd
    page (left margin 57.6 + 55 columns) and at **64.8pt** on an even one
    -- the left margin plus ONE column, so exactly one column survives the
    run; the same pair of numbers for its `.f1`, and 482.4/64.8 for its
    second, 59-blank `.h1`."""
    text = '\x0b' + ' ' * 55 + 'Header / #'
    assert pdf._ctrl_k_even_page(text, 3) == text
    assert pdf._ctrl_k_even_page(text, 2) == ' Header / #'
    # a blank run NOT introduced by a ^K is untouched on either parity
    plain = 'A' + ' ' * 9 + 'B'
    assert pdf._ctrl_k_even_page(plain, 2) == plain
    # and the rule reaches the resolved header line the printed page draws
    src = (b'.h1 \x0b' + b' ' * 55 + b'Header / #' + HARD
           + b'body' + HARD + b'.pa' + HARD + b'body' + HARD)
    doc = core.parse_ws(src)
    kw = dict(page_h=792.0, lead=12.0, size=12.0, left=57.6, printed=True)
    odd = pdf._resolve_head_foot_lines(doc, 1, **kw)['headers'][0][1]
    even = pdf._resolve_head_foot_lines(doc, 2, **kw)['headers'][0][1]
    # the 0x0B survives an odd page and costs nothing (`emit.hf_runs`
    # strips it with every other control byte, as every view always has)
    assert odd == '\x0b' + ' ' * 55 + 'Header / 1', repr(odd)
    assert even == ' Header / 2', repr(even)


def test_a_note_tabs_its_own_text_where_the_document_says():
    """A note's own TAB positions its text; the hang column yields to it.

    A note's text stream can carry a nested type-9 tab block -- the same
    one a body line uses, second word the absolute tab size in HMIs -- and
    real WS7 starts the note's text in that column. `_parse_note` skipped
    every nested block that was not the internal tag, so the number was
    thrown away, and `_notes_marker_pad_cols`'s computed hang column
    (widest marker + 2) positioned every note instead.

    MEASURED against real WS7 (ws7-prints/v4, PRISTINE.EXE) on
    `sawyer/REF/NOTES.TST`, left margin 57.6pt: its footnotes tab to HMI
    540 and WS7 prints "Footnote One." at 79.2pt (column 3); its endnotes
    tab to HMI 900 and print "Endnote one." at 93.6pt (column 5); its
    annotations tab nothing and print "Annotation One" at 86.4pt (column
    4) -- tag "AC1" plus the marker's own single space. The engine put all
    three at column 5. `-SCREEN.WS` and `DISPLAY.WS`, the documents the
    hang column was measured on, tab BOTH their notes to column 5, so
    they render identically either way."""
    from ctrlkd import pdf as pdfmod
    tab = ws7_block(0x09, (540).to_bytes(2, 'little') * 2 + b' \x01')
    note = (ws7_block(0x03, b'\x01\x00\x09\x80\x33'
                      + ws7_block(0x03, b'\x00\x00\x00\x00\x33')
                      + tab + b'Footnote One.' + HARD))
    doc = core.parse_ws(b'body' + note + b' more' + HARD)
    fns = [n for n in doc.notes if n.kind == 'footnote']
    assert fns and fns[0].text_indents == (3,), [n.text_indents for n in fns]
    def rendered(marker, indents):
        rows = pdfmod._note_wrap(marker, ['Footnote One.'], 65, 0, indents)
        return ''.join(t for t, _ in rows[0])
    assert rendered('1.', (3,)) == '1. Footnote One.'      # column 3
    assert rendered('(1)', (5,)) == '(1)  Footnote One.'   # column 5
    # a tab at or left of where the marker already ends leaves no gap
    assert rendered('(1)', (2,)) == '(1)Footnote One.'
    # and a note that tabs nothing keeps the previous join exactly
    assert rendered('1.', ()) == '1.Footnote One.'


def test_a_footer_governs_the_page_it_is_read_on():
    """A `.fo` reaches the page it appears on; a `.he` does not.

    A header is emitted at the TOP of a page, so a `.he`/`.h#` read after
    that page's first line cannot reach it. A footer is emitted at the
    BOTTOM, so a `.fo`/`.f#` read anywhere before the page ends still
    governs it. Both took the header's rule, which put every footer change
    one page late.

    MEASURED against real WS7 (ws7-prints/v4, PRISTINE.EXE) on
    `sawyer/MACROS/HOLYMAC/8MAC`, which sets `.fo<31 blanks>#` after a
    blank line -- so page 1 has already begun -- and clears it with a bare
    `.fo` immediately AFTER its first page break. WS7 prints "286" at
    280.8pt (column 31, exactly where the `#` sits) at the foot of page 1
    and NO footer on pages 2-10; from the same commands it prints NO
    header on page 1 and "HOLY MACRO!  #" on 2-10. This engine printed the
    automatic page number on page 1 and the footer on page 2."""
    from ctrlkd import pdf as pdfmod
    src = HARD.join([b'', b'.he HEAD #', b'.fo FOOT #', b'one',
                     b'.pa', b'.fo', b'two']) + HARD
    doc = core.parse_ws(src)
    pages = pdfmod._doc_to_pagelines(doc, True)
    assert len(pages) >= 2, len(pages)
    assert pages[0].footers.get(1) == 'FOOT #', pages[0].footers
    assert not pages[0].headers, pages[0].headers      # `.he` is one line late
    assert not pages[1].footers, pages[1].footers      # the bare `.fo` cleared it
    assert pages[1].headers.get(1) == 'HEAD #', pages[1].headers


# ---------------------------------------------------------------------------
# Planning #270 item 39 / triage Q6 -- two of the five HOLYMAC residuals.
#
#   D. `.pm`'s first-line indent reaches the PRINTED page only when print-time
#      paragraph realignment is on. MicroPro's own file-format reference is the
#      definition (`WSFORMAT.TXT`, the `.PF` row): "When OFF, paragraphs are not
#      realigned... Paragraphs are aligned using the left, right, and paragraph
#      margins currently in effect." With realignment off -- every archive file
#      but seven -- WordStar prints the stored physical lines verbatim and the
#      margins are edit-time state that already spent itself at typing time.
#      MEASURED: `sawyer/MACROS/HOLYMAC/-HOLYMAC.WS` (v4 PRISTINE capture, no
#      `.pf` anywhere, `.pm4` in force) opens its pages 223, 258 and 293 at the
#      plain left edge where this engine indented 3 columns, +21.60pt, 16
#      divergences.
#
#   E. A run that is all whitespace draws no text-showing op. Real WS7 never
#      sends blanks to a printer -- PCL moves the cursor instead -- so a blank
#      text op is ink no capture can contain. MEASURED: `-HOLYMAC.WS` pages 12
#      and 13 carry a WordStar screen diagram whose text line ends in a bare CR
#      (a real `^PM` overprint) and is overprinted by a line of 78 blanks
#      carrying the box's right-hand rule; the blanks drawn ACROSS the text cut
#      every word underneath into single letters for any reader that forms
#      words from characters, 32 divergences reported as "WS7 word missing" for
#      text that was on the page the whole time.


def test_pf_is_read_as_three_values_not_two():
    """`.pf` is ON / OFF / DIS, and `dis` is not `off` -- `_onoff` would read
    `dis` as neither and leave the state standing, which is why `.pf` has its
    own reader. Junk leaves the state alone, same as every other stateful dot
    command in `_parse_format_dot`."""
    for arg, want in ((b'on', 'on'), (b'ON', 'on'), (b'off', 'off'),
                      (b'OFF', 'off'), (b'dis', 'dis'), (b' Dis ', 'dis')):
        doc = core.parse_ws(ws7_block(0x00) + b'.pf ' + arg + HARD
                            + b'Some ordinary prose for the detector.' + HARD)
        assert doc.blocks[0].print_reformat == want, (arg, doc.blocks[0].print_reformat)
    doc = core.parse_ws(ws7_block(0x00) + b'.pf maybe' + HARD
                        + b'Some ordinary prose for the detector.' + HARD)
    assert doc.blocks[0].print_reformat is None
    doc = core.parse_ws(ws7_block(0x00)
                        + b'Some ordinary prose for the detector.' + HARD)
    assert doc.blocks[0].print_reformat is None       # never said is not "off"


def test_pf_change_closes_the_block_it_lands_in():
    """`.pf` is stateful and mid-paragraph it means the lines after it are
    realigned and the ones before are not -- one Block cannot hold both, the
    same reason `.lm` is in `_block_stamp`."""
    doc = core.parse_ws(ws7_block(0x00) + b'.pf off' + HARD + b'Before it.' + HARD
                        + b'.pf on' + HARD + b'After it.' + HARD)
    reformats = [b.print_reformat for b in doc.blocks if b.kind == 'para']
    assert reformats == ['off', 'on'], reformats


def test_pm_does_not_indent_a_printed_line_without_pf_on():
    """The HOLYMAC shape: `.pm` in force, `.pf` never set. The first line of
    the paragraph starts at the plain left edge, exactly where WS7 prints it,
    and the `.pm` column contributes nothing."""
    src = (ws7_block(0x00) + b'.pm 4' + HARD
           + b'First line of the paragraph.' + HARD
           + b'Second line of the paragraph.' + HARD)
    doc = core.parse_ws(src)
    assert doc.blocks[0].para_margin == 3.0          # parsed, just not printed
    assert pdf._printed_pm_fi_pt(doc.blocks[0]) is None
    out = pdf.emit_pdf(doc, mode='printed', page_numbers='off')
    first = re.search(rb'([\d.]+) [\d.]+ Td \(First line', out)
    second = re.search(rb'([\d.]+) [\d.]+ Td \(Second line', out)
    assert first and second
    assert first.group(1) == second.group(1), (first.group(1), second.group(1))


def test_pm_still_indents_a_printed_line_under_pf_on():
    """The other half of the same gate: the seven `.pf`-bearing archive files
    keep the behaviour they had. `.pm 4` -> 3 offset columns -> 21.6pt."""
    src = (ws7_block(0x00) + b'.pf on' + HARD + b'.pm 4' + HARD
           + b'First line of the paragraph.' + HARD
           + b'Second line of the paragraph.' + HARD)
    doc = core.parse_ws(src)
    assert pdf._printed_pm_fi_pt(doc.blocks[0]) == 21.6
    out = pdf.emit_pdf(doc, mode='printed', page_numbers='off')
    first = re.search(rb'([\d.]+) [\d.]+ Td \(First line', out)
    second = re.search(rb'([\d.]+) [\d.]+ Td \(Second line', out)
    assert round(float(first.group(1)) - float(second.group(1)), 6) == 21.6


def test_pm_indent_under_pf_dis_is_not_applied():
    """`dis` realigns only when merge data is substituted, which never happens
    on a document nobody merge-prints -- it is not `on`."""
    src = (ws7_block(0x00) + b'.pf dis' + HARD + b'.pm 4' + HARD
           + b'First line of the paragraph.' + HARD)
    doc = core.parse_ws(src)
    assert pdf._printed_pm_fi_pt(doc.blocks[0]) is None


def test_a_whitespace_only_run_draws_no_text_op():
    """A bold word, a plain space, an underlined word: the space between them
    is its own span (the style changed on either side of it) and carries no
    ink. It gets no `Tj`, and the words on either side keep the positions they
    always had -- the advance is unchanged, only the blank op is gone."""
    src = (ws7_block(0x00) + b'\x02bold\x02 \x13under\x13 and more prose here.' + HARD
           + b'A second line so the detector reads a document.' + HARD)
    out = pdf.emit_pdf(core.parse_ws(src), mode='printed', page_numbers='off')
    shown = re.findall(rb'Td \(([^)]*)\) Tj', out)
    assert not any(s and not s.strip() for s in shown), shown
    assert b'bold' in shown and b'under' in shown


def test_continuous_underline_across_inner_blanks_is_untouched():
    """What makes the skip safe. `_rules` has ALWAYS returned nothing for a
    whitespace-only run (`if not text.strip(): return ops`), so the invisible
    `Tj` was the only thing such a run still put in the stream. Underlining
    the blanks BETWEEN words -- the whole point of `.ul on` -- is drawn by the
    run that carries the LETTERS, across its own full width, and is unchanged:
    one rule, 31 characters wide, over "under lined across the blanks"."""
    src = (ws7_block(0x00) + b'.ul on' + HARD
           + b'\x13under lined across the blanks\x13' + HARD
           + b'A second line so the detector reads a document.' + HARD)
    out = pdf.emit_pdf(core.parse_ws(src), mode='printed', page_numbers='off')
    rules = re.findall(rb'0\.6 w ([\d.]+) ([\d.]+) m ([\d.]+) [\d.]+ l S', out)
    assert len(rules) == 1, rules
    x0, x1 = float(rules[0][0]), float(rules[0][2])
    assert round(x1 - x0, 6) == round(29 * 7.2, 6), (x0, x1)


def test_a_blank_overprint_line_leaves_the_words_beneath_it_whole():
    """The measured HOLYMAC shape, reduced: a text line ending in a BARE CR
    (`^PM`, WordStar's overprint) followed by a line of blanks that carries
    one trailing mark. Read back as characters and re-segmented, the words on
    the first line must survive as words -- before this, every blank drawn
    across them split them letter by letter."""
    src = (ws7_block(0x00)
           + b'Display Center ChkRest ChkWord\x0d'
           + b'                                  .' + HARD
           + b'A second line so the detector reads a document.' + HARD)
    out = pdf.emit_pdf(core.parse_ws(src), mode='printed', page_numbers='off')
    shown = re.findall(rb'Td \(([^)]*)\) Tj', out)
    assert b'Display Center ChkRest ChkWord' in shown, shown
    assert not any(s and not s.strip() for s in shown), shown
