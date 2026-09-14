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


def test_tier_for_typeface_covers_the_postscript_document_ids():
    """planning #225 (2026-09-08): the v4 capture round hit four typeface
    IDs -- 0, 16602, 16686, 31402 -- with no tier entry at all, which fell
    through to TIER_UNKNOWN and produced the 'unclassified-font-tier'
    divergence reason on any future document using them. Regression guard
    for the fix: each is now a real, sourced tier (see
    FONT_TIER_BY_TYPEFACE_ID's own comments for citations), never
    TIER_UNKNOWN, and TYPEFACE_FAMILY carries the matching AFM family."""
    assert pt.tier_for_typeface(0) == pt.TIER_EXACT           # LinePrinter
    assert pt.tier_for_typeface(16602) == pt.TIER_UNIVERS     # Triumvirate -> Arial
    assert pt.tier_for_typeface(16686) == pt.TIER_EXACT       # Symbol
    assert pt.tier_for_typeface(31402) == pt.TIER_NO_SUBSTITUTE  # ZapfDingbats -> Wingdings
    assert pt.pr.TYPEFACE_FAMILY.get(0) == 'Courier'
    assert pt.pr.TYPEFACE_FAMILY.get(16602) == 'Helvetica'
    assert pt.pr.TYPEFACE_FAMILY.get(16686) == 'Symbol'
    assert pt.pr.TYPEFACE_FAMILY.get(31402) == 'ZapfDingbats'
    # resolve_afm_basefont must hand back the literal, unstyled name for
    # Symbol/ZapfDingbats -- afm.WIDTHS has exactly one (unstyled) entry
    # for each, so a synthesized '-Bold'/'-Oblique' variant would be a
    # KeyError waiting to happen downstream.
    assert pt.pr.resolve_afm_basefont(1, 0, 3, 16686) == 'Symbol'
    assert pt.pr.resolve_afm_basefont(1, 1, 3, 31402) == 'ZapfDingbats'


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
def _pc(text, x_dp, size=24, font='Courier', underline=False):
    """A synthetic measurements.json chunk dict -- just the fields
    _merge_kerning_split_chunks (and, later, _dedupe_double_strike_chunks)
    read."""
    return {'text': text, 'x_decipoints': x_dp, 'y_decipoints': 1000,
            'size_pt': size, 'font': font, 'underline': underline}


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


def test_strip_box_drawing_chunk_edges_separates_a_glued_border_char():
    # SCRIPT.WS's own shape: a table-border '│' glued directly onto the
    # caption word with no space, one literal WS7 chunk. '│' (U+2502) at
    # 24pt Courier has natural width 14.4pt = 144dp.
    items = [(_pc('│Figure', 1000), _tc())]
    stripped = pt._strip_box_drawing_chunk_edges(items)
    assert len(stripped) == 1
    assert stripped[0][0]['text'] == 'Figure'
    assert stripped[0][0]['x_decipoints'] == 1000 + 144


def test_strip_box_drawing_chunk_edges_leaves_plain_text_alone():
    items = [(_pc('Figure', 1000), _tc())]
    stripped = pt._strip_box_drawing_chunk_edges(items)
    assert stripped[0][0]['text'] == 'Figure'
    assert stripped[0][0]['x_decipoints'] == 1000


def test_strip_box_drawing_chunk_edges_leaves_a_pure_box_run_alone():
    # Nothing but box-drawing characters -- _is_box_drawing_text's own
    # territory (applied later, in load_ws7_tokens), not this function's.
    items = [(_pc('│──', 1000), _tc())]
    stripped = pt._strip_box_drawing_chunk_edges(items)
    assert stripped[0][0]['text'] == '│──'
    assert stripped[0][0]['x_decipoints'] == 1000


def test_strip_box_drawing_chunk_edges_separates_a_trailing_border_char():
    # FIX 2 (generalizing mechanism N to both edges): a table row that
    # ends against its own right-hand border, e.g. '1│' -- the leading
    # edge is real text, so this must survive as leading-strip's own
    # no-op path while still dropping the TRAILING '│'. No x correction
    # is needed: a chunk's own x is its LEFT edge, unaffected by removing
    # characters off its right end.
    items = [(_pc('1│', 1000), _tc())]
    stripped = pt._strip_box_drawing_chunk_edges(items)
    assert stripped[0][0]['text'] == '1'
    assert stripped[0][0]['x_decipoints'] == 1000


def test_strip_box_drawing_chunk_edges_separates_both_edges_at_once():
    # A caption row glued to a border on BOTH sides, e.g. '│Figure 1│'
    # captured as one chunk (SCRIPT's own table shape, extended): both
    # the leading and trailing box-drawing runs are stripped in the same
    # pass, and only the leading strip shifts x.
    items = [(_pc('│Figure 1│', 1000), _tc())]
    stripped = pt._strip_box_drawing_chunk_edges(items)
    assert stripped[0][0]['text'] == 'Figure 1'
    assert stripped[0][0]['x_decipoints'] == 1000 + 144


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


