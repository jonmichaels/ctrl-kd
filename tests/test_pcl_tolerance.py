"""Unit tests for tools/pcl_tolerance.py's pure logic -- tier classification,
the tolerance formulas, and the two token-exclusion filters -- against
synthetic data only (per this repo's synthetic-fixtures-only convention).
The full corpus-driven report (doc_report()) is exercised by the `pcl`
pytest tier (tests/test_pcl_fidelity.py), which needs the private corpus;
everything here runs in tier 1, unconditionally, on any clone."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'tools'))
import pcl_tolerance as pt  # noqa: E402


# ------------------------------------------------------------- font tiers
def test_tier_for_typeface_covers_every_documented_id():
    assert pt.tier_for_typeface(4099) == pt.TIER_EXACT       # Courier, scalable
    assert pt.tier_for_typeface(3) == pt.TIER_EXACT          # Courier, bitmap
    assert pt.tier_for_typeface(4) == pt.TIER_EXACT          # real Helvetica, no substitution
    assert pt.tier_for_typeface(4101) == pt.TIER_CGTIMES     # CG Times -> Times
    assert pt.tier_for_typeface(4148) == pt.TIER_UNIVERS     # Univers -> Helvetica
    for no_sub_id in (4362, 4197, 4140, 4168, 4113, 4116):
        assert pt.tier_for_typeface(no_sub_id) == pt.TIER_NO_SUBSTITUTE


def test_tier_for_typeface_unknown_and_none():
    assert pt.tier_for_typeface(None) == pt.TIER_UNKNOWN
    assert pt.tier_for_typeface(999999) == pt.TIER_UNKNOWN


def test_pcl_render_typeface_family_has_univers_entry():
    """Regression guard for the 2026-09-05 bug this module's own docstring
    documents: pcl_render.TYPEFACE_FAMILY's own comments narrated 4148
    (Univers) as mapped to Helvetica, but the literal dict entry was
    missing, so it silently fell through to the Times fallback."""
    assert pt.pr.TYPEFACE_FAMILY.get(4148) == 'Helvetica'


# -------------------------------------------------------------- tolerances
def test_cgtimes_tolerance_grows_with_distance_into_line():
    at_start = pt.cgtimes_tolerance_pt(0.0)
    farther = pt.cgtimes_tolerance_pt(300.0)
    assert at_start == pt.CGTIMES_DRIFT_BASE_PT
    assert farther > at_start
    assert farther == pt.CGTIMES_DRIFT_BASE_PT + pt.CGTIMES_DRIFT_RATE_PT_PER_PT * 300.0


def test_univers_tolerance_shares_the_cgtimes_curve():
    # Documented in the module docstring: too little independent Univers
    # data (n=21) to fit its own curve -- shares CG Times's bound.
    for dist in (0.0, 42.0, 500.0):
        assert pt.univers_tolerance_pt(dist) == pt.cgtimes_tolerance_pt(dist)


# ------------------------------------------------------- token exclusions
def test_box_drawing_text_detects_pure_border_and_block_runs():
    assert pt._is_box_drawing_text('│')            # vertical bar
    assert pt._is_box_drawing_text('┌' + '─' * 5 + '┐')  # a box top
    assert pt._is_box_drawing_text('█' * 40)       # solid block fill
    assert not pt._is_box_drawing_text('Hello')
    assert not pt._is_box_drawing_text('')
    assert not pt._is_box_drawing_text('   ')


def test_unreliable_to_align_flags_short_and_punctuation_only_tokens():
    for tok in (',', '.', '),', '.]', ':', '!', 'A', "'s", '^K'):
        assert pt._is_unreliable_to_align(tok), tok
    for tok in ('the', 'WordStar', 'warp', '(1819-1892)'):
        assert not pt._is_unreliable_to_align(tok), tok


# ------------------------------------------------------------- doc report
def test_doc_report_skips_known_missing_source_docs_without_touching_env(monkeypatch):
    monkeypatch.delenv('CTRLKD_PRIVATE_CORPUS', raising=False)
    for name in pt.KNOWN_MISSING_SOURCE_DOCS:
        r = pt.doc_report(name)
        assert r['verdict'] == 'source-missing'
        assert r['source_ws'] is None
        assert r['counts_by_reason'] == {}


def test_relative_source_never_returns_an_absolute_path(monkeypatch, tmp_path):
    corpus_root = tmp_path / 'corpus'
    (corpus_root / 'pd-samples' / 'authored').mkdir(parents=True)
    ws_path = corpus_root / 'pd-samples' / 'authored' / 'LYING.WS'
    ws_path.write_bytes(b'')
    monkeypatch.setattr(pt.fg, '_PRIVATE_CORPUS_ROOT', str(corpus_root))
    monkeypatch.delenv(pt.fg.ARCHIVE_ENV, raising=False)
    rel = pt._relative_source(str(ws_path))
    assert not os.path.isabs(rel)
    assert rel == os.path.join('pd-samples', 'authored', 'LYING.WS')


def test_relative_source_falls_back_to_basename_outside_any_known_root(monkeypatch, tmp_path):
    monkeypatch.setattr(pt.fg, '_PRIVATE_CORPUS_ROOT', None)
    monkeypatch.delenv(pt.fg.ARCHIVE_ENV, raising=False)
    rel = pt._relative_source('/some/unrelated/place/DOC.WS')
    assert rel == 'DOC.WS'
    assert not os.path.isabs(rel)


def test_captured_docs_and_known_missing_source_docs_are_consistent():
    # Every name this module claims to know about either has a resolvable
    # source or is explicitly tracked as missing -- never silently absent
    # from both lists.
    assert pt.KNOWN_MISSING_SOURCE_DOCS <= set(pt.CAPTURED_DOCS)
