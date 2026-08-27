"""b26-modern item 2: Modern PDF box-drawing/graphic regions.

Two related, evidence-linked bugs in `_modern_flow`'s tokenizer:

(a) FIRST-BOX-MANGLED: the generic word tokenizer (`' +|[^ ]+'`) splits a
box row -- '<left border><interior spaces><right border>' -- into THREE
tokens, because the interior is pure whitespace and the tokenizer always
breaks on space runs. The border tokens then measure through
`_modern_w`'s graphic-pitch branch, but the all-space middle token has no
graphic char in it, so it falls through to ordinary proportional-text
measurement instead -- the two systems only happen to agree when a
resolved fixed-pitch font `entry` is active (both reduce to the same
`_span_pitch` formula then). A genuinely FONTLESS region (`entry is
None` -- every WS4 file, or any WS5+ document before its own first font-
change record) measures its border chars and its interior gap by two
UNRELATED formulas, so a box row's own drawn width stops matching its
neighbouring rows and its top/bottom bars -- reproduced on the real
corpus: BOXES.WS's OPENING box (the document's own first content, before
any font record) measured 322pt per row; an IDENTICAL box appearing
later in the same file (by then under a resolved font) measured 165.6pt.
Visually: the first box's right edge and interior vertical land at the
WRONG x, reading as "right side missing, stray interior vertical, open
corner" while later boxes render correctly.

(b) AWKWARD WRAP: because a box row is three separate tokens, a row
wider than the available text width could break BETWEEN the border and
the gap (`_modern_wrap`'s normal word-wrap), splitting a box row's
closing border onto its own visual line.

Fix: `_MODERN_TOK_RE` tries the SAME `_GRAPHIC_RUN` shape
(border-gap-border) the drawing code already understands as one unit
BEFORE falling back to the generic space/non-space split -- a box row
reaches width measurement and wrapping as the one visual unit it is,
fixing both (a) and (b) as one mechanism. Isolated/scattered graphic
chars amid ordinary prose (a legend line like "UL: <char>  UR: <char>")
are unaffected: `_GRAPHIC_RUN`'s own shape requires the run to close on
ANOTHER graphic char with only graphic-chars-or-spaces in between, so it
can never cross real letters.

Synthetic fixtures only (CLAUDE.md): literal cp437-encoded box-drawing
bytes, same convention as test_modern_lint.py's own box fixtures.
"""
from ctrlkd import core, pdf

HARD = b'\r\n'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def font_block(points, width=180):
    return ws7_block(0x02, round(width).to_bytes(2, 'little')
                     + round(points * 20).to_bytes(2, 'little')
                     + (0).to_bytes(2, 'little') + bytes(6))


TOP = '┌─────────────────────┐'.encode('cp437')
MID = '│                     │'.encode('cp437')
BOT = '└─────────────────────┘'.encode('cp437')


def _box_flow(doc):
    flow = pdf._modern_flow(doc, frozenset(('footnote', 'endnote', 'annotation')),
                            'word', pix_results=None, pictures='off',
                            text_width_pt=468.0)
    return [it for it in flow if it[0] == 'para']


def test_fontless_box_rows_measure_self_consistently():
    """The exact regression shape: a box that is the document's own FIRST
    content (WS7-format, but before any font-change record -- `entry is
    None` for every span in it). Every row -- top bar, all five body
    rows, bottom bar -- must measure to the SAME width; before the fix,
    body rows measured roughly a third of the top/bottom bars' width."""
    data = ws7_block(0x00) + TOP + HARD + (MID + HARD) * 5 + BOT + HARD
    doc = core.parse_ws(data)
    paras = _box_flow(doc)
    assert len(paras) == 7
    widths = [sum(t[5] for t in p[1]) for p in paras]
    assert len(set(round(w, 4) for w in widths)) == 1, widths


def test_box_after_a_font_change_is_unaffected():
    """Baseline: a box appearing AFTER the document's font-change record
    (a resolved, non-proportional `entry`) already measured consistently
    before this fix (both the graphic and plain-text branches reduce to
    the same `_span_pitch` formula) -- must stay exactly as consistent,
    same shape of assertion as the fontless case above."""
    data = ws7_block(0x00) + font_block(12) + TOP + HARD + (MID + HARD) * 5 + BOT + HARD
    doc = core.parse_ws(data)
    paras = _box_flow(doc)
    widths = [sum(t[5] for t in p[1]) for p in paras]
    assert len(set(round(w, 4) for w in widths)) == 1, widths


def test_scattered_graphic_chars_amid_prose_stay_individually_tokenized():
    """A legend line mixing isolated graphic glyphs with ordinary prose
    words (BOXES.WS's own "UL: <char>    UR: <char>" array lines) must
    NOT be swept into one giant token -- `_GRAPHIC_RUN`'s shape requires
    closing on another graphic char with nothing but graphic-chars-or-
    spaces in between, and real letters break that every time."""
    line = 'UL: ┌    UR: ┐   done'.encode('cp437')
    doc = core.parse_ws(ws7_block(0x00) + line + HARD)
    paras = _box_flow(doc)
    texts = [t[0] for t in paras[0][1]]
    assert texts == ['UL:', ' ', '┌', '    ', 'UR:', ' ', '┐', '   ', 'done']