def test_correct_toggle_boundary_chunks_underline_extension_chains_two_glues():
    # `-README`'s own page-5 shape, raw .pcl: `&a1512H(` + ESC&dD (underline
    # on, no position) + `http://www.vdosplus.org` (23 chars) + ESC&d@
    # (underline off, no position) + `)` + ` ` + `&a3384Hor` -- WS7 only
    # gave "(" a real H; the URL and the closing ")" both inherit "("'s own
    # stale x in measurements.json. Same font throughout (Courier) -- only
    # `underline` toggles -- so this must fire on the underline flag alone,
    # and it must CHAIN through both glued chunks, not just the first.
    # 12pt Courier: natural width 7.2pt/char = 72dp/char.
    assert len('http://www.vdosplus.org') == 23
    items = [
        (_pc('(', 1512, size=12, underline=False), _tc(4099)),
        (_pc('http://www.vdosplus.org', 1512, size=12, underline=True), _tc(4099)),
        (_pc(')', 1512, size=12, underline=False), _tc(4099)),
    ]
    corrected = pt._correct_toggle_boundary_chunks(items)
    xs = [c[0]['x_decipoints'] for c in corrected]
    assert xs == [1512, 1512 + 72, 1512 + 72 + 23 * 72]
    # And the corrected end, plus ")"'s own 1-char width and the one
    # source space before "or", lands exactly where WS7's own next real
    # `H` ("or") was measured -- 3384dp -- closing the loop with zero
    # residual (the source reads "...vdosplus.org) or the...").
    assert xs[-1] + 72 + 72 == 3384


def test_correct_toggle_boundary_chunks_leaves_a_same_underline_coincidence_alone():
    # Same x, same font, same underline state on both -- not a toggle
    # boundary at all; must not fire (mechanism D's dedupe territory if
    # the text also matched, but here it doesn't, so this stays untouched).
    items = [(_pc('Foo', 2000, underline=True), _tc()),
             (_pc('Bar', 2000, underline=True), _tc())]
    corrected = pt._correct_toggle_boundary_chunks(items)
    assert [c[0]['x_decipoints'] for c in corrected] == [2000, 2000]


# ----------------- mechanism J's re-strike pre-scan (planning #270 item 39)

def test_a_three_chunk_sandwich_leaves_the_second_strike_where_it_is():
    # -README.WS's own 'LASERJET.PDF', double-struck bold, with the rest of
    # its sentence emitted BETWEEN the two strikes -- the m=1 case. The
    # re-strike must NOT be "corrected" past the punctuation: it has to stay
    # on its own first strike so mechanism D can dedupe it.
    items = [(_pc('LASERJET.PDF', 1000, font='Courier-Bold'), _tc(4099)),
             (_pc(', and WS4.PDF).', 1000, font='Courier'), _tc(4099)),
             (_pc('LASERJET.PDF', 1000, font='Courier-Bold'), _tc(4099))]
    corrected = pt._correct_toggle_boundary_chunks(items)
    xs = [c[0]['x_decipoints'] for c in corrected]
    assert xs[0] == 1000 and xs[2] == 1000
    assert len(pt._dedupe_double_strike_chunks(corrected)) == 2


def test_a_repeated_pair_at_one_stale_x_is_a_re_strike_of_that_pair():
    # -HOLYMAC.WS page 198 / 7MAC1 page 8, the item 39 residual: `^K` and
    # `O` at the same raw x (the `O` never got its own H command because
    # UNDERLINE toggled between them), then the identical PAIR again. A run
    # of four shaped A,B,A,B -- invisible to any length-3 rule.
    # 12pt Courier: 72dp per character.
    def pair():
        return [(_pc('^K', 936, size=12, font='Courier-Bold', underline=False), _tc(4099)),
                (_pc('O', 936, size=12, font='Courier-Bold', underline=True), _tc(4099))]
    items = pair() + pair()
    corrected = pt._correct_toggle_boundary_chunks(items)
    xs = [c[0]['x_decipoints'] for c in corrected]
    # the first pair resolves: `^K` where it is, `O` one 2-character
    # advance along; the second pair takes those SAME two positions.
    assert xs == [936, 936 + 144, 936, 936 + 144]
    deduped = pt._dedupe_double_strike_chunks(corrected)
    assert len(deduped) == 2
    assert [c[0]['text'] for c in deduped] == ['^K', 'O']


