"""planning #202 batch (issue "bare tab byte (0x09) renders zero-width
instead of advancing to the next tab stop") AND planning #244 (the
round-trip gauntlet fix that moved the expansion out of `_decode_spans`).

WS7's own file-format reference (WSFORMAT.WS control-code table, byte 09h
^I) states the rule in one sentence -- "At print time the number of hard
spaces required to reach a modulus 8 print position is generated" -- and
this repo once rendered a bare 0x09 with ZERO width, gluing the word
before it to the word after (sawyer/REF/wordstar-file-format.ws: "^@" +
0x09 + "Fix" rendered as one run "^@Fix", no gap at all).

VERIFIED against WS7's own real LaserJet PCL capture
(ws7-prints/v4/sawyer__REF__wordstar-file-format_EXT_ws.pcl): the line
"00h ^@<TAB>Fix the print position." -- 6 characters ("00h ^@") before
the tab -- places "Fix" at exactly column 8 from the line's own margin
(WS7 x=115.2pt on a 57.6pt margin = 8 Courier columns of 7.2pt each),
the modulus-8 stop this fix computes.

THE SPLIT (planning #244, 2026-09-08): the FIRST fix (planning #202
batch) baked this expansion into `_decode_spans` at PARSE time, which
turned every computed space into something byte-indistinguishable from a
space the author actually typed -- `ctrlkd.writer`'s round-trip
(tools/roundtrip_census.py, tests/test_writer.py's own private-repo
gauntlet) re-emitted spaces instead of the source file's own 0x09 byte
and never reproduced sawyer/MACROS/HOLYMAC/-HOLYMAC.WS, sawyer/REF/
WINDOWS7.WS, or sawyer/REF/wordstar-file-format.ws (found 2026-09-08 by
the census, then confirmed against sr's own Swift port). `_decode_spans`
now keeps the literal 0x09 byte again (its pre-#237 form -- the document
model IS the source bytes, unexpanded); `pdf._expand_bare_tabs_for_
printed_layout` applies the SAME modulus-8 rule instead, at PRINTED-mode
render time only, on a transient copy of the segment text that never
touches the stored Span. Every OTHER mode (text, markdown, html, rtf,
and Modern PDF) sees the bare, un-expanded tab byte now -- exactly their
own pre-#237 behavior, since #237's own evidence (the WS7 LaserJet PCL
capture above) was Printed-PDF-only despite living in a function every
mode shared.

THE TWO OTHER FIXED-PITCH SURFACES (planning #264 item 1, packet row B3,
2026-09-12). Printed RTF and the fixed-pitch HTML block reproduce the same
physical line in the same monospaced face the Printed PDF does, so the same
question has the same answer there: a column IS a character and expanding
the tab to spaces is exact. They were emitting the raw byte instead --
measured on sawyer/REF/wordstar-file-format.ws, 62 surviving tabs in each
RTF and 103-107 in each HTML, where a browser usually collapses the tab to
a single space. Both now call `core.expand_bare_tabs_texts`, where the rule
moved so that one function answers for all three surfaces. MODERN IS
DELIBERATELY EXCLUDED (the packet's own "not for Modern"): a reflowed
proportional document has no print columns for a tab to land on. Text and
Markdown keep the raw byte in both modes -- unchanged, and not part of this
row.
"""
import re
import zlib

from ctrlkd import core, pdf

HARD = b'\r\n'


def _decoded_streams(pdf_bytes):
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', pdf_bytes, re.S):
        body = m[1]
        try:
            out.append(zlib.decompress(body))
        except zlib.error:
            out.append(body)
    return out


def _word_x(pdf_bytes, word):
    """The Td x immediately preceding `(word) Tj` in ANY decoded content
    stream, or None if the word never appears as its own Tj operand --
    copied from test_justification.py's own helper, this module's
    neighbour, per test_ctrlkd.py's own "copy, don't import" guidance."""
    needle = word.encode()
    pat = re.compile(rb'([\d.]+) [\d.]+ Td \(' + re.escape(needle) + rb'\) Tj')
    for stream in _decoded_streams(pdf_bytes):
        m = pat.search(stream)
        if m:
            return float(m[1])
    return None


def _drawn_line(pdf_bytes, contains):
    """The full Tj operand string of the first drawn text object CONTAINING
    `contains`, or None. A plain, single-styled fixed-pitch printed line
    draws as ONE whole-line Tj (this file's own bare-tab lines included --
    no styled span to split it, same as any other unjustified single-span
    line, see test_justification.py's `ojOffIsUnaffected` for the sibling
    finding) -- `_word_x`'s "one word, its own Tj" shape never fires here,
    so the expansion is checked directly in the drawn STRING instead."""
    pat = re.compile(rb'\((.*?' + re.escape(contains.encode()) + rb'.*?)\) Tj')
    for stream in _decoded_streams(pdf_bytes):
        m = pat.search(stream)
        if m:
            return m[1].decode('latin-1')
    return None


