"""b26-modern item 5: a quoted verse couplet (two short, hard-terminated,
identically-indented lines forming ONE quotation that merely spans two
lines) was misclassified as prose by `looks_like_verse`'s quote-opening
veto, so Modern inserted full paragraph spacing between the two lines
instead of tight verse spacing.

ROOT CAUSE (real corpus, WARPRAYR.WS -- "Mark Twain's The War Prayer",
the hymn couplet '"God the all-terrible! Thou who ordainest, / Thunder
thy clarion and lightning thy sword!"'): `VERSE_QUOTE_VETO_FRACTION`'s
veto counted ANY line starting with a quote mark (`_opens_quote`) toward
its fraction, without checking whether that line's quotation was ALSO
CLOSED on the same line. For this couplet, only line 1 opens with `"`
(1-of-2 = 0.5), comfortably past the 1/3 veto bar -- but that single
opening line does not itself close the quotation; the quotation spans
into line 2, which is exactly what a genuine multi-line quoted passage
(hymn, poem, prose excerpt) looks like, NOT what real spoken dialogue
looks like. The veto's own calibration evidence (test_ws4_dialogue_run_
does_not_false_positive_as_stanza's fixtures, '"Where are you going?"' /
'"I already told you."') is entirely SELF-CONTAINED quotes -- each opens
AND closes on its own single line.

FIX (general, not WARPRAYR-specific): `_self_contained_quote` requires
both an opening AND a closing quote mark on the SAME line before a line
counts toward the veto fraction. A line that only opens a quotation
(the passage continues past it) no longer single-handedly vetoes a
verse read; self-contained dialogue lines are unaffected.

Synthetic fixtures only (CLAUDE.md) -- same `ws7_block`/style-library
construction as test_modern_lint.py's own paragraph-assembly fixtures,
reproducing the couplet's exact real shape: a WS7-format document (no
`assemble_paragraphs` convention-outlier route needed -- both lines
carry the SAME 10-space indent, so Phase 1 already splits them into two
1-line units, and Phase 2's short-run reconsideration is what is being
tested).
"""
from ctrlkd import core

HARD = b'\x0d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _typed_paragraph_doc(lines):
    """A WS7-format document (header record present, no style library
    needed): one Block, `lines` as hard-return-terminated typed
    paragraphs -- same helper shape as test_modern_lint.py's own."""
    return core.parse_ws(ws7_block(0x00) + HARD.join(lines) + HARD)


def test_quoted_couplet_spanning_two_lines_reads_as_verse():
    """The exact regression shape: two 10-space-indented lines, together
    forming ONE quotation (opening `"` on line 1 only, closing `"` at the
    very end of line 2) -- must merge into ONE preserved unit, not split
    into two separately-paragraphed lines."""
    lines = [
        b'          "God the all-terrible! Thou who ordainest,',
        b'          Thunder thy clarion and lighten thy sword!"',
    ]
    doc = _typed_paragraph_doc(lines)
    margin = doc.meta.get('margin_estimate') or 65
    units = core.assemble_paragraphs(doc.blocks[0], margin)
    assert len(units) == 1, [core.line_visible_text(l) for u in units for l in u]
    assert sum(len(u) for u in units) == 2


def test_self_contained_quote_helper_distinguishes_span_from_utterance():
    """The mechanism directly: a line that both opens and closes its own
    quotation counts; a line that only opens one (the quote continues
    past it) does not -- even though `_opens_quote` alone says True for
    both."""
    assert core._self_contained_quote('"Where are you going?"') is True
    assert core._self_contained_quote('"God the all-terrible! Thou who ordainest,') is False
    assert core._opens_quote('"God the all-terrible! Thou who ordainest,') is True
    assert core._self_contained_quote('Thunder thy clarion and lightning thy sword!"') is False
    assert core._self_contained_quote('An ordinary line, no quote at all.') is False


def test_self_contained_dialogue_still_vetoes_as_prose():
    """The veto's own calibration fixture (test_modern_lint.py's dialogue-
    run test), re-pinned here at the `looks_like_verse` level directly:
    real spoken dialogue -- each line opening AND closing its own
    quotation -- must still veto a verse call exactly as before."""
    run_lines = [
        '"Where are you going?"',
        '"I already told you."',
    ]
    doc = core.parse_ws(b'placeholder' + HARD)
    fake_lines = [core.Line(spans=[core.Span(t)]) for t in run_lines]
    assert core.looks_like_verse(fake_lines, frozenset()) is False


def test_ordinary_prose_opening_a_quote_and_continuing_stays_prose():
    """Safety net: removing the bare quote-opening veto must not FLIP
    ordinary quoted prose into verse -- a two-line narrative sentence
    that happens to open with a quotation mark and continues as a
    normal, terminally-punctuated sentence still reads as prose via the
    terminal-punctuation signal (VERSE_ATTR_SUPPORTED_CEILING), same as
    it always has."""
    lines = [
        b'          "Well," she said, "I suppose we should be going',
        b'          now, before the weather turns any worse than this."',
    ]
    doc = _typed_paragraph_doc(lines)
    margin = doc.meta.get('margin_estimate') or 65
    units = core.assemble_paragraphs(doc.blocks[0], margin)
    assert len(units) == 2, [core.line_visible_text(l) for u in units for l in u]
