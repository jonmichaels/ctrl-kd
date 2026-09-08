"""planning #230: found during the #228 attempt -- a trial fix put
DISPLAY.WS's footnote and endnote together on page 1 (with a blank page
2), while WS7's real capture has the endnote alone on its own page 2.
tools/pcl_tolerance.py's own gate reported that document CLEAN anyway,
because match_doc() pairs words by TEXT across the whole document (by
design -- see its own docstring, needed so a pagination-capacity
difference doesn't lose the alignment near every divergence), and the
per-page classification loop below it then silently `continue`d past
any pair whose two halves landed on different page numbers, reasoning
that page-count-mismatch already covers pagination drift at the
document level. It doesn't: two documents can carry the IDENTICAL total
page count while individual content still sits on the wrong page of it
(this fixture's own shape, and DISPLAY.WS's own real one) -- a clean
verdict in that case does not prove page-level placement (memory: verify
the artifact, not the count).

Fix: a cross-page match is now its own divergence, reason code
REASON_PAGE_MEMBERSHIP ('page-membership'), never silently dropped and
never folded into 'clean'.

This is an end-to-end regression test (not a pure-logic unit test, unlike
this repo's usual tier-1 tests) because the reason is assigned inside
doc_report()'s own per-page loop, not a separately callable function --
it builds a tiny synthetic v4-shaped corpus (one document, two pages) in
a pytest tmp_path, self-consistently generated the same way the real
corpus is (tools/pcl_render.py's own CLI decodes the same synthetic .pcl
bytes this test writes, so the ground truth here is never hand-typed out
of sync with what the real decoder would produce), and points
tools/fidelity_gate.py's private-corpus root at it via monkeypatch
(`_PRIVATE_CORPUS_ROOT` is read once at import time from the env var, so
the env var alone is not enough after import). `engine_words` supplies
the synthetic "engine" side directly, skipping PDF rendering entirely --
this test's only interest is the page-membership classification, not
rendering."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

import pcl_tolerance as pt                                     # noqa: E402


def _build_synthetic_corpus(tmp_path):
    """A 2-page WS7 capture: page 1 carries 'footnote', page 2 carries
    'endnotetext' alone -- the DISPLAY.WS shape (footnote's own page,
    then the endnote on its OWN separate page)."""
    v4_dir = tmp_path / 'ws7-prints' / 'v4'
    v4_dir.mkdir(parents=True)
    (tmp_path / 'synthdocs').mkdir()
    ws_path = tmp_path / 'synthdocs' / 'PAGEMEMBERSHIP-LIKE.WS'
    ws_path.write_text('placeholder synthetic WS source (page-membership fixture)')

    pcl_bytes = (b'\x1b&a576H\x1b&a480Vfootnote'
                b'\x0c'
                b'\x1b&a576H\x1b&a480Vendnotetext')
    pcl_path = v4_dir / 'synth__page_membership.pcl'
    pcl_path.write_bytes(pcl_bytes)

    measurements_path = v4_dir / 'synth__page_membership.measurements.json'
    render_script = os.path.join(os.path.dirname(__file__), '..', 'tools', 'pcl_render.py')
    subprocess.run(
        [sys.executable, render_script, str(pcl_path),
         '--out-prefix', str(tmp_path / 'scratch'),
         '--json', str(measurements_path), '--no-png'],
        check=True, capture_output=True)

    return {'ws_path': str(ws_path), 'measurements_path': str(measurements_path),
            'pcl_path': str(pcl_path), 'capture_set': 'v4', 'install': 'pristine'}


def _engine_words_footnote_and_endnote_together_on_page_1():
    """The bug's own shape: the engine renders BOTH words on page 1 (a
    blank page 2 -- not represented here since an empty page contributes
    no tokens either way), so 'endnotetext' can only match WS7's own page
    2 word across a page boundary."""
    return {
        'schema_version': pt.fg.ENGINE_WORDS_SCHEMA_VERSION,
        'n_pages': 2,
        'words': [
            {'text': 'footnote', 'x_pt': 57.6, 'y_top_pt': 48.0, 'size_pt': 12.0,
             'font': 'Courier', 'font_class': 'exact', 'page': 1},
            {'text': 'endnotetext', 'x_pt': 57.6, 'y_top_pt': 48.0, 'size_pt': 12.0,
             'font': 'Courier', 'font_class': 'exact', 'page': 1},
        ],
        'rasters': [],
    }


def test_cross_page_match_is_a_page_membership_divergence(tmp_path, monkeypatch):
    capture = _build_synthetic_corpus(tmp_path)
    assert os.path.exists(capture['measurements_path'])
    monkeypatch.setattr(pt.fg, 'resolve_doc_capture', lambda name: capture)

    report = pt.doc_report('synth__page_membership',
                           engine_words=_engine_words_footnote_and_endnote_together_on_page_1())

    assert report['verdict'] == 'divergent', (
        f"a word matched across a page boundary must never verdict clean; got {report}")
    assert report['counts_by_reason'].get(pt.REASON_PAGE_MEMBERSHIP) == 1
    pm = [d for d in report['divergences'] if d['reason'] == pt.REASON_PAGE_MEMBERSHIP]
    assert len(pm) == 1
    assert pm[0]['words'] == ['endnotetext', 'endnotetext']
    assert 'page 1' in pm[0]['detail'] and 'page 2' in pm[0]['detail']
    # the SAME-page word ('footnote') must not be swept up in this --
    # only the genuinely cross-page pair gets the reason.
    assert not any(d['reason'] == pt.REASON_PAGE_MEMBERSHIP and 'footnote' in d['words']
                  for d in report['divergences'])


def test_same_page_match_is_not_flagged_page_membership(tmp_path, monkeypatch):
    """Control case: both words on their OWN matching pages (no bug) must
    report zero page-membership divergences -- this fixture/harness
    itself isn't what's producing the reason."""
    capture = _build_synthetic_corpus(tmp_path)
    assert os.path.exists(capture['measurements_path'])
    monkeypatch.setattr(pt.fg, 'resolve_doc_capture', lambda name: capture)

    engine_words = {
        'schema_version': pt.fg.ENGINE_WORDS_SCHEMA_VERSION,
        'n_pages': 2,
        'words': [
            {'text': 'footnote', 'x_pt': 57.6, 'y_top_pt': 48.0, 'size_pt': 12.0,
             'font': 'Courier', 'font_class': 'exact', 'page': 1},
            {'text': 'endnotetext', 'x_pt': 57.6, 'y_top_pt': 48.0, 'size_pt': 12.0,
             'font': 'Courier', 'font_class': 'exact', 'page': 2},
        ],
        'rasters': [],
    }
    report = pt.doc_report('synth__page_membership', engine_words=engine_words)
    assert report['counts_by_reason'].get(pt.REASON_PAGE_MEMBERSHIP, 0) == 0
    assert report['verdict'] == 'clean'
