"""LJ6DTP parity C5/C6: heading and running-head TYPEFACE resolution.

Two related font-resolution defects, both found by dumping `doc.fonts` and
`doc.styles` against LJ6DTP.WS's own declarations (deep-read 2026-08-23) --
neither is a missing WordStar print ATTRIBUTE (no outline/shadow bit exists
anywhere in this codebase's style-attrs bitmap, core.py's `_parse_style_
library`), both are a declared font-resolution property the PRINTED emitter
silently dropped:

C6 -- the running head ("LJ6DTP Desktop-Publishing PDF - N") renders in a
hardcoded Courier. The real `.h1` dot command opens with its own type-2 Font
block (WSFORMAT.TXT symmetric type 2: width/height/typestyle, contributing
no bytes of its own to the cleaned stream, just a `('font', idx)` mark) --
LJ6DTP's own is Antique Olive, proportional, 13pt. `core.parse_ws` already
decoded this into `doc.fonts` for every OTHER purpose; nothing captured
which entry belonged to the header line, so pdf.py's `_running_ops` had no
way to reach it and fell back to FONTS[(False, False)] (Courier) uncondi-
tionally. `doc.header_fonts`/`footer_fonts` (new: {line: doc.fonts index or
None}, mirroring headers/footers' own "final state" convention) close that
gap; `_running_ops` now resolves family through `_pdf_family`, the same
function a body span's own 'fontN' tag already used, and decodes the head's
typed toggle bytes through `emit.hf_runs` (already used by Modern/RTF for
this exact text, never before by Printed) instead of drawing them as
literal control characters.

C5 -- the section headings (Features, Files, Using LJ6DTP.PDF, ...) render
solid black bold sans; real WS7 (gpcl6-renders/LJ6DTP-p1.png, at 300dpi) is
a much LIGHTER, textured face. The document's "Section Heading Font" style
(doc.styles slot 15) declares `colour: 3` -- LJ6DTP's own palette (pdf.py's
`_COLOUR_GRAY_LJ6DTP`, already used for the page-5 shading-percentage demo)
maps that to 50% gray, which a real LaserJet halftone-screens into exactly
the light, patterned look the paper shows -- the SAME simplification
already ruled acceptable there (flat gray, not a real dot screen, to avoid
viewer moire) now reached through the SAME merge point `core.
effective_span_styles` already uses for a style's own declared bold
(`block.style_attrs`) -- `block.style_colour` was simply never read by
anything downstream. Family/weight (Helvetica-Bold) were ALREADY correct
before this fix; only the colour was missing.
"""
import re

import pytest

from ctrlkd import core, pdf
from ctrlkd.core import Block, Span, effective_span_styles

HARD = b'\x0d\x0a'

# Tier 2 (sawyer): LJ6DTP.WS, one of the ten committed manifest documents
# (tests/SAWYER-CORPUS.md) -- migrated 2026-08-26 from CTRLKD_WS7_DOCS/
# require_ws7, per Jon's "no third bucket" ruling that day.
needs_fixture = pytest.mark.sawyer


def ws7_block(cmd, content=b''):
    """One WS7 symmetrical sequence -- same construction as test_ctrlkd.py's
    `ws7_block` / test_lj6dtp_hp_patterns.py's `_ws_block`."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _font_block(w, h, style):
    """One type-2 Font symmetric block: width (HMI), height (VMI), typestyle,
    then three zeroed 'previous' words (unused by this test)."""
    content = (w.to_bytes(2, 'little') + h.to_bytes(2, 'little') +
               style.to_bytes(2, 'little') + b'\x00' * 6)
    return ws7_block(0x02, content)


PROP_SANS = 49877      # LJ6DTP.WS's own real word for Antique Olive: proportional
                       # bit set, generic_style sans, typestyle_number 213 --
                       # picked over a bare 0x8000 because typestyle_number 0
                       # resolves to the real WSFORMAT name 'LinePrinter', one of
                       # `_pdf_family`'s own MONO_FAMILIES (a fixed-pitch NAME
                       # degrades to Courier regardless of the proportional bit --
                       # correct behaviour there, just the wrong number to pick
                       # for a synthetic PROPORTIONAL fixture).


def _font_map_impl(pdf_bytes):
    """{'Fn': basefont-bytes} from every /Type /Font object, resolved through
    the page's own resource dict (`/Fn <objnum> 0 R`)."""
    out = {}
    for obj_m in re.finditer(rb'(\d+) 0 obj\n<< /Type /Font.*?/BaseFont /(\S+).*?>>',
                             pdf_bytes):
        out[int(obj_m[1])] = obj_m[2]
    # object number -> resource name ('/Fn <objnum> 0 R')
    names = {}
    for m in re.finditer(rb'/(F\d+) (\d+) 0 R', pdf_bytes):
        obj = int(m[2])
        if obj in out:
            names[m[1]] = out[obj]
    return names


