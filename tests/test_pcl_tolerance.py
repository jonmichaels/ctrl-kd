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


# -------------------------------------------- pristine frame-offset rule
def test_pristine_offset_exceeds_tolerance_fails_only_for_pristine_installs():
    # A sawyer-wschange capture's mechanism-S +7.2pt offset is real and
    # expected -- never a divergence, regardless of magnitude.
    assert not pt.pristine_offset_exceeds_tolerance('sawyer-wschange', 7.2)
    assert not pt.pristine_offset_exceeds_tolerance('sawyer-wschange', 500.0)
    # A pristine capture's own offset is checked against LINE_START_EPS_PT.
    assert not pt.pristine_offset_exceeds_tolerance('pristine', 0.0)
    assert not pt.pristine_offset_exceeds_tolerance('pristine', pt.LINE_START_EPS_PT)
    assert pt.pristine_offset_exceeds_tolerance('pristine', pt.LINE_START_EPS_PT + 0.01)
    assert pt.pristine_offset_exceeds_tolerance('pristine', -7.2)


def test_pristine_offset_exceeds_tolerance_none_median_never_fails():
    # frame_offset's own empty-input shape (no line-start same-page pairs
    # at all to measure) -- nothing measured, so nothing to fail on.
    assert not pt.pristine_offset_exceeds_tolerance('pristine', None)


def test_pristine_frame_offset_reason_is_not_a_font_substitution_reason():
    # A pristine-install frame-offset FAIL is a real bug, never accepted
    # by design the way CG-Times/Univers drift is.
    assert pt.REASON_PRISTINE_FRAME_OFFSET in pt.ALL_REASONS
    assert pt.REASON_PRISTINE_FRAME_OFFSET not in pt.FONT_SUBSTITUTION_REASONS
    assert not pt.is_font_substitution_reason(pt.REASON_PRISTINE_FRAME_OFFSET)


# --------------------------------------------- WS7 chunk-splitting fixes
def _pc(text, x_dp, size=24, font='Courier'):
    """A synthetic measurements.json chunk dict -- just the fields
    _merge_kerning_split_chunks (and, later, _dedupe_double_strike_chunks)
    read."""
    return {'text': text, 'x_decipoints': x_dp, 'y_decipoints': 1000,
            'size_pt': size, 'font': font}


def _tc(tid=4099):
    """A synthetic pcl_render reparse chunk dict -- just '_T', the
    pre-substitution PCL typeface id."""
    return {'_T': tid}


def test_merge_kerning_split_chunks_joins_a_contiguous_two_way_split():
    # 'W' then 'ar' at 24pt Courier: natural width of 'W' at 24pt Courier
    # (fixed-pitch, 0.6em/char) is exactly 14.4pt = 144 decipoints -- the
    # real WARPRAYR shape (measurements.json: 'W'/'ar' abutting exactly at
    # 'W's own natural glyph width).
    items = [(_pc('W', 1000), _tc()), (_pc('ar', 1000 + 144), _tc())]
    merged = pt._merge_kerning_split_chunks(items)
    assert len(merged) == 1
    pc, tc = merged[0]
    assert pc['text'] == 'War'
    assert pc['x_decipoints'] == 1000  # keeps the FIRST chunk's own position


def test_merge_kerning_split_chunks_joins_a_three_way_split():
    items = [(_pc('T', 1000), _tc()), (_pc('wa', 1000 + 144), _tc()),
             (_pc('in', 1000 + 144 + 288), _tc())]
    merged = pt._merge_kerning_split_chunks(items)
    assert len(merged) == 1
    assert merged[0][0]['text'] == 'Twain'


def test_merge_kerning_split_chunks_leaves_a_real_gap_unmerged():
    # A genuine space (or any gap well beyond eps_pt) between two chunks is
    # NOT a kerning split -- two separate words, left alone.
    items = [(_pc('The', 1000), _tc()), (_pc('War', 1000 + 500), _tc())]
    merged = pt._merge_kerning_split_chunks(items)
    assert len(merged) == 2
    assert [m[0]['text'] for m in merged] == ['The', 'War']


def test_merge_kerning_split_chunks_does_not_merge_across_a_font_change():
    # Same contiguous position as the joining test, but a different font on
    # the second chunk -- real WS7 never kerning-splits across a font
    # change, so this must NOT merge even though the x lines up.
    items = [(_pc('W', 1000, font='Courier'), _tc(4099)),
             (_pc('ar', 1000 + 144, font='Times-Bold'), _tc(4101))]
    merged = pt._merge_kerning_split_chunks(items)
    assert len(merged) == 2


def test_merge_kerning_split_chunks_single_item_is_a_no_op():
    items = [(_pc('Hello', 1000), _tc())]
    merged = pt._merge_kerning_split_chunks(items)
    assert len(merged) == 1
    assert merged[0][0]['text'] == 'Hello'