def test_a_re_strike_at_the_end_of_a_long_stale_x_run_is_still_a_re_strike():
    # -HOLYMAC.WS pages 12/13, the WordStar screen diagram: a bold digit,
    # its label, another bold digit, its label -- all at one stale raw x --
    # and then the FIRST digit struck again at the end of the line's
    # chunks. Five chunks, so the old exactly-three rule never saw it and
    # the re-strike was corrected off the end of 'Bold', where it printed
    # as a spurious trailing '3'.
    raw = [('3', 'Courier-Bold'), ('Undrlin', 'Courier'),
           ('4', 'Courier-Bold'), ('Bold', 'Courier'), ('3', 'Courier-Bold')]
    items = [(_pc(t, 1440, size=12, font=f), _tc(4099)) for t, f in raw]
    corrected = pt._correct_toggle_boundary_chunks(items)
    xs = [c[0]['x_decipoints'] for c in corrected]
    assert xs == [1440, 1440 + 72, 1440 + 72 + 7 * 72, 1440 + 72 + 8 * 72, 1440]
    deduped = pt._dedupe_double_strike_chunks(corrected)
    assert [c[0]['text'] for c in deduped] == ['3', 'Undrlin', '4', 'Bold']


def test_the_re_strike_pre_scan_never_fires_on_a_stale_x_chain_that_does_not_repeat():
    # SAWYER.WS's own 'D,B,A,C),' menu-tag chain, eight chunks at ONE raw
    # x: the last chunk's key matches nothing at the head of the run, so no
    # prefix repeats and nothing is marked. (The full pipeline assertion
    # lives in `test_toggle_boundary_before_double_strike_dedupe_...`; this
    # is the pre-scan's own half of it.)
    raw = [('D', 'Courier-Bold'), (',', 'Courier'), ('B', 'Courier-Bold'),
           (',', 'Courier'), ('A', 'Courier-Bold'), (',', 'Courier'),
           ('C', 'Courier-Bold'), ('),', 'Courier')]
    items = [(_pc(text, 1000, font=font), _tc()) for text, font in raw]
    corrected = pt._correct_toggle_boundary_chunks(items)
    xs = [c[0]['x_decipoints'] for c in corrected]
    assert len(set(xs)) == 8, 'every chunk must resolve to its own distinct x'
    assert xs == sorted(xs)


def test_a_repeat_needs_the_same_font_and_typeface_id_not_just_the_same_text():
    # The same letter in a DIFFERENT face is not a re-strike of anything:
    # the pre-scan keys on (text, font, size, typeface id), never text
    # alone, so this stays an ordinary toggle boundary and gets corrected
    # forward like any other.
    items = [(_pc('A', 1000, size=12, font='Courier-Bold'), _tc(4099)),
             (_pc('bc', 1000, size=12, font='Courier'), _tc(4099)),
             (_pc('A', 1000, size=12, font='Courier-Oblique'), _tc(4099))]
    corrected = pt._correct_toggle_boundary_chunks(items)
    xs = [c[0]['x_decipoints'] for c in corrected]
    assert xs == [1000, 1000 + 72, 1000 + 72 + 2 * 72]
    # ... and with the SAME face on both, it is a re-strike and lands back
    # on the first one.
    same = [(_pc('A', 1000, size=12, font='Courier-Bold'), _tc(4099)),
            (_pc('bc', 1000, size=12, font='Courier'), _tc(4099)),
            (_pc('A', 1000, size=12, font='Courier-Bold'), _tc(4099))]
    assert [c[0]['x_decipoints']
            for c in pt._correct_toggle_boundary_chunks(same)] == [1000, 1072, 1000]


# --------------------------------------- mechanism Z: same-side segmentation
# 2026-09-07, Jon's ruling from the real-LaserJet paper scan of -SCREEN
# (the private corpus's own verdicts.json doc87 p6): the WS7-side half of
# same-side character segmentation (fg.segment_words_from_chars/
# fg.char_space_width_pt) -- see tools/fidelity_gate.py's own
# engine_page_tokens tests for the engine-side half of these same four
# Tier-1 shapes (styled-span split inside a word, punctuation after a
# word, two words separated by exactly one space, superscript in a word).
def test_merge_zero_gap_cross_font_chunks_merges_across_a_font_change():
    # SAWYER.WS's own 'WSMSGS.OVR' (bold) + '.]' (plain) shape, at the
    # exact zero gap mechanism J's own correction resolves it to (its own
    # test above confirms this position). Neither mechanism C nor K ever
    # touch this (both require the SAME font on both sides) -- mechanism
    # Z is the general, font-agnostic case.
    end_dp = _natural_end_dp('WSMSGS.OVR', 1000, 'Courier-Bold', 24)
    items = [(_pc('WSMSGS.OVR', 1000, font='Courier-Bold'), _tc()),
             (_pc('.]', end_dp, font='Courier'), _tc())]
    merged = pt._merge_zero_gap_cross_font_chunks(items)
    assert len(merged) == 1
    assert merged[0][0]['text'] == 'WSMSGS.OVR.]'
    assert merged[0][0]['x_decipoints'] == 1000


def test_merge_zero_gap_cross_font_chunks_leaves_a_real_gap_unmerged():
    items = [(_pc('Hello', 1000), _tc()), (_pc('world', 1000 + 2000), _tc())]
    merged = pt._merge_zero_gap_cross_font_chunks(items)
    assert len(merged) == 2
    assert [m[0]['text'] for m in merged] == ['Hello', 'world']


