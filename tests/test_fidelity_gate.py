"""Round 26 fidelity gate, NUMBERS side: tools/fidelity_gate.py on synthetic
data. The tool's own README is its module docstring; this file only checks
that each stage does what that docstring claims -- PDF content-stream
parsing, engine word-splitting, WS7/engine matching, and frame-offset
arithmetic -- against inputs whose right answer is known by construction,
never against the real WS7 corpus (private, outside the repo; see
tools/fidelity_gate.py's own doc-resolution/skip-when-absent logic)."""
import json
import os
import re
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'tools'))
import fidelity_gate as fg  # noqa: E402

from ctrlkd import core, pdf, pictures  # noqa: E402

HARD = b'\x0d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _plain_doc(body):
    return core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)


# --------------------------------------------------------------- PDF parsing
def test_parse_text_ops_reads_plain_and_tz_scaled_runs():
    # ORDER BUG fixed alongside `_TEXT_OP_RE` itself (2026-09-06): every one
    # of pdf.py's own `ops.append(b'BT ...')` call sites writes `Tf <rise>
    # Ts` FIRST and the optional `<tz> Tz` SECOND, immediately before `Td`
    # -- this fixture previously encoded the reverse order (`Tz` before
    # `Ts`), which matched the regex's OWN prior (wrong) assumption but
    # never matched a real pdf.py content stream, so this test could never
    # have caught the bug it was meant to guard against.
    content = (b'BT /F1 12 Tf 3 Ts 100.0 700.0 Td (Hello) Tj ET\n'
              b'BT /F1 12 Tf 0 Ts 85.00 Tz 200.0 700.0 Td (World) Tj ET\n'
              # a third op with NO Tz -- must carry the 85.00 scale forward,
              # exactly like pdf.py's own per-page tz_state does
              b'BT /F1 12 Tf 0 Ts 300.0 700.0 Td (Again) Tj ET\n')
    ops = fg.parse_text_ops(content)
    assert [o['text'] for o in ops] == ['Hello', 'World', 'Again']
    assert ops[0]['tz'] == 100.0 and ops[0]['rise'] == 3
    assert ops[1]['tz'] == 85.0
    assert ops[2]['tz'] == 85.0            # carried forward, not reset
    assert ops[2]['x'] == 300.0 and ops[2]['y'] == 700.0


def test_parse_text_ops_unescapes_parens_and_backslash():
    # pdf.py's _esc escapes \, ( and ) -- nothing else.
    content = b'BT /F1 12 Tf 0 Ts 10.0 10.0 Td (a \\(b\\) c \\\\d) Tj ET'
    ops = fg.parse_text_ops(content)
    assert ops[0]['text'] == 'a (b) c \\d'


def test_extract_pages_finds_mediabox_fonts_and_content_in_page_order():
    doc = _plain_doc(b'First page text.' + HARD + b'\x0c' + b'Second page text.' + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    pages = fg.extract_pages(out)
    assert len(pages) == 2
    assert pages[0]['mediabox'] == (612.0, 792.0)
    assert b'First page' in pages[0]['content']
    assert b'Second page' in pages[1]['content']
    # the Courier-four font table is always present, by basefont name
    assert 'Courier' in pages[0]['fonts'].values()


def test_extract_pages_matches_pm_offset_from_test_printed_fidelity():
    """Cross-check against the exact arithmetic
    test_printed_fidelity.py's own test_pm_shifts_printed_pdf_first_line_start_x
    asserts via regex: a `.pm 10` first-line indent shifts the leading Td x
    by 64.8pt (9 offset columns * 7.2pt/col) versus a baseline with none."""
    doc = _plain_doc(b'.pm 10' + HARD + b'Some paragraph text without a typed indent at all.' + HARD)
    baseline = _plain_doc(b'Some paragraph text without a typed indent at all.' + HARD)
    # page_numbers='off': neither fixture touches .pn/.pg/.op, so the stock
    # automatic number (the real `auto` default since 2026-09-07,
    # ws7-prints/v3 finding #2) would otherwise add its own text op ahead
    # of `ops[0]` -- unrelated to the `.pm` arithmetic this test checks.
    out = pdf.emit_pdf(doc, mode='printed', page_numbers='off')
    out_base = pdf.emit_pdf(baseline, mode='printed', page_numbers='off')
    x = fg.extract_pages(out)[0]
    x_base = fg.extract_pages(out_base)[0]
    ops = fg.parse_text_ops(x['content'])
    ops_base = fg.parse_text_ops(x_base['content'])
    assert round(ops[0]['x'] - ops_base[0]['x'], 6) == 64.8


# ------------------------------------------- READER operand-order coverage
# Mechanism Z (2026-09-07): the regex `parse_text_ops` used to be keyed to
# ONE fixed operand order and silently dropped every op pdf.py wrote in a
# different order -- a Symbol-face bold/italic/bold-italic run, entirely
# (see the "READER BUG" comment above `_CS_TOKEN_RE` in fidelity_gate.py).
# These are the three shapes named in that comment, encoded byte-for-byte
# as pdf.py itself would write them (`_symbol_style_op`'s own docstring),
# so a regression here can never be explained by anything except the
# reader itself losing an operand-order case again.
def test_parse_text_ops_reads_the_plain_shape():
    content = b'BT /F5 12 Tf 0 Ts 95.09 Tz 57.6 468.0 Td (a) Tj ET'
    ops = fg.parse_text_ops(content)
    assert len(ops) == 1
    op = ops[0]
    assert (op['font'], op['size'], op['tz'], op['rise'], op['x'], op['y'], op['text']) == (
        'F5', 12, 95.09, 0, 57.6, 468.0, 'a')


def test_parse_text_ops_reads_the_faux_bold_shape():
    # Tf -> [Tz] -> `2 Tr <w> w` -> Ts -> Td (_symbol_style_op's own order --
    # Tz and Tr/w BOTH precede Ts here, the opposite of the plain shape).
    content = b'BT /F5 12 Tf 95.09 Tz 2 Tr 0.48 w 0 Ts 180.0 468.0 Td (a) Tj ET'
    ops = fg.parse_text_ops(content)
    assert len(ops) == 1
    op = ops[0]
    assert (op['font'], op['size'], op['tz'], op['rise'], op['x'], op['y'], op['text']) == (
        'F5', 12, 95.09, 0, 180.0, 468.0, 'a')


def test_parse_text_ops_reads_the_faux_oblique_shape():
    # Tf -> [Tz] -> `0 Tr` -> Ts -> a b c d x y Tm (the shear matrix, NOT
    # Td) -- position must come from Tm's own e/f, not from a Td that was
    # never written at all.
    content = b'BT /F5 12 Tf 95.09 Tz 0 Tr 0 Ts 1 0 0.2126 1 302.4 468.0 Tm (a) Tj ET'
    ops = fg.parse_text_ops(content)
    assert len(ops) == 1
    op = ops[0]
    assert (op['font'], op['size'], op['tz'], op['rise'], op['x'], op['y'], op['text']) == (
        'F5', 12, 95.09, 0, 302.4, 468.0, 'a')


def test_parse_text_ops_reads_the_faux_bold_oblique_shape():
    # Both faux effects together: Tr/w AND Tm in the same op.
    content = (b'BT /F5 12 Tf 95.09 Tz 2 Tr 0.48 w 0 Ts '
              b'1 0 0.2126 1 424.8 468.0 Tm (a) Tj ET')
    ops = fg.parse_text_ops(content)
    assert len(ops) == 1
    op = ops[0]
    assert (op['x'], op['y'], op['text']) == (424.8, 468.0, 'a')


def test_parse_text_ops_reads_a_superscript_rise():
    # Ts carries a nonzero rise -- always present per this emitter's own
    # discipline (every call site writes it explicitly), unrelated to the
    # Tz/Tr/Td-vs-Tm operand-order question the other tests here check.
    content = b'BT /F1 9 Tf 3 Ts 200.0 700.0 Td (2) Tj ET'
    ops = fg.parse_text_ops(content)
    assert ops[0]['rise'] == 3 and ops[0]['size'] == 9


_PDF_PY_SRC = open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'src', 'ctrlkd', 'pdf.py')).read()