def test_dedupe_double_strike_chunks_collapses_an_exact_duplicate():
    items = [(_pc('SAWYER.EXE', 2000), _tc()), (_pc('SAWYER.EXE', 2000), _tc())]
    deduped = pt._dedupe_double_strike_chunks(items)
    assert len(deduped) == 1
    assert deduped[0][0]['text'] == 'SAWYER.EXE'


def test_dedupe_double_strike_chunks_keeps_a_coincidental_same_x_different_text():
    items = [(_pc('Foo', 2000), _tc()), (_pc('Bar', 2000), _tc())]
    deduped = pt._dedupe_double_strike_chunks(items)
    assert len(deduped) == 2


def test_dedupe_double_strike_chunks_keeps_the_same_text_at_a_different_x():
    items = [(_pc('the', 2000), _tc()), (_pc('the', 3000), _tc())]
    deduped = pt._dedupe_double_strike_chunks(items)
    assert len(deduped) == 2


def test_dedupe_double_strike_chunks_requires_matching_font_and_typeface_id():
    items = [(_pc('the', 2000, font='Courier'), _tc(4099)),
             (_pc('the', 2000, font='Times-Bold'), _tc(4101))]
    deduped = pt._dedupe_double_strike_chunks(items)
    assert len(deduped) == 2


def test_dedupe_double_strike_chunks_collapses_a_small_slant_offset():
    # PREVIEW.WS's own shape: WS7 fakes italic AND bold via double-strike on
    # the same pass, offsetting the second strike by a small amount (~14dp
    # = 1.4pt measured) to simulate the slant instead of an exact repeat.
    items = [(_pc('Italic', 3446, font='Times-Bold'), _tc()),
             (_pc('Italic', 3460, font='Times-Bold'), _tc())]
    deduped = pt._dedupe_double_strike_chunks(items)
    assert len(deduped) == 1
    assert deduped[0][0]['x_decipoints'] == 3446    # keeps the FIRST chunk's position


def test_dedupe_double_strike_chunks_epsilon_does_not_swallow_a_real_word_gap():
    # The same small epsilon must not collapse two genuinely different
    # occurrences of the same word separated by a real word-to-word gap --
    # only PREVIEW's own ~1.4pt slant offset is this close.
    items = [(_pc('the', 2000, font='Courier'), _tc()),
             (_pc('the', 2000 + 200, font='Courier'), _tc())]
    deduped = pt._dedupe_double_strike_chunks(items)
    assert len(deduped) == 2


# --------------------------------------- mechanism J: toggle-boundary advance
def _natural_end_dp(text, x_dp, font, size):
    return x_dp + round(pt.fg.afm.string_width_pt(text, font, size) * pt.fg.DECIPT_PER_PT)


def test_merge_trailing_punctuation_chunks_joins_a_trailing_comma():
    # WARPRAYR.WS's own shape: 'country' at 12pt Times-Roman -- WS7's own
    # ',' chunk starts 19dp (1.9pt) past 'country's own natural AFM end,
    # just outside KERNING_MERGE_EPS_PT (15dp) but inside this function's
    # own 3.0pt (30dp) bound.
    end_dp = _natural_end_dp('country', 1000, 'Times-Roman', 12)
    items = [(_pc('country', 1000, size=12, font='Times-Roman'), _tc()),
             (_pc(',', end_dp + 19, size=12, font='Times-Roman'), _tc())]
    merged = pt._merge_trailing_punctuation_chunks(items)
    assert len(merged) == 1
    assert merged[0][0]['text'] == 'country,'
    assert merged[0][0]['x_decipoints'] == 1000


def test_merge_trailing_punctuation_chunks_leaves_two_real_words_alone():
    # The next chunk has real alnum content -- never this mechanism's
    # territory, no matter how close the gap (mechanism C's own, narrower,
    # is the only one allowed to merge two alnum chunks).
    end_dp = _natural_end_dp('country', 1000, 'Times-Roman', 12)
    items = [(_pc('country', 1000, size=12, font='Times-Roman'), _tc()),
             (_pc('and', end_dp + 19, size=12, font='Times-Roman'), _tc())]
    merged = pt._merge_trailing_punctuation_chunks(items)
    assert len(merged) == 2


def test_merge_trailing_punctuation_chunks_respects_its_own_gap_bound():
    # A punctuation chunk far beyond even this wider bound is a real,
    # separate thing (or a different sentence entirely) -- left alone.
    end_dp = _natural_end_dp('country', 1000, 'Times-Roman', 12)
    items = [(_pc('country', 1000, size=12, font='Times-Roman'), _tc()),
             (_pc(',', end_dp + 200, size=12, font='Times-Roman'), _tc())]
    merged = pt._merge_trailing_punctuation_chunks(items)
    assert len(merged) == 2


