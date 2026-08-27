"""Style-driven leading in Printed PDF -- WS7 paragraph styles carry their
own line height (`line_height_vmi`, core.py's style-record parse, field
offset 88), but nothing consumed it: Printed PDF's y-advance
(`_page_stream`'s `y -= line.lead or lead`) only ever read `.lh` dot-command
state (`Line.lead_48`), so every style-governed document rendered at the
document's uniform default leading regardless of its own styles' font
sizes -- 46/46 baseline gaps measured 12.0pt on a real styled document that
should NOT have been uniform.

MEASURED ORACLE (real WordStar 7, captured via dosbox-x's LaserJet driver,
2026-08-20 -- decoded with tools/pcl_text.py's PCL decipoint grammar; kept
out of this repo per CLAUDE.md's synthetic-fixtures-only rule, so every test
below re-encodes the SAME behavior as constructed WS7 style-library bytes,
`_style_record`/`_style_library`/`_style_ref` mirroring test_ctrlkd.py's/
test_modern_lint.py's own trimmed copies): a Title/Author style at 16pt and
a Body style at 12pt, both `line_height_vmi == -2` ("auto", the only value
either style ever carried) produced PDF baseline gaps of exactly 19.2pt
(16pt line to 16pt line), 14.4pt (12pt line to 12pt line), and 33.6pt across
a blank line sitting between a 16pt block and the following 12pt block
(19.2 + 14.4 -- the blank line advances at the PRECEDING block's own
leading, not the next block's).

Unit for -2 ("auto"): 1.2 x the style's own font size -- matches this
codebase's own `MODERN_LINE = 1.2` constant (pdf.py) for the same "auto/
single-spacing" concept in Modern layout, and is exactly what the oracle
measured.

Unit for an explicit positive vmi: WSFORMAT.WS's own format-spec text
("Word: Font height in VMIs (1/1440ths)") documents VMI as the SAME
1/1440in unit a font's own height word uses, so vmi/20.0 is points -- the
identical conversion `_font_entry` already applies to a font's height word.
Corroborated independently by pdf.py's own footnote-area comment ("VMI 240
= one blank line at 6 LPI", i.e. 240/20 = 12.0pt) and by WARPRAYR.WS, where
vmi=240 recurs UNCHANGED across styles of differing font size (16pt and
12pt) -- an absolute count, not a per-font multiplier. UNCONFIRMED against a real WS7 print, though: no
oracle exists for a document that actually uses an explicit vmi (flagged
in pdf._style_lead_pt's own docstring).
"""
import re

from ctrlkd import core, pdf, emit

HARD = b'\x0d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


# ---------------------------------------------------- style-library helpers
# Trimmed local copy with FONT + line-height fields (offsets 0/2/4 and 88) --
# see test_ctrlkd.py's/test_modern_lint.py's own trimmed `_style_record`s for
# the margin/tab-focused siblings; this file needs the font/vmi fields they
# don't carry.

def _style_record(font=None, vmi=None, just=0, attrs_on=0):
    """One 102-byte WS7 style record. `font` is (width_1800, height_1440,
    typestyle) or None (0xFFFF -- 'inherited', core.py's own f0==-1 test).
    `vmi` is the RAW word to store at offset 88 (0xFFFF=-1 'inherit',
    0xFFFE=-2 'auto', or an explicit positive count); None means 0xFFFF."""
    rec = bytearray(102)

    def put_u(off, val):
        rec[off:off + 2] = (val & 0xFFFF).to_bytes(2, 'little')

    if font is None:
        put_u(0, 0xFFFF)
    else:
        put_u(0, font[0])
        put_u(2, font[1])
        put_u(4, font[2])
    put_u(10, 0xFFFE)          # left margin: inherit
    put_u(12, 0xFFFE)          # right margin: inherit
    put_u(14, 0xFFFE)          # para margin: inherit
    rec[18] = 0xFF
    rec[19] = 0xFF              # tabs: inherit
    rec[86] = just % 256
    rec[87] = 1                 # wrap on
    put_u(88, 0xFFFF if vmi is None else vmi)
    rec[90] = 0xFF               # line spacing: inherit
    rec[91:93] = attrs_on.to_bytes(2, 'little')
    rec[95] = 0xFF               # colour: inherit
    return bytes(rec)