def test_bt_writing_call_site_count_is_the_one_this_reader_was_checked_against():
    """A grep-driven trip-wire, not a parser: pdf.py has exactly two
    mechanisms that write a `BT..ET` text-showing op --
      (a) 14 literal `b'BT ...'` byte-string sites (13 `ops.append`/`return`
          call sites building either the FIXED-RISE-ONLY shape ('0 Ts', no
          Tz ever -- 5 sites) or the VARIABLE-RISE-WITH-OPTIONAL-Tz PAIR
          shape (4 with/without-Tz site pairs), plus `_symbol_style_op`'s
          own internal `parts = [b'BT ...']` builder line) -- all covered
          by test_parse_text_ops_reads_the_plain_shape (and the existing
          test_parse_text_ops_reads_plain_and_tz_scaled_runs's Tz case)
          above.
      (b) 3 call sites of `_symbol_style_op` (the sole writer of the faux-
          bold/faux-oblique/faux-bold-oblique shapes) -- covered by the
          three faux-* tests above.
    Every one of these reduces to one of the FOUR shapes this file's tests
    exercise (plain, faux-bold, faux-oblique, faux-bold-oblique), because
    `parse_text_ops` is a state machine over individual operators, not a
    per-call-site pattern -- so covering the four shapes covers every
    site. If this count ever changes, a new call site was added: check
    whether it writes one of the four known shapes (if so, just update
    the counts here) or a genuinely new one (if so, this reader needs a
    new test -- and, before that, a check that parse_text_ops still
    handles it, since a fifth shape is exactly how the regex this state
    machine replaced went blind to three of them at once)."""
    n_literal = len(re.findall(r"b'BT ", _PDF_PY_SRC))
    n_symbol_style_op = len(re.findall(r'_symbol_style_op\(', _PDF_PY_SRC)) - 1  # minus `def`
    assert n_literal == 14, (
        f'pdf.py now has {n_literal} literal BT-writing sites (was 14) -- see this '
        'test\'s own docstring')
    assert n_symbol_style_op == 3, (
        f'pdf.py now has {n_symbol_style_op} _symbol_style_op call sites (was 3) -- '
        'see this test\'s own docstring')


# ---- real-emitter regression: every Tj-family op actually gets read, on a
# real (not hand-crafted) content stream, for both mechanisms above.
def _symbol_styled_greek_doc():
    """Reuses test_ctrlkd.py's own construction
    (test_pdf_symbol_run_styling_is_synthesized_bold_italic_bold_italic):
    one cp437 Greek/math run, printed plain/bold/italic/bold-italic, one
    per line -- the ONLY path in pdf.py that writes the faux-bold/faux-
    oblique shapes at all."""
    line = 'αΓπ'.encode('cp437')
    data = (ws7_block(0x00)
           + b'Plain prose padding so the detector reads this as a document.'
           + HARD + line + HARD
           + b'\x02' + line + b'\x02' + HARD             # bold
           + b'\x19' + line + b'\x19' + HARD             # italic
           + b'\x02\x19' + line + b'\x02\x19' + HARD     # bold-italic
           + b'And a closing line of ordinary prose keeps the ratio honest.'
           + HARD)
    return core.parse_ws(data)


def test_parse_text_ops_consumes_every_op_on_a_real_symbol_styled_page():
    """The op-count-consumed invariant, checked against REAL pdf.py output
    (not a hand-crafted fixture): every `BT` this emitter writes is one
    self-contained text-showing op (pdf.py's own convention, confirmed by
    grep -- see the call-site test above), so simply counting `BT ` tokens
    in the raw content stream is a reader-independent ground truth for how
    many ops parse_text_ops should return. Before mechanism Z this failed
    for this exact fixture: bold/italic/bold-italic silently vanished."""
    doc = _symbol_styled_greek_doc()
    out = pdf.emit_pdf(doc, mode='printed')
    for page in fg.extract_pages(out):
        n_bt = page['content'].count(b'BT ')
        ops = fg.parse_text_ops(page['content'])
        assert len(ops) == n_bt, (n_bt, len(ops), page['content'])


def test_parse_text_ops_reads_bold_italic_and_bold_italic_symbol_runs():
    """The actual historical bug, reproduced against real pdf.py output:
    before mechanism Z, only the PLAIN run of these four survived
    `parse_text_ops` -- bold/italic/bold-italic were silently dropped, not
    reported unmatched. All four must come back now, at the SAME x (each
    starts its own line at the same left margin) and DIFFERENT y (stacked
    lines), with 'aGp' as the transliterated cp437 Greek run's own text."""
    doc = _symbol_styled_greek_doc()
    out = pdf.emit_pdf(doc, mode='printed')
    ops = []
    for page in fg.extract_pages(out):
        ops.extend(fg.parse_text_ops(page['content']))
    styled = [o for o in ops if o['text'] == 'aGp']
    assert len(styled) == 4, styled
    xs = {o['x'] for o in styled}
    ys = {o['y'] for o in styled}
    assert len(xs) == 1, styled                  # same left margin, every line
    assert len(ys) == 4, styled                   # four distinct stacked lines


@pytest.mark.parametrize('name', ['LYING', 'WARPRAYR'])
def test_parse_text_ops_consumes_every_op_in_a_bundled_tz_scaled_sample(name):
    """Same op-count-consumed invariant as above, on the bundled PUBLIC
    samples that carry real Tz-scaled (CG-Times/Univers-substituted
    proportional) runs -- the shape the 2026-09-06 fix addressed. Locks
    that fix in as a real-output regression test, not just the synthetic
    fixture test_parse_text_ops_reads_plain_and_tz_scaled_runs already
    checks."""
    ws_path = os.path.join(SAMPLES_DIR, f'{name}.WS')
    pdf_bytes = fg.render_engine_pdf(ws_path)
    pages = fg.extract_pages(pdf_bytes)
    assert any(b' Tz ' in p['content'] for p in pages), (
        f'{name} no longer has a Tz-scaled run -- this test needs a different sample')
    for page in pages:
        n_bt = page['content'].count(b'BT ')
        ops = fg.parse_text_ops(page['content'])
        assert len(ops) == n_bt, (name, n_bt, len(ops))