def test_merge_trailing_punctuation_chunks_does_not_merge_across_a_font_change():
    end_dp = _natural_end_dp('country', 1000, 'Times-Roman', 12)
    items = [(_pc('country', 1000, size=12, font='Times-Roman'), _tc(4101)),
             (_pc(',', end_dp + 19, size=12, font='Times-Bold'), _tc(4102))]
    merged = pt._merge_trailing_punctuation_chunks(items)
    assert len(merged) == 2


def test_is_pure_punctuation_excludes_real_single_letter_words():
    # A lone letter is a real word ('I', 'a') -- must never be swept up by
    # this mechanism, unlike a lone comma or closing quote.
    assert pt._is_pure_punctuation(',')
    assert pt._is_pure_punctuation('."')
    assert not pt._is_pure_punctuation('a')
    assert not pt._is_pure_punctuation('I')
    assert not pt._is_pure_punctuation('')


def test_strip_leading_box_drawing_chunks_separates_a_glued_border_char():
    # SCRIPT.WS's own shape: a table-border '│' glued directly onto the
    # caption word with no space, one literal WS7 chunk. '│' (U+2502) at
    # 24pt Courier has natural width 14.4pt = 144dp.
    items = [(_pc('│Figure', 1000), _tc())]
    stripped = pt._strip_leading_box_drawing_chunks(items)
    assert len(stripped) == 1
    assert stripped[0][0]['text'] == 'Figure'
    assert stripped[0][0]['x_decipoints'] == 1000 + 144


def test_strip_leading_box_drawing_chunks_leaves_plain_text_alone():
    items = [(_pc('Figure', 1000), _tc())]
    stripped = pt._strip_leading_box_drawing_chunks(items)
    assert stripped[0][0]['text'] == 'Figure'
    assert stripped[0][0]['x_decipoints'] == 1000


def test_strip_leading_box_drawing_chunks_leaves_a_pure_box_run_alone():
    # Nothing but box-drawing characters -- _is_box_drawing_text's own
    # territory (applied later, in load_ws7_tokens), not this function's.
    items = [(_pc('│──', 1000), _tc())]
    stripped = pt._strip_leading_box_drawing_chunks(items)
    assert stripped[0][0]['text'] == '│──'
    assert stripped[0][0]['x_decipoints'] == 1000


def test_correct_toggle_boundary_chunks_shifts_a_style_change_with_no_advance():
    # BOXES.WS's own shape: '(' (24pt Courier, natural width 14.4pt = 144dp)
    # immediately followed by a bold toggle with no space -- WS7's own
    # capture puts the bold chunk at the SAME x as '(' itself (a full
    # character's advance dropped), not at '('s natural end.
    items = [(_pc('(', 1000, font='Courier'), _tc(4099)),
             (_pc("^K'", 1000, font='Courier-Bold'), _tc(4099))]
    corrected = pt._correct_toggle_boundary_chunks(items)
    assert len(corrected) == 2
    assert corrected[0][0]['x_decipoints'] == 1000        # '(' itself untouched
    assert corrected[1][0]['x_decipoints'] == 1000 + 144   # shifted to '('s natural end


def test_correct_toggle_boundary_chunks_leaves_a_same_font_coincidence_alone():
    # Same x, but the SAME font on both -- not a style toggle, mechanism D's
    # (double-strike dedupe) territory, not this one's. Must not fire.
    items = [(_pc('Foo', 2000, font='Courier'), _tc(4099)),
             (_pc('Bar', 2000, font='Courier'), _tc(4099))]
    corrected = pt._correct_toggle_boundary_chunks(items)
    assert [c[0]['x_decipoints'] for c in corrected] == [2000, 2000]


def test_correct_toggle_boundary_chunks_leaves_a_normal_font_change_alone():
    # A font change that does NOT start at the exact same x as the
    # preceding chunk (the ordinary, overwhelmingly common case -- a normal
    # word boundary or gap) is untouched; only an EXACT x coincidence is
    # this mechanism's own confirmed shape.
    items = [(_pc('(', 1000, font='Courier'), _tc(4099)),
             (_pc("^K'", 1000 + 144, font='Courier-Bold'), _tc(4099))]
    corrected = pt._correct_toggle_boundary_chunks(items)
    assert [c[0]['x_decipoints'] for c in corrected] == [1000, 1144]


def test_correct_toggle_boundary_chunks_single_item_is_a_no_op():
    items = [(_pc('Hello', 1000), _tc())]
    corrected = pt._correct_toggle_boundary_chunks(items)
    assert len(corrected) == 1
    assert corrected[0][0]['x_decipoints'] == 1000


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


# --------------------------------------- mechanism P: glued-chunk reconcile
def _ws7_word(text, page=1, y_top=100.0):
    return {'text': text, 'page': page, 'y_top': y_top, 'x': 50.0, 'tier': 'exact'}