def _style_library(entries):
    n = len(entries)
    items = b''
    records = b''
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
    base_bytes = base.to_bytes(4, 'little')
    doc[4 + 12:4 + 16] = base_bytes
    return bytes(doc)


def _line_ys(out):
    """Distinct baseline Y positions, in the order text was drawn -- each
    PDF text object's own Td y, deduplicated for the several BT..ET blocks
    (font/colour changes) a single PageLine can split into."""
    ys = [float(y) for _, y in re.findall(rb'([\d.]+) ([\d.]+) Td \(', out)]
    uniq = []
    for y in ys:
        if not uniq or abs(uniq[-1] - y) > 1e-6:
            uniq.append(y)
    return uniq


def _gaps(doc, mode='printed'):
    out = pdf.emit_pdf(doc, mode=mode)
    ys = _line_ys(out)
    return [round(ys[i - 1] - ys[i], 4) for i in range(1, len(ys))]


# 16pt / 12pt styles, both auto (-2) -- the ONLY vmi value LYING.WS's real
# styles ever carry.
_AUTO_16PT = _style_record(font=(180, 320, 0), vmi=0xFFFE)   # 320/20 = 16.0pt
_AUTO_12PT = _style_record(font=(180, 240, 0), vmi=0xFFFE)   # 240/20 = 12.0pt


def test_auto_vmi_leading_matches_measured_lying_gap_profile():
    """Two consecutive lines under the SAME auto-leading style: 16pt style
    -> 19.2pt gap, 12pt style -> 14.4pt gap. Pins the oracle's own numbers
    (LYING.pcl: Title->Author 192 decipoints, Body-to-Body 144 decipoints)."""
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('Big', _AUTO_16PT), ('Body', _AUTO_12PT)])
    body = (_style_ref(2) + b'First big line.' + HARD + b'Second big line.' + HARD
            + _style_ref(3) + b'First body line.' + HARD + b'Second body line.' + HARD)
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    assert doc.blocks[0].line_height_vmi == -2
    assert doc.blocks[0].style_font_pt == 16.0
    gaps = _gaps(doc)
    assert gaps[0] == 19.2                    # within the 16pt block
    assert gaps[-1] == 14.4                   # within the 12pt block


def test_blank_line_between_styles_advances_at_its_own_blocks_leading():
    """The exact structural shape of LYING.WS itself: a style-ref, one
    text line, a BLANK line, then a style switch to a smaller style and
    its own text line. core.py's own blank-line handling (the 'para' sep
    + `doc.blocks[-1].kind == 'para'` attach) puts the blank Line on the
    OLD (16pt) block, so it advances by 19.2pt, not the new block's 14.4pt
    -- the combined gap across the blank line is 19.2 + 14.4 = 33.6pt,
    exactly LYING.pcl's measured 336-decipoint gap ("by Mark Twain" to
    "Essay, For Discussion...")."""
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('Big', _AUTO_16PT), ('Body', _AUTO_12PT)])
    body = (_style_ref(2) + b'Last big line.' + HARD + HARD
            + _style_ref(3) + b'First body line.' + HARD)
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    # the blank Line landed on the OLD (16pt) block, confirming which style
    # the measured 19.2+14.4 split is attributed to
    assert doc.blocks[0].style_name == 'Big'
    assert len(doc.blocks[0].lines) == 2                # text line + blank
    assert doc.blocks[0].lines[1].spans == []
    gaps = _gaps(doc)
    assert gaps == [33.6]