# ------------------------------- mechanism Z: same-side segmentation (Tier 1)
# 2026-09-07, Jon's ruling from the real-LaserJet paper scan of -SCREEN
# (the private corpus's own verdicts.json doc87 p6): a same-baseline word is
# segmented from CHARACTERS (segment_words_from_chars/char_space_width_pt,
# tools/fidelity_gate.py), never from which text op/PCL chunk happened to
# carry them -- a font/style/rise switch with NO real horizontal gap is
# not a boundary; a space, or a real gap, is. A same-side-only attempt at
# this (2026-09-07, reverted the same day, replaced by this whole
# mechanism) merged on the engine side ALONE and broke six previously-
# clean documents -- see tools/PCL-DIVERGENCE-TRIAGE.md mechanism Z for
# the full trace and tools/pcl_tolerance.py's own tests for the matching
# WS7-side half of this fix (`_merge_zero_gap_cross_font_chunks`).
def _screen_greek_math_line_doc():
    """-SCREEN's own cp437 Greek/math demo line, drawn through FIVE
    alternating Symbol/Courier text ops at zero gap. Factored out (rather
    than inlined, this repo's usual test-module convention) so both the
    op-level test below AND the engine-chars round-trip tests (further
    down this file) exercise the identical fixture."""
    line = 'αßΓπΣσµτΦΘΩδφε'.encode('cp437')
    data = (ws7_block(0x00)
           + b'Plain prose padding so the detector reads this as a document.'
           + HARD + line + HARD
           + b'And a closing line of ordinary prose keeps the ratio honest.'
           + HARD)
    return core.parse_ws(data)


def test_engine_page_tokens_merges_a_styled_span_split_inside_a_word():
    """Tier 1: styled-span split inside a word. -SCREEN's own cp437
    Greek/math demo line draws through FIVE alternating Symbol/Courier
    text ops at zero gap; this must now merge into ONE word, with the
    Symbol-styled characters untransliterated back to their real Unicode
    identity (ctrlkd.symbolmap, via `_op_chars`) so the merged text
    matches WS7's own cp437-decoded capture exactly, not just its
    position."""
    doc = _screen_greek_math_line_doc()
    out = pdf.emit_pdf(doc, mode='printed')
    page = fg.extract_pages(out)[0]
    texts = [t['text'] for t in fg.engine_page_tokens(page, 1)]
    line = 'αßΓπΣσµτΦΘΩδφε'.encode('cp437')
    assert line.decode('cp437') in texts


def _zero_gap_punctuation_doc():
    """SAWYER.WS's own 'WSMSGS.OVR' (bold) immediately followed by '.]'
    (plain), no typed space between them. Factored out for the same
    reason as `_screen_greek_math_line_doc`, above."""
    return core.parse_ws(
        ws7_block(0x00) + b'Plain prose padding so the detector reads this as a document.'
        + HARD + b'See \x02WSMSGS.OVR\x02.] for details.' + HARD)


def test_engine_page_tokens_merges_zero_gap_punctuation_after_a_word():
    """Tier 1: punctuation after a word, zero real gap. SAWYER.WS's own
    'WSMSGS.OVR' (bold) immediately followed by '.]' (plain), no typed
    space between them, must now merge into one word -- this is what
    real WS7 actually printed (confirmed via mechanism J's own toggle-
    boundary correction resolving the WS7-side twin of this exact
    fixture to the identical zero gap; see tools/pcl_tolerance.py's own
    `_merge_zero_gap_cross_font_chunks` tests)."""
    punct_out = pdf.emit_pdf(_zero_gap_punctuation_doc(), mode='printed')
    punct_page = fg.extract_pages(punct_out)[0]
    punct_tokens = [t['text'] for t in fg.engine_page_tokens(punct_page, 1)]
    assert 'WSMSGS.OVR.]' in punct_tokens
    assert 'WSMSGS.OVR' not in punct_tokens


def test_engine_page_tokens_keeps_two_words_separated_by_exactly_one_space():
    """Tier 1: two words separated by exactly one space -- the ordinary
    case must still split, not merge, even at the exact boundary
    threshold (one space glyph's own width -- segment_words_from_chars'
    own `gap >= threshold` rule)."""
    content = b'BT /F1 12 Tf 0 Ts 72.0 700.0 Td (Hello world) Tj ET'
    page = {'mediabox': (612, 792), 'fonts': {'F1': 'Courier'}, 'content': content}
    texts = [t['text'] for t in fg.engine_page_tokens(page, 1)]
    assert texts == ['Hello', 'world']


def _superscript_in_a_word_doc():
    """A footnote-style reference digit directly after a period, no typed
    space -- this engine keeps ONE Td line and only applies a `Ts` rise for
    the raised character (mechanism G), so the two ops sit at zero gap.
    Factored out for the same reason as `_screen_greek_math_line_doc`,
    above."""
    return core.parse_ws(
        ws7_block(0x00) + b'Plain prose padding so the detector reads this as a document.'
        + HARD + b'See cases.\x145\x14 for the ruling.' + HARD)


def test_engine_page_tokens_merges_a_superscript_inside_a_word():
    """Tier 1: superscript in a word (a footnote-style reference digit
    directly after a period, no typed space) -- this engine keeps ONE Td
    line and only applies a `Ts` rise for a raised character (mechanism
    G), so the two ops sit at zero gap and must merge into one word,
    matching DOCC.WS's own real footnote-reference shape (WS7's own
    capture instead moves the PEN, landing the marker on a genuinely
    different y -- see tools/pcl_tolerance.py's own off-baseline
    stitching tests for that half, `_find_offbaseline_occupant`)."""
    out = pdf.emit_pdf(_superscript_in_a_word_doc(), mode='printed')
    page = fg.extract_pages(out)[0]
    texts = [t['text'] for t in fg.engine_page_tokens(page, 1)]
    assert 'cases.5' in texts


# ---------------------------------------------------------- classification
def test_classify_font():
    assert fg.classify_font('Times-Bold') == 'serif'
    assert fg.classify_font('Courier-Oblique') == 'fixed'
    assert fg.classify_font('Helvetica') == 'sans'
    assert fg.classify_font('Symbol') == 'symbol'
    assert fg.classify_font('ZapfDingbats') == 'symbol'
    assert fg.classify_font(None) == 'unknown'
    assert fg.classify_font('Wingdings') == 'unknown'


# --------------------------------------------------------- word splitting
def test_split_engine_op_splits_courier_run_into_words_on_the_afm_grid():
    # Courier is monospace: AFM width 600/1000 em -> 7.2pt/char at 12pt,
    # matching pdf.py's own SIZE*0.6 constant exactly.
    op = {'text': 'Hello world', 'x': 100.0, 'size': 12, 'tz': 100.0}
    words = fg.split_engine_op(op, 'Courier')
    assert [w[0] for w in words] == ['Hello', 'world']
    assert words[0][1] == 100.0
    # "Hello" (5 chars) + one space = 6 chars before "world" starts
    assert round(words[1][1] - words[0][1], 3) == round(6 * 7.2, 3)


def test_split_engine_op_honours_tz_scale():
    op = {'text': 'AB CD', 'x': 0.0, 'size': 12, 'tz': 50.0}
    words = fg.split_engine_op(op, 'Courier')
    # half-scale Courier: 2 chars + 1 space = 3 * 7.2 * 0.5 = 10.8
    assert round(words[1][1] - words[0][1], 3) == 10.8


def test_split_engine_op_single_word_run_is_unaffected():
    op = {'text': 'Solo', 'x': 42.0, 'size': 12, 'tz': 100.0}
    words = fg.split_engine_op(op, 'Times-Roman')
    assert words == [('Solo', 42.0)]


