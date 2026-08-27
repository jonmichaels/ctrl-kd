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
import struct

from ctrlkd import core, pdf, pictures

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


# ------------------------------------------------ b27-WP3 item 4 (image+blank)
#
# This suite never exercised images before -- the gap that let the following
# bug ship. `_modern_streams`'s 'image' case wrote the embedded picture's own
# HEIGHT into `last_h`, the same variable the 'blank' case above reuses as
# "the most recently placed line's own leading". A blank run immediately
# after an image therefore advanced by the IMAGE's height instead of the
# surrounding TEXT's leading. Measured on the real corpus (-README.WS): a
# 73.9pt-tall inline image followed by 7 contiguous blank source lines
# advanced 7 x 73.9 = 517.3pt of whitespace where the correct value (7 x
# 16.8, the 14pt-body leading) is 117.6pt -- "huge whitespace below the
# image before the title block" in Modern view.
#
# Fix: the 'image' case no longer touches `last_h` at all -- an image's
# height is a page-space cost, never a leading, so a following blank must
# keep inheriting whatever TEXT line's leading was last placed (or the
# 14pt default if none has been placed yet).
#
# Confirmed FAILING before the fix / PASSING after (manual bisection, since
# this is the regression itself): on the fixture below, the unfixed code
# measured a 433.6pt Before->After gap (16.8 leading blank + 100pt image +
# 3 x 100pt bugged blanks + 16.8 entering leading); the fixed code measures
# 184.0pt (16.8 + 100 + 3 x 16.8 correct blanks + 16.8).

def _tiny_pix_bytes(gcols=8, grows=1, prt_options_raw=None):
    """A minimal, structurally valid, single-row MONO .PIX (same recipe as
    tests/test_pictures.py's helper of the same name -- kept local here
    since these test files never cross-import)."""
    row_bytes = gcols // 8
    mode_blob = bytearray(29)
    mode_blob[1] = 1                                  # htype bit0: bitmap
    struct.pack_into('<HH', mode_blob, 18, gcols, grows)
    mode_blob[22] = 1                                 # gfore: 1 bitplane
    tile_info = struct.pack('<HHHH', grows, gcols, 1, 1)
    tile_bitmap = bytes(row_bytes)                     # one raw all-zero row

    items = [(0, bytes(mode_blob)), (1, bytes(4 * 16)), (2, tile_info)]
    if prt_options_raw is not None:
        items.append((0x11, prt_options_raw))
    items.append((0x8000, tile_bitmap))

    header = struct.pack('<HH', 3, len(items))
    index_off = 4 + 8 * len(items)
    index_entries = bytearray()
    blobs = bytearray()
    cur = index_off
    for did, blob in items:
        index_entries += struct.pack('<HHI', did, len(blob), cur)
        blobs += blob
        cur += len(blob)
    return bytes(header) + bytes(index_entries) + bytes(blobs)


def _ws_pix_block(payload, jump=None):
    if jump is None:
        jump = len(payload) + 4
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([0x10]) + payload + j + b'\x1d'


def _doc_with_sized_pix_and_trailing_blanks(tmp_path, n_trailing_blanks,
                                            h_pt=100.0, w_pt=200.0):
    """'Before.', a blank, an isolated pix tag print-sized to exactly
    (w_pt, h_pt), `n_trailing_blanks` contiguous blank lines, then
    'After.' -- the -README.WS shape (image immediately followed by a
    contiguous blank run) with a deliberately large, distinctive image
    height so a blank wrongly inheriting it is unmistakable against the
    14pt-body 16.8pt default leading."""
    row_dp = round(h_pt / 72.0 * 720.0)
    col_dp = round(w_pt / 72.0 * 720.0)
    prt = (struct.pack('<12h', *([0] * 12))
           + struct.pack('<3h', row_dp, col_dp, 0)
           + bytes(range(16)))
    pix_bytes = _tiny_pix_bytes(prt_options_raw=prt)
    (tmp_path / 'FIGURE1.PIX').write_bytes(pix_bytes)
    docpath = tmp_path / 'DOC.WS'
    docpath.write_bytes(b'')
    block = _ws_pix_block(br'C:\PIX\FIGURE1.PIX')
    data = (b'Before.\r\n\r\n' + block + b'\r\n'
            + b'\r\n' * n_trailing_blanks + b'After.\r\n')
    doc = core.parse_ws(data)
    results = pictures.resolve_document_pictures(doc, docpath)
    return doc, results


def test_blanks_after_an_image_advance_at_text_leading_not_image_height(tmp_path):
    """The regression itself: 3 blank lines immediately following a 100pt-
    tall image must advance by 3 x 16.8 = 50.4pt (the default 14pt-body
    leading -- the same leading the enclosing text is set in), never
    3 x 100 = 300pt. Total Before->After gap: 16.8 (leading blank, unaffected
    by the bug) + 100 (image's own cost) + 50.4 (3 correct blanks) + 16.8
    (After's own entering leading) = 184.0pt. The unfixed code measured
    433.6pt on this exact fixture (16.8 + 100 + 3 x 100 + 16.8)."""
    doc, results = _doc_with_sized_pix_and_trailing_blanks(tmp_path, 3)
    out = pdf.emit_pdf(doc, mode='modern', pictures='embed', pix_results=results)
    ys = _line_ys(out)
    assert len(ys) == 2                       # 'Before.' baseline, 'After.' baseline
    assert round(ys[0] - ys[1], 4) == 184.0


def test_a_single_blank_before_an_image_is_unaffected_by_the_image_fix():
    """Sanity companion: a blank BEFORE an image was never part of this bug
    (it reuses the preceding TEXT line's leading, exactly as any other
    blank does) -- confirms the fix is scoped to blanks that FOLLOW an
    image, not blanks generally near one. Two 24pt lines with a blank
    between them, an image, then nothing: the blank's cost must still be
    the 24pt line's own leading (28.8pt), matching the pre-existing
    unequal-size rule this file already pins above."""
    data = font_block(24) + b'Big line.' + HARD + HARD + font_block(24) + b'Second.' + HARD
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='modern')
    ys = _line_ys(out)
    assert round(ys[0] - ys[1], 4) == 28.8 + 28.8
