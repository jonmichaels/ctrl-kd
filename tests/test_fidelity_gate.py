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

import pytest

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