# ---------------------------------------- image-placeholder token exclusion
def test_engine_page_tokens_excludes_a_picture_placeholder_span():
    # core.py's own literal `[image: NAME]` text for an unembedded picture
    # (pictures.py: the CLI default is --pictures off) has, by
    # construction, no WS7 text counterpart at all -- real WS7 printed the
    # actual raster, never this label (confirmed on PREVIEW.WS's own
    # `[image: WORDSTAR.PIX]`, previously two `extra-word-in-engine`
    # divergences neither position nor content could ever resolve).
    content = (b'BT /F1 12 Tf 0 Ts 72.0 700.0 Td (Body text before the image.) Tj ET\n'
               b'BT /F1 12 Tf 0 Ts 72.0 680.0 Td ([image: WORDSTAR.PIX]) Tj ET\n'
               b'BT /F1 12 Tf 0 Ts 72.0 660.0 Td (Body text after it.) Tj ET')
    page = {'mediabox': (612, 792), 'fonts': {'F1': 'Courier'}, 'content': content}
    tokens = fg.engine_page_tokens(page, 1)
    texts = [t['text'] for t in tokens]
    assert texts == ['Body', 'text', 'before', 'the', 'image.',
                     'Body', 'text', 'after', 'it.']
    assert not any('PIX' in t or '[' in t for t in texts)


# -------------------------------------------------------------------- match
def _tok(text, x, y_top, page=1, size=12, font='Courier'):
    return {'text': text, 'x': x, 'y_top': y_top, 'size': size,
            'basefont': font, 'font_class': fg.classify_font(font), 'page': page}


def test_match_doc_pairs_equal_runs_and_reports_unmatched_on_each_side():
    ws7 = [_tok('The', 10, 20), _tok('quick', 40, 20), _tok('fox', 80, 20)]
    eng = [_tok('The', 10.5, 20.5), _tok('slow', 40, 20), _tok('fox', 80.2, 20.1)]
    m = fg.match_doc(ws7, eng)
    matched_texts = [(w['text'], e['text']) for w, e in m['pairs']]
    assert matched_texts == [('The', 'The'), ('fox', 'fox')]
    assert [t['text'] for t in m['unmatched_ws7']] == ['quick']
    assert [t['text'] for t in m['unmatched_engine']] == ['slow']


def test_frame_offset_recovers_an_injected_constant_translation():
    dx0, dy0 = 5.4, -23.7
    ws7 = [_tok(w, x, y) for w, x, y in
          [('one', 10, 100), ('two', 50, 100), ('three', 90, 112)]]
    eng = [_tok(w, x + dx0, y + dy0) for w, x, y in
          [('one', 10, 100), ('two', 50, 100), ('three', 90, 112)]]
    m = fg.match_doc(ws7, eng)
    deltas = fg.pair_deltas(m['pairs'])
    assert len(deltas) == 3 and all(d['same_page'] for d in deltas)
    offset = fg.frame_offset(deltas)
    assert offset['median_dx'] == round(dx0, 3)
    assert offset['median_dy'] == round(dy0, 3)
    assert offset['iqr_dx'] == 0.0 and offset['iqr_dy'] == 0.0
    resid = fg.residuals(deltas, offset)
    assert all(r['resid_pt'] == 0.0 for r in resid)


def test_frame_offset_dy_excludes_cross_page_pairs():
    """A pair whose WS7/engine page numbers disagree must never leak into
    the dy statistic (pagination drift, not a margin measurement) -- dx
    stays page-independent and DOES include it."""
    ws7 = [_tok('same', 10, 20, page=1), _tok('shifted', 10, 700, page=1)]
    eng = [_tok('same', 15, 25, page=1), _tok('shifted', 15, 30, page=2)]
    m = fg.match_doc(ws7, eng)
    deltas = fg.pair_deltas(m['pairs'])
    same = [d for d in deltas if d['ws7_text'] == 'same']
    shifted = [d for d in deltas if d['ws7_text'] == 'shifted']
    assert same[0]['same_page'] is True
    assert shifted[0]['same_page'] is False
    offset = fg.frame_offset(deltas)
    assert offset['n_dx'] == 2          # dx uses every pair
    assert offset['n_dy'] == 1          # dy uses only the same-page pair
    assert offset['median_dy'] == 5.0   # from 'same' alone: 25 - 20


def test_residuals_never_produced_for_cross_page_pairs():
    ws7 = [_tok('a', 10, 20, page=1), _tok('b', 10, 700, page=1)]
    eng = [_tok('a', 15, 25, page=1), _tok('b', 15, 30, page=2)]
    m = fg.match_doc(ws7, eng)
    deltas = fg.pair_deltas(m['pairs'])
    offset = fg.frame_offset(deltas)
    resid = fg.residuals(deltas, offset)
    assert len(resid) == 1 and resid[0]['ws7_text'] == 'a'


# ------------------------------------------------------- PCL corroboration
def test_extract_pcl_top_margin_fields_reads_combined_group():
    # real shape observed in the WS7 corpus: ESC & l 0 o 0 E (two fields
    # in one escape, 'o' non-final lowercase, 'E' the group terminator)
    pcl = b'\x1b&l0o0E' + b'text' + b'\x1b&l6E'
    assert fg.extract_pcl_top_margin_fields(pcl) == ['0', '6']


def test_extract_pcl_top_margin_fields_empty_when_absent():
    assert fg.extract_pcl_top_margin_fields(b'no escape sequences here') == []


# --------------------------------------------------------- doc-path resolution
def test_resolve_doc_paths_fails_loud_when_private_corpus_unset(monkeypatch):
    """No flag, no default -- an unset CTRLKD_PRIVATE_CORPUS must raise,
    never SKIP, since the ground-truth prints directory can't be found at
    all without it."""
    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', None)
    with pytest.raises(RuntimeError, match='CTRLKD_PRIVATE_CORPUS'):
        fg.resolve_doc_paths('LYING')


def test_resolve_doc_paths_fails_loud_when_measurements_missing(tmp_path, monkeypatch):
    """CTRLKD_PRIVATE_CORPUS set but ws7-prints/v1/NAME.measurements.json
    absent -- FAIL LOUD naming the exact path, never a silent skip."""
    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))
    monkeypatch.setattr(fg, 'DEFAULT_AUTHORED_ROOT',
                        os.path.join(str(tmp_path), 'pd-samples', 'authored'))
    expected = os.path.join(str(tmp_path), 'ws7-prints', 'v1', 'LYING.measurements.json')
    with pytest.raises(RuntimeError, match=re.escape(expected)):
        fg.resolve_doc_paths('LYING')


def test_resolve_doc_paths_resolves_measurements_from_private_corpus_env(tmp_path, monkeypatch):
    """The real resolution this used to need a dedicated flag for: a
    ws7-prints/v1/ subdirectory INSIDE the private corpus, same relative
    layout as the vault copy it was captured into."""
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'LYING.measurements.json').write_text('{}')
    (prints_dir / 'LYING.pcl').write_bytes(b'')
    authored_root = tmp_path / 'pd-samples' / 'authored'
    authored_root.mkdir(parents=True)
    (authored_root / 'LYING.WS').write_bytes(b'')

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))
    monkeypatch.setattr(fg, 'DEFAULT_AUTHORED_ROOT', str(authored_root))

    ws_path, mpath, pcl_path = fg.resolve_doc_paths('LYING')
    assert ws_path == str(authored_root / 'LYING.WS')
    assert mpath == str(prints_dir / 'LYING.measurements.json')
    assert pcl_path == str(prints_dir / 'LYING.pcl')


def test_resolve_doc_paths_skips_archive_doc_when_sawyer_archive_unset(tmp_path, monkeypatch):
    """A PRIVATE_DOCS entry (e.g. SAWYER) still SKIPS -- not errors -- when
    only $CTRLKD_SAWYER_ARCHIVE is unset, once the prints directory itself
    resolves fine; the archive corpus is a separate, legitimately-optional
    concern from the ground-truth prints directory."""
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'SAWYER.measurements.json').write_text('{}')

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))
    monkeypatch.delenv(fg.ARCHIVE_ENV, raising=False)

    ws_path, mpath, pcl_path = fg.resolve_doc_paths('SAWYER')
    assert ws_path is None
    assert mpath == str(prints_dir / 'SAWYER.measurements.json')


