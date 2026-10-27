"""Where Printed puts a footnote, and what it calls it (WS7 teardown: report
11.11, 14.8, 14.15, 15.1, 15.10; runs fnmb0, fn2, fnfit52, fnr0-fnr99, fnbig,
fnhuge, fnlong120, fnnum5, w16-fnlow2, w16-fnup2). Synthetic documents only;
the teardown fixtures themselves run in test_teardown_fixtures.py.
"""
from ctrlkd import core, emit, pdf
from ctrlkd.pdf import CONTINUATION_TEXT, FOOTNOTE_SEPARATOR

HARD = b'\x0d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def ws7_note(text, number=0):
    content = ((1).to_bytes(2, 'little') + number.to_bytes(2, 'little') +
               bytes([0x30]) + text)
    return ws7_block(0x03, content)


def _doc(n_lines, ref_line, note, number=0, head=b''):
    """`n_lines` body lines, the note's reference at the end of `ref_line`."""
    body = b''
    for i in range(1, n_lines + 1):
        body += b'line %02d' % i
        if i == ref_line:
            body += ws7_note(note, number)
        body += HARD
    return core.parse_ws(head + ws7_block(0x00) + body)


def _pages(doc):
    return [[''.join(t for t, _ in line).rstrip() for line in pg]
            for pg in pdf._doc_to_pagelines(doc, True)]


def _words(n):
    return ' '.join('w%03d' % i for i in range(n)).encode()


def _body(page):
    """The body lines, without the reference mark a line may end in."""
    return [t[:7] for t in page if t.startswith('line ')]


def _note_lines(page):
    return [t for t in page if t.startswith('w') or t[:2] == '1.']


def test_a_note_reference_on_a_trailing_blank_last_line_is_kept():
    # run fnmb0: the note sits on the unterminated empty line after line 05
    data = (ws7_block(0x00) + b''.join(b'line %02d' % i + HARD for i in range(1, 6)) +
            ws7_note(b'note text'))
    doc = core.parse_ws(data)
    assert any('fnref' in s.styles for b in doc.blocks for ln in b.lines
               for s in ln.spans)
    (page,) = _pages(doc)
    assert FOOTNOTE_SEPARATOR in page and '1.note text' in page


def test_a_note_that_does_not_fit_moves_with_its_reference_line():
    # run fnfit52: a one-line note at line 52 of 60; 51 is the last line
    # that keeps its note on the page (the area is three lines and the
    # bottom margin line stays free)
    pages = _pages(_doc(60, 52, b'note'))
    assert len(_body(pages[0])) == 51 and _body(pages[0])[-1] == 'line 51'
    assert _body(pages[1])[0] == 'line 52'
    assert '1.note' in pages[1] and '1.note' not in pages[0]
    pages = _pages(_doc(60, 51, b'note'))
    assert _body(pages[0])[-1] == 'line 51' and '1.note' in pages[0]


def test_a_long_note_moves_whole_below_fnrun_and_runs_at_or_above_it():
    # runs fnlong2 / fnr0-fnr99: line 50 of 60 leaves 6 note lines of room;
    # the factory fnrun is 8, so the line and the whole note go to page 2
    note = _words(100)
    pages = _pages(_doc(60, 50, note))
    assert _body(pages[0])[-1] == 'line 49'
    assert _body(pages[1])[0] == 'line 50'
    # fnrun 6 (a patched WS.EXE): the note runs, one line under the reference
    doc = _doc(60, 50, note)
    doc.meta['fnrun'] = 6
    pages = _pages(doc)
    assert _body(pages[0])[-1] == 'line 50'
    assert len(_note_lines(pages[0])) == 1
    # fnrun 7: moves again
    doc = _doc(60, 50, note)
    doc.meta['fnrun'] = 7
    assert _body(_pages(doc)[0])[-1] == 'line 49'


def test_a_running_note_fills_the_page_and_continues_under_the_separator():
    # run fnbig: a 20-line note at line 40: 11 lines under the reference,
    # no body line after it on the page, and the rest on page 2 with the
    # Continued line directly under the separator and a blank after it
    note = _words(250)          # about 20 lines
    pages = _pages(_doc(60, 40, note))
    assert _body(pages[0])[-1] == 'line 40'
    nxt = pages[1]
    sep = nxt.index(FOOTNOTE_SEPARATOR)
    assert nxt[sep + 1] == CONTINUATION_TEXT and nxt[sep + 2] == ''
    assert _body(nxt)[0] == 'line 41'


def test_a_note_longer_than_a_page_makes_note_only_pages():
    # run fnlong120: no floor of body lines against a carried-over note
    pages = _pages(_doc(60, 50, _words(1500)))
    note_only = [pg for pg in pages if not _body(pg)]
    assert note_only and all(pg[0] == FOOTNOTE_SEPARATOR for pg in note_only)
    text = ' '.join(t for pg in pages for t in pg
                    if t.startswith('w') or t.startswith('1.w'))
    assert ' '.join(_words(1500).decode().split()) == text.replace('1.', '', 1)


def _ys(pg):
    """(baseline y in points, text) for each line of a page: the page top plus
    every line's own lead, the document default 12 where it has none."""
    y, out = 36.0, []
    for ln in pg:
        y += ln.lead if ln.lead is not None else 12.0
        out.append((round(y, 1), ''.join(t for t, _ in ln).rstrip()))
    return out


def _chain_pages(words):
    return pdf._doc_to_pagelines(_doc(60, 50, _words(words), 0), True)


def _at(rows, prefix):
    return [y for y, t in rows if t.startswith(prefix)]


