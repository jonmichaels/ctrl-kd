"""A RESOLVED ORDINARY TYPEFACE BEATS THE CHARACTER-SET BITS (ruling 2026-09-16).

A WS5+ font record carries a typestyle word whose low nine bits name a
typeface out of WSFORMAT's own 245-entry table and whose bits 12-13 pick one
of four upper-128 character sets (cp437, cp850, math, symbols). The two are
independent fields. `font_translit_kind` used to let the character-set bits
overrule ANY name that did not itself say "symbol" or "dingbat", so a font
record reading "Courier, math character set" redirected its whole run through
Adobe Symbol's encoding -- and every ordinary Latin letter came out as the
Greek letter sitting at its keyboard position.

That is a real corpus record, not a hypothetical: the front-matter paragraph
styles of a WS7 manuscript in the Sawyer archive carry typestyle word 0x6603
(number 3 = Courier, letter-quality, symbol_map = math) and ten pages of
ordinary English prose rendered as Greek in PDF, RTF, Markdown and the layout
JSON alike. Real WS7's own LaserJet output prints those pages as plain
readable Courier.

THE RULE: the character-set bits are the fallback for a face the name table
cannot resolve (and for the handful of named faces that are themselves
non-text repertoires -- Symbol, ZapfDingbats, Math, PI, Greek...). A resolved
ordinary face wins. Characters that genuinely have no home in the body face
are still rescued one at a time by the per-character fallback
(`char_translit_kind`), which is what that mechanism was built for.

Synthetic fixtures only -- the typestyle words below are transcribed into
constructed bytes, no corpus file is read.
"""
import re
import zlib

import pytest

from ctrlkd import core, emit, emit_layout, pdf
from ctrlkd.symbolmap import font_translit_kind

HARD = b'\x0d\x0a'
PROSE = b'If you choose to depict the physicist on the cover'
# Long enough that the WS5+ text body is unambiguous -- a two-word document
# does not exercise the parse path this test is about.
GREEKABLE = b'alpha beta gamma alpha beta gamma alpha beta gamma'

# typestyle words, built field by field from core._font_entry's own bit table:
#   bits 0-8   typeface number (WSFORMAT's name table)
#   bits 12-13 character set: 0 cp437, 1 cp850, 2 math, 3 symbols
#   bit 14     letter quality
#   bit 15     proportional
MATH_BITS = 2 << 12
COURIER_MATH = 3 | MATH_BITS | 0x4000          # 0x6603, the real corpus word
SYMBOL_MATH = 192 | MATH_BITS | 0x4000         # a genuine Symbol face
DINGBATS_MATH = 82 | MATH_BITS | 0x4000        # ZapfDingbats, bits say 'math'
UNNAMED_MATH = 300 | MATH_BITS | 0x4000        # past the 245-entry name table


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def font_block(style, w=180, h=240):
    """One type-2 Font symmetric block: width (HMI), height (VMI), typestyle,
    then three zeroed 'previous' words."""
    content = (w.to_bytes(2, 'little') + h.to_bytes(2, 'little') +
               style.to_bytes(2, 'little') + b'\x00' * 6)
    return ws7_block(0x02, content)


def doc_in_face(style, text=PROSE):
    return core.parse_ws(ws7_block(0x00) + font_block(style) + text + HARD)


def decoded_streams(pdf_bytes):
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', pdf_bytes, re.S):
        try:
            out.append(zlib.decompress(m[1]))
        except zlib.error:
            out.append(m[1])
    return b'\n'.join(out)


def symbol_resource_names(pdf_bytes):
    obj_font = {int(m[1]): m[2] for m in
                re.finditer(rb'(\d+) 0 obj\s*<< /Type /Font /Subtype /Type1 '
                            rb'/BaseFont /(\S+)', pdf_bytes)}
    return {m[1] for m in re.finditer(rb'/(F\d+) (\d+) 0 R', pdf_bytes)
            if obj_font.get(int(m[2])) in (b'Symbol', b'ZapfDingbats')}


