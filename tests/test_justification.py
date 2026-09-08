"""Planning #238: `.oj on` full justification in Printed mode.

Root cause (2026-09-08 placement-triage, cause 3): Printed mode had ZERO
handling of `align='justify'` -- `grep -n justification src/ctrlkd/pdf.py`
found one unrelated comment. Rule and captured evidence: the maintainer's
own private research notes -- PRIVATE corpus paths/findings stay out of
this public repo, only the RULE and synthetic fixtures do.

Measured against real WS7 (sawyer/LSRBOX/LSRBOX.WS, sawyer/REF/CTRL-K.H1,
both `ws7-prints/v4`, private corpus):

  1. Every line of a `.oj on` (align='justify') paragraph EXCEPT ITS OWN
     LAST physical line is stretched so its last character lands exactly
     on the block's resolved right margin (`.rm`, in print columns,
     measured from the same `.po` origin as the left edge). The last
     line of the paragraph is left ragged -- confirmed directly (LSRBOX's
     own final line sits short of the margin in the real capture).
  2. Only single-blank inter-word gaps are stretched -- a run of 2+
     literal blanks (e.g. an author's own end-of-sentence double space)
     is left at its natural width. The line's total slack is split evenly
     across the single-blank gaps (a documented APPROXIMATION: WS7's own
     real per-gap split is not perfectly flat even when the total divides
     evenly, e.g. one measured 8-gap/72-decipoint line split 7,7,10,9,10,
     9,10,10 rather than a flat 9 each -- WS7's own internal rounding was
     not reverse-engineered to the decipoint this pass; the always-flush,
     self-consistent even split ships instead, documented as approximate).
  3. Only a line that resolves to exactly ONE styled span is justified --
     a styled/mixed line (a bold word mid-sentence, a leading indent) is
     left unjustified this pass (narrow, documented scope).
  4. Only a FIXED-PITCH span is justified -- no evidenced proportional-
     font `.oj on` capture was found in the corpus this pass; a
     proportional line's own natural-width path is unmodified.
  5. Modern mode is untouched -- Modern already expresses `align='justify'`
     as a CSS/RTF property rather than literal padding (`test_justify_
     `is_not_faked_with_padding_in_plain_text` in test_ctrlkd.py); no
     reference evidence says Modern should ALSO carry literal justified
     spacing, so nothing there changed (report, don't decide).

Fixed-pitch WS4-shaped fontless documents throughout (no font block --
`_span_pitch` falls back to `pt * 0.6` = 7.2pt/char at the 12pt default,
the same 10-CPI grid the real captures print on), so every width below is
exact arithmetic, not a font-metric approximation.
"""
import re
import zlib

from ctrlkd import core, pdf

