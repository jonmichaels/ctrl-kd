"""ctrlkd.pix -- decode Inset Systems .PIX files (WordStar 5.0+'s bundled
"Inset" graphics program) to RGB pixels / PNG.

STATUS: reverse-engineered from a secondary source (the EGFF /
fileformat.info write-up of the Inset PIX format) and validated empirically
against real WordStar-7-archive sample files, THEN against Inset's own
on-screen rendering under dosbox-x ground truth (see the vault's
pix-research/inset-groundtruth/). Jon's ruling after that validation
(2026-08-17): "our PIX conversion is excellent." Validation method for the
compression layer: the vertical run-length decoder is byte-exact -- for
every sample tested, the number of bytes consumed while decoding a tile's
compressed planes equals the tile's declared length in the file's own index
table, with zero slack. That is a very strong correctness signal for
something reverse engineered without vendor source.

KNOWN GOOD:
  - Header + data-item index table parsing (tag/length/offset).
  - mode_data (image info) parsing: dimensions (gcols/grows), bit-plane
    count (gfore), palette bit-depths.
  - Tile_Data parsing and 2D tile-grid reassembly (row-major).
  - Vertical RLE decompression, both single-plane (monochrome) and
    multi-plane (CGA 4-color, EGA 16-color) -- exact byte-consumption
    match on every sample tried.
  - The plane-boundary row-band fix (see decode_pix()'s inline comment):
    the bottom row-band, when the image height isn't a multiple of the
    tile height, only has real encoded data for the rows that truly exist
    -- asking the plane decoder for more rows than that reads into the
    next plane's bytes and corrupts every subsequent plane in the tile.
    Byte-exact-consumption checks alone could not catch this (the tile's
    TOTAL byte count still matched either way); it was caught by visual
    inspection and fixed by tracking each tile's true row count
    separately from its nominal (padded) tile height.
  - Palette byte -> RGB scaling, settled against Inset/dosbox-x ground
    truth (see build_rgb_palette()'s docstring for the full account):
    the asymmetric EGA DAC formula (170*bit0 + 85*bit1, NOT a uniform
    value*85 ramp) and the CGA corrupted-duplicate-slot repair (real
    files sometimes store a duplicate palette slot where hardware wants
    a fourth, distinct member of one of the four canonical CGA families
    -- repaired by family completion, not trusted verbatim).

NOT FULLY VALIDATED / OPEN QUESTIONS:
  - "Text mode" / alphanumeric PIX files (mode_data htype bit 0 == 0) are
    detected but NOT decoded -- no local sample of this kind was found to
    test against (every local .PIX sample decoded as bitmap-type). The
    WordStar 7 manual documents that text-mode .PIX files exist (captured
    from a text-mode screen) and are NOT previewable in WordStar either,
    so this may be an acceptable scope cut, not just a gap.
  - Multi-vertical-tile-strip images (Tile_Data stp_cols > 1, i.e. a 2-D
    grid of tiles as opposed to one column of vertically stacked strips)
    were exercised on MAN.PIX/PC.PIX/SYMBOLS.PIX (2x2 grid) and
    EGACHART.PIX/EGALOGOS.PIX (6x5 grid) and decoded correctly by
    inspection, but note the vendor's own 2005 open-source pix2pcx
    converter (Ed Crenshaw) explicitly does NOT support this case ("Right
    now the program handles pix files which consist of horizontal tiles
    only... If an input file with more than one vertical tile is
    processed, an error message is printed") -- so this may handle MORE
    cases than the one surviving open-source converter, but that also
    means there is no independent tool to cross-check it against for
    those files.
  - Plane-to-color-index bit order (plane 0 = LSB of the index) is a
    reasonable guess consistent with correct-looking output, cross-
    checked against ground truth but not against a written spec.

Format summary (see the long comment above for caveats):

  Header (4 bytes):
    WORD RevisionLevel        (observed: 3)
    WORD DataItemsInTable

  Index table (8 bytes * DataItemsInTable), each entry:
    WORD DataID     (0=image info, 1=palette, 2=tile info, 0x11=print
                      options, 0x8000+n = bitmap data for tile n)
    WORD DataLength
    LONG DataLocation (absolute file offset)

  Image info (DataID 0), byte offsets within its own blob (empirically
  determined -- differs from the field list published by some secondary
  sources by a constant +4 byte offset for reasons not fully understood,
  possibly an undocumented/reserved field):
    offset  0: hmode  (BYTE)
    offset  1: htype  (BYTE, bit0: 0=alphanumeric/text, 1=bitmap)
    offset 18: gcols  (WORD) -- image width in pixels
    offset 20: grows  (WORD) -- image height in pixels
    offset 22: gfore  (BYTE) -- number of bitplanes (log2 of color count)
    offset 23: prepal (BYTE)
    offset 24: lodpal (BYTE)
    offset 25: lintens (BYTE) -- palette bits for intensity channel
    offset 26: lred    (BYTE) -- palette bits for red channel
    offset 27: lgreen  (BYTE) -- palette bits for green channel
    offset 28: lblue   (BYTE) -- palette bits for blue channel

  Tile info (DataID 2), 8 bytes:
    WORD page_rows  -- rows per tile
    WORD page_cols  -- columns per tile (multiple of 8)
    WORD stp_rows   -- tile rows (vertical tile count)
    WORD stp_cols   -- tile columns (horizontal tile count)
    Total tiles = stp_rows * stp_cols, numbered row-major from the
    upper-left (tile IDs are 0x8000 | tile_number).

  Palette (DataID 1), 4 bytes * 16 entries:
    BYTE intensity, BYTE red, BYTE green, BYTE blue (small integers,
    scale is per lintens/lred/lgreen/lblue bit-depths above)

  Per-tile bitmap data: gfore planes stored sequentially. Each plane is
  page_rows scanlines of (page_cols/8) bytes, vertically RLE-compressed:
    - row 0: stored raw, uncompressed.
    - row N>0: preceded by ceil(row_bytes/8) "compression bytes" forming a
      bitmask (MSB-first) with one bit per byte position in the row (1 =
      this byte differs from the previous row and is present next in the
      stream; 0 = byte is unchanged, copy from previous row).
  Combine plane bits per pixel: index = sum(plane_bit[p] << p for p in
  range(gfore)); look up index in the palette.

API:
    decode(data: bytes) -> (width, height, rgb_rows)
        rgb_rows is a tuple of `height` rows, each a tuple of `width`
        (r, g, b) tuples -- decoded to trueread pixels regardless of the
        source bit depth (mono/CGA/EGA).
    to_png(data: bytes) -> bytes
        PNG-encoded bytes (stdlib zlib/struct only -- no third-party
        dependencies, same constraint as the rest of ctrl-kd).

Raises PixFormatError (a malformed or unsupported-shape file) or its
subclass PixTextModeUnsupported (a text-mode/alphanumeric capture -- no
local sample exists to validate a decoder against, see above).
"""
from __future__ import annotations

