"""M27/E8 (Jon, 2026-09-17): Modern puts the SAME gap after a list bullet
that Printed and the app's Native view do.

THE DEFECT. A bullet row's marker and the single space after it each occupy
one monospace CELL in Printed and in Native, so the item's first word starts
two cells past the marker's own left edge. Modern already drew the marker
pinned to that same cell -- `■` is vector art, not a glyph (`_GRAPHIC_CELL_
RECTS`) -- but then measured the SPACE after it in the READING face, where a
Times-14 space is 3.5pt against the cell's 7.2. Measured off the rendered PDF
for `sawyer/-README.WS`: the first word landed 4.70pt past the square's ink
where Native puts it 8.40pt past. The bullet and its text read as one crowded
word.

THE FIX. Give that one space the cell's own width, in both the Modern PDF and
Modern RTF's hanging indent. The marker keeps its pinned cell; every other
space keeps the reading face.

WHY THE CELL AND NOT THE BODY SIZE. `col_pt` is the document's own `.cw`-
derived fixed pitch (7.2pt at the default `.cw 12`) -- the same cell Printed
lays its whole page on and the same one the marker is already pinned to. The
Modern BODY size would have given 14 x 0.6 = 8.4pt of gap and put the word
9.66pt past the ink, past what Native shows. The measured target was the cell.

SCOPED TO BULLETS, not to every `■`: the gate is the structure classifier's
own `kind == 'bullet'` plus its recorded marker -- the same detection the
hanging indent already uses -- so a square in running prose or in a cp437 box
figure is untouched.

Synthetic fixtures only.
"""
import pytest

from ctrlkd import core, emit, pdf

HARD = b'\r\n'
SQUARE = '■'
CELL_PT = 7.2                 # the default `.cw 12` fixed pitch, 12 * 0.6


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


WS5_SEED = ws7_block(0x0B, b'\x00' * 4)


def _bullet_list(*items):
    """Two or more `■ text` rows: `classify_rows` only calls a glyph a marker
    when it repeats, which is what makes the rows a LIST rather than one line
    that happens to start with a square."""
    body = b''.join(SQUARE.encode('cp437') + b' ' + t + HARD for t in items)
    return WS5_SEED + body


def _toks_for(data):
    """The first bullet row's Modern tokens, after the flow has applied the
    structure ladder -- i.e. what actually gets measured and drawn."""
    doc = core.parse(data)
    flow = pdf._modern_flow(doc, keep=emit.DEFAULT_NOTE_KINDS,
                            text_width_pt=pdf.PAGE_W - 2 * pdf.MARGIN)
    for item in flow:
        if item[0] == 'para' and any(t[0] == SQUARE for t in item[1]):
            return item[1]
    raise AssertionError('no bullet row in the flow')


def test_the_space_after_a_bullet_is_one_fixed_pitch_cell():
    """The whole fix, at the one place it happens: the marker keeps its pinned
    cell and the space after it becomes the same width."""
    toks = _toks_for(_bullet_list(b'Alpha item text here.', b'Beta item text here.'))
    assert toks[0][0] == SQUARE
    assert toks[1][0] == ' '
    assert toks[0][5] == pytest.approx(CELL_PT), toks[0]
    assert toks[1][5] == pytest.approx(CELL_PT), toks[1]


def test_the_first_word_starts_two_cells_past_the_marker():
    """What Jon actually looked at: Printed and Native start the text two
    cells in, and Modern now agrees."""
    toks = _toks_for(_bullet_list(b'Alpha item text here.', b'Beta item text here.'))
    advance = toks[0][5] + toks[1][5]
    assert advance == pytest.approx(2 * CELL_PT), advance


def test_the_hang_follows_the_widened_gap():
    """A wrapped continuation lines up under the item's first word, so the
    hang has to be measured AFTER the gap is widened -- measured before, every
    continuation would sit 3.7pt to the left of the text it belongs to."""
    data = _bullet_list(b'Alpha ' + b'word ' * 40, b'Beta item text here.')
    doc = core.parse(data)
    flow = pdf._modern_flow(doc, keep=emit.DEFAULT_NOTE_KINDS,
                            text_width_pt=pdf.PAGE_W - 2 * pdf.MARGIN)
    row = next(i for i in flow if i[0] == 'para' and any(t[0] == SQUARE for t in i[1]))
    assert row[10] == pytest.approx(2 * CELL_PT), row[10]        # hang_pt


def test_every_other_space_keeps_the_reading_face():
    """Only the ONE space after the marker moves. A Times-14 space is 3.5pt
    and stays 3.5pt everywhere else in the row."""
    toks = _toks_for(_bullet_list(b'Alpha beta gamma.', b'Delta epsilon zeta.'))
    later = [t for t in toks[2:] if t[0] == ' ']
    assert later, toks
    assert all(abs(t[5] - CELL_PT) > 0.01 for t in later), later
    assert all(abs(t[5] - 3.5) < 0.01 for t in later), later


def test_a_square_in_running_prose_is_untouched():
    """SCOPE. A `■` that is not a list marker -- no repeating column, so
    `classify_rows` never calls it one -- keeps the reading face's own space
    after it."""
    data = (WS5_SEED + b'A line about the '
            + SQUARE.encode('cp437') + b' symbol in ordinary prose.' + HARD)
    doc = core.parse(data)
    flow = pdf._modern_flow(doc, keep=emit.DEFAULT_NOTE_KINDS,
                            text_width_pt=pdf.PAGE_W - 2 * pdf.MARGIN)
    rows = [i for i in flow if i[0] == 'para' and any(t[0] == SQUARE for t in i[1])]
    assert rows, flow
    for row in rows:
        i = next(j for j, t in enumerate(row[1]) if t[0] == SQUARE)
        after = row[1][i + 1]
        assert after[0] == ' ' and abs(after[5] - CELL_PT) > 0.01, after


def test_the_rtf_bullet_hang_is_the_same_two_cells():
    """Modern RTF expresses the same measurement as a hanging indent, and it
    used to compute a THIRD number (the two characters in Times, 9.72pt) that
    matched neither Printed nor the Modern PDF."""
    doc = core.parse(_bullet_list(b'Alpha item.', b'Beta item.'))
    structure = {'kind': 'bullet', 'level': 1, 'marker': SQUARE}
    li, fi = emit._rtf_structure_indent_hang(structure, doc, SQUARE + ' ')
    assert li == int(round(2 * CELL_PT * 20)), (li, fi)   # 288 twips
    assert fi == -li


def test_a_def_row_hang_is_unchanged():
    """A def row has a real proportional LABEL in front of it, not a pinned
    cell, so its hang stays the fixed points figure it always was."""
    doc = core.parse(WS5_SEED + b'Label  body text.' + HARD)
    li, fi = emit._rtf_structure_indent_hang({'kind': 'def', 'level': 1}, doc, '')
    assert li == int(round(pdf.MODERN_DEF_HANG_PT * 20)), (li, fi)