def test_merge_zero_gap_cross_font_chunks_splits_at_exactly_one_space_width():
    # Tier 1: two words separated by exactly one space -- the boundary
    # case (gap == one space glyph's own width) must still split, not
    # merge (segment_words_from_chars' own `gap >= threshold` rule).
    end_dp = _natural_end_dp('Hello', 1000, 'Courier', 24)
    space_dp = round(pt.fg.char_space_width_pt('Courier', 24) * pt.fg.DECIPT_PER_PT)
    items = [(_pc('Hello', 1000), _tc()), (_pc('world', end_dp + space_dp), _tc())]
    merged = pt._merge_zero_gap_cross_font_chunks(items)
    assert len(merged) == 2
    assert [m[0]['text'] for m in merged] == ['Hello', 'world']


def test_merge_zero_gap_cross_font_chunks_leaves_a_same_position_overlay_untouched():
    # -SCREEN.WS/-README.WS's own "Strike-out" demo: a literal dash-
    # overlay chunk printed a SECOND time at the SAME position as the
    # word it strikes through (WS7's own double-strike-style rendering of
    # a strikethrough, not an exact-text double-strike mechanism D
    # already dedupes). x never advances for it -- it must never enter
    # the character stream at all, only pass through untouched.
    items = [(_pc('Strike-out', 1000), _tc()), (_pc('----------', 1000), _tc())]
    merged = pt._merge_zero_gap_cross_font_chunks(items)
    texts = [m[0]['text'] for m in merged]
    assert 'Strike-out' in texts
    assert '----------' in texts
    assert not any('S-t-r' in t for t in texts)


def test_find_offbaseline_occupant_matches_a_raised_footnote_marker():
    # A private WS4 paper's own real measured shape: a word ends at 216.0pt;
    # its footnote-reference '1' sits exactly there too, but 4.5pt ABOVE
    # the line's own baseline (WS7 really moves the pen for a super/
    # subscript character -- mechanism G).
    marker = _pc('1', 2160, size=9.25, font='Courier')
    marker['y_decipoints'] = 1275
    occ = pt._find_offbaseline_occupant([(marker, _tc())], 2160, 2359, 1320)
    assert occ is not None
    assert occ[0]['text'] == '1'


def test_find_offbaseline_occupant_never_absorbs_a_real_checkable_word():
    # A nearby off-baseline candidate that WOULD become its own checkable
    # token (long enough / has alnum content beyond mechanism Z's own
    # unreliable-to-align scope) must never be absorbed -- only a
    # fragment that could never independently align is fair game.
    word = _pc('Word', 2160, font='Courier')
    word['y_decipoints'] = 1275
    occ = pt._find_offbaseline_occupant([(word, _tc())], 2160, 3000, 1320)
    assert occ is None


def test_merge_zero_gap_cross_font_chunks_stitches_a_superscript_inside_a_word():
    # Tier 1: superscript in a word. A private WS4 paper's own real measured
    # numbers: a word (x=158.4pt, ends at 216.0pt) + a raised
    # footnote '1' (x=216.0pt, y 4.5pt above the line) + 'The' (the next
    # real word, x=235.9pt) -- the gap between the two words looks
    # too wide to merge on its own, but is fully explained by the marker
    # sitting inside it.
    word = _pc('Example.', 1584, font='Courier', size=12)
    word['y_decipoints'] = 1320
    nxt = _pc('The', 2359, font='Courier', size=12)
    nxt['y_decipoints'] = 1320
    marker = _pc('1', 2160, size=9.25, font='Courier')
    marker['y_decipoints'] = 1275
    items = [(word, _tc()), (nxt, _tc())]
    page_chunks = items + [(marker, _tc())]
    merged = pt._merge_zero_gap_cross_font_chunks(items, page_chunks)
    texts = [m[0]['text'] for m in merged]
    assert 'Example.1' in texts
    assert 'The' in texts


def test_merge_zero_gap_cross_font_chunks_stitches_a_subscript_inside_a_word():
    # Tier 1: -SCREEN.WS's own real measured 'H2O' shape -- 'H' and 'O'
    # on the same baseline, a lowered subscript '2' sitting exactly
    # between them on a different y.
    h = _pc('H', 1728, font='Courier', size=12)
    h['y_decipoints'] = 1680
    o = _pc('O', 1855, font='Courier', size=12)
    o['y_decipoints'] = 1680
    two = _pc('2', 1800, size=9.25, font='Courier')
    two['y_decipoints'] = 1725
    items = [(h, _tc()), (o, _tc())]
    page_chunks = items + [(two, _tc())]
    merged = pt._merge_zero_gap_cross_font_chunks(items, page_chunks)
    assert [m[0]['text'] for m in merged] == ['H2O']


