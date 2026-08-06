"""wschange: the WSCHANGE .PAT interpreter, checked against the real
Sawyer-archive dumps -- a known-answer gauntlet, because the cli.py page
presets ('default' = factory, 'sawyer') were HAND-derived from these very
bytes (INIEDT-full-decode.md); the interpreter must reproduce conclusions
already trusted, not merely run without crashing.

The archive fixtures live outside the repo (same pattern as
test_ctrlkd.py's _real_fixture tests); every test that reads them skips
when the path is absent. Their contents are never copied here, and the
path appears only in the one constant below.
"""
import os
import pytest

from ctrlkd.wschange import parse_pat, page_settings, ruler_tabs

# The ONE place the archive path lives (private-local; keep it a single
# constant for future scrubbing).
import os
# private corpus path via environment only (standing rule); unset -> skip
_ARCHIVE = os.environ.get('CTRLKD_PRIVATE_CORPUS', '').rstrip('/') + '/WS' \
    if os.environ.get('CTRLKD_PRIVATE_CORPUS') else ''


def _pat(name):
    p = os.path.join(_ARCHIVE, name + '.PAT')
    if not os.path.exists(p):
        pytest.skip(f'{name}.PAT archive fixture not present')
    return open(p, 'rb').read()


# ---------------------------------------------------------- known answers

def test_pristine_reproduces_the_factory_page():
    """PRISTINE.PAT is the unmodified factory dump: page_settings must
    land on WordStar's own documented defaults -- .mt 3 lines (0.5in),
    .mb 8 lines (1.33in), .po 0.8in = 8.0 columns, .pl 66 lines,
    .hm/.fm 2 lines, .lh 8/48in -- i.e. exactly what an EMPTY settings
    dict means to effective_page ('default' preset = {})."""
    page = page_settings(parse_pat(_pat('PRISTINE')))
    assert page['mt_lines'] == pytest.approx(3.0, abs=1e-6)
    assert page['mb_lines'] == pytest.approx(8.0, abs=1e-6)
    assert page['po_cols'] == pytest.approx(8.0, abs=1e-6)
    assert page['pl_lines'] == pytest.approx(66.0, abs=1e-6)
    assert page['hm_lines'] == pytest.approx(2.0, abs=1e-6)
    assert page['fm_lines'] == pytest.approx(2.0, abs=1e-6)
    assert page['lh_48'] == pytest.approx(8.0, abs=1e-6)


def test_default_reproduces_the_sawyer_preset():
    """DEFAULT.PAT is Sawyer's machine: the geometry must equal cli.py's
    'sawyer' preset (mt 1195/1440in*6, mb 6 lines, po 7 columns -- those
    literals ARE the preset; PAGE_PRESETS is local to cli.main so the
    values are restated here rather than imported). Everything the preset
    leaves alone must still read factory."""
    page = page_settings(parse_pat(_pat('DEFAULT')))
    assert page['mt_lines'] == pytest.approx(1195 / 1440 * 6, abs=1e-6)
    assert page['mb_lines'] == pytest.approx(6.0, abs=1e-6)
    assert page['po_cols'] == pytest.approx(7.0, abs=1e-6)
    # unchanged-from-factory fields (decode doc: only mt/mb/po differ)
    assert page['pl_lines'] == pytest.approx(66.0, abs=1e-6)
    assert page['hm_lines'] == pytest.approx(2.0, abs=1e-6)
    assert page['fm_lines'] == pytest.approx(2.0, abs=1e-6)
    assert page['lh_48'] == pytest.approx(8.0, abs=1e-6)


def test_full_dumps_share_one_label_set():
    """Both full dumps carry 294 label LINES -- but UDATE appears twice
    (lines 1 and 559, identical bytes: WSCHANGE stamps the dump date at
    both ends), so the decode doc's '294 labels' is 293 unique names in
    the mapping. Asserting the TRUE parsed count, per the brief."""
    pri = parse_pat(_pat('PRISTINE'))
    saw = parse_pat(_pat('DEFAULT'))
    assert set(pri) == set(saw)
    assert len(pri) == len(saw) == 293
    # struct sizes the decode doc derives from PATCH.LST (INISIZ = 68;
    # ten 74-byte .RR records + 1 reserved = 741)
    for pat in (pri, saw):
        assert len(pat['INIEDT']) == 68
        assert len(pat['RLRINI']) == 741


# Grep-estimates in the brief were PATHS 55, NOTYPE 25, ALL 3; the TRUE
# parsed label counts differ for those three because the estimates counted
# continuation lines as labels (PATHS: 40 labels + path continuations;
# NOTYPE: UDATE + one NOTYPE block whose 23 quoted ="XXX" lines are all
# continuations; ALL: UDATE + one two-line INIFIN). Asserting reality.
@pytest.mark.parametrize('name,labels', [
    ('WSMIN', 4), ('VCOLOR', 1), ('PATHS', 40), ('NOTYPE', 2), ('ALL', 2),
])
def test_partial_patch_sets_parse_with_true_counts(name, labels):
    pat = parse_pat(_pat(name))
    assert len(pat) == labels


