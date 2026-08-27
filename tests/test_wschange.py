"""wschange: the WSCHANGE .PAT interpreter -- format-corner tests against
synthetic bytes.

The known-answer gauntlet checked against the real Sawyer-archive dumps
(PRISTINE.PAT, DEFAULT.PAT, and the other named .PAT fixtures) was Jon's
private-corpus tier (tier 3) and has been relocated out of this public repo
entirely -- see the private test suite in the companion repo, which runs
these same interpreter functions against that archive from outside ctrl-kd.
"""
import pytest

from ctrlkd.wschange import parse_pat, page_settings, ruler_tabs


# ---------------------------------------------------------- format corners
# Synthetic bytes only.

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