def test_a_note_only_page_sits_1_6_pt_below_the_grid_and_prints_its_number():
    # runs fnlong120, fnch175, fnch250: separator 616, Continued 736, first
    # note 976, the 51st note line at BB + 16 decipoints
    pg = _chain_pages(1464)[2]
    rows = _ys(pg)
    assert rows[0] == (61.6, FOOTNOTE_SEPARATOR)
    assert rows[1] == (73.6, CONTINUATION_TEXT)
    assert rows[3][0] == 97.6 and rows[-1][0] == 697.6
    assert len(rows) == 54
    # nothing on it to look the automatic number up from: it takes the state
    # of the last block read (run fnlong120 prints "3" on this page)
    assert pg.explicit_break_bi is not None


def test_the_page_where_a_chain_of_note_only_pages_ends_sits_at_bb_less_r_lh_2h():
    # run fnlong120 p4: R = 19 note lines left; P = BB - R*LH - 2H puts the
    # separator at 396 pt, one blank row more under Continued, the first note
    # line at P + 720 (444 pt) and the last three rows above BB
    pg = _chain_pages(1464)[3]
    rows = _ys(pg)
    assert _at(rows, 'line ')[:1] == [48.0] and _at(rows, 'line ')[-1] == 156.0
    assert _at(rows, '-----') == [396.0]
    assert _at(rows, '...Continued') == [408.0]
    notes = [y for y, t in rows if t.startswith('w')]
    assert len(notes) == 19 and notes[0] == 444.0 and notes[-1] == 660.0


def test_a_remainder_too_long_for_the_text_prints_under_it_and_runs_on():
    # run fnch250: 250 note lines, note-only pages 3-5; page 6 has 47 left,
    # which with 2H does not fit under the resumed text: lines 51-55, the
    # separator three rows under the last of them, 45 note lines to BB, the
    # other two on page 7, again under the text, with the extra blank row
    pages = _chain_pages(2898)
    assert len(pages) == 7
    rows = _ys(pages[5])
    assert _at(rows, 'line ')[-1] == 96.0 and len(_at(rows, 'line ')) == 5
    assert _at(rows, '-----') == [132.0] and _at(rows, '...Continued') == [144.0]
    notes = [y for y, t in rows if t.startswith('w')]
    assert notes[0] == 168.0 and notes[-1] == 696.0 and len(notes) == 45
    rows = _ys(pages[6])
    assert [t for _, t in rows if t.startswith('line ')][-1] == 'line 60'
    assert _at(rows, 'line ')[-1] == 96.0 and len(_at(rows, 'line ')) == 5
    assert _at(rows, '-----') == [132.0] and _at(rows, '...Continued') == [144.0]
    notes = [y for y, t in rows if t.startswith('w')]
    assert notes == [180.0, 192.0]


def test_a_bare_f_hash_start_is_not_added_to_the_stored_numbers():
    # run fnnum5: `.f# 5` stored 4, 5 / 0, 1 and printed 5., 6. / 1., 2.
    data = (b'.f# 5' + HARD + ws7_block(0x00) +
            b'one' + ws7_note(b'n', 4) + HARD +
            b'two' + ws7_note(b'n', 5) + HARD + b'.pa' + HARD +
            b'three' + ws7_note(b'n', 0) + HARD)
    pages = _pages(core.parse_ws(data))
    assert [t for t in pages[0] if t.endswith('.n')] == ['5.n', '6.n']
    assert [t for t in pages[1] if t.endswith('.n')] == ['1.n']


def _f_hash(arg):
    return (b'.f# ' + arg + HARD + ws7_block(0x00) +
            b'one' + ws7_note(b'n', 0) + HARD + b'two' + ws7_note(b'n', 1) + HARD)


def test_f_hash_letters_label_the_printed_notes():
    # runs w16-fnlow2 / w16-fnup2: the .f# format at print time, not the
    # note's stored format nibble
    low = core.parse_ws(_f_hash(b'a'))
    assert low.meta['footnote_number_format'] == 'lower'
    page = _pages(low)[0]
    assert [t for t in page if t.endswith('.n')] == ['a.n', 'b.n']
    up = _pages(core.parse_ws(_f_hash(b'A')))[0]
    assert [t for t in up if t.endswith('.n')] == ['A.n', 'B.n']
    assert 'a' in ''.join(emit.emit_text(low, mode='printed').split())


def test_digits_and_modes_in_f_hash_keep_arabic_labels():
    for arg in (b'3', b'd 1', b'page', b'p'):
        doc = core.parse_ws(_f_hash(arg))
        assert 'footnote_number_format' not in doc.meta, arg
        assert [t for t in _pages(doc)[0] if t.endswith('.n')][0].startswith(
            ('1.', '3.')), arg


def test_f_hash_letters_reach_the_other_printed_exports_and_not_modern():
    doc = core.parse_ws(_f_hash(b'a'))
    rtf = emit.emit_rtf(doc, mode='printed')
    assert r'\ftnnalc' in rtf
    assert r'\ftnnalc' not in emit.emit_rtf(doc, mode='modern')
    e_doc = core.parse_ws(b'.e# A' + HARD + ws7_block(0x00) + b'x' +
                          ws7_block(0x04, (1).to_bytes(2, 'little') + bytes(2) +
                                    bytes([0x30]) + b'end') + HARD)
    assert r'\aftnnauc' in emit.emit_rtf(e_doc, mode='printed')
    modern = emit.emit_text(doc, mode='modern')
    assert '[1] n' in modern and '[a]' not in modern