import struct
import zlib

__all__ = ['PixFormatError', 'PixTextModeUnsupported', 'decode', 'to_png',
           'physical_size_in']


class PixFormatError(Exception):
    """A malformed .PIX file, or a structurally valid one this decoder
    does not support (a shape that has no local validated sample)."""


class PixTextModeUnsupported(PixFormatError):
    """A text-mode (alphanumeric) .PIX capture. WordStar itself doesn't
    preview these either; decoding is out of scope pending a sample."""


def _parse_index_table(data: bytes):
    if len(data) < 4:
        raise PixFormatError("file too short for PIX header")
    rev, nitems = struct.unpack_from('<HH', data, 0)
    items = {}
    off = 4
    for _ in range(nitems):
        if off + 8 > len(data):
            raise PixFormatError("index table truncated")
        did, dlen, dloc = struct.unpack_from('<HHI', data, off)
        items[did] = (dlen, dloc)
        off += 8
    return rev, items


def _parse_mode_data(data: bytes, items: dict):
    if 0 not in items:
        raise PixFormatError("no image-info (DataID 0) data item")
    dlen, dloc = items[0]
    md = data[dloc:dloc + dlen]
    if len(md) < 29:
        raise PixFormatError("image-info data item too short")
    hmode = md[0]
    htype = md[1]
    gcols, grows = struct.unpack_from('<HH', md, 18)
    gfore = md[22]
    prepal, lodpal, lintens, lred, lgreen, lblue = md[23:29]
    is_bitmap = bool(htype & 1)
    return {
        'hmode': hmode, 'htype': htype, 'is_bitmap': is_bitmap,
        'gcols': gcols, 'grows': grows, 'gfore': gfore,
        'prepal': prepal, 'lodpal': lodpal,
        'lintens': lintens, 'lred': lred, 'lgreen': lgreen, 'lblue': lblue,
    }