def _eng_word(text, page=1, y_top=100.0):
    return {'text': text, 'page': page, 'y_top': y_top, 'x': 50.0, 'font_class': 'serif'}


def test_reconcile_glued_ws7_chunks_resolves_a_two_word_glue():
    # LYING.WS's own shape: WS7's own chunk 'lies--everyday;' is really the
    # engine's own two adjacent, already-correct words 'lies--every' and
    # 'day;' glued with no space -- mechanism C's own kerning-merge (a
    # WS7-side chunk-split fix) already ran and produced this single WS7
    # token before this function ever sees it.
    eng_tokens = [_eng_word('Everybody'), _eng_word('lies--every'),
                 _eng_word('day;'), _eng_word('every')]
    unmatched_ws7 = [_ws7_word('lies--everyday;')]
    unmatched_engine = [eng_tokens[1], eng_tokens[2]]
    new_ws7, new_eng = pt._reconcile_glued_ws7_chunks(
        eng_tokens, unmatched_ws7, unmatched_engine)
    assert new_ws7 == []
    assert new_eng == []


def test_reconcile_glued_ws7_chunks_leaves_a_real_single_word_mismatch_alone():
    # A genuine content mismatch (no engine pair concatenates to the WS7
    # text) must never be silently swallowed.
    eng_tokens = [_eng_word('Something'), _eng_word('Else')]
    unmatched_ws7 = [_ws7_word('Different')]
    unmatched_engine = list(eng_tokens)
    new_ws7, new_eng = pt._reconcile_glued_ws7_chunks(
        eng_tokens, unmatched_ws7, unmatched_engine)
    assert new_ws7 == unmatched_ws7
    assert new_eng == unmatched_engine


def test_reconcile_glued_ws7_chunks_requires_true_adjacency_in_the_engine_stream():
    # 'lies--every' and 'day;' are NOT next to each other in the engine's
    # own reading order here (an unrelated word sits between them) -- the
    # WS7 chunk must NOT be reconciled against two words it never sat
    # between on the real page.
    eng_tokens = [_eng_word('lies--every'), _eng_word('unrelated'),
                 _eng_word('day;')]
    unmatched_ws7 = [_ws7_word('lies--everyday;')]
    unmatched_engine = [eng_tokens[0], eng_tokens[2]]
    new_ws7, new_eng = pt._reconcile_glued_ws7_chunks(
        eng_tokens, unmatched_ws7, unmatched_engine)
    assert new_ws7 == unmatched_ws7
    assert new_eng == unmatched_engine


def test_reconcile_glued_ws7_chunks_requires_both_engine_words_still_unmatched():
    # If the SequenceMatcher already paired 'day;' with some other real
    # 'day;' occurrence elsewhere in the document, it is no longer in
    # unmatched_engine -- this must not double-claim it.
    eng_tokens = [_eng_word('lies--every'), _eng_word('day;')]
    unmatched_ws7 = [_ws7_word('lies--everyday;')]
    unmatched_engine = [eng_tokens[0]]              # 'day;' already matched elsewhere
    new_ws7, new_eng = pt._reconcile_glued_ws7_chunks(
        eng_tokens, unmatched_ws7, unmatched_engine)
    assert new_ws7 == unmatched_ws7
    assert new_eng == unmatched_engine


def test_reconcile_glued_ws7_chunks_respects_page_boundaries():
    # Same text, but the WS7 chunk and the candidate engine pair are on
    # different pages -- a coincidental cross-page text match must never
    # merge (page-count-mismatch/pagination-drift is its own, separate
    # finding, not this mechanism's territory).
    eng_tokens = [_eng_word('lies--every', page=2), _eng_word('day;', page=2)]
    unmatched_ws7 = [_ws7_word('lies--everyday;', page=1)]
    unmatched_engine = list(eng_tokens)
    new_ws7, new_eng = pt._reconcile_glued_ws7_chunks(
        eng_tokens, unmatched_ws7, unmatched_engine)
    assert new_ws7 == unmatched_ws7
    assert new_eng == unmatched_engine


def test_reconcile_glued_ws7_chunks_only_consumes_each_token_once():
    # Two separate WS7 glue chunks on the same line must each claim their
    # OWN engine pair, never double-claim a word already spent resolving
    # the other one.
    eng_tokens = [_eng_word('failing--a'), _eng_word('wholly'),
                 _eng_word('case--as'), _eng_word('personal')]
    unmatched_ws7 = [_ws7_word('failing--awholly'), _ws7_word('case--aspersonal')]
    unmatched_engine = list(eng_tokens)
    new_ws7, new_eng = pt._reconcile_glued_ws7_chunks(
        eng_tokens, unmatched_ws7, unmatched_engine)
    assert new_ws7 == []
    assert new_eng == []
