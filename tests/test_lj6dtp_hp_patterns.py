"""LJ6DTP parity C3: HP1-HP6 render as real, visually distinct fill
patterns instead of the same flat mid-gray.

LJ6DTP.WS page 5 ("Color" Mappings) exists solely to show off the driver's
colour palette -- seven shading densities (colour1-7) and six HP fill
patterns (colour9-14, HP1 horizontal / HP2 vertical / HP3 diagonal `/` /
HP4 diagonal `\\` / HP5 crosshatch `+` / HP6 dense crosshatch `X`), each
sample printed as a run of solid block characters. Before this round,
`pdf._COLOUR_GRAY_LJ6DTP` mapped every one of colour9-14 to the SAME flat
0.5 gray -- the table's own comment admitted it ("approximated mid-gray --
texture is not expressible without pattern objects"). Real WS7 (confirmed
against ws7-prints/gpcl6-renders/LJ6DTP-p5.png) prints six patterns that are
each other's opposite in direction and weave, not six identical gray bars.

The fix: colour9-14 now paint with real PDF tiling patterns
(`pdf._LJ6DTP_HP_PATTERNS`, `/PatternType 1 /PaintType 1`) instead of a flat
gray -- registered as page /Resources /Pattern objects, selected with
`/Pattern cs /Pn scn`, exactly parallel to how /Font and /XObject already
work in this emitter. colour1-7 (the shading percentages) are UNCHANGED --
they already read as seven distinct densities at a flat gray (verified
against the same reference render), so that half of the page was never the
reported defect; see the updated comment on `_COLOUR_GRAY_LJ6DTP` for the
full reasoning.

No fixture dependency: these documents are built the same way
test_ctrlkd.py's `test_modern_applies_lj6dtp_character_substitutions` builds
its driver-declaring doc, and test_flags_toc_inline.py's `_colour_doc`
builds its colour-block doc -- a WSFORMAT type-0 header block (driver name)
plus WSFORMAT type-1 colour-change blocks (fg, bg), fed straight to
`core.parse_ws`.
"""
import re

from ctrlkd import core, pdf

HARD = b'\x0d\x0a'


def _ws_block(cmd, content=b''):
    """One WS5+ symmetric sequence: `1D <jump> <cmd> <content> <jump> 1D`.
    Same construction as test_ctrlkd.py's `_ws_block` / tools/ws_fixture.py."""
    jump = len(content) + 4
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([cmd]) + content + j + b'\x1d'


def _colour_block(fg, bg=0):
    return _ws_block(0x01, bytes([fg, bg]))


def _hp_rows_doc(driver_header):
    """One line per HP index (9-14), each a run of plain text under its
    own colour, restored to Black (0) afterward -- the same colour-run
    shape as LJ6DTP.WS's own page 5 rows (real WS7 uses block characters;
    plain text exercises exactly the same colour/pattern-fill code path)."""
    body = b''
    for idx in range(9, 15):
        body += _colour_block(idx) + b'X' * 10 + _colour_block(0) + HARD
    return core.parse_ws(driver_header + body)


def _pattern_stream_bodies(pdf_bytes):
    """{obj_num: stream-bytes} for every /PatternType 1 object."""
    out = {}
    for m in re.finditer(
            rb'(\d+) 0 obj\n<< /Type /Pattern /PatternType 1.*?>>'
            rb'\nstream\n(.*?)\nendstream', pdf_bytes, re.S):
        out[int(m[1])] = m[2]
    return out


def test_hp_indices_no_longer_collapse_to_one_flat_gray():
    """The bug, named directly: colour9-14 used to all map to 0.5 in
    `_COLOUR_GRAY_LJ6DTP`. They must not be there at all any more (patterns
    render them now), and the six patterns must not all be the same fill."""
    for idx in range(9, 15):
        assert idx not in pdf._COLOUR_GRAY_LJ6DTP
    assert sorted(pdf._LJ6DTP_HP_PATTERNS) == [9, 10, 11, 12, 13, 14]
    contents = [pdf._LJ6DTP_HP_PATTERNS[idx][2] for idx in range(9, 15)]
    assert len(set(contents)) == 6                # six DISTINCT geometries


def test_lj6dtp_document_emits_six_distinct_pattern_fills():
    driver = _ws_block(0x00, b'pLJ6DTP\x00\x00\x00\x80')
    doc = _hp_rows_doc(driver)
    assert doc.meta['printer_driver'] == 'LJ6DTP'
    out = pdf.emit_pdf(doc, mode='printed')

    # Every HP index got its own /Pattern object, and no two share a stream.
    bodies = _pattern_stream_bodies(out)
    assert len(bodies) == 6
    assert len({v for v in bodies.values()}) == 6

    # The page content actually selects all six pattern names via the
    # Pattern colour space, one per HP row.
    used = set(re.findall(rb'/Pattern cs /(P\d+) scn', out))
    assert used == {b'P9', b'P10', b'P11', b'P12', b'P13', b'P14'}

    # Every pattern object is wired into the page's own /Resources /Pattern
    # dict (not just floating, unreferenced objects).
    assert re.search(rb'/Pattern << (?:/P\d+ \d+ 0 R ?){6}>>', out)


def test_non_lj6dtp_driver_keeps_colour_indices_opaque():
    """Same document, a driver this table does not know -- the ruled
    behaviour (`_COLOUR_GRAY_LJ6DTP`'s own docstring) is that colour9-14
    stay unrendered: no Pattern resources, no pattern colour-space
    operators, byte-for-byte as if HP patterns had never been added."""
    driver = _ws_block(0x00, b'pLASERJET\x00\x00\x00\x80')
    doc = _hp_rows_doc(driver)
    assert doc.meta['printer_driver'] == 'LASERJET'
    out = pdf.emit_pdf(doc, mode='printed')
    assert b'/Pattern' not in out
    assert b'scn' not in out
    assert b'PatternType' not in out