def _decoded_streams(pdf_bytes):
    """Every content stream, Flate-inflated -- page content streams are
    always compressed by this emitter, so a literal Tj search must run
    against the DECODED bytes, not the raw file."""
    import zlib
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', pdf_bytes, re.S):
        body = m[1]
        try:
            out.append(zlib.decompress(body))
        except zlib.error:
            out.append(body)          # an uncompressed stream (e.g. a pattern)
    return out


def _tj_font(pdf_bytes, needle):
    """The /Fn token immediately governing the Tj that contains `needle`,
    searched across every decoded content stream."""
    pat = re.compile(rb'/(F\d+) (\d+) Tf[^()]*\(' + re.escape(needle) + rb'[^()]*\)')
    for stream in _decoded_streams(pdf_bytes):
        m = pat.search(stream)
        if m:
            return m[1]
    raise AssertionError('%r not found in any Tj' % needle)


# --------------------------------------------------------------- C6, synthetic

def _doc_with_header_font():
    driver = ws7_block(0x00, b'pLJ6DTP\x00\x00\x00\x80')
    font = _font_block(207, 280, PROP_SANS)          # 14pt proportional sans
    body = (b'.h1 ' + font + b'Running Title #' + HARD +
            b'Body text, plain and ordinary and long enough to be real.' + HARD)
    return core.parse_ws(driver + body)


def _doc_with_plain_header():
    body = (b'.h1 Plain Title #' + HARD +
            b'Body text, plain and ordinary and long enough to be real.' + HARD)
    return core.parse_ws(ws7_block(0x00) + body)


def test_header_font_block_is_captured_on_the_document():
    """Register C6: a `.h1` line's OWN type-2 Font block resolves into
    doc.header_fonts, the same doc.fonts entry a body span's 'fontN' tag
    would point at -- not silently dropped as it was before this fix."""
    doc = _doc_with_header_font()
    idx = doc.header_fonts.get(1)
    assert idx is not None
    entry = doc.fonts[idx]
    assert entry['proportional'] is True
    assert entry['generic_style'] == 'sans'
    assert entry['points'] == 14.0


def test_header_with_no_font_block_records_none():
    doc = _doc_with_plain_header()
    assert doc.header_fonts.get(1) is None
    assert doc.footer_fonts == {}


def test_printed_header_uses_the_declared_font_not_hardcoded_courier():
    doc = _doc_with_header_font()
    out = pdf.emit_pdf(doc, mode='printed')
    fname = _tj_font(out, b'Running')
    basefont = _font_map_impl(out)[fname]
    assert basefont == b'Helvetica', (
        'a .h1 that declares a proportional sans font must render its '
        'running head in that family, not Courier')


def test_printed_header_toggle_bytes_do_not_reach_the_page_as_control_chars():
    """The same LJ6DTP hazard test_writer.py's Modern/RTF test guards
    (`test_running_head_toggle_bytes_become_styles_not_glyphs`), now for
    Printed: a font-carrying head must ALSO decode via hf_runs, not draw
    raw \\x02 bytes as literal characters."""
    driver = ws7_block(0x00, b'pLJ6DTP\x00\x00\x00\x80')
    font = _font_block(207, 280, PROP_SANS)
    body = (b'.h1 ' + font + b'\x02Bold Title\x02 #' + HARD +
            b'Body text, plain and ordinary and long enough to be real.' + HARD)
    doc = core.parse_ws(driver + body)
    out = pdf.emit_pdf(doc, mode='printed')
    streams = _decoded_streams(out)
    assert not any(b'\x02' in s for s in streams)
    assert any(b'Bold' in s for s in streams)