def test_merge_zero_gap_cross_font_chunks_stitches_a_trailing_marker_at_line_end():
    # A real private-corpus regression: a footnote reference at the very END
    # of a printed line has no FOLLOWING same-baseline chunk to bound a
    # gap window against at all -- must still be found via the trailing
    # window search past the line's own last chunk.
    word = _pc('statement.', 4176, font='Courier', size=12)
    word['y_decipoints'] = 2520
    marker = _pc('2', 4896, size=9.25, font='Courier')
    marker['y_decipoints'] = 2475
    items = [(word, _tc())]
    page_chunks = items + [(marker, _tc())]
    merged = pt._merge_zero_gap_cross_font_chunks(items, page_chunks)
    assert merged[0][0]['text'] == 'statement.2'


def test_merge_zero_gap_cross_font_chunks_a_lone_offbaseline_marker_runs_no_search_of_its_own():
    # The real -SCREEN.WS regression: a baseline made ENTIRELY of a
    # fragment that would never become its own checkable token anyway
    # (e.g. a lone raised trademark 'TM' marker, its own by_y group) must
    # never run ITS OWN occupant search and wrongly absorb the FOLLOWING
    # real line's own punctuation.
    marker = _pc('TM', 1440, size=9.25, font='Courier')
    marker['y_decipoints'] = 2595
    comma = _pc(',', 1550, font='Courier', size=12)
    comma['y_decipoints'] = 2640
    items = [(marker, _tc())]
    page_chunks = items + [(comma, _tc())]
    merged = pt._merge_zero_gap_cross_font_chunks(items, page_chunks)
    assert merged[0][0]['text'] == 'TM'


def test_toggle_boundary_before_double_strike_dedupe_does_not_swallow_a_stale_x_chain():
    # SAWYER.WS's own 'D,B,A,C),' menu-tag list, the real regression that
    # moved mechanism J ahead of mechanism D (see J's own docstring):
    # FOUR separate literal commas, none of which ever got a real
    # repositioning command, all sharing one stale raw x=57.6pt along
    # with the four bold letters. Run in the SAME order load_ws7_tokens
    # itself uses (N, J, D, C, K, Z): J must resolve each comma to its
    # own real, distinct, cascading position BEFORE D ever looks at x,
    # so D finds no duplicates at all, and mechanism Z then merges the
    # whole, now-contiguous chain into one word.
    raw = [('D', 'Courier-Bold'), (',', 'Courier'), ('B', 'Courier-Bold'),
          (',', 'Courier'), ('A', 'Courier-Bold'), (',', 'Courier'),
          ('C', 'Courier-Bold'), ('),', 'Courier')]
    items = [(_pc(text, 1000, font=font), _tc()) for text, font in raw]
    items = pt._correct_toggle_boundary_chunks(items)      # mechanism J
    items = pt._dedupe_double_strike_chunks(items)         # mechanism D
    assert len(items) == 8, 'mechanism D must not drop any of these 8 chunks'
    items = pt._merge_kerning_split_chunks(items)          # mechanism C
    items = pt._merge_trailing_punctuation_chunks(items)   # mechanism K
    merged = pt._merge_zero_gap_cross_font_chunks(items)   # mechanism Z
    assert len(merged) == 1
    assert merged[0][0]['text'] == 'D,B,A,C),'


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


# --------------------------- mechanism P-SPLIT: split-word reconcile (#270/41)
def _ws7_frag(text, x, tier='univers', page=1, y_top=114.0, line_start_x=57.6):
    return {'text': text, 'page': page, 'y_top': y_top, 'x': x, 'tier': tier,
            'dist_into_line_pt': round(x - line_start_x, 3)}


def _eng_whole(text, x, basefont='Helvetica-Bold', size=18, page=1, y_top=114.0):
    return {'text': text, 'page': page, 'y_top': y_top, 'x': x,
            'basefont': basefont, 'size': size, 'font_class': 'sans'}


def test_a_word_ws7_split_in_two_reconciles_against_the_engines_own_word():
    # PRINT.TST's own title, real numbers from the v4 capture: WS7 sends
    # 'PRINT' at 94.8pt and '.TST' at 143.7pt under ONE font-selection
    # command; the engine draws 'PRINT.TST' at 93.5pt.
    unmatched_ws7 = [_ws7_frag('PRINT', 94.8), _ws7_frag('.TST', 143.7)]
    unmatched_engine = [_eng_whole('PRINT.TST', 93.5)]
    new_ws7, new_eng = pt._reconcile_split_ws7_chunks(unmatched_ws7, unmatched_engine)
    assert new_ws7 == []
    assert new_eng == []


def test_a_split_point_the_engine_puts_a_whole_column_away_is_not_reconciled():
    # REF/FONT-TAG.CMP's own shape, inverted onto this side so the bar is
    # visible: fixed-pitch Courier, where EXACT_EPS_PT (0.2pt) governs.
    # One 7.2pt Courier cell of disagreement about where the second
    # fragment starts is a real placement divergence, never a segmentation
    # artefact, and must stay reported.
    unmatched_ws7 = [_ws7_frag('#:', 259.2, tier='exact', line_start_x=230.4),
                    _ws7_frag('Usage:', 280.8, tier='exact', line_start_x=230.4)]
    unmatched_engine = [_eng_whole('#:Usage:', 259.2, basefont='Courier', size=12)]
    new_ws7, new_eng = pt._reconcile_split_ws7_chunks(unmatched_ws7, unmatched_engine)
    assert new_ws7 == unmatched_ws7
    assert new_eng == unmatched_engine


