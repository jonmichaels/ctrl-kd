"""Round 18 ("flags-toc-inline"): RULINGS-LEDGER.md rows 4 and 10 -- the
last two unbuilt engine features from the 2026-08-17 twelve-point exchange.
Fail-first, same discipline as test_printed_fidelity.py (round 17).
"""
import re

from ctrlkd import core, emit, pdf, info

HARD = b'\x0d\x0a'
SOFT = b'\x8d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _rtf_body_only(r):
    body = r
    for grp in (r'\fonttbl', r'\colortbl', r'\stylesheet', r'\info'):
        i = body.find('{' + grp)
        if i == -1:
            continue
        depth, j = 0, i
        while j < len(body):
            if body[j] == '{':
                depth += 1
            elif body[j] == '}':
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        body = body[:i] + body[j:]
    return body


def _header():
    return ws7_block(0x00, bytes([0x70]) + bytes(15))


# --------------------------------------------------------------- ledger row 10
# Inline 0x01 colour / 0x02 size (symmetric records). Colour: previously
# parsed into `colourN` span tags, read by no emitter at all (register C2).
# Size: previously ALREADY rendered via the two-producer font mechanism
# (round 9) -- this round adds the FLAG to strip it, and adds the missing
# colour half.

def _colour_doc():
    colourblk = ws7_block(0x01, bytes([4, 0]))     # fg=4 (red), bg=0
    return core.parse_ws(_header() + colourblk + b'Red text.' + HARD)


def _size_doc():
    fontblk = ws7_block(0x02, (180).to_bytes(2, 'little')
                        + (480).to_bytes(2, 'little')
                        + (0x8000).to_bytes(2, 'little') + b'\x00' * 6)
    return core.parse_ws(_header() + fontblk + b'Big 24pt text.' + HARD)


def test_inline_colour_renders_in_rtf_with_cga_colour_table():
    doc = _colour_doc()
    r = emit.emit_rtf(doc, mode='modern')
    assert r'{\colortbl' in r
    assert r'\red170\green0\blue0;' in r      # WordStar colour 4 = CGA red
    assert r'\cf5 ' in _rtf_body_only(r)       # colour index 4 -> \cf(4+1)


def test_inline_colour_renders_in_html_with_css_class():
    doc = _colour_doc()
    h = emit.emit_html(doc, mode='modern')
    assert '.ws-colour-4 { color:#aa0000 }' in h
    assert 'class="ws-colour-4"' in h


def test_inline_styling_off_strips_colour_from_rtf_and_html():
    doc = _colour_doc()
    r = emit.emit_rtf(doc, mode='modern', inline_styling=False)
    assert r'\colortbl' not in r and r'\cf' not in r
    h = emit.emit_html(doc, mode='modern', inline_styling=False)
    assert 'ws-colour' not in h


def test_inline_size_already_renders_in_rtf_and_html_pdf():
    """Verifies round 9's own two-producer font mechanism already carries
    an inline (mid-text) size change through -- register row 10 grouped
    this with colour, but the machinery predates this round; only the
    FLAG to strip it is new."""
    doc = _size_doc()
    r = emit.emit_rtf(doc, mode='modern')
    assert r'\fs48' in r    # 24pt * 2 half-points
    h = emit.emit_html(doc, mode='modern')
    assert 'font-size:24pt' in h
    out = pdf.emit_pdf(doc, mode='modern')
    sizes = set(re.findall(rb'/\S+ (\d+) Tf', out))
    assert b'24' in sizes


def test_inline_styling_off_strips_size_but_not_family():
    doc = _size_doc()
    r = emit.emit_rtf(doc, mode='modern', inline_styling=False)
    assert r'\fs48' not in r
    assert r'\f2' in r     # the family switch survives -- not "styling"
    h = emit.emit_html(doc, mode='modern', inline_styling=False)
    assert 'font-size:24pt' not in h


def test_inline_styling_never_strips_a_styles_own_declared_size():
    """A paragraph STYLE's own font field is document formatting, not the
    author's inline styling choice (round 9's OWN two-producer model,
    `offset is None` for a style-derived font entry) -- --inline-styling
    off must not touch it."""
    rec = _style_record_with_font(width=180, height=480, typestyle=0x8000)
    lib = _style_library([('WordStar Defaults', None),
                          ('WordStar Defaults', None),
                          ('Big Style', rec)])
    body = _style_ref(2) + b'Styled big paragraph.' + HARD
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    r = emit.emit_rtf(doc, mode='modern', inline_styling=False)
    assert r'\fs48' in r
    h = emit.emit_html(doc, mode='modern', inline_styling=False)
    assert 'font-size:24pt' in h


def test_inline_styling_never_reaches_pdf_colour_beyond_lj6dtp():
    """No new PDF colour path this round -- confirmed the driver-gated
    mechanism (LJ6DTP only) is untouched and no generic colour rendering
    was added to pdf.py."""
    doc = _colour_doc()
    out = pdf.emit_pdf(doc, mode='modern')
    out_off = pdf.emit_pdf(doc, mode='modern', inline_styling=False)
    assert out == out_off      # the flag makes zero PDF byte difference


# ------------------------------------------------------------- helpers (local
# copies of the style-library fixture builders, matching
# test_printed_fidelity.py's own convention)

def _style_record_with_font(width=None, height=None, typestyle=None,
                            left=1800, just=0):
    rec = bytearray(102)

    def put(off, b):
        rec[off:off + len(b)] = b
    if width is not None:
        put(0, width.to_bytes(2, 'little') + height.to_bytes(2, 'little')
            + typestyle.to_bytes(2, 'little'))
    else:
        put(0, (0xFFFF).to_bytes(2, 'little'))
    put(10, left.to_bytes(2, 'little'))
    put(12, (0xFFFE).to_bytes(2, 'little'))
    put(14, (0xFFFE).to_bytes(2, 'little'))
    rec[18] = 0xFF
    rec[19] = 0xFF
    rec[86] = just % 256
    rec[87] = 1
    put(88, (0xFFFF).to_bytes(2, 'little'))
    rec[90] = 0xFF
    put(91, (0).to_bytes(2, 'little'))
    rec[95] = 0xFF
    return bytes(rec)


def _style_library(entries):
    n = len(entries)
    items, records = b'', b''
    rec_base = 13 + 5 + 33 * n
    for name, rec in entries:
        if name is None:
            items += b'\x3f' * 24 + b'\x00' * 9
            continue
        nm = name.encode().ljust(24, b' ')
        if rec is not None:
            items += (nm + b'\x02' + b'\x00' * 4
                      + (rec_base + len(records)).to_bytes(4, 'little'))
            records += rec
        else:
            items += nm + b'\x00' + b'\x00' * 8
    head = (b'\x1a\x55' + (1).to_bytes(2, 'little') + b'\x01'
            + n.to_bytes(2, 'little') + (102).to_bytes(2, 'little')
            + (13).to_bytes(4, 'little'))
    return head + bytes([n]) + b'\x00' * 4 + items + records


def _style_ref(slot):
    payload = ((0x0200 | slot).to_bytes(2, 'little') + (0x0201).to_bytes(2, 'little')
              + (0x0300).to_bytes(2, 'little') + (0x0201).to_bytes(2, 'little'))
    return ws7_block(0x11, payload)


def _doc_with_style_library(body, library, header=None):
    header = header if header is not None else bytes([0x70]) + bytes(15)
    doc = bytearray(ws7_block(0x00, header) + body)
    base = ((len(doc) + 127) // 128) * 128
    while len(doc) < base:
        doc.append(0x1a)
    doc += library
    doc[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    return bytes(doc)