def test_printed_header_with_no_font_block_is_byte_identical_to_courier_path():
    """No font declared on this line (the overwhelmingly common case, every
    document that never opens a `.h#`/`.f#` with a font block): still one
    Tj, the whole string, Courier -- the new path never fires here."""
    doc = _doc_with_plain_header()
    out = pdf.emit_pdf(doc, mode='printed')
    fname = _tj_font(out, b'Plain Title')
    basefont = _font_map_impl(out)[fname]
    assert basefont == b'Courier'


@needs_fixture
def test_real_lj6dtp_header_font_is_antique_olive_proportional_sans(require_sawyer_doc):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    idx = doc.header_fonts.get(1)
    assert idx is not None
    entry = doc.fonts[idx]
    assert entry['proportional'] is True
    assert entry['generic_style'] == 'sans'
    assert 'Antique Olive' in (entry['typestyle_name'] or '')


@needs_fixture
def test_real_lj6dtp_printed_header_is_helvetica_not_courier(require_sawyer_doc):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    out = pdf.emit_pdf(doc, mode='printed')
    fname = _tj_font(out, b'LJ6DTP Desktop-Publishing PDF')
    basefont = _font_map_impl(out)[fname]
    assert basefont == b'Helvetica'


# --------------------------------------------------------------- C5, unit

def test_style_colour_merges_into_governed_spans():
    block = Block('para', heading=2, style_colour=3, style_attrs=frozenset({'b'}))
    span = Span('Features', frozenset({'font38'}))
    styles = effective_span_styles(span, block, heading_bold=True)
    assert 'colour3' in styles
    assert 'b' in styles


def test_style_colour_zero_adds_no_tag():
    """Colour 0 is explicit Black in the style record, but every known
    driver palette (and RTF's own colour-0-is-automatic convention, emit.py)
    already treats it identically to 'no colour tag at all' -- merging it
    would add a colourN class/control word to nearly every plain paragraph
    in a styled document for zero visual change."""
    block = Block('para', style_colour=0)
    span = Span('plain text', frozenset())
    styles = effective_span_styles(span, block)
    assert not any(t.startswith('colour') for t in styles)


def test_explicit_inline_colour_overrides_style_default():
    """An inline type-1 colour change mid-run (a span's own 'colourN' tag)
    must win over the paragraph style's declared default -- never the
    reverse."""
    block = Block('para', style_colour=3)
    span = Span('white knockout', frozenset({'colour15'}))
    styles = effective_span_styles(span, block)
    assert 'colour15' in styles
    assert 'colour3' not in styles


def test_no_style_colour_is_unaffected():
    block = Block('para')
    span = Span('plain', frozenset({'b'}))
    styles = effective_span_styles(span, block)
    assert styles == frozenset({'b'})


@needs_fixture
def test_real_lj6dtp_section_heading_style_declares_colour_3(require_sawyer_doc):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    heading_style = next(s for s in doc.styles if s['name'] == 'Section Heading Font')
    assert heading_style['colour'] == 3


@needs_fixture
def test_real_lj6dtp_printed_features_heading_paints_at_lj6dtp_gray(require_sawyer_doc):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    out = pdf.emit_pdf(doc, mode='printed')
    # The heading's own `g` (gray fill) op must land in the stream shortly
    # before its Tj -- same page, same text object run.
    stream = next(s for s in _decoded_streams(out) if b'(Features)' in s)
    idx = stream.find(b'(Features)')
    window = stream[max(0, idx - 200):idx]
    assert b'0.50 g' in window, (
        'Section Heading Font declares colour 3 (50%% gray under the LJ6DTP '
        'palette) -- Features must paint at that gray, not solid black')