# 16pt / 12pt styles with an EXPLICIT (not auto) vmi=240 -- WARPRAYR.WS's
# real Author/Body style records (240/20 = 12.0pt: too small for the 16pt
# style, exactly right for the 12pt one).
_EXP240_16PT = _style_record(font=(180, 320, 0), vmi=240)
_EXP240_12PT = _style_record(font=(180, 240, 0), vmi=240)


def test_entering_line_after_too_small_vmi_style_uses_raw_not_fallback():
    """Fix C (b26-print-fidelity-2, WARPRAYR.WS): the SAME structural shape
    as the sibling LYING-shaped test above (a style-ref, one text line, a
    BLANK line, a style switch, the next style's own text line), but the
    OUTGOING style has an EXPLICIT vmi too small for its own font
    (WARPRAYR's Author: vmi=240=12pt on a 16pt font -- Finding B's
    fallback makes ITS OWN first line's entry gap 19.2pt). Its trailing
    BLANK line does NOT also take that 19.2pt fallback (nothing to clip,
    see `_style_lead_pt`'s `raw` note): it advances at the RAW, unfallen-
    back vmi/20 (12.0pt) -- and the entering Body line (vmi=240=12pt,
    fits its OWN font, no fallback needed either) advances at its own
    12.0pt too, no floor needed (12.0 >= 12.0 already). Combined:
    12.0 + 12.0 = 24.0pt -- WARPRAYR.pcl's measured gap ("by Mark Twain"
    to "It was a time...", 240 decipoints), NOT 19.2 + 12.0 = 31.2 (the
    pre-Fix-C bug, treating Finding B's fallback as block-wide)."""
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('Author', _EXP240_16PT), ('Body', _EXP240_12PT)])
    body = (_style_ref(2) + b'The byline itself.' + HARD + HARD
            + _style_ref(3) + b'First body line.' + HARD)
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    assert doc.blocks[0].line_height_vmi == 240
    assert len(doc.blocks[0].lines) == 2            # text line + blank
    assert _gaps(doc) == [24.0]


def test_entering_line_after_auto_style_is_floored_at_the_auto_lead():
    """Fix C's OTHER direction, WARPRAYR's Quote -> Body (a genuinely
    AUTO style, vmi=-2, into an EXPLICIT vmi=240=12pt style that fits its
    own font): the entering Body line's own 12.0pt gap is FLOORED at the
    outgoing Quote block's own 14.4pt (1.2 x its 12pt font) -- an
    EXPLICIT style's first line never sits closer to what preceded it
    than that content's own natural lead was. Quote's trailing blank
    advances at its own unambiguous 14.4pt (auto has no raw-vs-fallback
    distinction). Combined: 14.4 + 14.4 = 28.8pt -- WARPRAYR.pcl's
    measured gap ('Thunder thy clarion...' to 'Then came the "long"
    prayer...', 288 decipoints), NOT 14.4 + 12.0 = 26.4 (the pre-Fix-C
    bug: Body's own entering gap, un-floored)."""
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('Quote', _AUTO_12PT), ('Body', _EXP240_12PT)])
    body = (_style_ref(2) + b'Last quote line.' + HARD + HARD
            + _style_ref(3) + b'First body line.' + HARD)
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    assert _gaps(doc) == [28.8]


def test_entering_an_auto_style_is_never_floored():
    """The negative case the floor must NOT fire for: WARPRAYR's Body ->
    Quote (an EXPLICIT vmi=240=12pt style into a genuinely AUTO one) --
    `_entering_lead_pt`'s own guard only floors a block being entered
    that HAS an explicit vmi; Quote (auto) is entered at its own natural
    14.4pt, never floored up against Body's own outgoing 12.0pt (which
    wouldn't raise it anyway) or down. Body's trailing blank advances at
    its own 12.0pt (vmi=240 fits its 12pt font -- no raw-vs-fallback
    distinction possible here either). Combined: 12.0 + 14.4 = 26.4pt --
    WARPRAYR.pcl's measured gap ('...that tremendous invocation--' to
    '"God the all-terrible!...', 264 decipoints), unchanged by Fix C."""
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('Body', _EXP240_12PT), ('Quote', _AUTO_12PT)])
    body = (_style_ref(2) + b'Last body line.' + HARD + HARD
            + _style_ref(3) + b'First quote line.' + HARD)
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    assert _gaps(doc) == [26.4]


