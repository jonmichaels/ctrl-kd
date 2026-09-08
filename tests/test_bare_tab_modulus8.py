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
    """Every mode OTHER than Printed PDF sees the raw, un-expanded byte --
    the pre-#237 behavior, now deliberately restored rather than
    accidentally shared. `mode='printed'` TEXT output (not PDF) is
    included in that "every other mode": the layout-time fix lives in
    `pdf.py`'s PDF writer alone, per this module's own header."""
    from ctrlkd import emit
    doc = core.parse_ws(b'From:\tWordStar' + HARD)
    text_out = emit.emit_text(doc, mode='printed')
    assert '\t' in text_out, repr(text_out)


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