def test_resolve_doc_paths_uses_sources_index_for_any_private_group(tmp_path, monkeypatch):
    """ws7-prints/v1/sources.json resolves a capture to a corpus-relative
    source path regardless of which private group it lives under -- a
    made-up group/folder name here (this repo never names a real private
    corpus group in its own tracked code), never previously reachable via
    PRIVATE_DOCS or DEFAULT_AUTHORED_ROOT at all."""
    import json as _json
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'WIDGET.measurements.json').write_text('{}')
    (prints_dir / 'sources.json').write_text(_json.dumps({
        'format': 1,
        'captures': {'WIDGET': {'source': 'some-other-group/MISC/WIDGET.WS4',
                                'group': 'some-other-group'}},
    }))

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))

    ws_path, mpath, pcl_path = fg.resolve_doc_paths('WIDGET')
    assert ws_path == str(tmp_path / 'some-other-group' / 'MISC' / 'WIDGET.WS4')
    assert mpath == str(prints_dir / 'WIDGET.measurements.json')


def test_resolve_doc_paths_index_overrides_private_docs_archive_search(tmp_path, monkeypatch):
    """A capture that IS in the legacy PRIVATE_DOCS table (e.g. SAWYER)
    still resolves through sources.json when the index is present --
    $CTRLKD_SAWYER_ARCHIVE is not even consulted."""
    import json as _json
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'SAWYER.measurements.json').write_text('{}')
    (prints_dir / 'sources.json').write_text(_json.dumps({
        'format': 1,
        'captures': {'SAWYER': {'source': 'sawyer/SAWYER.WS', 'group': 'sawyer'}},
    }))

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))
    monkeypatch.delenv(fg.ARCHIVE_ENV, raising=False)

    ws_path, mpath, pcl_path = fg.resolve_doc_paths('SAWYER')
    assert ws_path == str(tmp_path / 'sawyer' / 'SAWYER.WS')


def test_resolve_doc_paths_prefers_a_v2_capture_of_the_same_source(tmp_path, monkeypatch):
    """Mechanism E (tools/PCL-DIVERGENCE-TRIAGE.md): a v2 recapture of the
    SAME sources.json 'source' path is preferred over v1 when it exists on
    disk -- v2's own layout nests the capture under the source path itself
    (v2/sawyer/-README.WS.measurements.json), not v1's flat
    NAME.measurements.json."""
    import json as _json
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / '-README.measurements.json').write_text('{"v": 1}')
    (prints_dir / '-README.pcl').write_bytes(b'v1')
    (prints_dir / 'sources.json').write_text(_json.dumps({
        'format': 1,
        'captures': {'-README': {'source': 'sawyer/-README.WS', 'group': 'sawyer'}},
    }))
    v2_dir = tmp_path / 'ws7-prints' / 'v2' / 'sawyer'
    v2_dir.mkdir(parents=True)
    (v2_dir / '-README.WS.measurements.json').write_text('{"v": 2}')
    (v2_dir / '-README.WS.pcl').write_bytes(b'v2')

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))

    ws_path, mpath, pcl_path = fg.resolve_doc_paths('-README')
    assert ws_path == str(tmp_path / 'sawyer' / '-README.WS')
    assert mpath == str(v2_dir / '-README.WS.measurements.json')
    assert pcl_path == str(v2_dir / '-README.WS.pcl')


def test_resolve_doc_paths_uses_v1_when_no_v2_capture_exists_for_that_source(tmp_path, monkeypatch):
    """Same index shape as above, but no v2 directory at all -- must fall
    back to v1 exactly as before this mechanism-E change (every other
    document in the corpus, which has no v2 recapture yet)."""
    import json as _json
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'SAWYER.measurements.json').write_text('{}')
    (prints_dir / 'SAWYER.pcl').write_bytes(b'')
    (prints_dir / 'sources.json').write_text(_json.dumps({
        'format': 1,
        'captures': {'SAWYER': {'source': 'sawyer/SAWYER.WS', 'group': 'sawyer'}},
    }))
    assert not (tmp_path / 'ws7-prints' / 'v2').exists()

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))

    ws_path, mpath, pcl_path = fg.resolve_doc_paths('SAWYER')
    assert mpath == str(prints_dir / 'SAWYER.measurements.json')
    assert pcl_path == str(prints_dir / 'SAWYER.pcl')


def test_resolve_doc_paths_falls_back_to_group_search_when_index_absent(tmp_path, monkeypatch):
    """No sources.json in the corpus at all (an older clone) -- resolution
    must still work the old way, unchanged."""
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'SAWYER.measurements.json').write_text('{}')
    assert not (prints_dir / 'sources.json').exists()

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))
    monkeypatch.setenv(fg.ARCHIVE_ENV, str(tmp_path / 'sawyer-archive'))

    ws_path, mpath, pcl_path = fg.resolve_doc_paths('SAWYER')
    assert ws_path == str(tmp_path / 'sawyer-archive' / 'SAWYER.WS')


# ------------------------------------------------- v3 (pristine) resolution
def test_resolve_doc_capture_prefers_v3_over_v2_and_v1(tmp_path, monkeypatch):
    """v3 uses v1's OWN flat NAME.measurements.json naming (not v2's
    source-relative-path naming) -- checked directly by doc_name, and
    preferred over BOTH v2 and v1 when present."""
    import json as _json
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / '-README.measurements.json').write_text('{"v": 1}')
    (prints_dir / '-README.pcl').write_bytes(b'v1')
    (prints_dir / 'sources.json').write_text(_json.dumps({
        'format': 1,
        'captures': {'-README': {'source': 'sawyer/-README.WS', 'group': 'sawyer'}},
    }))
    v2_dir = tmp_path / 'ws7-prints' / 'v2' / 'sawyer'
    v2_dir.mkdir(parents=True)
    (v2_dir / '-README.WS.measurements.json').write_text('{"v": 2}')
    (v2_dir / '-README.WS.pcl').write_bytes(b'v2')
    v3_dir = tmp_path / 'ws7-prints' / 'v3'
    v3_dir.mkdir(parents=True)
    (v3_dir / '-README.measurements.json').write_text('{"v": 3}')
    (v3_dir / '-README.pcl').write_bytes(b'v3')

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))

    ws_path, mpath, pcl_path = fg.resolve_doc_paths('-README')
    assert ws_path == str(tmp_path / 'sawyer' / '-README.WS')
    assert mpath == str(v3_dir / '-README.measurements.json')
    assert pcl_path == str(v3_dir / '-README.pcl')

    info = fg.resolve_doc_capture('-README')
    assert info['capture_set'] == 'v3'
    assert info['install'] == 'pristine'


def test_resolve_doc_capture_v3_without_sources_index_entry(tmp_path, monkeypatch):
    """v3 resolution doesn't need the sources.json index to resolve at all
    -- it's checked directly by doc_name (same shape as v1's own default),
    independent of whichever branch (index-hit / PRIVATE_DOCS / authored
    fallback) supplies ws_path."""
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'SAWYER.measurements.json').write_text('{}')
    (prints_dir / 'SAWYER.pcl').write_bytes(b'')
    assert not (prints_dir / 'sources.json').exists()
    v3_dir = tmp_path / 'ws7-prints' / 'v3'
    v3_dir.mkdir(parents=True)
    (v3_dir / 'SAWYER.measurements.json').write_text('{"v": 3}')
    (v3_dir / 'SAWYER.pcl').write_bytes(b'v3')

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))
    monkeypatch.setenv(fg.ARCHIVE_ENV, str(tmp_path / 'sawyer-archive'))

    info = fg.resolve_doc_capture('SAWYER')
    assert info['capture_set'] == 'v3'
    assert info['measurements_path'] == str(v3_dir / 'SAWYER.measurements.json')
    assert info['ws_path'] == str(tmp_path / 'sawyer-archive' / 'SAWYER.WS')
    assert info['install'] == 'pristine'