def test_explicit_vmi_is_absolute_points_unless_too_small_for_its_font():
    """vmi=240 (WSFORMAT.WS: same 1/1440in unit as a font's own height word,
    so 240/20.0 = 12.0pt) recurs unchanged in WARPRAYR.WS's real style
    records at a 12pt font (WARPRAYR's Body) -- the value does not scale
    with the font the way -2/auto
    does, AS LONG AS it is not smaller than the font itself. Finding B
    (b26-print-fidelity-2, WARPRAYR.pcl): the SAME 240 at a 16pt font
    (WARPRAYR's Author/byline) measures 19.2pt on real WS7 -- 1.2 x 16, the
    SAME auto formula an unset vmi gets on that line, because 12pt leading
    cannot hold 16pt type. Absolute ONLY when it fits; a fallback, not a
    scaling rule, so a vmi genuinely larger than its font (never measured,
    but not this rule's business to invent a ceiling for) would stay
    absolute too -- see `_style_lead_pt`'s own docstring for the full
    evidence trail, including the reverted vmi==240-always-auto
    over-generalisation this fix replaces with a narrower, font-relative one."""
    exp16 = _style_record(font=(180, 320, 0), vmi=240)
    exp12 = _style_record(font=(180, 240, 0), vmi=240)
    body = _style_ref(2) + b'Line one.' + HARD + b'Line two.' + HARD
    for rec, want in ((exp16, 19.2), (exp12, 12.0)):
        lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                              ('Exp', rec)])
        doc = core.parse_ws(_doc_with_style_library(body, lib))
        assert doc.blocks[0].line_height_vmi == 240
        assert _gaps(doc) == [want]


def test_style_auto_with_no_font_of_its_own_falls_back_to_document_size():
    """A style can set line_height_vmi=-2 (auto) while declaring no font of
    its own (font=None -> core.py's f0==-1 'inherit' sentinel, so
    Block.style_font_pt stays None) -- `_style_lead_pt` falls back to the
    document's own printed SIZE (the .cw-derived default, 12pt here) rather
    than crashing or silently picking an arbitrary size."""
    rec = _style_record(font=None, vmi=0xFFFE)
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('AutoNoFont', rec)])
    body = _style_ref(2) + b'Line one.' + HARD + b'Line two.' + HARD
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    assert doc.blocks[0].style_font_pt is None
    assert _gaps(doc) == [14.4]              # 1.2 x document default 12pt


def test_lh_dot_command_overrides_style_auto_leading():
    """No corpus evidence exists for how real WS7 arbitrates a style's own
    vmi against an ACTIVE `.lh` dot command, so the fix stays conservative:
    a document that uses `.lh` at all (core.meta['page']['lh_source'] ==
    'file') keeps the pre-existing `.lh`-driven leading UNCHANGED, even
    inside a styled block. `.lh 20` is 20/48in = 30pt, which must win over
    the 16pt style's own 19.2pt auto leading."""
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('Big', _AUTO_16PT)])
    body = b'.lh 20' + HARD + _style_ref(2) + b'Line one.' + HARD + b'Line two.' + HARD
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    assert doc.meta['page']['lh_source'] == 'file'
    assert _gaps(doc) == [30.0]


def test_styleless_doc_leading_is_unchanged():
    """A document with no style library at all (WS4, or a WS7 file that
    never selected a style) must render at exactly the pre-existing
    document-default leading -- 12.0pt (`.lh` default 8/48in x 1.5) --
    UNCHANGED by this fix."""
    doc = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'Line one.' + HARD + b'Line two.' + HARD + b'Line three.' + HARD)
    assert doc.blocks[0].line_height_vmi is None
    assert _gaps(doc) == [12.0, 12.0]