def test_two_genuinely_separate_ws7_words_are_never_fused_into_one():
    # 'Zapf' + 'Chancery' (PSSAMPLE.WS) and 'Helv' + 'Narrow' (PS-FONTS.REF)
    # ALSO measure as backward steps under a substituted face -- which is
    # why geometry alone cannot decide this. The engine has no single word
    # 'ZapfChancery', so nothing reconciles.
    unmatched_ws7 = [_ws7_frag('Zapf', 100.0), _ws7_frag('Chancery', 138.0)]
    unmatched_engine = [_eng_whole('Zapf', 100.0), _eng_whole('Chancery', 142.0)]
    new_ws7, new_eng = pt._reconcile_split_ws7_chunks(unmatched_ws7, unmatched_engine)
    assert new_ws7 == unmatched_ws7
    assert new_eng == unmatched_engine


def test_a_split_run_never_crosses_a_baseline_or_a_page():
    # A coincidental text match on another line or another page is not a
    # split word -- same law mechanism P's own page check states.
    unmatched_ws7 = [_ws7_frag('PRINT', 94.8), _ws7_frag('.TST', 143.7, y_top=126.0)]
    unmatched_engine = [_eng_whole('PRINT.TST', 93.5)]
    assert pt._reconcile_split_ws7_chunks(unmatched_ws7, unmatched_engine) == (
        unmatched_ws7, unmatched_engine)
    other_page = [_ws7_frag('PRINT', 94.8, page=2), _ws7_frag('.TST', 143.7, page=2)]
    assert pt._reconcile_split_ws7_chunks(other_page, unmatched_engine) == (
        other_page, unmatched_engine)


def test_a_split_run_only_consumes_each_fragment_once():
    unmatched_ws7 = [_ws7_frag('LJ6DTP', 50.4, line_start_x=50.4),
                    _ws7_frag('.DOC', 91.4, line_start_x=50.4),
                    _ws7_frag('LJ6DTP', 50.4, y_top=128.0, line_start_x=50.4),
                    _ws7_frag('.PDF', 91.4, y_top=128.0, line_start_x=50.4)]
    unmatched_engine = [_eng_whole('LJ6DTP.DOC', 50.4, size=12),
                       _eng_whole('LJ6DTP.PDF', 50.4, y_top=128.0, size=12)]
    new_ws7, new_eng = pt._reconcile_split_ws7_chunks(unmatched_ws7, unmatched_engine)
    assert new_ws7 == []
    assert new_eng == []


def test_a_single_ws7_fragment_is_never_a_split():
    # One WS7 token whose text simply IS the engine word is a 1:1 match
    # fg.match_doc should have made (or a real position divergence) --
    # never this mechanism's business.
    unmatched_ws7 = [_ws7_frag('PRINT.TST', 94.8)]
    unmatched_engine = [_eng_whole('PRINT.TST', 93.5)]
    assert pt._reconcile_split_ws7_chunks(unmatched_ws7, unmatched_engine) == (
        unmatched_ws7, unmatched_engine)


# --------------------------------------------- per-page calibration (#235)
def _cal_item(is_line_start, tier, dx=0.0, dy=0.0):
    """One (ws7_token, engine_token, delta) triple, minimal enough for
    _page_calibration_items -- it only reads w['is_line_start']/w['tier']
    and the delta's own dx/dy."""
    w = {'is_line_start': is_line_start, 'tier': tier}
    e = {}
    d = {'dx': dx, 'dy': dy, 'same_page': True}
    return (w, e, d)


def test_page_calibration_prefers_line_start_fixed_pitch_words():
    # planning #235: a page dominated by contaminated (mid-line,
    # font-substitution) words must not drag the calibration off the
    # genuinely-correct line-start Courier words' own dx/dy.
    items = [
        _cal_item(True, pt.TIER_EXACT, dx=0.0, dy=0.0),
        _cal_item(True, pt.TIER_EXACT, dx=0.0, dy=0.0),
        _cal_item(False, pt.TIER_CGTIMES, dx=500.0, dy=500.0),
        _cal_item(False, pt.TIER_CGTIMES, dx=520.0, dy=520.0),
        _cal_item(False, pt.TIER_CGTIMES, dx=540.0, dy=540.0),
    ]
    chosen = pt._page_calibration_items(items)
    assert chosen == items[:2]


def test_page_calibration_falls_back_to_any_line_start_word():
    # No fixed-pitch line-start word on this page (e.g. an all-proportional
    # document) -- fall back to line-start words of any tier rather than
    # letting mid-line words calibrate the page.
    items = [
        _cal_item(True, pt.TIER_CGTIMES, dx=1.0, dy=1.0),
        _cal_item(False, pt.TIER_CGTIMES, dx=500.0, dy=500.0),
    ]
    chosen = pt._page_calibration_items(items)
    assert chosen == items[:1]