# --------------------------------------------------------------- the verdict

def test_resolved_ordinary_face_ignores_the_character_set_bits():
    entry = {'typestyle_name': 'Courier', 'typestyle_number': 3,
             'symbol_map': 'math'}
    assert font_translit_kind(entry) is None


def test_a_named_symbol_face_still_transliterates():
    """The name is still the specific signal -- unchanged, and the reason the
    name is read BEFORE the bits (a Dingbats row whose coarse bits read 'math'
    must transliterate as Dingbats, not as Greek)."""
    assert font_translit_kind({'typestyle_name': 'Symbol',
                               'typestyle_number': 192,
                               'symbol_map': 'math'}) == 'math'
    assert font_translit_kind({'typestyle_name': 'ZapfDingbats',
                               'typestyle_number': 82,
                               'symbol_map': 'math'}) == 'symbols'


def test_an_unresolved_face_still_falls_back_to_the_bits():
    """The fallback the function's docstring always claimed: a typeface number
    the 245-entry table does not carry has no name to prefer, so the
    character-set bits are all there is."""
    assert font_translit_kind({'typestyle_name': None,
                               'typestyle_number': 300,
                               'symbol_map': 'math'}) == 'math'


def test_a_named_non_text_repertoire_still_falls_back_to_the_bits():
    """'Math', 'PI' and 'Greek' are names for a glyph repertoire, not for a
    typeface a sentence can be set in -- they are not 'ordinary faces' and do
    not win over the bits."""
    for number, name in ((188, 'Math'), (166, 'PI'),
                         (244, 'Greek (PS (Universal Greek))')):
        assert font_translit_kind({'typestyle_name': name,
                                   'typestyle_number': number,
                                   'symbol_map': 'math'}) == 'math', name


# ------------------------------------------------- one rule, every emitter

@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_courier_math_prose_stays_latin_in_every_text_format(mode):
    """Every emitter reads the SAME verdict, so one rule fixes all of them at
    once. Before the ruling each of these carried the Greek transliteration."""
    doc = doc_in_face(COURIER_MATH)
    for name, out in (
            ('text', emit.emit_text(doc, mode)),
            ('markdown', emit.emit_markdown(doc, mode)),
            ('html', emit.emit_html(doc, mode)),
            ('rtf', emit.emit_rtf(doc, mode)),
            ('layout', emit_layout(doc, mode))):
        text = out.decode('utf-8', 'replace') if isinstance(out, bytes) else out
        assert 'If you choose' in text, f'{name}/{mode}: prose is not Latin'
        assert not any('\u0370' <= c <= '\u03ff' for c in text), \
            f'{name}/{mode}: a Greek code point reached the output'


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_courier_math_prose_uses_no_symbol_font_in_the_pdf(mode):
    doc = doc_in_face(COURIER_MATH)
    pdf_bytes = pdf.emit_pdf(doc, mode=mode)
    assert not symbol_resource_names(pdf_bytes), \
        f'{mode}: a Symbol/ZapfDingbats font resource was registered'
    # Printed sets the whole physical line in one Tj, Modern one word per
    # Tj -- the word is what both share.
    assert b'choose' in decoded_streams(pdf_bytes)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_genuine_symbol_face_is_untouched_by_the_ruling(mode):
    """The guard on the other side: a run really set in Symbol still resolves
    to the Symbol resource and still writes that face's own byte codes."""
    doc = doc_in_face(SYMBOL_MATH, text=GREEKABLE)
    pdf_bytes = pdf.emit_pdf(doc, mode=mode)
    assert symbol_resource_names(pdf_bytes), \
        f'{mode}: a real Symbol face lost its Symbol resource'


def test_an_unresolved_face_is_untouched_by_the_ruling():
    doc = doc_in_face(UNNAMED_MATH, text=GREEKABLE)
    kinds = [font_translit_kind(f) for f in doc.fonts]
    assert 'math' in kinds, 'the bits fallback stopped working for unnamed faces'