def test_style_auto_leading_never_reaches_modern_pdf():
    """Modern PDF already spaces lines by their own font size (a wholly
    separate, pre-existing MODERN_LINE=1.2 x size mechanism, keyed off each
    span's font tag, not `Block.line_height_vmi`) -- so it is not enough to
    check for a particular number; two documents that share EVERY byte
    except `line_height_vmi` (-2 'auto' vs 240 'explicit', which printed
    mode renders at two different leadings, 14.4pt vs 12.0pt -- proven
    below) must render to BYTE-IDENTICAL Modern PDF output, because Modern
    never reads that field at all. A 12pt style font (not WARPRAYR's own
    16pt byline): Finding B (b26-print-fidelity-2) makes vmi=240 fall back
    to the SAME 1.2x-font auto leading a 16pt font gets (see the sibling
    "too small for its font" test), which would make this test's own two
    numbers coincide and stop proving printed reads the field at all."""
    def doc_with_vmi(vmi):
        rec = _style_record(font=(180, 240, 0), vmi=vmi)
        lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                              ('Big', rec)])
        body = _style_ref(2) + b'Line one.' + HARD + b'Line two.' + HARD
        return core.parse_ws(_doc_with_style_library(body, lib))

    auto_doc = doc_with_vmi(0xFFFE)     # -2, auto
    explicit_doc = doc_with_vmi(240)    # explicit 12.0pt (fits its 12pt font)

    assert _gaps(auto_doc, mode='printed') == [14.4]
    assert _gaps(explicit_doc, mode='printed') == [12.0]
    assert (pdf.emit_pdf(auto_doc, mode='modern')
            == pdf.emit_pdf(explicit_doc, mode='modern'))


# ============================================================================
# Ruling 2026-08-26 (register row, b33 field notes N2): Printed/Native RTF's
# own `\sl` used to read ONLY `.lh` dot-state (emit.py's `_rtf_block_lead_48`,
# pre-fix), never this file's own style-driven leading -- every document
# above rendered ONE flat `\sl` for its whole body in RTF even though its
# Printed PDF (same document, same functions) already varied it correctly.
# `_rtf_block_lead_48` now delegates to `pdf.resolved_printed_leads_48`,
# which recomputes the SAME per-line precedence (`_lead_pt`/`_style_lead_pt`/
# `_entering_lead_pt`/`_font_lead_pt`) `_doc_to_pagelines` uses for the PDF
# page, collapsed to each block's own first real line -- these tests pin
# that RTF now agrees with the PDF gaps already proven above, in twips
# (1/48in unit * 30 twips/48in-unit, negative/EXACT per `_rtf_sl_twips`).

def _rtf_sl_sequence(r):
    """Every `\\sl` VALUE that actually appears as a direct token in `r`,
    in document order -- the persistence optimisation (`_rtf_emit_para`)
    means a paragraph whose own resolved lead is UNCHANGED from the one
    still in force emits no new token at all, so this is "every point the
    lead changed", not "one entry per paragraph"."""
    return [int(x) for x in re.findall(r'\\sl(-?\d+)\\slmult0 ', r)]


def test_auto_vmi_leading_reaches_printed_rtf_as_two_distinct_sl_values():
    """The exact fixture behind `test_auto_vmi_leading_matches_measured_
    lying_gap_profile` (16pt Title/Author style, 12pt Body style, both
    auto/-2) -- the real LYING.WS/WARPRAYR.WS b33 clipping case: a 16pt
    title on a document whose OWN plain default is 12pt. Pre-fix this was
    a single `\\sl-240\\slmult0` throughout (12pt, clipping the 16pt
    title in Word/TextEdit); now two distinct values, matching the PDF
    gaps already proven above 1:1 (19.2pt/14.4pt * 20 twips/pt)."""
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('Big', _AUTO_16PT), ('Body', _AUTO_12PT)])
    body = (_style_ref(2) + b'First big line.' + HARD + b'Second big line.' + HARD
            + _style_ref(3) + b'First body line.' + HARD + b'Second body line.' + HARD)
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    r = emit.emit_rtf(doc, mode='printed')
    assert _rtf_sl_sequence(r) == [-384, -288]        # 19.2pt, 14.4pt in twips
    assert r'\sl-240\slmult0' not in r                # the pre-fix flat default


