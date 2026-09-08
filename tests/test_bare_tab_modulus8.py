"""planning #202 batch (issue "bare tab byte (0x09) renders zero-width
instead of advancing to the next tab stop"): WS7's own file-format
reference (WSFORMAT.WS control-code table, byte 09h ^I) states the rule
in one sentence -- "At print time the number of hard spaces required to
reach a modulus 8 print position is generated" -- and this repo rendered
a bare 0x09 with ZERO width, gluing the word before it to the word after
(sawyer/REF/wordstar-file-format.ws: "^@" + 0x09 + "Fix" rendered as one
run "^@Fix", no gap at all).

VERIFIED against WS7's own real LaserJet PCL capture
(ws7-prints/v4/sawyer__REF__wordstar-file-format_EXT_ws.pcl): the line
"00h ^@<TAB>Fix the print position." -- 6 characters ("00h ^@") before
the tab -- places "Fix" at exactly column 8 from the line's own margin
(WS7 x=115.2pt on a 57.6pt margin = 8 Courier columns of 7.2pt each),
the modulus-8 stop this fix computes. Fixing it turned this document's
exact-drift count from 248 to 0 (tests/pcl_fidelity_manifest.json,
planning #202 batch commit).

`core._decode_spans` is exercised directly, the same way several other
tests in this file's neighbourhood do (test_ctrlkd.py, test_polarity_
gate.py) -- it is the one function that owns this expansion (see its own
0x09 branch and the `col` tracking above it), and reaching it through the
full WS5+ symmetric-block binary format would test far more machinery
than this fix touches. `core.parse_ws` is used too, for a plain
print-stream document, to confirm the fix is reachable through the public
parse entry point and not just the private helper.
"""
from ctrlkd import core


def _spans_text(raw: bytes) -> str:
    spans = core._decode_spans(raw, False, 'cp437', set(), {})
    return ''.join(s.text for s in spans)


def test_bare_tab_after_six_columns_reaches_the_next_modulus_8_stop():
    """The exact WS7-verified case: 6 characters before the tab ("00h ^@"),
    landing on column 8 -- 2 hard spaces, not zero."""
    text = _spans_text(b'00h ^@\tFix')
    assert text == '00h ^@  Fix', repr(text)


def test_bare_tab_at_line_start_expands_to_a_full_stop():
    """A tab at column 0 is still "not yet at a stop" by the standard tab
    convention (a tab always advances at least one column) -- it must
    reach column 8, a full 8 hard spaces, not 0."""
    text = _spans_text(b'\tWord')
    assert text == ' ' * 8 + 'Word', repr(text)


def test_bare_tab_exactly_on_a_stop_still_advances_a_full_8():
    """8 characters before the tab -- already sitting on a modulus-8
    print position. WordStar's own rule ("hard spaces required to REACH
    a modulus 8 position") still means the next one, not zero -- the
    standard tab convention, and the only reading consistent with the
    line-start case above."""
    text = _spans_text(b'12345678\tWord')
    assert text == '12345678' + ' ' * 8 + 'Word', repr(text)


def test_bare_tab_column_count_resets_at_the_next_physical_line():
    """`_decode_spans` is called once per physical (CRLF-delimited)
    source line -- the column count must not carry over from a previous
    call, or a short second line would land on the wrong stop."""
    text = _spans_text(b'\tWord')
    assert text == ' ' * 8 + 'Word'
    # A second, independent call (simulating the next physical line)
    # starts fresh at column 0 again, not wherever the first call ended.
    text2 = _spans_text(b'ab\tWord')
    assert text2 == 'ab' + ' ' * 6 + 'Word', repr(text2)


def test_bare_tab_reachable_through_parse_ws_public_entry_point():
    """Not just the private helper -- a real (print-stream-detected)
    document carrying a bare 0x09 expands it the same way through the
    public parse_ws() entry point."""
    doc = core.parse_ws(b'From: \tWordStar\r\n')
    text = ''.join(sp.text for blk in doc.blocks
                   for ln in getattr(blk, 'lines', [])
                   for sp in ln.spans)
    assert text == 'From:   WordStar', repr(text)


def test_a_tb_ruler_type9_tab_block_is_unaffected():
    """core.py's own note (the 0x09 branch's neighbour): 46 archive files
    use `.tb` and ZERO contain a bare 0x09 -- the two mechanisms never
    coexist, and a type-9 tab block's own padding bytes never reach the
    bare-0x09 branch at all: `pending_tab` drains BEFORE the per-byte
    dispatch loop ever sees the offset the block starts at (see
    `_decode_spans`'s own comment on why it drains last among the mark
    queues, but still strictly before the fallback byte-by-byte path),
    consuming `cols` bytes and tagging the result 'tabhmi<N>' rather than
    falling into the `elif b == 0x09` branch this fix changed."""
    raw = b'Word' + b'  ' + b'Next'      # the block's own 2 padding bytes
    tab_at = [(4, 720, (0x20,), 2)]      # (rel_offset, hmi, leader, cols)
    spans = core._decode_spans(raw, False, 'cp437', set(), {},
                               tab_target_at=tab_at)
    text = ''.join(s.text for s in spans)
    assert text == 'Word  Next', repr(text)
    tagged = [s for s in spans if any(t.startswith('tabhmi') for t in s.styles)]
    assert len(tagged) == 1, 'the padding must route through the tabhmi tag, not the bare-0x09 branch'
