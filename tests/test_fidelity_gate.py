"""Round 26 fidelity gate, NUMBERS side: tools/fidelity_gate.py on synthetic
data. The tool's own README is its module docstring; this file only checks
that each stage does what that docstring claims -- PDF content-stream
parsing, engine word-splitting, WS7/engine matching, and frame-offset
arithmetic -- against inputs whose right answer is known by construction,
never against the real WS7 corpus (private, outside the repo; see
tools/fidelity_gate.py's own doc-resolution/skip-when-absent logic)."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'tools'))
import fidelity_gate as fg  # noqa: E402

from ctrlkd import core, pdf  # noqa: E402

HARD = b'\x0d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _plain_doc(body):
    return core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)


# --------------------------------------------------------------- PDF parsing
def test_parse_text_ops_reads_plain_and_tz_scaled_runs():
    content = (b'BT /F1 12 Tf 3 Ts 100.0 700.0 Td (Hello) Tj ET\n'
              b'BT /F1 12 Tf 85.00 Tz 0 Ts 200.0 700.0 Td (World) Tj ET\n'
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
    out = pdf.emit_pdf(doc, mode='printed')
    out_base = pdf.emit_pdf(baseline, mode='printed')
    x = fg.extract_pages(out)[0]
    x_base = fg.extract_pages(out_base)[0]
    ops = fg.parse_text_ops(x['content'])
    ops_base = fg.parse_text_ops(x_base['content'])
    assert round(ops[0]['x'] - ops_base[0]['x'], 6) == 64.8


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


# -------------------------------------------------------------- end to end
def test_run_gate_end_to_end_on_a_synthetic_ws7_capture(tmp_path):
    """A full run_gate() pass against a hand-built measurements.json that
    mimics the real schema, matched to the actual engine render of the
    matching source text -- exercises the whole pipeline the way the six
    real docs are run, without touching the private/vault corpus."""
    import json
    text = 'A short synthetic paragraph for the fidelity gate itself.'
    doc = _plain_doc(text.encode() + HARD)
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
    ws_path.write_bytes(ws7_block(0x00, bytes([0x70]) + bytes(15)) + text.encode() + HARD)
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