def test_explicit_vmi_too_small_for_font_reaches_printed_rtf_too():
    """WARPRAYR.WS's real shape: an EXPLICIT vmi (240=12pt) too small for
    its own 16pt font falls back to the SAME auto formula (Finding B),
    19.2pt -- confirmed at PDF level by
    `test_entering_line_after_too_small_vmi_style_uses_raw_not_fallback`'s
    sibling `test_explicit_vmi_is_absolute_points_unless_too_small_for_
    its_font`; this pins the identical value now reaches RTF's `\\sl`."""
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('Author', _EXP240_16PT), ('Body', _EXP240_12PT)])
    body = (_style_ref(2) + b'The byline itself.' + HARD
            + _style_ref(3) + b'First body line.' + HARD)
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    r = emit.emit_rtf(doc, mode='printed')
    assert _rtf_sl_sequence(r) == [-384, -240]         # 19.2pt fallback, 12.0pt fits


def test_lh_dot_command_overrides_style_auto_leading_in_rtf_too():
    """RTF's own guard must match the PDF one exactly (same conservative
    doctrine, no separate formula): `.lh 20` (30pt) wins over the 16pt
    style's own 19.2pt auto leading -- mirrors
    `test_lh_dot_command_overrides_style_auto_leading` at the PDF layer."""
    lib = _style_library([('WordStar Defaults', None), ('WordStar Defaults', None),
                          ('Big', _AUTO_16PT)])
    body = b'.lh 20' + HARD + _style_ref(2) + b'Line one.' + HARD + b'Line two.' + HARD
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    assert doc.meta['page']['lh_source'] == 'file'
    r = emit.emit_rtf(doc, mode='printed')
    assert _rtf_sl_sequence(r) == [-600]               # 20/48in = 30pt = 600 twips


def test_mid_document_lh_change_produces_two_distinct_rtf_sl_values():
    """A styleless document (no style library at all -- WS4/plain WS7
    shape) whose OWN `.lh` dot command changes MID-DOCUMENT (after body
    text has already begun, so `doc.meta['page']['lh_source']` -- which
    core.py resolves from only a PRE-TEXT `.lh` -- stays 'default'; the
    per-LINE override this test actually exercises is `Line.lead_48`, a
    separate, genuinely stateful mechanism core.py's own comment names
    explicitly: "the per-page checkpoint machinery ... picks this up on
    its own"): RTF's `\\sl` is a paragraph property, so each paragraph's
    own first line's `.lh` state must be reflected, same "ceiling of what
    RTF can express per paragraph" doctrine as the style-driven case
    above. Pre-fix this was already meant to work (round 6's original
    `_rtf_block_lead_48` read `Line.lead_48` directly) -- pinned here
    explicitly because this fix replaces that function's entire body and
    must not regress the case it already handled."""
    body = (b'First paragraph at the document default.' + HARD + HARD
            + b'.lh 16' + HARD
            + b'Second paragraph after the .lh change.' + HARD)
    doc = core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)
    assert len(doc.blocks) == 2                       # a real block boundary
    assert doc.blocks[-1].lines[0].lead_48 == 16.0    # the stateful override landed
    r = emit.emit_rtf(doc, mode='printed')
    # default .lh 8 = 12pt = -240 twips; changed .lh 16 = 24pt = -480 twips
    assert _rtf_sl_sequence(r) == [-240, -480]
