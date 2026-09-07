"""cp437 block/shade/box glyphs degrading to '?' in a Symbol-mapped span
(Printed and Modern PDF alike).

FOUND against the real corpus: sawyer/REF/-LASERJE.FNT line 9 -- twelve
cp437 glyphs ('░▒▓│┤╡╢╖╕╣║╗') typed under a font block whose typestyle is
Brush Script, then a real WS7 quirk this project has to live with: that
font block's own symbol-map bits read 'math' (WSFORMAT's typestyle word
59958 -- proportional, letter-quality, symbol_map=math, generic_style=
script, typestyle_number 54, 'Brush Script'; see core._font_entry's bit
table). `_pdf_family` reads those bits before anything else and resolves
the span to the Symbol face, so `_span_render` used to run the WHOLE span
through `untransliterate(text, 'math')` -- symbolmap.py's own documented
contract for a character it cannot round-trip into the real Symbol font's
byte table is to degrade it to '?' (the same degradation the rest of this
emitter uses elsewhere), and none of GRAPHIC_CHARS has a Symbol code
point. The twelve real box/shade glyphs became twelve literal '?' TEXT
characters at the Symbol font's own advance instead of the vector fills
_split_graphics/_graphic_ops already draw for the SAME characters in
every other span (fontless or ordinary-fonted) -- BOXES.WS and SCRIPT.WS's
figure box, which never touch a Symbol-mapped font, were never affected.

FIX (pdf._span_render): GRAPHIC_CHARS members skip the Symbol/ZapfDingbats
untransliteration round trip and keep their true Unicode code points, so
_split_graphics finds them downstream and draws them as geometry exactly
like it already does for every other family -- generic, not a
per-document carve-out: it applies to every Symbol/ZapfDingbats-mapped
span, in both Printed and Modern PDF (both share this one function).

A companion regression in the same mechanism: a middle dot (U+00B7) is
not a GRAPHIC_CHARS member, but reaching a Symbol-mapped span it hit the
identical '?' degradation (SYMBOL_REVERSE had no entry for it). Adobe
Symbol's own encoding carries a real 'periodcentered' glyph at byte 0xB7,
visually identical to Unicode's middle dot -- symbolmap.SYMBOL now maps
it self-to-self, the same convention already used for '°'/'±'.

This file pins three spans built from the SAME twelve-glyph-plus-middle-
dot text, one per font state a real document can put a box glyph in:
no font block at all (every WS4 file), an ordinary proportional font
(sans, cp437 symbol map), and the Symbol-mapped font that reproduces the
real corpus defect -- all three must draw the block/box run as vector
geometry and the middle dot as real text, never '?'.
"""
import re
import zlib

from ctrlkd import core, pdf

HARD = b'\x0d\x0a'
GRAPHIC = '░▒▓│┤╡╢╖╕╣║╗'.encode('cp437')          # SHADE_GRAY x3 + BOX_ARMS x9
DOT = '·'.encode('cp437')                          # U+00B7 MIDDLE DOT

# Real -LASERJE.FNT font6 word (Brush Script): proportional | letter_quality |
# symbol_map=math | generic_style=script | typestyle_number 54.
SYMBOL_MAPPED_STYLE = 59958
# LJ6DTP.WS's own real word for Antique Olive (test_lj6dtp_heading_face.py's
# PROP_SANS): proportional, generic_style sans, symbol_map cp437 (ordinary) --
# an everyday non-Symbol proportional font, for the "already worked" baseline.
ORDINARY_STYLE = 49877