def test_page_calibration_falls_back_to_all_words_when_no_line_start_matched():
    # Degenerate case: nothing on the page matched as a line-start word at
    # all (e.g. every line-start token happened to land in unmatched_ws7/
    # unmatched_engine instead) -- must not return an empty calibration
    # set (frame_offset([]) reports n=0/median=None, silently disabling
    # every check on the page); fall back to the pre-#235 behavior.
    items = [
        _cal_item(False, pt.TIER_CGTIMES, dx=1.0, dy=1.0),
        _cal_item(False, pt.TIER_UNIVERS, dx=2.0, dy=2.0),
    ]
    chosen = pt._page_calibration_items(items)
    assert chosen == items


def test_page_calibration_rtf_wrap_probes_no_longer_contaminate_line_starts():
    """End-to-end regression for the four documents planning #235 named
    (sawyer/RTF-RJS/1-SINGLE.WS, 1-5LINES.WS, 2-DOUBLE.WS, REF/FONTS.REF):
    a page shaped like their own failure -- a handful of correct
    line-start Courier words, then many mid-line words all displaced by
    the SAME large constant (an unbroken RTF/markup token wrapping
    differently on each side, or accumulated proportional-width drift) --
    must calibrate from the correct words, not the contaminated majority,
    so the line-start words measure clean (resid_dx == 0) while the real
    mid-line divergence still surfaces on its own words."""
    items = [
        _cal_item(True, pt.TIER_EXACT, dx=0.0, dy=0.0),
        _cal_item(True, pt.TIER_EXACT, dx=0.0, dy=0.0),
        _cal_item(True, pt.TIER_EXACT, dx=0.0, dy=0.0),
    ] + [_cal_item(False, pt.TIER_CGTIMES, dx=450.0, dy=0.0) for _ in range(20)]
    chosen = pt._page_calibration_items(items)
    offset = pt.fg.frame_offset([d for (_, _, d) in chosen])
    assert offset['median_dx'] == 0.0
    # the line-start words themselves now measure a zero residual...
    for w, e, d in chosen:
        assert d['dx'] - offset['median_dx'] == 0.0
    # ...while the contaminated mid-line words' own residual is untouched
    # (still real, still reportable) -- calibration doesn't erase them.
    contaminated = [it for it in items if it not in chosen]
    for w, e, d in contaminated:
        assert d['dx'] - offset['median_dx'] == 450.0


# ------------------------------------------------ the v4 exclusion classes
def test_the_four_printer_font_charts_are_excluded_as_font_chart():
    """planning #270 item 28, Jon's ruling 2026-09-13 ("Let's move them to
    the LJ6DTP category. Exclude them from tests for now... I'd rather
    support user's actual WordStar files, not font charts.").

    Robert J. Sawyer's four printer-font CHARACTER SUBSTITUTION CHARTS --
    REF/SYMBOL.CHT, REF/WINGDING.CHT, PRINTERS/fontcrib.ws and PRINTER.PS
    (whose byte-identical duplicate PRINTERS/FONTCRIB.PS was already an
    excluded 'duplicate') -- leave the pcl tier as their own named class.
    Each prints every character CODE of a printer-RESIDENT font we do not
    have; the residual is the chart's subject matter, not a placement bug
    (triage cause 8 / Q2). Parked with LJ6DTP on planning #210, so this
    opens no new issue -- and the class name is asserted here, not just
    the membership, because the reason string is what the tier prints for
    each of them on every run."""
    charts = {
        'sawyer__REF__SYMBOL_EXT_CHT',
        'sawyer__REF__WINGDING_EXT_CHT',
        'sawyer__PRINTERS__fontcrib_EXT_ws',
        'sawyer__PRINTER_EXT_PS',
    }
    for doc in charts:
        assert doc in pt.CAPTURED_DOCS, f'{doc} must still be collected by name'
        assert doc in pt.EXCLUDED_V4, f'{doc} must be excluded from the pcl tier'
        assert pt.EXCLUDED_V4[doc].startswith('font-chart: '), pt.EXCLUDED_V4[doc]
        assert 'planning #210' in pt.EXCLUDED_V4[doc]
    # exactly four -- a fifth document joining this class is a real ruling,
    # not a drive-by edit
    font_charts = {d for d, r in pt.EXCLUDED_V4.items() if r.startswith('font-chart: ')}
    assert font_charts == charts