def test_partials_are_subsets_of_the_full_dump():
    """Subset semantics: a partial patch set is a mapping of only the
    labels it names -- every one of which exists in the full dump's 293."""
    full = set(parse_pat(_pat('PRISTINE')))
    for name in ('WSMIN', 'VCOLOR', 'PATHS', 'NOTYPE', 'ALL'):
        assert set(parse_pat(_pat(name))) <= full, name


def test_partial_without_iniedt_says_nothing_about_the_page():
    """WSMIN.PAT carries no INIEDT: the machine layer must contribute NO
    page overrides, not factory values -- {} is 'this dump is silent',
    which is not the same claim as 'this dump says factory'."""
    assert page_settings(parse_pat(_pat('WSMIN'))) == {}


def test_notype_quoted_strings_reassemble():
    """NOTYPE.PAT is the corpus's only use of quoted-string items: one
    block of 23 three-char extension strings plus a 0x00 terminator,
    wrapped one string per continuation line. The known answer for the
    quoted path: 70 bytes, first and last extensions where they belong."""
    pat = parse_pat(_pat('NOTYPE'))
    block = pat['NOTYPE']
    assert len(block) == 70
    assert block.startswith(b"'''")
    assert block.endswith(b'XLS\x00')


def test_ruler_tabs_reproduce_the_factory_ruler():
    """.RR 0 in BOTH dumps (byte-identical per the decode doc -- Sawyer
    never touched his ruler): 11 stops every 900 HMI = every 5 columns."""
    want = [5.0 * i for i in range(1, 12)]
    for name in ('PRISTINE', 'DEFAULT'):
        tabs = ruler_tabs(parse_pat(_pat(name)))
        assert tabs == pytest.approx(want, abs=1e-6), name


# ---------------------------------------------------------- format corners
# Synthetic bytes -- no archive needed below this line.

def test_continuation_lines_reassemble_in_order():
    pat = parse_pat(b'ABC=01,02\r\n=03,04\r\n=05\r\nDEF=FF\r\n')
    assert pat == {'ABC': b'\x01\x02\x03\x04\x05', 'DEF': b'\xff'}


def test_lf_only_trailing_whitespace_and_blank_lines():
    pat = parse_pat(b'ABC=01,02  \n\n=03\t\nDEF=0A \n')
    assert pat == {'ABC': b'\x01\x02\x03', 'DEF': b'\x0a'}


def test_empty_continuation_and_trailing_comma():
    # The real full dumps end PRNID with a bare '=' line; tolerate both
    # that and a trailing comma without inventing a byte for either.
    pat = parse_pat(b'ABC=01,\r\n=\r\n=02\r\n')
    assert pat == {'ABC': b'\x01\x02'}


def test_ctrl_z_padding_is_discarded():
    pat = parse_pat(b'ABC=41\r\n\x1a\x1a\x1a\x1a')
    assert pat == {'ABC': b'A'}


def test_quoted_items_mix_with_hex_and_keep_commas():
    # No corpus string contains a comma, but splitting inside quotes
    # would be silent corruption, so the tokenizer honours them anyway.
    pat = parse_pat(b'X=01,"A,B",02\r\n')
    assert pat == {'X': b'\x01A,B\x02'}


def test_repeated_label_restarts_last_wins():
    # The real dumps repeat UDATE (identical bytes); a repeat RESTARTS
    # the value rather than appending, matching re-apply semantics.
    pat = parse_pat(b'UDATE=01\r\nOTHER=02\r\nUDATE=03\r\n')
    assert pat == {'UDATE': b'\x03', 'OTHER': b'\x02'}


def test_malformed_lines_raise_rather_than_guess():
    with pytest.raises(ValueError):
        parse_pat(b'no equals sign here\r\n')
    with pytest.raises(ValueError):
        parse_pat(b'ABC=GG\r\n')            # not hex
    with pytest.raises(ValueError):
        parse_pat(b'ABC=123\r\n')           # 3 digits: not a byte pair
    with pytest.raises(ValueError):
        parse_pat(b'=01\r\n')               # continuation before any label


def test_missing_blocks_yield_empty_interpretations():
    assert page_settings({}) == {}
    assert ruler_tabs({}) == []
    assert ruler_tabs({'RLRINI': b'\x00' * 10}) == []   # short record


def test_truncated_iniedt_yields_only_the_fields_it_carries():
    # 0x16 bytes covers mt (rel 0x14, LE16) and nothing after it: a
    # damaged dump reports what it has instead of guessing the rest.
    ie = bytearray(0x16)
    ie[0x14:0x16] = (720).to_bytes(2, 'little')
    page = page_settings({'INIEDT': bytes(ie)})
    assert page == {'mt_lines': pytest.approx(3.0)}