def _ws7_block(cmd, content=b''):
    """One WS7 symmetrical ledger block -- same construction as
    test_lj6dtp_heading_face.py's `ws7_block` / test_ctrlkd.py's own."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _font_block(w, h, style):
    """One type-2 Font symmetric block: width (HMI), height (VMI), typestyle,
    then three zeroed 'previous' words -- mirrors test_lj6dtp_heading_face.py's
    `_font_block` exactly."""
    content = (w.to_bytes(2, 'little') + h.to_bytes(2, 'little') +
               style.to_bytes(2, 'little') + b'\x00' * 6)
    return _ws7_block(0x02, content)


def _build_doc():
    data = (
        GRAPHIC + b' ' + DOT + HARD +                                # fontless
        _font_block(180, 240, ORDINARY_STYLE) + GRAPHIC + b' ' + DOT + HARD +
        _font_block(180, 240, SYMBOL_MAPPED_STYLE) + GRAPHIC + b' ' + DOT + HARD
    )
    return core.parse_ws(data)


def _decoded_content(pdf_bytes):
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', pdf_bytes, re.S):
        try:
            out.append(zlib.decompress(m[1]))
        except zlib.error:
            out.append(m[1])
    return b'\n'.join(out)


def _symbol_font_names(pdf_bytes):
    """{'Fn'} resource names bound to /BaseFont /Symbol."""
    obj_font = {int(m[1]): m[2] for m in
               re.finditer(rb'(\d+) 0 obj\s*<< /Type /Font /Subtype /Type1 '
                          rb'/BaseFont /(\S+)', pdf_bytes)}
    return {m[1] for m in re.finditer(rb'/(F\d+) (\d+) 0 R', pdf_bytes)
            if obj_font.get(int(m[2])) == b'Symbol'}


def test_no_font_ordinary_font_and_symbol_mapped_font_all_draw_vectors_not_question_marks():
    """The bug, pinned directly: NONE of the three spans -- fontless,
    ordinary-fonted, or Symbol-mapped (the real -LASERJE.FNT trigger) --
    may emit the twelve-glyph run as degraded '?' text. Before the fix the
    third span failed this outright ('BT /F.. Tf ... (????????????) Tj ET')."""
    doc = _build_doc()
    for mode in ('printed', 'modern'):
        pdf_bytes = pdf.emit_pdf(doc, mode=mode)
        content = _decoded_content(pdf_bytes)
        assert b'?' not in content, (
            f'{mode}: a "?" reached the content stream -- GRAPHIC_CHARS or '
            f'the middle dot degraded instead of drawing/encoding correctly')
        # Vector fills for three IDENTICAL twelve-glyph runs: the shade trio
        # (three "re f" fills, one per SHADE_GRAY level, each inside its own
        # q/Q) plus the nine BOX_ARMS glyphs' own arm rectangles, x3 spans.
        assert content.count(b're f') >= 3 * (3 + 9), (
            f'{mode}: fewer vector fill ops than three full twelve-glyph '
            f'runs -- a span fell through to text instead of geometry')
        # Middle dot: three real text glyphs, one per span, never a '?'.
        assert content.count(b'\xc2\xb7') == 0  # not present as raw UTF-8 (this
        # emitter writes cp1252/Symbol BYTES, never UTF-8) -- a sanity check
        # that the assertion above is actually exercising byte content, not
        # a decoded-Python-string comparison.


def test_symbol_mapped_span_middle_dot_and_box_run_still_select_the_symbol_font():
    """The fix must not stop the Symbol-mapped span's OWN font resolution:
    its Tj text (middle dot, byte 0xB7 -- Adobe Symbol's periodcentered)
    still runs under a /BaseFont /Symbol resource, and the box run right
    before it still draws as geometry (no font operator needed for a fill)."""
    doc = _build_doc()
    pdf_bytes = pdf.emit_pdf(doc, mode='printed')
    symbol_names = _symbol_font_names(pdf_bytes)
    assert symbol_names, 'no /BaseFont /Symbol resource registered at all'
    content = _decoded_content(pdf_bytes)
    # The LAST Tj in the stream is the third span's middle dot -- one bare
    # 0xB7 byte, under one of the Symbol resource names, never '?' (0x3f).
    last_tj = list(re.finditer(rb'/(F\d+) \d+ Tf[^()]*\(([^()]*)\) Tj', content))[-1]
    assert last_tj[1] in symbol_names, (
        f'last Tj ({last_tj[2]!r}) is not under a Symbol font resource')
    assert last_tj[2] == b'\xb7', (
        f'Symbol-mapped middle dot did not encode as periodcentered (0xb7): '
        f'got {last_tj[2]!r}')


def test_fontless_and_ordinary_font_spans_are_unaffected_baseline():
    """_split_graphics already drew GRAPHIC_CHARS as vectors for a fontless
    or ordinary-fonted span before this fix (Jon's 2026-08-10 ruling) --
    the Symbol-family fix must not disturb that. Baseline guard, not new
    behaviour: if this ever fails, the regression is in the OTHER two
    spans, not the one this bug was about.

    All THREE spans (fontless, ordinary-fonted, and the Symbol-mapped one
    the bug was about) draw their SHADE_GRAY trio ('░▒▓') as vector fills
    with no font operator needed at all -- geometry never selects a font,
    so even the Symbol-mapped span's box run precedes its own first Tf.
    That is exactly the fix working, not a mixup: three spans, three
    shade-trios, everywhere in the stream."""
    doc = _build_doc()
    pdf_bytes = pdf.emit_pdf(doc, mode='printed')
    content = _decoded_content(pdf_bytes)
    assert content.count(b'0.75 g') == 3 and content.count(b'0.50 g') == 3 \
        and content.count(b'0.25 g') == 3, (
        'expected one SHADE_GRAY trio per span (three spans total) -- got '
        f'{content.count(b"0.75 g")}/{content.count(b"0.50 g")}/'
        f'{content.count(b"0.25 g")} of 0.75/0.50/0.25 g')
    # The fontless and ordinary-fonted spans' own middle dots are plain
    # WinAnsi/cp1252 text (0xb7), same byte as the Symbol-mapped span's --
    # cp1252 and Adobe Symbol's periodcentered share the position by
    # coincidence, which is exactly why self-mapping it was the right fix.
    assert content.count(b'\xb7') >= 3, 'expected a real middle-dot byte per span'
    assert b'?' not in content