HARD = b'\r\n'
SOFT = b'\x8d\n'


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
    stream, or None if the word never appears as its own Tj operand."""
    needle = word.encode()
    pat = re.compile(rb'([\d.]+) [\d.]+ Td \(' + re.escape(needle) + rb'\) Tj')
    for stream in _decoded_streams(pdf_bytes):
        m = pat.search(stream)
        if m:
            return float(m[1])
    return None


def _doc(src, meta_variant='ws4'):
    doc = core.parse_ws(src)
    doc.meta['variant'] = meta_variant
    return doc


def test_justified_line_reaches_the_resolved_right_margin():
    """`.po 0"` / `.lm 0` / `.rm 20` (144pt) -- "AA BB CC" is 8 chars (57.6pt)
    natural, 2 single-blank gaps, needing 86.4pt of slack split evenly
    (43.2pt/gap, `base` below): AA@0, BB@AA(14.4)+gap(7.2+43.2)=64.8,
    CC@BB_end(64.8+14.4)+gap(7.2+43.2)=129.6, ending at 129.6+14.4=144.0 --
    the one confirmed-solid part of the rule (every justified line in the
    corpus lands its last character exactly on the margin); the per-gap
    SPLIT that gets it there is this pass's own documented approximation
    (see this module's docstring, rule 2), not a WS7 byte-for-byte match."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD)
    b = doc.blocks[0]
    assert b.align == 'justify'
    assert len(b.lines) == 2
    out = pdf.emit_pdf(doc, mode='printed')
    x_aa = _word_x(out, 'AA')
    x_bb = _word_x(out, 'BB')
    x_cc = _word_x(out, 'CC')
    assert x_aa == 0.0
    base = (144.0 - 8 * 7.2) / 2       # 43.2pt of slack per elastic gap
    x_bb_expected = 2 * 7.2 + (7.2 + base)
    x_cc_expected = x_bb_expected + 2 * 7.2 + (7.2 + base)
    assert x_bb == round(x_bb_expected, 1)
    assert x_cc == round(x_cc_expected, 1)
    # The confirmed-solid part of the rule: CC's own right edge lands
    # exactly on the margin, not just "somewhere further right".
    assert x_cc + 2 * 7.2 == 144.0


def test_last_line_of_justified_paragraph_is_not_stretched():
    """WS7 never justifies a paragraph's own trailing line (measured
    directly against LSRBOX.WS's real capture) -- "DD." here is the
    second (last) physical line of the SAME block and must render at its
    natural, un-stretched position."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    assert _word_x(out, 'DD.') == 0.0


def test_multi_space_gap_is_not_stretched_single_space_gaps_absorb_it():
    """`.rm` chosen so the SINGLE-blank gap (AA-BB) and the DOUBLE-blank
    gap (BB-CC, an author's own end-of-sentence spacing) are both present
    on the one physical line -- only the single-blank gap should carry any
    of the line's slack; the double stays at its natural 2*7.2=14.4pt."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB  CC' + SOFT + b'DD.' + HARD)
    b = doc.blocks[0]
    assert b.lines[0].text() == 'AA BB  CC'
    out = pdf.emit_pdf(doc, mode='printed')
    x_aa = _word_x(out, 'AA')
    x_bb = _word_x(out, 'BB')
    x_cc = _word_x(out, 'CC')
    assert x_aa == 0.0
    # BB's own gap (AA-BB, single blank) carries ALL the line's slack --
    # the only elastic gap on this line.
    natural_total = 9 * 7.2      # "AA BB  CC" = 9 chars
    stretch = 144.0 - natural_total
    assert x_bb == round(2 * 7.2 + 7.2 + stretch, 1)
    # BB-CC stays at its natural DOUBLE-blank width -- not stretched.
    assert x_cc == round(x_bb + 2 * 7.2 + 2 * 7.2, 1)
    assert x_cc + 2 * 7.2 == 144.0


def test_oj_off_is_unaffected():
    """The default (no `.oj on` anywhere) must render byte-identically to
    before this feature existed: one whole-line Tj (`justify_eligible`
    never fires, so the line is never split into per-word pieces), the
    line's own single, exact, un-stretched text."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD)
    assert doc.blocks[0].align == 'left'
    out = pdf.emit_pdf(doc, mode='printed')
    assert _word_x(out, 'AA BB CC') == 0.0
    assert _word_x(out, 'BB') is None     # never its OWN Tj -- not split


def test_oj_on_then_off_mid_document_only_justifies_the_on_block():
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD +
              b'.oj off\r\nEE FF GG' + SOFT + b'HH.' + HARD)
    assert [b.align for b in doc.blocks] == ['justify', 'left']
    out = pdf.emit_pdf(doc, mode='printed')
    x_bb = _word_x(out, 'BB')                 # justified block -- split, stretched
    assert x_bb is not None and x_bb > 2 * 7.2 + 7.2
    assert _word_x(out, 'EE FF GG') == 0.0     # .oj off block -- one whole-line Tj
    assert _word_x(out, 'FF') is None          # never split into pieces


def test_styled_mixed_line_is_left_unjustified_documented_scope():
    """A line that carries more than one styled span (a bold word
    mid-sentence) resolves to more than one seg -- out of this pass's
    scope (see this module's own docstring, point 3) -- so it renders at
    its natural width rather than guessing how to split the slack among
    several spans."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 40\r\n.oj on\r\n'
              b'AA \x02BB\x02 CC' + HARD)
    b = doc.blocks[0]
    assert b.align == 'justify'
    assert len(b.lines[0].spans) > 1
    out = pdf.emit_pdf(doc, mode='printed')
    x_bb = _word_x(out, 'BB')
    assert x_bb == 2 * 7.2 + 7.2     # natural, not stretched to the 40-col margin