def _spans_text(raw: bytes) -> str:
    spans = core._decode_spans(raw, False, 'cp437', set(), {})
    return ''.join(s.text for s in spans)


# ------------------------------------------------------- _decode_spans
# The document model's own job now: keep the byte, verbatim, round-trip it.

def test_decode_spans_keeps_the_literal_tab_byte():
    """The parsed IR carries a real '\\t' character now, not computed
    spaces -- the round-trip half of planning #244's split."""
    text = _spans_text(b'00h \xc2^@\tFix')
    assert '\t' in text, repr(text)


def test_decode_spans_reachable_through_parse_ws_public_entry_point():
    """Not just the private helper -- a real (print-stream-detected)
    document carrying a bare 0x09 keeps it literal through the public
    parse_ws() entry point too."""
    doc = core.parse_ws(b'From: \tWordStar\r\n')
    text = ''.join(sp.text for blk in doc.blocks
                   for ln in getattr(blk, 'lines', [])
                   for sp in ln.spans)
    assert text == 'From: \tWordStar', repr(text)


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


# -------------------------------------------- Printed-PDF layout-time expansion
# `pdf._expand_bare_tabs_for_printed_layout` -- the WS7-verified visual fix,
# now applied only where it was ever evidenced: PRINTED-mode rendering.

def _printed_pdf(src: bytes) -> bytes:
    doc = core.parse_ws(src)
    return pdf.emit_pdf(doc, mode='printed')


def test_bare_tab_after_six_columns_reaches_the_next_modulus_8_stop_in_printed_pdf():
    """The exact WS7-verified case: 6 characters before the tab ("00h ^@"),
    landing on column 8 -- 2 hard spaces, not zero. Fontless (no font
    block), so `_span_pitch` falls back to the 12pt-default 7.2pt/char
    grid -- exact arithmetic, not a font-metric approximation. The whole
    line draws as ONE Tj (a plain, unstyled fixed-pitch line, nothing to
    split it), so the expansion is checked in the drawn string itself."""
    pdf_bytes = _printed_pdf(b'.po 0"\r\n.lm 0\r\n' + b'00h ^@\tFix.' + HARD)
    assert _drawn_line(pdf_bytes, 'Fix.') == '00h ^@  Fix.'


def test_bare_tab_at_line_start_expands_to_a_full_stop_in_printed_pdf():
    """A tab at column 0 is still "not yet at a stop" by the standard tab
    convention (a tab always advances at least one column) -- it must
    reach column 8, a full 8 hard spaces, not 0."""
    pdf_bytes = _printed_pdf(b'.po 0"\r\n.lm 0\r\n' + b'\tWord.' + HARD)
    assert _drawn_line(pdf_bytes, 'Word.') == ' ' * 8 + 'Word.'


def test_bare_tab_exactly_on_a_stop_still_advances_a_full_8_in_printed_pdf():
    """8 characters before the tab -- already sitting on a modulus-8
    print position. WordStar's own rule ("hard spaces required to REACH
    a modulus 8 position") still means the next one, not zero -- the
    standard tab convention, and the only reading consistent with the
    line-start case above."""
    pdf_bytes = _printed_pdf(b'.po 0"\r\n.lm 0\r\n' + b'12345678\tWord.' + HARD)
    assert _drawn_line(pdf_bytes, 'Word.') == '12345678' + ' ' * 8 + 'Word.'


def test_bare_tab_column_count_resets_at_the_next_physical_line_in_printed_pdf():
    """Printed mode renders physical lines verbatim, never rewrapped, and
    `_expand_bare_tabs_for_printed_layout` runs once per `_line_ops_
    printed` call (one physical line) -- a short second line must not
    inherit the column count from the line before it. Without the reset,
    line two's own running count would start at line one's ending column
    (16, not 0), and "ab" + a tab from there lands on column 24, not 8 --
    `_drawn_line`'s own comment on why "WordOne."/"WordTwo." must differ
    to disambiguate which line's Tj gets matched."""
    pdf_bytes = _printed_pdf(
        b'.po 0"\r\n.lm 0\r\n' + b'\tWordOne.' + HARD + b'ab\tWordTwo.' + HARD)
    assert _drawn_line(pdf_bytes, 'WordOne.') == ' ' * 8 + 'WordOne.'
    assert _drawn_line(pdf_bytes, 'WordTwo.') == 'ab' + ' ' * 6 + 'WordTwo.'