def test_resolve_doc_capture_falls_back_to_v2_then_v1_when_no_v3_file(tmp_path, monkeypatch):
    """Until a given doc's own v3 capture exists, resolution (and its
    install label) is exactly the pre-v3 v2-then-v1 rule."""
    import json as _json
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'SAWYER.measurements.json').write_text('{}')
    (prints_dir / 'SAWYER.pcl').write_bytes(b'')
    (prints_dir / 'sources.json').write_text(_json.dumps({
        'format': 1,
        'captures': {'SAWYER': {'source': 'sawyer/SAWYER.WS', 'group': 'sawyer'}},
    }))
    assert not (tmp_path / 'ws7-prints' / 'v3').exists()

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))

    info = fg.resolve_doc_capture('SAWYER')
    assert info['capture_set'] == 'v1'
    assert info['install'] == 'sawyer-wschange'
    assert info['measurements_path'] == str(prints_dir / 'SAWYER.measurements.json')


def test_resolve_doc_capture_reads_install_from_v3_sources_json_when_present(tmp_path, monkeypatch):
    """A v3 sources.json declaring its own top-level 'install' field wins
    over the DEFAULT_INSTALL_BY_SUBDIR fallback -- forward-compatible with
    whatever the real capture job's own sources.json ends up saying."""
    import json as _json
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'SAWYER.measurements.json').write_text('{}')
    v3_dir = tmp_path / 'ws7-prints' / 'v3'
    v3_dir.mkdir(parents=True)
    (v3_dir / 'SAWYER.measurements.json').write_text('{}')
    (v3_dir / 'sources.json').write_text(_json.dumps({
        'format': 1, 'install': 'pristine-custom-label', 'captures': {},
    }))

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))
    monkeypatch.setattr(fg, 'DEFAULT_AUTHORED_ROOT',
                        os.path.join(str(tmp_path), 'pd-samples', 'authored'))

    info = fg.resolve_doc_capture('SAWYER')
    assert info['capture_set'] == 'v3'
    assert info['install'] == 'pristine-custom-label'


def test_resolve_doc_capture_v2_capture_set_is_sawyer_wschange(tmp_path, monkeypatch):
    """v2 has no sources.json of its own -- its install label comes from
    DEFAULT_INSTALL_BY_SUBDIR, same provenance as v1 (same install, a
    different capture round/tooling -- see PRINTS_SUBDIR_V2's docstring)."""
    import json as _json
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / '-README.measurements.json').write_text('{"v": 1}')
    (prints_dir / 'sources.json').write_text(_json.dumps({
        'format': 1,
        'captures': {'-README': {'source': 'sawyer/-README.WS', 'group': 'sawyer'}},
    }))
    v2_dir = tmp_path / 'ws7-prints' / 'v2' / 'sawyer'
    v2_dir.mkdir(parents=True)
    (v2_dir / '-README.WS.measurements.json').write_text('{"v": 2}')
    assert not (v2_dir.parent / 'sources.json').exists()

    monkeypatch.setattr(fg, '_PRIVATE_CORPUS_ROOT', str(tmp_path))

    info = fg.resolve_doc_capture('-README')
    assert info['capture_set'] == 'v2'
    assert info['install'] == 'sawyer-wschange'