def _parse_tile_data(data: bytes, items: dict):
    if 2 not in items:
        raise PixFormatError("no tile-info (DataID 2) data item")
    dlen, dloc = items[2]
    td = data[dloc:dloc + dlen]
    if len(td) < 8:
        raise PixFormatError("tile-info data item too short")
    page_rows, page_cols, stp_rows, stp_cols = struct.unpack_from('<HHHH', td, 0)
    return page_rows, page_cols, stp_rows, stp_cols


def _parse_palette(data: bytes, items: dict):
    if 1 not in items:
        return bytes(4 * 16)
    dlen, dloc = items[1]
    return data[dloc:dloc + dlen]


# ---- print-options record (DataID 0x11) -- physical size for embedding ----
#
# Struct per the EGFF (fileformat.info) secondary source: 15 signed SHORTs
# followed by a 16-byte ink_tab. VALIDATED against the one real sample this
# integration targets (WORDSTAR.PIX, referenced by all 5 real corpus
# documents): its own ecol/erow (1948/307) equal gcols-1/grows-1 from the
# image-info record (1949/308) exactly, and its row_dp/col_dp (739/4679
# decipoints, i.e. 1/720in) work out to 1.027in x 6.498in -- matching the
# pixel count interpreted at 300dpi (308/300, 1949/300 = 1.027in x 6.497in)
# to within a rounding hair. That double agreement, on a struct with no
# vendor source, is the validating evidence; per fileformat.info's own field
# descriptions p_wid ("Printer width (not required, set to 0)") and siz
# ("Size (not used, set to 0)") are NOT the authoritative size fields despite
# their names -- row_dp/col_dp are ("Height/Width of image in decipoints"),
# confirmed above -- so those two, not p_wid/siz, are what physical_size_in
# reads. No independent second color-depth sample exists to widen this
# validation (same caveat as the rest of this module).
_PRT_OPTIONS_FIELDS = ('pitch', 'scol', 'ecol', 'srow', 'erow', 'p_wid',
                       'siz', 'rotat', 'do_sw', 'res_1', 'res_2', 'pcolor',
                       'row_dp', 'col_dp', 'flags')
_DECIPOINTS_PER_INCH = 720.0


def _parse_print_options(data: bytes, items: dict):
    """DataID 0x11 -> a dict of its raw fields (see _PRT_OPTIONS_FIELDS)
    plus `ink_tab` (16 raw bytes), or None if the item is absent or too
    short to hold the full struct (15*2 + 16 = 46 bytes)."""
    if 0x11 not in items:
        return None
    dlen, dloc = items[0x11]
    blob = data[dloc:dloc + dlen]
    if len(blob) < 30:
        return None
    fields = struct.unpack_from('<15h', blob, 0)
    info = dict(zip(_PRT_OPTIONS_FIELDS, fields))
    info['ink_tab'] = blob[30:46]
    return info


def physical_size_in(data: bytes):
    """(width_in, height_in) from the print-options record's row_dp/col_dp,
    or None when the record is absent, too short, or its size fields are
    zero or implausible (<=0 or >100in -- guards a garbage/misaligned read
    on a struct validated against only one real sample). Callers fall back
    to fit-to-text-measure sizing when this returns None; on the one
    validated sample (WORDSTAR.PIX) the two methods independently agree
    (see the module comment above _PRT_OPTIONS_FIELDS)."""
    try:
        rev, items = _parse_index_table(data)
    except PixFormatError:
        return None
    opts = _parse_print_options(data, items)
    if opts is None:
        return None
    w = opts['col_dp'] / _DECIPOINTS_PER_INCH
    h = opts['row_dp'] / _DECIPOINTS_PER_INCH
    if w <= 0 or h <= 0 or w > 100 or h > 100:
        return None
    return (w, h)