def test_oj_off_default_text_mode_keeps_the_bare_tab_literal():
    """TEXT sees the raw, un-expanded byte in both modes -- the pre-#237
    behavior, now deliberately restored rather than accidentally shared,
    and NOT changed by planning #264 item 1 (which reaches Printed RTF and
    the fixed-pitch HTML block only; see this module's own header)."""
    from ctrlkd import emit
    doc = core.parse_ws(b'From:\tWordStar' + HARD)
    text_out = emit.emit_text(doc, mode='printed')
    assert '\t' in text_out, repr(text_out)


def test_bare_tab_preceded_by_a_single_space_lands_one_column_further():
    """Planning #237 remainder (probed 2026-09-09): a literal space
    immediately before the tab shifts the modulus-8 stop by the length
    of that trailing space run, confirmed against real WS7 print output
    (8 probe docs, `research/2026-09-09_space-tab-lattice-shift.md`).
    7 characters, the last one a space ("ABCDEF ") -- WITHOUT the space
    quirk this would land on column 8, same as the 7-non-space-char case
    above; WITH it, the driver computes the stop from column 6 (8) and
    adds the 1-column space run back on top, landing on 9."""
    pdf_bytes = _printed_pdf(b'.po 0"\r\n.lm 0\r\n' + b'ABCDEF \tWord.' + HARD)
    assert _drawn_line(pdf_bytes, 'Word.') == 'ABCDEF ' + ' ' * 2 + 'Word.'


def test_bare_tab_preceded_by_two_spaces_adds_the_whole_run_back():
    """5 characters + 2 trailing spaces (column 7): the stop is computed
    from column 5 (-> 8) and the FULL 2-space run is added back, landing
    on column 10 -- not 9, ruling out a flat "+1" in favour of "+space
    run length"."""
    pdf_bytes = _printed_pdf(b'.po 0"\r\n.lm 0\r\n' + b'ABCDE  \tWord.' + HARD)
    assert _drawn_line(pdf_bytes, 'Word.') == 'ABCDE  ' + ' ' * 3 + 'Word.'


def test_bare_tab_preceded_by_space_exactly_on_a_stop_still_shifts():
    """The shape the corpus had never exercised before this probe: 7
    characters + 1 space puts the cursor AT column 8, already on a
    modulus-8 stop. The old same-column rule's on-stop-advances-a-full-8
    answer would land column 16; real WS7 instead computes the stop from
    column 7 (the space stripped back off) -> 8, then adds the 1-column
    space run back -> 9. If this regresses to 16, the fix has been
    narrowed to only the below-a-stop case."""
    pdf_bytes = _printed_pdf(b'.po 0"\r\n.lm 0\r\n' + b'ABCDEFG \tWord.' + HARD)
    assert _drawn_line(pdf_bytes, 'Word.') == 'ABCDEFG ' + ' ' * 1 + 'Word.'


def test_bare_tab_preceded_by_a_soft_space_shifts_the_same_as_a_literal_one():
    """A WS5+ soft space (0xA0) decodes to plain ' ' (core.py's `0xA0`
    branch) before this function ever sees the text, so it is
    indistinguishable from an author-typed space here -- and real WS7
    printed output treats it identically: the probe (`P6`) landed on the
    same column as the literal-space case at the same starting column."""
    pdf_bytes = _printed_pdf(b'.po 0"\r\n.lm 0\r\n' + b'ABCDEF\xa0\tWord.' + HARD)
    assert _drawn_line(pdf_bytes, 'Word.') == 'ABCDEF ' + ' ' * 2 + 'Word.'


def test_win7_etc_subject_line_shape_lands_on_the_ws7_verified_column():
    """The actual WIN7.ETC residual planning #237 left open: ` Subject: `
    (10 characters, the last one a space) followed by a bare tab. Real
    WS7's capture places the word after the tab at column 17 (WS7 x =
    187.2pt over a 57.6pt/8-column default `.po` margin, i.e. 18 Courier
    columns from the page edge, 17 from the tab's own landing before the
    literal space WIN7.ETC's own source carries between the tab and the
    word) -- this fix's `base = 10 - 1 = 9` -> modulus stop 16 -> `+1`
    space run -> 17, matching exactly; the pre-fix same-column rule gave
    16, one short, which is what planning #237 reported."""
    pdf_bytes = _printed_pdf(b'.po 0"\r\n.lm 0\r\n' + b' Subject: \tWord.' + HARD)
    assert _drawn_line(pdf_bytes, 'Word.') == ' Subject: ' + ' ' * 7 + 'Word.'