# -------------------------------------------------------------- end to end
def test_run_gate_end_to_end_on_a_synthetic_ws7_capture(tmp_path):
    """A full run_gate() pass against a hand-built measurements.json that
    mimics the real schema, matched to the actual engine render of the
    matching source text -- exercises the whole pipeline the way the six
    real docs are run, without touching the private/vault corpus."""
    import json
    text = 'A short synthetic paragraph for the fidelity gate itself.'
    # `.op`: this fixture's engine render AND run_gate()'s own internal
    # re-render (fg.render_engine_pdf, below -- it takes no options) must
    # agree on page count/content, so the stock automatic number (the real
    # `auto` default since 2026-09-07, ws7-prints/v3 finding #2) needs
    # suppressing at the DOCUMENT level, not via an emit_pdf() option one
    # of the two call sites can't take.
    doc = _plain_doc(b'.op' + HARD + text.encode() + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    page = fg.extract_pages(out)[0]
    ops = fg.parse_text_ops(page['content'])
    assert len(ops) == 1 and ops[0]['text'] == text
    mb_h = page['mediabox'][1]

    # Build a WS7 measurements.json that reproduces the SAME text at a
    # deliberately offset position, word-by-word (WS7's own granularity),
    # so run_gate has a real doc to point at.
    words = text.split(' ')
    # WS7 x is 6pt to the RIGHT of the engine's -> dx = engine - ws7 = -6.
    # WS7 y_top is 12pt CLOSER TO THE TOP than the engine's -> dy = +12.
    x = ops[0]['x'] + 6.0
    y_top = (mb_h - ops[0]['y']) - 12.0
    chunks = []
    for w in words:
        chunks.append({'x_decipoints': round(x * 10), 'y_decipoints': round(y_top * 10),
                       'size_pt': 12.0, 'font': 'Courier', 'text': w})
        x += (len(w) + 1) * 7.2
    measurements = {'pages': [{'page': 1, 'chunks': chunks, 'baseline_gaps_pt': []}]}

    ws_path = tmp_path / 'SYN.WS'
    ws_path.write_bytes(ws7_block(0x00, bytes([0x70]) + bytes(15))
                        + b'.op' + HARD + text.encode() + HARD)
    m_path = tmp_path / 'SYN.measurements.json'
    m_path.write_text(json.dumps(measurements))

    report = fg.run_gate('SYN', str(ws_path), str(m_path))
    assert report['n_ws7_pages'] == 1 and report['n_engine_pages'] == 1
    assert report['doc_matched'] == len(words)
    assert report['doc_unmatched_ws7'] == 0 and report['doc_unmatched_engine'] == 0
    off = report['first_page_frame_offset']
    assert off['median_dx'] == -6.0
    assert off['median_dy'] == 12.0
    assert report['doc_font_class_agreement'] == 1.0


# --------------------------------------------------- --pdf / pdf_bytes mode
def test_run_gate_accepts_pre_rendered_pdf_bytes_instead_of_ws_path(tmp_path):
    """The `pdf_bytes` path (backing --pdf on the CLI) must produce the
    IDENTICAL report as rendering ws_path ourselves, given the same bytes
    -- this is what lets a different engine's own Printed PDF (e.g. sr's)
    reuse this gate without ws_path or even a .WS source at all."""
    import json
    text = 'Another short synthetic paragraph for the pdf-bytes path.'
    doc = _plain_doc(text.encode() + HARD)
    # page_numbers='off': this fixture touches no .pn/.pg/.op, so the stock
    # automatic number (the real `auto` default since 2026-09-07,
    # ws7-prints/v3 finding #2) would otherwise show up as an extra,
    # unmatched engine word against `measurements` below.
    pdf_bytes = pdf.emit_pdf(doc, mode='printed', page_numbers='off')
    page = fg.extract_pages(pdf_bytes)[0]
    ops = fg.parse_text_ops(page['content'])
    mb_h = page['mediabox'][1]

    words = text.split(' ')
    x = ops[0]['x']
    y_top = mb_h - ops[0]['y']
    chunks = []
    for w in words:
        chunks.append({'x_decipoints': round(x * 10), 'y_decipoints': round(y_top * 10),
                       'size_pt': 12.0, 'font': 'Courier', 'text': w})
        x += (len(w) + 1) * 7.2
    measurements = {'pages': [{'page': 1, 'chunks': chunks, 'baseline_gaps_pt': []}]}
    m_path = tmp_path / 'PDFMODE.measurements.json'
    m_path.write_text(json.dumps(measurements))

    via_bytes = fg.run_gate('PDFMODE', None, str(m_path), pdf_bytes=pdf_bytes)
    assert via_bytes['n_engine_pages'] == 1
    assert via_bytes['doc_matched'] == len(words)
    assert via_bytes['doc_unmatched_ws7'] == 0 and via_bytes['doc_unmatched_engine'] == 0
    assert via_bytes['doc_frame_offset']['median_dx'] == 0.0
    assert via_bytes['doc_frame_offset']['median_dy'] == 0.0


def test_cli_pdf_flag_with_explicit_measurements_needs_no_corpus_env(tmp_path, monkeypatch, capsys):
    """`--pdf PATH --measurements PATH` is fully standalone -- no
    CTRLKD_PRIVATE_CORPUS, no CTRLKD_SAWYER_ARCHIVE, no --doc at all."""
    import json
    monkeypatch.delenv(fg.PRIVATE_CORPUS_ENV, raising=False)
    monkeypatch.delenv(fg.ARCHIVE_ENV, raising=False)

    text = 'Standalone pdf flag test text right here.'
    doc = _plain_doc(text.encode() + HARD)
    pdf_bytes = pdf.emit_pdf(doc, mode='printed')
    page = fg.extract_pages(pdf_bytes)[0]
    ops = fg.parse_text_ops(page['content'])
    mb_h = page['mediabox'][1]
    words = text.split(' ')
    x = ops[0]['x']
    y_top = mb_h - ops[0]['y']
    chunks = []
    for w in words:
        chunks.append({'x_decipoints': round(x * 10), 'y_decipoints': round(y_top * 10),
                       'size_pt': 12.0, 'font': 'Courier', 'text': w})
        x += (len(w) + 1) * 7.2
    measurements = {'pages': [{'page': 1, 'chunks': chunks, 'baseline_gaps_pt': []}]}

    pdf_path = tmp_path / 'STANDALONE.pdf'
    pdf_path.write_bytes(pdf_bytes)
    m_path = tmp_path / 'STANDALONE.measurements.json'
    m_path.write_text(json.dumps(measurements))
    out_json = tmp_path / 'out.json'

    rc = fg.main(['--pdf', str(pdf_path), '--measurements', str(m_path),
                 '--out-json', str(out_json)])
    assert rc == 0
    report = json.loads(out_json.read_text())
    assert report['doc_matched'] == len(words)
    assert report['doc_unmatched_ws7'] == 0


# ------------------------------------------ engine-words/engine-chars (JSON) schema
# Planning: the PCL fidelity gate must accept PRE-EXTRACTED word/character
# positions, so a PDF written by a different emitter (macOS Quartz's
# `Tm`/`TJ` over subset fonts, which parse_text_ops cannot parse at all) can
# be judged by the same tolerance model -- see dump_engine_words/
# load_engine_words's own docstrings for the words schema, and
# dump_engine_chars/load_engine_chars's own for the chars schema (mechanism
# Z, 2026-09-07: an external reader hands this gate CHARACTERS, this gate
# segments them ITSELF -- so mechanism Z's own word-boundary rule is never
# re-implemented a second time by any consumer). The claim under test here:
# run_gate(pdf_bytes=X), run_gate(engine_words=dump_engine_words(X)), and
# run_gate(engine_chars=dump_engine_chars(X)) must all report BYTE-IDENTICAL
# results for the same X, for real, non-trivial engine output -- not just a
# hand-built one-line fixture. Three sources of X, per this repo's
# synthetic-fixtures-only convention: the bundled PUBLIC samples (src/
# ctrlkd/samples/*.WS, which ship in this repo and need no private corpus --
# real multi-page prose, whatever font substitution each one happens to
# hit, e.g. WARPRAYR's own Univers-substituted Tz-scaled quote line), the
# Tier 1 synthetic styled fixtures mechanism Z's own tests already built
# (symbol-styled bold/italic, the -SCREEN Greek/math zero-gap line, zero-gap
# punctuation, a superscript inside a word -- see further down this file),
# and one fully synthetic, GENERATED fixture built here that deliberately
# forces an embedded picture (a raster -- the one extraction path the
# bundled samples never exercise, since none of them reference a .PIX at
# all). The private corpus's own 18 captured documents are checked the same
# way, manually (not in this repo's own test suite -- see
# tools/PCL-DIVERGENCE-TRIAGE.md mechanism Z).
SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'src', 'ctrlkd', 'samples')
BUNDLED_SAMPLE_DOCS = ['LYING', 'WARPRAYR', 'TWAINLET', 'OCAPTAIN']


def _fake_measurements_matching_page_count(n_pages):
    """A placeholder WS7 measurements.json carrying only the right page
    COUNT, no chunks at all. Sufficient for the round-trip claim under
    test: both run_gate() calls being compared are given the EXACT SAME
    ws7 fixture, so its content can never explain a difference between
    the two ENGINE-side extraction paths -- only real extraction disagreement
    could. (Real ws7 ground truth is exercised separately, in the private
    `pcl` tier -- tests/test_pcl_fidelity.py.)"""
    return {'pages': [{'page': i + 1, 'chunks': [], 'baseline_gaps_pt': []}
                      for i in range(n_pages)]}


def _assert_gate_round_trips_pdf_bytes(name, pdf_bytes, m_path, ws_path=None):
    """gate(pdf) == gate(engine_words dump(pdf)) == gate(engine_chars
    dump(pdf)), for an ALREADY-RENDERED pdf_bytes (ws_path is carried
    through only for the report's own 'ws_path' field -- run_gate accepts
    None there, same as its own --pdf CLI path). Both the words-level and
    the chars-level claims are checked here, and BOTH are also
    round-tripped through an actual JSON string (not just the in-memory
    dict) -- catches anything a dump_* function wrote that json.dumps/
    json.loads wouldn't survive byte-for-byte (e.g. a non-JSON-native
    key)."""
    via_pdf = fg.run_gate(name, ws_path, m_path, pdf_bytes=pdf_bytes)

    words = fg.dump_engine_words(pdf_bytes)
    assert words['schema_version'] == fg.ENGINE_WORDS_SCHEMA_VERSION
    assert words['n_pages'] == via_pdf['n_engine_pages']
    via_words = fg.run_gate(name, ws_path, m_path, engine_words=words)
    assert via_pdf == via_words, name
    via_words_json = fg.run_gate(name, ws_path, m_path,
                                 engine_words=json.loads(json.dumps(words)))
    assert via_pdf == via_words_json, name

    chars = fg.dump_engine_chars(pdf_bytes)
    assert chars['schema_version'] == fg.ENGINE_CHARS_SCHEMA_VERSION
    assert chars['n_pages'] == via_pdf['n_engine_pages']
    via_chars = fg.run_gate(name, ws_path, m_path, engine_chars=chars)
    assert via_pdf == via_chars, name
    via_chars_json = fg.run_gate(name, ws_path, m_path,
                                 engine_chars=json.loads(json.dumps(chars)))
    assert via_pdf == via_chars_json, name