def _decode_plane(buf: bytes, pos: int, n_rows: int, row_bytes: int,
                   pad_to: int | None = None):
    """Decode one bitplane's vertically-RLE-compressed rows starting at
    byte offset `pos` in `buf`. Returns (rows, new_pos). Rows are
    bytearrays of length row_bytes; bit 7 of byte 0 is the leftmost pixel.

    `n_rows` MUST be the true number of encoded rows for THIS plane in
    THIS tile -- see decode_pix() for why that is not always page_rows.
    `pad_to` (defaults to n_rows) pads the returned row list with blank
    rows up to that count, for tiles whose nominal page_rows is taller
    than the real content (the bottom row-band when grows isn't a
    multiple of page_rows) but still need to fill their tile-grid slot.
    """
    if pad_to is None:
        pad_to = n_rows
    rows = []
    prev = bytearray(row_bytes)
    comp_bytes_needed = (row_bytes + 7) // 8
    for _ in range(n_rows):
        if pos + (row_bytes if not rows else comp_bytes_needed) > len(buf):
            break
        if not rows:
            row = bytearray(buf[pos:pos + row_bytes])
            pos += row_bytes
        else:
            mask = buf[pos:pos + comp_bytes_needed]
            pos += comp_bytes_needed
            row = bytearray(prev)
            ok = True
            for bytei in range(row_bytes):
                if mask[bytei // 8] & (1 << (7 - (bytei % 8))):
                    if pos >= len(buf):
                        ok = False
                        break
                    row[bytei] = buf[pos]
                    pos += 1
            if not ok:
                break
        rows.append(row)
        prev = row
    while len(rows) < pad_to:
        rows.append(bytearray(row_bytes))
    return rows, pos


def _decode_pix(data: bytes):
    """Decode to (gcols, grows, index_img, rgb_palette, info). Internal --
    `index_img` is a palette-index bitmap (rows of ints, one per pixel);
    `decode()` below turns it into true RGB, handling the mono special
    case (see build_rgb_palette's docstring)."""
    rev, items = _parse_index_table(data)
    info = _parse_mode_data(data, items)
    if not info['is_bitmap']:
        raise PixTextModeUnsupported(
            "this .PIX is a text-mode (alphanumeric) capture; decoding "
            "that variant is not implemented (no local sample to validate "
            "against -- see module docstring)")

    gcols, grows, gfore = info['gcols'], info['grows'], info['gfore']
    if gcols == 0 or grows == 0:
        raise PixFormatError("zero-sized image (gcols/grows == 0)")
    if gfore == 0:
        raise PixFormatError("zero bitplanes (gfore == 0)")

    page_rows, page_cols, stp_rows, stp_cols = _parse_tile_data(data, items)
    if page_rows == 0 or page_cols == 0 or stp_rows == 0 or stp_cols == 0:
        raise PixFormatError("degenerate tile geometry (zero rows/cols/tiles)")
    row_bytes = page_cols // 8
    if row_bytes == 0:
        raise PixFormatError("page_cols < 8, can't compute row byte width")

    full_w = page_cols * stp_cols
    full_h = page_rows * stp_rows
    index_img = [bytearray(full_w) for _ in range(full_h)]

    for trow in range(stp_rows):
        for tcol in range(stp_cols):
            tidx = trow * stp_cols + tcol
            did = 0x8000 + tidx
            if did not in items:
                raise PixFormatError(f"missing tile data item {tidx} (0x{did:04x})")
            tlen, tloc = items[did]
            buf = data[tloc:tloc + tlen]
            pos = 0
            planes = []
            # THE TILE-ROW-BAND FIX: the bottom row-band, when grows isn't
            # a multiple of page_rows, only has REAL encoded data for the
            # rows that truly exist in the image (n_rows_here), not the
            # full nominal page_rows. Each bitplane is a separate
            # compressed sub-stream packed back to back inside the tile's
            # buffer; asking decode_plane for more rows than a plane truly
            # has makes it read past that plane's end and INTO the next
            # plane's bytes, reinterpreting them as more (garbage) rows of
            # the current plane -- every subsequent plane in the tile is
            # then offset and corrupted too. The tile's TOTAL byte count
            # still matches its declared length either way (the same
            # bytes get consumed, just misattributed to the wrong
            # rows/planes), which is why byte-exact-consumption checks
            # alone couldn't catch this.
            n_rows_here = min(page_rows, grows - trow * page_rows)
            for _p in range(gfore):
                rows, pos = _decode_plane(buf, pos, n_rows_here, row_bytes,
                                           pad_to=page_rows)
                planes.append(rows)

            base_y = trow * page_rows
            base_x = tcol * page_cols
            for ry in range(page_rows):
                out_row = index_img[base_y + ry]
                for cx in range(page_cols):
                    byte_i = cx >> 3
                    bit_i = 7 - (cx & 7)
                    val = 0
                    for p in range(gfore):
                        bit = (planes[p][ry][byte_i] >> bit_i) & 1
                        val |= (bit << p)
                    out_row[base_x + cx] = val

    # crop to true (unpadded) dimensions
    index_img = [row[:gcols] for row in index_img[:grows]]

    pal_raw = _parse_palette(data, items)
    num_used = min(16, 1 << gfore)
    rgb_palette = _build_rgb_palette(pal_raw, info, num_used)

    return gcols, grows, index_img, rgb_palette, info


# Canonical IBM CGA/EGA/VGA default 16-color hardware palette. This is
# public, well-documented hardware fact (not Inset-specific) -- see e.g.
# Wikipedia "Color Graphics Adapter" and "Enhanced Graphics Adapter", or any
# DOS-era programmer's reference. Index is the classic 4-bit IRGB code
# (bit3=intensity, bit2=red, bit1=green, bit0=blue). Note the color-6 "brown"
# special case (170,85,0) instead of the "expected" (170,170,0) -- a genuine
# CGA hardware quirk baked into every real CGA/EGA adapter, not a bug.
CANONICAL_16 = [
    (0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170),
    (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
    (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255),
    (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255),
]


# The four standard CGA hardware palettes, as their IRGB codes (indices into
# CANONICAL_16) in ASCENDING order -- which is also the order real Inset
# files present them in slot 0..3 (verified: MAN.PIX's clean, uncorrupted
# slots are literally 0,2,4,6 in slot order; TEST.PIX's surviving good slots
# are 0,11,_,15 in slot order; PCMAN.PIX's clean slots are 0,11,13,15).
PAL0_LOW = [0, 2, 4, 6]      # black, green, red, brown
PAL0_HIGH = [0, 10, 12, 14]  # black, light green, light red, yellow
PAL1_LOW = [0, 3, 5, 7]      # black, cyan, magenta, light gray
PAL1_HIGH = [0, 11, 13, 15]  # black, light cyan, light magenta, white
CGA_FAMILIES = [PAL0_LOW, PAL0_HIGH, PAL1_LOW, PAL1_HIGH]


def _build_rgb_palette(pal_raw: bytes, info: dict, num_used: int):
    """Turn the raw {intensity,red,green,blue} palette bytes into RGB.

    Two regimes, distinguished by how many distinct entries this image's
    own bitplane count (gfore) actually indexes into (`num_used` = 2**gfore,
    capped at 16). Both were revised after ground-truth comparison against
    real Inset (WordStar 7) renders under dosbox-x -- see the vault's
    pix-research/inset-groundtruth/ -- which is the deciding evidence for
    everything below; earlier guesses (declared-bit-depth linear scaling,
    then plain value*85) were each disproven by it in turn.

    - CGA-depth images (gfore <= 2, num_used <= 4): each active R/G/B/I
      channel byte is a single bit (0 or 1) forming a 4-bit IRGB code,
      looked up in the fixed hardware CANONICAL_16 table. This part was
      already right (confirmed against ground truth for MAN.PIX/PC.PIX/
      PCMAN.PIX: e.g. MAN's slots literally decode to black/green/red/
      brown, byte for byte).

      BUT ground truth also caught cases the naive per-entry read gets
      wrong: SPORTS.PIX and TEST.PIX render "VERY wrong", and LOGOS1/
      LOGOS2.PIX render with some colors incorrect. Comparing decoded pixel
      content against the real-Inset screenshot (matching each raw index's
      *actual* on-screen color, not the file's claimed palette bytes) shows
      the true colors always land on exactly one of the 4 standard CGA
      families (never an arbitrary RGB) -- but the file's own stored slots
      sometimes DON'T reproduce that family cleanly:
        - TEST.PIX: slots are 0, 11, 0, 15 -- slot 2 is a corrupt duplicate
          of slot 0. The 3 surviving distinct values (0, 11, 15) are a
          subset of exactly one family, PAL1_HIGH = {0,11,13,15}; ground
          truth confirms slot 2 should be 13 (light magenta), the missing
          member.
        - LOGOS1.PIX: slots are 0, 11, 13, 11 -- slot 3 duplicates slot 1;
          ground truth confirms slot 3 should be 15 (white), completing
          PAL1_HIGH.
        - LOGOS2.PIX: slots are 0, 13, 13, 15 -- slot 1 duplicates slot 2;
          ground truth confirms slot 1 should be 11 (light cyan), again
          completing PAL1_HIGH.
        - SPORTS.PIX: slots are 0, 0, 1, 2 -- fully degenerate (a plain
          0..15 enumeration artifact, shared byte-for-byte with several
          other sibling files' *unused* upper palette slots). None of the
          surviving codes beyond 0 belong to any single family, so there's
          nothing to complete. Ground truth shows SPORTS wants PAL0_LOW
          (black/green/red/brown) -- the same family as its structural
          siblings MAN.PIX/PC.PIX (byte-identical mode_data). Falling back
          to PAL0_LOW here is a documented default (CGA's power-on
          palette), not a derivation -- flagged as the one remaining
          low-confidence case.
      Repair rule: collect the distinct IRGB codes among the num_used
      active slots. If they are NOT all distinct (a duplicate exists) --
      real, uncorrupted files never show duplicates among active slots --
      try to match the surviving distinct codes against each of the 4
      standard families (CGA_FAMILIES); if exactly one family contains all
      of them, replace all num_used slots with that family's codes in
      ascending order (which is also slot order). If no family matches
      (fully degenerate data), fall back to PAL0_LOW.
    - EGA-depth images (gfore > 2): local samples (EGACHART.PIX,
      EGALOGOS.PIX) use the full 0-3 range per channel. A first attempt
      scaled this as a plain linear ramp (value*85 uniformly), which
      LOOKED plausible (recognizable pastel colors) but ground-truth
      per-index comparison proved it wrong: raw value 1 must render as 170,
      not 85, and raw value 2 must render as 85, not 170 -- the two bits
      of the 2-bit value are NOT equal-weighted. The correct, hardware-
      accurate EGA DAC formula treats them asymmetrically: bit 0 (LSB) is
      the "normal" component worth 0xAA (170), bit 1 is the "secondary"
      component worth 0x55 (85); the two sum when both set (170+85=255).
      Confirmed exactly against every distinct raw value seen in
      EGACHART.PIX's ground truth (0->0, 1->170, 2->85, 3->255) with zero
      exceptions. The intensity byte is still ignored (always 0 in every
      local EGA-depth sample).
    """
    use_bit_mode = num_used <= 4
    entries = []
    for i in range(16):
        off = i * 4
        if off + 4 <= len(pal_raw):
            inten, r, g, b = pal_raw[off:off + 4]
        else:
            inten = r = g = b = 0
        entries.append((inten, r, g, b))

    if use_bit_mode:
        codes = []
        for i in range(num_used):
            inten, r, g, b = entries[i]
            idx = ((inten & 1) << 3) | ((r & 1) << 2) | ((g & 1) << 1) | (b & 1)
            codes.append(idx)
        if len(set(codes)) < len(codes):
            distinct = set(codes)
            matches = [fam for fam in CGA_FAMILIES if distinct <= set(fam)]
            codes = matches[0] if len(matches) == 1 else PAL0_LOW
            codes = codes[:num_used]
        palette = [CANONICAL_16[c] for c in codes]
        while len(palette) < 16:
            palette.append(CANONICAL_16[0])
        return palette

    palette = []
    for inten, r, g, b in entries:
        def chan(v):
            return min(255, 170 * (v & 1) + 85 * ((v >> 1) & 1))
        palette.append((chan(r), chan(g), chan(b)))
    return palette


def decode(data: bytes):
    """Decode a .PIX file's bytes to (width, height, rgb_rows).

    rgb_rows is a tuple of `height` rows, each a tuple of `width`
    (r, g, b) int-triples -- always true RGB, regardless of source bit
    depth. Monochrome (gfore == 1) images render as plain black-ink-on-
    white (index 0 = background/white, index 1 = ink/black): this is the
    prototype's original choice, ground-truth confirmed correct on
    WORDSTAR.PIX and FIG1.PIX, and deliberately bypasses the palette
    machinery above (which is unvalidated for the 1-bitplane case and
    unneeded -- a scanned page or wordmark is ink on paper, not a CGA
    screen).

    Raises PixFormatError / PixTextModeUnsupported -- see module docstring.
    """
    gcols, grows, index_img, rgb_palette, info = _decode_pix(data)
    if info['gfore'] == 1:
        mono_rgb = ((255, 255, 255), (0, 0, 0))
        rows = tuple(tuple(mono_rgb[v] for v in row) for row in index_img)
    else:
        rows = tuple(tuple(rgb_palette[v] for v in row) for row in index_img)
    return gcols, grows, rows


# ---- minimal PNG writer (stdlib only: zlib + struct) ----

def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    c = tag + payload
    crc = zlib.crc32(c) & 0xffffffff
    return struct.pack('>I', len(payload)) + c + struct.pack('>I', crc)


def _png_bytes(ihdr: bytes, idat: bytes) -> bytes:
    return (b'\x89PNG\r\n\x1a\n' + _png_chunk(b'IHDR', ihdr) +
            _png_chunk(b'IDAT', idat) + _png_chunk(b'IEND', b''))


def _write_png_grayscale1(width: int, height: int, index_img) -> bytes:
    """1-bit grayscale PNG. `index_img` rows are sequences where a truthy
    value means 'ink'/foreground; PNG sample 0 renders black, so bits are
    inverted on the way out (1=ink -> PNG sample 0 -> black)."""
    row_bytes_needed = (width + 7) // 8
    raw = bytearray()
    for row in index_img[:height]:
        packed = bytearray(row_bytes_needed)
        for x, v in enumerate(row):
            if v:
                packed[x >> 3] |= (1 << (7 - (x & 7)))
        raw.append(0)  # filter: none
        raw.extend((~b) & 0xFF for b in packed)
    compressed = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack('>IIBBBBB', width, height, 1, 0, 0, 0, 0)
    return _png_bytes(ihdr, compressed)


def _write_png_rgb8(width: int, height: int, index_img, palette) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        row = index_img[y]
        for x in range(width):
            r, g, b = palette[row[x]]
            raw.extend((r, g, b))
    compressed = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return _png_bytes(ihdr, compressed)


def to_png(data: bytes) -> bytes:
    """Decode a .PIX file's bytes to PNG-encoded bytes.

    Monochrome (gfore == 1) images are written as 1-bit grayscale
    (smaller, and matches decode()'s black-ink-on-white treatment);
    everything else as 8-bit RGB. Stdlib zlib/struct only.

    Raises PixFormatError / PixTextModeUnsupported -- see module docstring.
    """
    gcols, grows, index_img, palette, info = _decode_pix(data)
    if info['gfore'] == 1:
        return _write_png_grayscale1(gcols, grows, index_img)
    return _write_png_rgb8(gcols, grows, index_img, palette)
