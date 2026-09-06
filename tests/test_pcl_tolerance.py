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


# ------------------------------------------------------- reason vocabulary
def test_font_substitution_reasons_are_exactly_cgtimes_and_univers():
    assert pt.FONT_SUBSTITUTION_REASONS == {
        pt.REASON_CGTIMES_DRIFT_EXCEEDS_TOLERANCE,
        pt.REASON_UNIVERS_DRIFT_EXCEEDS_TOLERANCE,
    }
    assert pt.FONT_SUBSTITUTION_REASONS <= pt.ALL_REASONS


def test_is_font_substitution_reason_true_only_for_the_two_named_reasons():
    assert pt.is_font_substitution_reason(pt.REASON_CGTIMES_DRIFT_EXCEEDS_TOLERANCE)
    assert pt.is_font_substitution_reason(pt.REASON_UNIVERS_DRIFT_EXCEEDS_TOLERANCE)
    for other in pt.ALL_REASONS - pt.FONT_SUBSTITUTION_REASONS:
        assert not pt.is_font_substitution_reason(other), other
    # Regression guard for the actual bug: the OLD literal the test used to
    # filter on was never a real reason at all.
    assert not pt.is_font_substitution_reason('font-substitution')


def test_doc_report_verdict_ignores_only_font_substitution_reasons(monkeypatch):
    """A document whose ONLY divergences are font-substitution passes
    (verdict 'clean'); any other reason, even alongside font-substitution
    ones, is 'divergent'. Exercises the exact `real_reasons`/`verdict`
    logic in doc_report() via a synthetic counts dict, since doc_report()
    itself needs the private corpus."""
    def real_reasons(counts):
        return [r for r in counts if not pt.is_font_substitution_reason(r)]

    only_font_sub = {pt.REASON_CGTIMES_DRIFT_EXCEEDS_TOLERANCE: 25,
                     pt.REASON_UNIVERS_DRIFT_EXCEEDS_TOLERANCE: 2}
    assert not any(only_font_sub[r] for r in real_reasons(only_font_sub))

    mixed = dict(only_font_sub, **{pt.REASON_WORD_UNMATCHED: 1})
    assert any(mixed[r] for r in real_reasons(mixed))


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


def test_relative_source_handles_a_sources_index_resolved_path(monkeypatch, tmp_path):
    # A path resolved through ws7-prints/v1/sources.json (any private
    # group -- a made-up one here) must still come back corpus-relative,
    # never absolute, same as the older group-search paths. (This is
    # _relative_source's own raw behavior -- doc_report never calls it
    # directly for a non-public group; see _source_ws_for_report below.)
    corpus_root = tmp_path / 'corpus'
    (corpus_root / 'some-other-group' / 'MISC').mkdir(parents=True)
    ws_path = corpus_root / 'some-other-group' / 'MISC' / 'SOMEDOC.WS4'
    ws_path.write_bytes(b'')
    monkeypatch.setattr(pt.fg, '_PRIVATE_CORPUS_ROOT', str(corpus_root))
    monkeypatch.delenv(pt.fg.ARCHIVE_ENV, raising=False)
    rel = pt._relative_source(str(ws_path))
    assert not os.path.isabs(rel)
    assert rel == os.path.join('some-other-group', 'MISC', 'SOMEDOC.WS4')


# -------------------------------------------- published source-path redaction
def _index_fixture(tmp_path, doc_name, source, group):
    import json as _json
    prints_dir = tmp_path / 'ws7-prints' / 'v1'
    prints_dir.mkdir(parents=True)
    (prints_dir / 'sources.json').write_text(_json.dumps({
        'format': 1, 'captures': {doc_name: {'source': source, 'group': group}},
    }))
    return prints_dir


def test_source_ws_for_report_publishes_the_real_path_for_a_public_group(tmp_path, monkeypatch):
    corpus_root = tmp_path / 'corpus'
    _index_fixture(corpus_root, 'LYING', 'pd-samples/authored/LYING.WS', 'pd-samples')
    monkeypatch.setattr(pt.fg, '_PRIVATE_CORPUS_ROOT', str(corpus_root))
    ws_path = os.path.join(str(corpus_root), 'pd-samples', 'authored', 'LYING.WS')
    assert pt._source_ws_for_report('LYING', ws_path) == os.path.join(
        'pd-samples', 'authored', 'LYING.WS')


def test_source_ws_for_report_withholds_the_path_for_a_non_public_group(tmp_path, monkeypatch):
    """This is the actual privacy guard: a corpus group this repo does not
    allowlist (PUBLIC_SOURCE_GROUPS) must never have its real relative
    path -- personal folder layout included -- written into a checked-in,
    PUBLIC manifest. Only the (already-public, per CAPTURED_DOCS) doc name
    may appear."""
    corpus_root = tmp_path / 'corpus'
    _index_fixture(corpus_root, 'WIDGET', 'some-other-group/MISC/WIDGET.WS4', 'some-other-group')
    monkeypatch.setattr(pt.fg, '_PRIVATE_CORPUS_ROOT', str(corpus_root))
    ws_path = os.path.join(str(corpus_root), 'some-other-group', 'MISC', 'WIDGET.WS4')
    published = pt._source_ws_for_report('WIDGET', ws_path)
    assert 'some-other-group' not in published
    assert 'MISC' not in published
    assert 'WIDGET' in published
