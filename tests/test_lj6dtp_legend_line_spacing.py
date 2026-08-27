"""LJ6DTP parity C13: page 3's symbol-legend line spacing was reported as
tighter than WS7's. Measured, it is not -- both the single-glyph legend
(em dash/en dash/quotes/rounded corners, one symbol + description per
line) and the "You type / Shows on screen as / Prints as" chart already
render at a UNIFORM 14pt lead, matching LJ6DTP-p3.png to within 1px at
300dpi.

Evidence trail (not asserted here, just recorded): pixel-sampled row
tops in the reference PNG for the ten entries from "copyright symbol"
through "lower-right rounded box corner" -- 323, 382, 440, 498, 557,
615, 673, 732, 790, 848 -- step by 58-59px throughout (0.1935-0.1967in,
~13.9-14.1pt at 300dpi). Our own render's row tops for the same ten
entries step identically. Cross-checked directly against the emitted
PDF's own Td y-coordinates (no rasterization involved at all) for the
em/en-dash and rounded-corner lines: 678.0, 664.0, 650.0, 636.0 (not
sampled here but implied), 622.0, 608.0, 594.0, 580.0 -- EXACTLY 14.0pt
apart, every single gap, no exceptions including across the block
boundary between the dash/quote paragraph and the four separate
rounded-corner paragraphs (each corner entry is its own Block, per its
own paragraph-style handle, register C7's own finding -- if a missing
`.psb`/`.psa` were the defect, that boundary specifically would show a
wider gap than the others; it does not).

Checked out the commit immediately before this session's first change
(99fbd64) and re-measured from its own emitted PDF: byte-for-byte the
SAME Td y-coordinates. This defect, if it was ever real, predates and is
unrelated to anything touched in this round (C7/C9/C11/C12) -- it simply
does not reproduce against the current engine. Reported rather than
"fixed" for lack of anything to fix; this file exists as the regression
guard so a future change doesn't reopen it unnoticed.
"""
import pytest

from ctrlkd import core, pdf


def _last_td_y(pdf_bytes, needle):
    import re
    m = next(re.finditer(re.escape(needle), pdf_bytes))
    seg = pdf_bytes[max(0, m.start() - 200):m.start()]
    tds = re.findall(rb'([\d.]+) ([\d.]+) Td', seg)
    return float(tds[-1][1])


@pytest.mark.sawyer
def test_symbol_legend_lines_are_uniformly_14pt_apart(require_sawyer_doc):
    """Tier 2 (sawyer): LJ6DTP.WS, one of the ten committed manifest
    documents (tests/SAWYER-CORPUS.md)."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    out = pdf.emit_pdf(doc, mode='printed')
    ys = [_last_td_y(out, needle) for needle in
         (b'long', b'short', b'(individual', b'upper-left',
          b'upper-right', b'lower-left', b'lower-right')]
    # '(individual' matches BOTH the open- and close-quote lines; take
    # the two in appearance order explicitly instead.
    import re
    opens = [m.start() for m in re.finditer(rb'\(individual', out)]
    assert len(opens) >= 2
    y_open = float(re.findall(rb'([\d.]+) ([\d.]+) Td',
                              out[opens[0] - 200:opens[0]])[-1][1])
    y_close = float(re.findall(rb'([\d.]+) ([\d.]+) Td',
                               out[opens[1] - 200:opens[1]])[-1][1])
    y_long, y_short, _, y_ul, y_ur, y_ll, y_lr = ys
    full = [y_long, y_short, y_open, y_close, y_ul, y_ur, y_ll, y_lr]
    deltas = [round(full[i] - full[i + 1], 3) for i in range(len(full) - 1)]
    assert deltas == [14.0] * len(deltas), (
        f'legend leading is no longer uniform 14pt: {deltas}')