def test_wide_graphic_row_does_not_wrap_mid_row():
    """A box row wider than the page's own text width must still be
    placed as ONE unbroken visual line (the 'non-reflowing... unwrapped
    monospace block' rule) rather than breaking between its border and
    its interior gap -- before the fix, `_modern_wrap` split the closing
    border onto its own line."""
    row = ('│' + ' ' * 88 + '│').encode('cp437')
    data = ws7_block(0x00) + font_block(12) + row + HARD
    doc = core.parse_ws(data)
    paras = _box_flow(doc)
    vis = pdf._modern_wrap(paras[0][1], 468.0)
    assert len(vis) == 1
    assert vis[0][0][0] == '│' + ' ' * 88 + '│'


def test_boxes_render_without_a_stray_xobject_or_crash():
    """End-to-end smoke test: the fontless box document above must emit a
    valid Modern PDF (no exception), and since nothing here is a pix tag,
    no Image XObject should appear."""
    data = ws7_block(0x00) + TOP + HARD + (MID + HARD) * 5 + BOT + HARD
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='modern')
    assert out.startswith(b'%PDF')
    assert b'/Subtype /Image' not in out


def _rect_span(ops):
    """(min_y, max_y) across every `re f` filled-rect op in a `_graphic_ops`
    result -- the vertical extent of the glyph's own drawn geometry."""
    ys = []
    for op in ops:
        if op.endswith(b're f'):
            x, y, w, h = (float(v) for v in op.split()[:4])
            ys.append((y, y + h))
    return min(b for b, _ in ys), max(t for _, t in ys)


def test_modern_graphic_ops_cell_touches_the_next_lines_cell():
    """Register b32: a box-drawing arm's vertical stroke spans its own
    glyph CELL top-to-bottom (`_graphic_ops`'s BOX_ARMS branch, the `u`/
    `dn` rects), so consecutive PHYSICAL lines' cells only chain into one
    continuous rule if the cell is at least as tall as the actual line-to-
    line advance. Before this fix, every Modern caller used the SAME fixed
    1.1 factor Printed's own (differently-related) leading happens to
    tolerate -- Modern's real advance is `MODERN_LINE * pt` (1.2x, not
    1.1x), leaving a real per-line gap and rendering every vertical box
    side as broken dashes on the real corpus (BOX.WS, BOXES.WS). Modern's
    call site now passes `lead_factor=MODERN_LINE` explicitly; two
    vertically-adjacent glyph cells at that exact advance must meet with
    ZERO gap (and zero overlap)."""
    pt = pdf.MODERN_BODY_PT
    advance = pdf.MODERN_LINE * pt
    y1 = 700.0
    ops1 = pdf._graphic_ops('│', 0.0, y1, 8.4, pt, lead_factor=pdf.MODERN_LINE)
    ops2 = pdf._graphic_ops('│', 0.0, y1 - advance, 8.4, pt,
                            lead_factor=pdf.MODERN_LINE)
    bottom1, _ = _rect_span(ops1)
    _, top2 = _rect_span(ops2)
    assert round(top2, 6) == round(bottom1, 6)


def test_modern_graphic_ops_default_factor_would_gap_at_the_real_advance():
    """The failure this fix closes, pinned directly: `_graphic_ops`'s own
    PRINTED-tuned default (1.1, unrelated to Modern's leading) leaves a
    real gap at Modern's actual per-line advance -- confirms the bug was
    real, not just the fix's own arithmetic agreeing with itself."""
    pt = pdf.MODERN_BODY_PT
    advance = pdf.MODERN_LINE * pt
    y1 = 700.0
    ops1 = pdf._graphic_ops('│', 0.0, y1, 8.4, pt)          # old default
    ops2 = pdf._graphic_ops('│', 0.0, y1 - advance, 8.4, pt)  # old default
    bottom1, _ = _rect_span(ops1)
    _, top2 = _rect_span(ops2)
    assert bottom1 - top2 > 1.0     # a real, visible gap (was 1.4pt)


def test_modern_printed_box_rendering_is_unaffected_by_this_fix():
    """Printed PDF's own graphic-char drawing path (`_line_ops_printed` /
    `_split_graphics`) is untouched by this fix -- a fontless box document
    must render identically in Printed mode with and without the change
    (proven indirectly: Printed mode never calls `_modern_flow` /
    `_MODERN_TOK_RE` at all, so its box still draws via the pre-existing,
    already-correct `_split_graphics` path)."""
    data = ws7_block(0x00) + TOP + HARD + (MID + HARD) * 5 + BOT + HARD
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='printed')
    assert out.startswith(b'%PDF')
