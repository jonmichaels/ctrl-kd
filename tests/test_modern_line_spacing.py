"""b26-modern item 4: Modern PDF's inter-line advance must be consistently
size-proportional, including across a blank line.

Modern already sizes each rendered line's own advance by that line's own
max token size (`MODERN_LINE * size`, `_modern_streams`) -- that part was
never in question. The bug was narrower: a 'blank' item's advance was a
FIXED constant (`MODERN_LINE * MODERN_BODY_PT`, the 14pt document default)
baked at flow-build time, independent of what was actually on the page
around it. Measured on the real corpus (PREVIEW.WS, a font-sample page
mixing 24pt/20pt/12pt lines): a blank between two 24pt lines advanced by
the exact same fixed amount a blank between a 24pt line and an 8pt line
would, so the total inter-paragraph gap tracked only the ENTERING line's
size and ignored the size actually being LEFT -- visibly inconsistent
spacing wherever font size varied line-to-line.

Fix: a blank now advances at the MOST RECENTLY PLACED line's own leading
-- the same "a blank advances at the preceding content's own leading"
principle Printed PDF already uses for style-driven leading
(test_style_leading.py), applied at Modern's own per-line granularity.

Synthetic fixtures only (CLAUDE.md): WS7 font-change blocks (cmd 0x02),
same construction as test_ctrlkd.py's own `_font_block` helper.
"""
import re

from ctrlkd import core, pdf

HARD = b'\r\n'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def font_block(points, width=180):
    """One WS5+ font-change block at a given point size (12pt default
    typestyle 0 -- Courier under the base-14 mapping)."""
    return ws7_block(0x02, round(width).to_bytes(2, 'little')
                     + round(points * 20).to_bytes(2, 'little')
                     + (0).to_bytes(2, 'little') + bytes(6))


def _line_ys(out):
    """Distinct baseline Y positions in draw order (a visual line often
    splits into several Tj ops -- one per word -- all sharing one Td y)."""
    ys = [float(y) for _, y in re.findall(rb'([\d.]+) ([\d.]+) Td \(', out)]
    uniq = []
    for y in ys:
        if not uniq or abs(uniq[-1] - y) > 1e-6:
            uniq.append(y)
    return uniq


def test_blank_between_unequal_sizes_advances_at_the_preceding_lines_leading():
    """A 24pt line, a blank, then an 8pt line: the blank must cost the
    24pt line's OWN leading (1.2 x 24 = 28.8pt), not a fixed 14pt-default
    amount -- combined with the 8pt line's own entering leading (1.2 x 8 =
    9.6pt), the total gap is 38.4pt."""
    data = font_block(24) + b'Big line.' + HARD + HARD + font_block(8) + b'Small line.' + HARD
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='modern')
    ys = _line_ys(out)
    assert round(ys[0] - ys[-1], 4) == 38.4


def test_blank_between_equal_large_sizes_is_proportionally_larger_than_default():
    """Two 24pt lines separated by a blank: BOTH sides of the gap scale
    with the 24pt size (28.8 + 28.8 = 57.6), not the old fixed-blank
    total of 45.6 (28.8 entering + a 16.8 constant that ignored the
    24pt line being left)."""
    data = font_block(24) + b'First big line.' + HARD + HARD + font_block(24) + b'Second big line.' + HARD
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='modern')
    ys = _line_ys(out)
    assert round(ys[0] - ys[-1], 4) == 57.6


def test_consecutive_gaps_are_uniform_when_size_is_uniform():
    """The regression shape itself: three same-size (24pt) one-line
    paragraphs, each separated by one blank line -- both gaps must be
    IDENTICAL (57.6pt each), proving the rule is truly proportional and
    not just correct for one transition."""
    data = (font_block(24) + b'Line one.' + HARD + HARD +
            b'Line two.' + HARD + HARD +
            b'Line three.' + HARD)
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='modern')
    ys = _line_ys(out)
    gaps = [round(ys[i] - ys[i + 1], 4) for i in range(len(ys) - 1)]
    assert gaps == [57.6, 57.6]


def test_default_size_blank_spacing_is_unchanged():
    """A document that never changes font size at all (the common case,
    every existing corpus doc without an explicit font-sample page) must
    render at exactly the pre-existing 16.8pt-per-blank spacing (1.2 x
    the 14pt Modern body default) -- the fix must not perturb the
    overwhelmingly common uniform-size case."""
    data = b'Line one.' + HARD + HARD + b'Line two.' + HARD
    doc = core.parse_ws(data)
    doc.meta['variant'] = 'ws4'
    out = pdf.emit_pdf(doc, mode='modern')
    ys = _line_ys(out)
    assert round(ys[0] - ys[1], 4) == 16.8 + 16.8


def test_modern_printed_leading_is_unaffected_by_this_fix():
    """Printed PDF's own leading mechanism (`.lh`, style vmi) is a wholly
    separate code path (`_page_stream`, not `_modern_streams`) -- a
    document that mixes font sizes must render Printed mode identically
    whether or not this fix is present, proven by an unrelated Printed
    invariant: `.lh`-driven leading stays exactly what `.lh` says."""
    data = b'.lh 20' + HARD + font_block(24) + b'Line one.' + HARD + b'Line two.' + HARD
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='printed')
    ys = _line_ys(out)
    assert round(ys[0] - ys[1], 4) == 30.0   # 20/48in = 30pt, untouched by Modern's fix