def test_lsrbox_is_parked_with_lj6dtp_and_loses_no_sole_coverage():
    """planning #270 item 38, Jon's ruling 2026-09-13 ("Defer. Remove it
    from testing (unless it's an example of something we don't have any
    other test for). Add it to the LJ6DTP category.").

    `sawyer/LSRBOX/LSRBOX.WS` leaves the pcl tier as 'parked-lj6dtp'. The
    ruling's own "unless" clause is what this test really guards: every
    mechanism LSRBOX.WS is the corpus's SOLE carrier of has its own
    SYNTHETIC tier-1 fixture, named here so that deleting one of them
    while LSRBOX is parked fails loudly instead of silently ending the
    mechanism's only remaining cover."""
    doc = 'sawyer__LSRBOX__LSRBOX_EXT_WS'
    assert doc in pt.CAPTURED_DOCS, 'must still be collected and skipped BY NAME'
    assert doc in pt.EXCLUDED_V4
    reason = pt.EXCLUDED_V4[doc]
    assert reason.startswith('parked-lj6dtp: ')
    assert 'planning #210' in reason
    # the reference rendering is recorded, and recorded as what it IS --
    # a real PDF, not the WordStar Printer Definition File a 1990s `.PDF`
    # otherwise always is in this corpus
    assert 'LSRBOX.PDF' in reason
    assert 'not a WordStar Printer Definition File' in reason
    # the sole-carrier fixtures, by name and by file
    import importlib.util
    import pathlib
    here = pathlib.Path(__file__).parent
    covers = {
        'test_pcl_v4_column_geometry.py': [
            'test_a_print_controls_display_string_never_reaches_a_running_head',
            'test_a_running_heads_print_control_draws_its_own_rectangles',
            'test_a_fill_with_an_omitted_value_is_solid_black',
            'test_f_a_column_break_terminator_is_not_an_overprint',
            'test_f_a_column_breaks_last_line_pays_its_lead',
        ],
        'test_justification.py': [
            'test_last_line_of_justified_paragraph_is_not_stretched',
        ],
    }
    for filename, names in covers.items():
        src = (here / filename).read_text()
        for name in names:
            assert f'def {name}(' in src, (
                f'{name} is LSRBOX.WS mechanism coverage and LSRBOX.WS is '
                f'parked out of the pcl tier -- {filename} must keep it')


# -------------------------------------------- the printer's right ceiling
def test_a_saturated_ws7_x_and_an_off_paper_engine_x_are_a_match():
    """planning #270 item 27 / triage Q1, Jon's ruling 2026-09-13 ("We
    shouldn't 'correct' it in Native or Printed. It's 'corrected' in
    Modern.").

    WordStar prints the start of an over-long line and then stops moving
    right: the LaserJet's horizontal position counter saturates and the
    capture reports every later word at exactly 9999 decipoints
    (999.9pt). Our engine keeps counting and reports the word's true x.
    Both are far off the right edge of an 8.5x11in sheet, so NEITHER
    deposits ink and the printed result is identical -- a match. Real
    numbers, `REF/MACBOOK.AIR` page 1: WS7 999.9 against engine 1015.2,
    1051.2, 1080.0 and 1166.4."""
    letter = pt.sheet_right_edge_pt({'page_size_in': [8.5, 11.0]})
    assert letter == 792.0   # the WIDEST side, so either orientation is covered
    for engine_x in (1015.2, 1051.2, 1080.0, 1166.4):
        assert pt.both_words_are_off_the_paper(999.9, engine_x, letter)


def test_an_engine_word_still_on_the_paper_is_never_scored_a_match():
    """The other half of the same ruling: "when the on-paper ink is
    identical". A saturated WS7 word against an engine word that is still
    ON the sheet is a REAL divergence -- one side prints something, the
    other prints nothing -- and must stay reported. This is what keeps the
    three `RTF-RJS` documents' own line-start findings (engine x = 0.0,
    the left margin, against a saturated WS7 x) visible."""
    letter = pt.sheet_right_edge_pt({'page_size_in': [8.5, 11.0]})
    for engine_x in (0.0, 57.6, 300.0, 611.0, 791.9):
        assert not pt.both_words_are_off_the_paper(999.9, engine_x, letter)


def test_a_ws7_x_short_of_the_ceiling_is_a_real_measurement():
    """A WS7 word at 990pt is not saturated -- it is where the printer
    actually put it -- so the guard must not fire, however far off the
    sheet it is. Only the ceiling value itself means "we cannot know"."""
    letter = pt.sheet_right_edge_pt({'page_size_in': [8.5, 11.0]})
    assert pt.PCL_X_CEILING_PT == 999.9
    assert not pt.both_words_are_off_the_paper(990.0, 1200.0, letter)
    assert not pt.both_words_are_off_the_paper(999.8, 1200.0, letter)
    assert pt.both_words_are_off_the_paper(999.9, 1200.0, letter)


def test_the_guard_refuses_a_sheet_as_wide_as_the_ceiling():
    """The claim "the WS7 word is off the paper too" is CHECKED per
    document, never assumed: on a hypothetical sheet at least as wide as
    the ceiling, a word at 999.9pt could still be on the paper, so the
    guard declines rather than silently scoring a match. Same for a
    capture that records no page size at all."""
    assert not pt.both_words_are_off_the_paper(999.9, 1200.0, 1000.0)
    assert not pt.both_words_are_off_the_paper(999.9, 1200.0, None)
    assert pt.sheet_right_edge_pt({}) is None
    assert pt.sheet_right_edge_pt(None) is None