def _assert_gate_round_trips(name, ws_path, m_path):
    pdf_bytes = fg.render_engine_pdf(ws_path)
    _assert_gate_round_trips_pdf_bytes(name, pdf_bytes, m_path, ws_path=ws_path)


@pytest.mark.parametrize('name', BUNDLED_SAMPLE_DOCS)
def test_engine_words_and_chars_round_trip_on_bundled_samples(name, tmp_path):
    """gate(pdf) == gate(words-dump(pdf)) == gate(chars-dump(pdf)), for
    every bundled PUBLIC sample .WS -- this repo's own real Printed output
    (multi-page, real body text, whatever font substitution each sample
    happens to hit, e.g. WARPRAYR's own Tz-scaled quote line -- see
    load_engine_chars()'s own TOLERANCE note for why a Tz-scaled run is the
    one case the chars path could, in principle, disagree with the
    ops-based path on), needing no private corpus at all."""
    ws_path = os.path.join(SAMPLES_DIR, f'{name}.WS')
    pdf_bytes = fg.render_engine_pdf(ws_path)
    n_pages = len(fg.extract_pages(pdf_bytes))
    m_path = tmp_path / f'{name}.measurements.json'
    m_path.write_text(json.dumps(_fake_measurements_matching_page_count(n_pages)))
    _assert_gate_round_trips(name, ws_path, str(m_path))


# ---- the four Tier 1 synthetic styled fixtures mechanism Z's own tests
# built above (styled-span split inside a word, zero-gap punctuation, a
# superscript inside a word) get the SAME three-way round-trip claim here --
# these are exactly the shapes a font/style/rise switch with no real gap
# could, in principle, tempt a from-scratch chars-side segmenter into
# treating as a boundary; segment_words_from_chars (reused, not
# reimplemented, by load_engine_chars) proves it doesn't.
def test_engine_chars_round_trip_on_symbol_styled_bold_italic_run(tmp_path):
    doc = _symbol_styled_greek_doc()
    out = pdf.emit_pdf(doc, mode='printed')
    n_pages = len(fg.extract_pages(out))
    m_path = tmp_path / 'SYMBOL_STYLED.measurements.json'
    m_path.write_text(json.dumps(_fake_measurements_matching_page_count(n_pages)))
    _assert_gate_round_trips_pdf_bytes('SYMBOL_STYLED', out, str(m_path))


def test_engine_chars_round_trip_on_screen_greek_math_zero_gap_line(tmp_path):
    doc = _screen_greek_math_line_doc()
    out = pdf.emit_pdf(doc, mode='printed')
    n_pages = len(fg.extract_pages(out))
    m_path = tmp_path / 'SCREEN_GREEK.measurements.json'
    m_path.write_text(json.dumps(_fake_measurements_matching_page_count(n_pages)))
    _assert_gate_round_trips_pdf_bytes('SCREEN_GREEK', out, str(m_path))


def test_engine_chars_round_trip_on_zero_gap_punctuation_after_a_word(tmp_path):
    out = pdf.emit_pdf(_zero_gap_punctuation_doc(), mode='printed')
    n_pages = len(fg.extract_pages(out))
    m_path = tmp_path / 'PUNCT.measurements.json'
    m_path.write_text(json.dumps(_fake_measurements_matching_page_count(n_pages)))
    _assert_gate_round_trips_pdf_bytes('PUNCT', out, str(m_path))


def test_engine_chars_round_trip_on_superscript_inside_a_word(tmp_path):
    out = pdf.emit_pdf(_superscript_in_a_word_doc(), mode='printed')
    n_pages = len(fg.extract_pages(out))
    m_path = tmp_path / 'SUPERSCRIPT.measurements.json'
    m_path.write_text(json.dumps(_fake_measurements_matching_page_count(n_pages)))
    _assert_gate_round_trips_pdf_bytes('SUPERSCRIPT', out, str(m_path))


# ---- generated fixture: force an embedded picture (the raster round-trip
# path -- none of the bundled samples above reference a .PIX at all).
def _tiny_pix_bytes(gcols=8, grows=1):
    """A minimal, structurally valid, single-row MONO .PIX -- same
    construction as tests/test_pictures.py's own _tiny_pix_bytes (row 0 is
    always stored raw, so this needs none of test_pix.py's tile-encoding
    machinery); duplicated here rather than imported since test modules
    aren't a shared library by this repo's own convention."""
    row_bytes = gcols // 8
    mode_blob = bytearray(29)
    mode_blob[1] = 1                                  # htype bit0: bitmap
    struct.pack_into('<HH', mode_blob, 18, gcols, grows)
    mode_blob[22] = 1                                 # gfore: 1 bitplane
    tile_info = struct.pack('<HHHH', grows, gcols, 1, 1)
    tile_bitmap = bytes(row_bytes)                     # one raw all-zero row

    items = [(0, bytes(mode_blob)), (1, bytes(4 * 16)), (2, tile_info),
            (0x8000, tile_bitmap)]
    header = struct.pack('<HH', 3, len(items))
    index_off = 4 + 8 * len(items)
    index_entries = bytearray()
    blobs = bytearray()
    cur = index_off
    for did, blob in items:
        index_entries += struct.pack('<HHI', did, len(blob), cur)
        blobs += blob
        cur += len(blob)
    return bytes(header) + bytes(index_entries) + bytes(blobs)


def _ws_pix_block(payload):
    jump = (len(payload) + 4).to_bytes(2, 'little')
    return b'\x1d' + jump + bytes([0x10]) + payload + jump + b'\x1d'


def test_engine_words_and_chars_round_trip_on_generated_picture_fixture(tmp_path):
    """gate(pdf) == gate(words-dump(pdf)) == gate(chars-dump(pdf)) for a
    synthetic document that embeds a real picture -- the raster extraction
    path (engine_page_rasters / 'rasters' in both JSON schemas), which none
    of the bundled prose samples above ever exercise. Regression guard for
    the real bug this test caught while it was being written: load_engine_
    words() originally dropped the raster dict's own 'page' key
    (engine_page_rasters() includes it, load_engine_words() didn't put it
    back), which made a picture-bearing document's `rasters` report differ
    between the two paths -- silently, since every OTHER field still
    compared equal. load_engine_chars() shares the same raster-loading code
    shape, so this guard covers it too."""
    (tmp_path / 'FIGURE1.PIX').write_bytes(_tiny_pix_bytes())
    ws_path = tmp_path / 'DOC.WS'
    block = _ws_pix_block(br'C:\PIX\FIGURE1.PIX')
    ws_path.write_bytes(b'Before the picture.\r\n\r\n' + block
                        + b'\r\n\r\nAfter the picture.\r\n')
    doc = core.parse_ws(ws_path.read_bytes())
    pix_results = pictures.resolve_document_pictures(doc, str(ws_path))
    assert pix_results and pix_results[0].ok, 'fixture must actually resolve the picture'

    pdf_bytes = fg.render_engine_pdf(str(ws_path))
    engine_pages = fg.extract_pages(pdf_bytes)
    assert any(fg.engine_page_rasters(p, i + 1) for i, p in enumerate(engine_pages)), \
        'fixture must actually draw a raster op, or this test proves nothing'

    m_path = tmp_path / 'DOC.measurements.json'
    m_path.write_text(json.dumps(_fake_measurements_matching_page_count(len(engine_pages))))
    _assert_gate_round_trips('DOC', str(ws_path), str(m_path))