def test_a_styled_mixed_line_with_a_bare_tab_is_still_drawn_correctly():
    """A line resolving to more than one styled span still reaches
    `_expand_bare_tabs_for_printed_layout` (it runs on the RAW `segs`,
    ahead of the split that later decides eligibility for other
    per-line features like planning #238's justification) -- the tab
    expands the same way regardless of how many styles surround it."""
    pdf_bytes = _printed_pdf(
        b'.po 0"\r\n.lm 0\r\n' + b'AB\x02\tCD\x02EF.' + HARD)
    x = _word_x(pdf_bytes, 'EF.')
    assert x == (8 + 2) * 7.2, x


# --------------------------------- Printed RTF and the fixed-pitch HTML block
# planning #264 item 1 (packet row B3). The same rule, on the two other
# surfaces that set a physical line in a monospaced face. `core.expand_bare_
# tabs_texts` is the one implementation all three now call.

def _emit(src: bytes, fmt: str, mode: str) -> str:
    from ctrlkd import emit
    doc = core.parse_ws(src)
    return getattr(emit, 'emit_' + fmt)(doc, mode=mode)


def test_core_expand_bare_tabs_texts_is_a_no_op_without_a_tab():
    """The shared entry point returns None -- not a copy -- for a line with
    no tab in it, so every caller keeps its own objects and the
    overwhelming majority of printed lines cost one scan."""
    assert core.expand_bare_tabs_texts(['abc', 'def']) is None
    assert core.expand_bare_tabs_texts(['00h ^@', '\tFix']) == ['00h ^@', '  Fix']


def test_printed_rtf_expands_a_bare_tab_to_the_modulus_8_stop():
    """The WS7-verified line, in RTF: "00h ^@" is 6 characters, so the tab
    is 2 spaces and "Fix." starts at column 8 -- where the document's own
    continuation lines are already typed."""
    out = _emit(b'.po 0"\r\n.lm 0\r\n' + b'00h ^@\tFix.' + HARD, 'rtf', 'printed')
    assert '\t' not in out
    assert '00h ^@  Fix.' in out


def test_printed_html_expands_a_bare_tab_to_the_modulus_8_stop():
    """The same line in the fixed-pitch HTML block (`p.ws-native`), where a
    raw tab byte collapsed to a single space in a browser."""
    out = _emit(b'.po 0"\r\n.lm 0\r\n' + b'00h ^@\tFix.' + HARD, 'html', 'printed')
    assert '\t' not in out
    assert '00h ^@  Fix.' in out


def test_modern_rtf_and_html_keep_the_bare_tab():
    """The packet's own exclusion, pinned: Modern reflows into a
    proportional face with no print columns for a tab to land on, so the
    byte stays exactly as it was.

    Built as an IR document rather than parsed bytes on purpose -- the
    surrounding tests' own source carries print-CONTROL bytes, which
    `_printed(doc)` (correctly) forces into the printed path in either
    mode, so a parsed fixture could never exercise the Modern branch."""
    from ctrlkd import emit
    doc = core.Document(
        blocks=[core.Block('para',
                           lines=[core.Line(spans=[core.Span('00h\tFix.')])])],
        meta={'variant': 'ws5+'})
    assert '\t' in emit.emit_rtf(doc, mode='modern')
    assert '\t' in emit.emit_html(doc, mode='modern')
    assert '\t' not in emit.emit_rtf(doc, mode='printed')
    assert '\t' not in emit.emit_html(doc, mode='printed')


def test_printed_rtf_column_count_resets_at_the_next_physical_line():
    """One call is one physical line in RTF too -- line two's count starts
    at 0, so "ab" + a tab lands on column 8, not on line one's 24."""
    out = _emit(b'.po 0"\r\n.lm 0\r\n' + b'\tWordOne.' + HARD + b'ab\tWordTwo.' + HARD,
                'rtf', 'printed')
    assert ' ' * 8 + 'WordOne.' in out
    assert 'ab' + ' ' * 6 + 'WordTwo.' in out


def test_printed_rtf_honours_the_preceding_space_run_shift():
    """Planning #237's measured remainder reaches RTF as well, because it
    is part of the one shared rule: ` Subject: ` (10 characters, the last
    a space) puts the next word at column 17, not 16."""
    out = _emit(b'.po 0"\r\n.lm 0\r\n' + b' Subject: \tWord.' + HARD, 'rtf', 'printed')
    assert ' Subject: ' + ' ' * 7 + 'Word.' in out


def test_printed_text_and_markdown_still_carry_the_raw_byte():
    """Row B3 named two surfaces. Text and Markdown are not among them and
    do not move -- stated as a test so a later change to them is a
    deliberate one."""
    src = b'.po 0"\r\n.lm 0\r\n' + b'00h ^@\tFix.' + HARD
    assert '\t' in _emit(src, 'text', 'printed')
    assert '\t' in _emit(src, 'markdown', 'printed')
