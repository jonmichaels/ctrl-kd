"""ctrlkd.pix / ctrlkd.piximg tests.

Decoder tests: synthetic PIX fixtures ONLY for the always-run tests (same
discipline as the rest of the suite -- no corpus content ships in this
repo). Byte streams are built in-code by build_pix_bytes()/build_tile_bytes()
below, exercising the same vertical-RLE encoding real Inset files use, so
the decoder is tested against the real wire format, not a shortcut.

An OPTIONAL corpus gauntlet runs only when CTRLKD_PIX_SAMPLES points at a
directory of real .PIX files (private tree, never checked in here) -- it
decodes every sample and asserts the same byte-exact-consumption signal
that validated the original prototype, plus basic structural sanity. It is
skipped, not failed, when the env var is absent.

Resolution tests: synthetic directory trees under tmp_path proving every
ruled probe location and the ancestor walk, matching the real corpus shape
(WordStar-Feature-Decision-Register.md, "PIX images RULED IN": root docs
hit INSET/PIX one hop, APP/-nested docs two-three hops up).
"""
import glob
import os
import struct
import zlib

import pytest

from ctrlkd import pix
from ctrlkd.piximg import resolve_pix


# ============================================================== builders

def encode_plane_rows(rows, row_bytes):
    """Vertical RLE encode: row 0 raw; later rows carry a real changed-
    byte bitmask against the previous row (bytes equal to the previous
    row are marked unchanged and omitted) -- this exercises BOTH the
    changed-byte and the copy-from-previous-row paths, not just the
    naive 'send everything' case."""
    out = bytearray()
    prev = bytes(row_bytes)
    comp_bytes_needed = (row_bytes + 7) // 8
    for i, row in enumerate(rows):
        row = bytes(row).ljust(row_bytes, b'\x00')[:row_bytes]
        if i == 0:
            out += row
        else:
            mask = bytearray(comp_bytes_needed)
            changed = bytearray()
            for bytei in range(row_bytes):
                if row[bytei] != prev[bytei]:
                    mask[bytei // 8] |= (1 << (7 - (bytei % 8)))
                    changed.append(row[bytei])
            out += bytes(mask)
            out += bytes(changed)
        prev = row
    return bytes(out)


def build_tile_bytes(index_rows, page_rows, page_cols, gfore, n_rows_here):
    """One tile's bitmap data item: gfore planes, sequentially. Only the
    first `n_rows_here` rows carry real encoded data per plane -- matching
    real files' bottom row-band, and exercising the plane-boundary
    row-band fix (asking for more than a plane truly has would read into
    the next plane's bytes)."""
    row_bytes = page_cols // 8
    out = bytearray()
    for p in range(gfore):
        plane_rows = []
        for ry in range(n_rows_here):
            row = index_rows[ry]
            packed = bytearray(row_bytes)
            for cx in range(page_cols):
                bit = (row[cx] >> p) & 1
                if bit:
                    packed[cx >> 3] |= (1 << (7 - (cx & 7)))
            plane_rows.append(bytes(packed))
        out += encode_plane_rows(plane_rows, row_bytes)
    return bytes(out)


def build_pix_bytes(gcols, grows, gfore, page_rows, page_cols, stp_rows, stp_cols,
                     index_img, palette_raw=None, htype=1,
                     lintens=0, lred=0, lgreen=0, lblue=0):
    """Assemble a complete, structurally valid .PIX byte stream: header +
    index table + mode-data blob + palette blob + tile-info blob + one
    bitmap data item per tile, row-major. `index_img` is the full
    (grows x gcols)-shaped list of rows of palette-index ints (0..2**gfore-1);
    it gets tiled and padded to the page_rows/page_cols/stp_rows/stp_cols
    grid exactly like a real encoder would."""
    if palette_raw is None:
        palette_raw = bytes(4 * 16)

    mode_blob = bytearray(29)
    mode_blob[1] = htype
    struct.pack_into('<HH', mode_blob, 18, gcols, grows)
    mode_blob[22] = gfore
    mode_blob[25] = lintens
    mode_blob[26] = lred
    mode_blob[27] = lgreen
    mode_blob[28] = lblue

    tile_info_blob = struct.pack('<HHHH', page_rows, page_cols, stp_rows, stp_cols)

    # pad index_img out to the full tile grid so slicing below never runs
    # off the end (mirrors decode_pix's own full_w/full_h padding)
    full_w, full_h = page_cols * stp_cols, page_rows * stp_rows
    padded = [list(r) + [0] * (full_w - len(r)) for r in index_img]
    padded += [[0] * full_w] * (full_h - len(padded))

    tiles = []
    for trow in range(stp_rows):
        for tcol in range(stp_cols):
            n_rows_here = min(page_rows, grows - trow * page_rows)
            n_rows_here = max(n_rows_here, 0)
            base_y, base_x = trow * page_rows, tcol * page_cols
            tile_rows = [padded[base_y + ry][base_x:base_x + page_cols]
                         for ry in range(n_rows_here)]
            tiles.append(build_tile_bytes(tile_rows, page_rows, page_cols,
                                           gfore, n_rows_here))

    items = [(0, bytes(mode_blob)), (1, palette_raw), (2, tile_info_blob)]
    items += [(0x8000 + i, tb) for i, tb in enumerate(tiles)]

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


def solid_rows(gcols, grows, value):
    return [[value] * gcols for _ in range(grows)]


# ============================================================== mono

def test_decode_mono_ink_on_white():
    # 8x2 mono image: row0 all ink (left half) / bg (right half), row1 reversed
    rows = [[1, 1, 1, 1, 0, 0, 0, 0], [0, 0, 0, 0, 1, 1, 1, 1]]
    data = build_pix_bytes(gcols=8, grows=2, gfore=1, page_rows=2, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=rows)
    w, h, rgb = pix.decode(data)
    assert (w, h) == (8, 2)
    WHITE, BLACK = (255, 255, 255), (0, 0, 0)
    assert rgb[0] == (BLACK, BLACK, BLACK, BLACK, WHITE, WHITE, WHITE, WHITE)
    assert rgb[1] == (WHITE, WHITE, WHITE, WHITE, BLACK, BLACK, BLACK, BLACK)


def test_decode_mono_multi_row_rle_copy():
    # row2 repeats row1 exactly -- exercises the "unchanged, copy from
    # previous row" branch of the vertical RLE decoder
    rows = [[1] * 8, [0] * 8, [0] * 8, [1] * 8]
    data = build_pix_bytes(gcols=8, grows=4, gfore=1, page_rows=4, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=rows)
    w, h, rgb = pix.decode(data)
    BLACK, WHITE = (0, 0, 0), (255, 255, 255)
    assert rgb[0] == (BLACK,) * 8
    assert rgb[1] == (WHITE,) * 8
    assert rgb[2] == (WHITE,) * 8
    assert rgb[3] == (BLACK,) * 8


def test_to_png_mono_is_valid_1bit_png():
    rows = [[1, 0, 1, 0, 1, 0, 1, 0], [0, 1, 0, 1, 0, 1, 0, 1]]
    data = build_pix_bytes(gcols=8, grows=2, gfore=1, page_rows=2, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=rows)
    png = pix.to_png(data)
    assert png.startswith(b'\x89PNG\r\n\x1a\n')
    assert png.endswith(_png_iend())
    width, height, bitdepth, colortype = _read_ihdr(png)
    assert (width, height, bitdepth, colortype) == (8, 2, 1, 0)


# ============================================================== CGA

def _irgb_palette_raw(codes):
    """codes: list of 4-bit IRGB indices (0-15) for palette slots 0..len-1.
    Only the low bit of each channel byte is read by the decoder's CGA
    bit-mode path, so this is a faithful minimal encoding."""
    raw = bytearray(4 * 16)
    for i, c in enumerate(codes):
        inten = (c >> 3) & 1
        red = (c >> 2) & 1
        green = (c >> 1) & 1
        blue = c & 1
        raw[i * 4:i * 4 + 4] = bytes((inten, red, green, blue))
    return bytes(raw)


def test_decode_cga_canonical_palette():
    # PAL0_LOW family: black, green, red, brown -- clean, no duplicates
    codes = [0, 2, 4, 6]
    palette_raw = _irgb_palette_raw(codes)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3]]
    data = build_pix_bytes(gcols=8, grows=1, gfore=2, page_rows=1, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=rows,
                            palette_raw=palette_raw)
    w, h, rgb = pix.decode(data)
    expected = [pix.CANONICAL_16[c] for c in codes]
    assert list(rgb[0][:4]) == expected


def test_decode_cga_duplicate_slot_repair():
    # TEST.PIX's real shape: slots 0, 11, 0, 15 -- slot 2 is a corrupt
    # duplicate of slot 0. The 3 surviving distinct codes (0, 11, 15) are
    # a subset of exactly one family, PAL1_HIGH = {0,11,13,15}; repair
    # must complete slot 2 to 13 (light magenta), not leave it as black.
    codes = [0, 11, 0, 15]
    palette_raw = _irgb_palette_raw(codes)
    rows = [[0, 1, 2, 3]]
    data = build_pix_bytes(gcols=8, grows=1, gfore=2, page_rows=1, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=rows,
                            palette_raw=palette_raw)
    w, h, rgb = pix.decode(data)
    assert rgb[0][:4] == tuple(pix.CANONICAL_16[c] for c in pix.PAL1_HIGH)


def test_decode_cga_degenerate_falls_back_to_pal0_low():
    # SPORTS.PIX's real shape: 0, 0, 1, 2 -- fully degenerate, no family
    # match. Documented fallback: PAL0_LOW (CGA's power-on palette).
    codes = [0, 0, 1, 2]
    palette_raw = _irgb_palette_raw(codes)
    rows = [[0, 1, 2, 3]]
    data = build_pix_bytes(gcols=8, grows=1, gfore=2, page_rows=1, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=rows,
                            palette_raw=palette_raw)
    w, h, rgb = pix.decode(data)
    assert rgb[0][:4] == tuple(pix.CANONICAL_16[c] for c in pix.PAL0_LOW)


# ============================================================== EGA

def test_decode_ega_asymmetric_dac():
    # Ground-truth-confirmed formula: bit0 (LSB) worth 170, bit1 worth 85
    # -- NOT a uniform value*85 ramp. raw 0->0, 1->170, 2->85, 3->255.
    palette_raw = bytearray(4 * 16)
    for i, rawval in enumerate([0, 1, 2, 3]):
        palette_raw[i * 4:i * 4 + 4] = bytes((0, rawval, 0, 0))
    rows = [[0, 1, 2, 3]]
    data = build_pix_bytes(gcols=8, grows=1, gfore=4, page_rows=1, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=rows,
                            palette_raw=bytes(palette_raw))
    w, h, rgb = pix.decode(data)
    reds = [px[0] for px in rgb[0][:4]]
    assert reds == [0, 170, 85, 255]
    assert all(px[1] == 0 and px[2] == 0 for px in rgb[0][:4])


def test_decode_ega_multi_tile_grid():
    # 2x2 tile grid, EGA depth -- exercises tile-grid reassembly beyond
    # the single-tile case, and a grows-not-multiple-of-page_rows band.
    gcols, grows = 12, 5
    page_rows, page_cols = 3, 8
    stp_rows, stp_cols = 2, 2
    rows = solid_rows(gcols, grows, 3)   # solid "index 3" image
    palette_raw = bytearray(4 * 16)
    palette_raw[3 * 4:3 * 4 + 4] = bytes((0, 3, 3, 3))
    data = build_pix_bytes(gcols, grows, gfore=4, page_rows=page_rows,
                            page_cols=page_cols, stp_rows=stp_rows,
                            stp_cols=stp_cols, index_img=rows,
                            palette_raw=bytes(palette_raw))
    w, h, rgb = pix.decode(data)
    assert (w, h) == (gcols, grows)
    for row in rgb:
        assert all(px == (255, 255, 255) for px in row)


def test_to_png_rgb_roundtrips_pixels():
    codes = [0, 2, 4, 6]
    palette_raw = _irgb_palette_raw(codes)
    rows = [[0, 1, 2, 3]]
    data = build_pix_bytes(gcols=4, grows=1, gfore=2, page_rows=1, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=rows,
                            palette_raw=palette_raw)
    png = pix.to_png(data)
    width, height, bitdepth, colortype = _read_ihdr(png)
    assert (width, height, bitdepth, colortype) == (4, 1, 8, 2)
    pixels = _read_rgb8_pixels(png, width, height)
    assert pixels[0] == [pix.CANONICAL_16[c] for c in codes]


# ============================================================== errors

def test_decode_text_mode_raises_specific_error():
    data = build_pix_bytes(gcols=8, grows=1, gfore=1, page_rows=1, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=[[0] * 8],
                            htype=0)   # bit0 clear -> alphanumeric/text mode
    with pytest.raises(pix.PixTextModeUnsupported):
        pix.decode(data)


def test_decode_truncated_header_raises_format_error():
    with pytest.raises(pix.PixFormatError):
        pix.decode(b'\x03\x00')


def test_decode_truncated_index_table_raises_format_error():
    with pytest.raises(pix.PixFormatError):
        pix.decode(struct.pack('<HH', 3, 5) + b'\x00' * 4)   # claims 5 items, has 0


def test_decode_missing_image_info_raises_format_error():
    # a valid, empty index table (0 items) -- no DataID 0 at all
    with pytest.raises(pix.PixFormatError):
        pix.decode(struct.pack('<HH', 3, 0))


def test_decode_zero_dimension_raises_format_error():
    data = build_pix_bytes(gcols=0, grows=1, gfore=1, page_rows=1, page_cols=8,
                            stp_rows=1, stp_cols=1, index_img=[[0] * 8])
    with pytest.raises(pix.PixFormatError):
        pix.decode(data)


# ============================================================== PNG helpers

def _iter_chunks(png):
    pos = 8
    while pos < len(png):
        (length,) = struct.unpack_from('>I', png, pos)
        tag = png[pos + 4:pos + 8]
        payload = png[pos + 8:pos + 8 + length]
        yield tag, payload
        pos += 8 + length + 4


def _read_ihdr(png):
    for tag, payload in _iter_chunks(png):
        if tag == b'IHDR':
            width, height, bitdepth, colortype = struct.unpack('>IIBB', payload[:10])
            return width, height, bitdepth, colortype
    raise AssertionError('no IHDR chunk')


def _png_iend():
    return struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)


def _read_rgb8_pixels(png, width, height):
    idat = b''.join(payload for tag, payload in _iter_chunks(png) if tag == b'IDAT')
    raw = zlib.decompress(idat)
    stride = 1 + width * 3
    out = []
    for y in range(height):
        row = raw[y * stride + 1: y * stride + stride]
        out.append([tuple(row[x * 3:x * 3 + 3]) for x in range(width)])
    return out


# ============================================================== resolve_pix

DOS_PATH = rb'C:\WS\INSET\PIX\WORDSTAR.PIX'


def test_resolve_tail_suffix_one_hop_from_doc_dir(tmp_path):
    # doc lives at the "WS" root; image sits under INSET/PIX relative to
    # that same directory (the tail suffix INSET/PIX/WORDSTAR.PIX, one
    # component short of the full recorded WS/INSET/PIX/... path)
    doc_dir = tmp_path / 'WS'
    doc_dir.mkdir()
    (doc_dir / 'PREVIEW.WS').write_bytes(b'')
    img_dir = doc_dir / 'INSET' / 'PIX'
    img_dir.mkdir(parents=True)
    target = img_dir / 'WORDSTAR.PIX'
    target.write_bytes(b'PIXDATA')

    got = resolve_pix(DOS_PATH, doc_dir / 'PREVIEW.WS')
    assert got == str(target)


def test_resolve_tail_suffix_ancestor_walk_two_to_three_hops(tmp_path):
    # doc nested two levels under APP/; image still resolves via the
    # tail-suffix walk up the ancestor chain to where INSET/PIX/ sits
    root = tmp_path / 'WS'
    doc_dir = root / 'APP' / 'SUB'
    doc_dir.mkdir(parents=True)
    (doc_dir / '-README.WS').write_bytes(b'')
    img_dir = root / 'INSET' / 'PIX'
    img_dir.mkdir(parents=True)
    target = img_dir / 'WORDSTAR.PIX'
    target.write_bytes(b'PIXDATA')

    got = resolve_pix(DOS_PATH, doc_dir / '-README.WS')
    assert got == str(target)


def test_resolve_prefers_longest_tail_suffix(tmp_path):
    # both a full-tail match (WS/INSET/PIX/WORDSTAR.PIX) and a shorter
    # one (INSET/PIX/WORDSTAR.PIX) exist at the same ancestor; the
    # longer, more specific suffix must win
    root = tmp_path
    (root / 'PREVIEW.WS').write_bytes(b'')
    full = root / 'WS' / 'INSET' / 'PIX' / 'WORDSTAR.PIX'
    full.parent.mkdir(parents=True)
    full.write_bytes(b'FULL')
    short = root / 'INSET' / 'PIX' / 'WORDSTAR.PIX'
    short.parent.mkdir(parents=True)
    short.write_bytes(b'SHORT')

    got = resolve_pix(DOS_PATH, root / 'PREVIEW.WS')
    assert got == str(full)


def test_resolve_basename_same_dir_fallback(tmp_path):
    doc_dir = tmp_path / 'docs'
    doc_dir.mkdir()
    (doc_dir / 'X.WS').write_bytes(b'')
    target = doc_dir / 'WORDSTAR.PIX'
    target.write_bytes(b'PIXDATA')

    got = resolve_pix(DOS_PATH, doc_dir / 'X.WS')
    assert got == str(target)


@pytest.mark.parametrize('probe_dir', ['INSET/PIX', 'INSET', 'media',
                                        'attachments', 'images'])
def test_resolve_basename_probe_locations(tmp_path, probe_dir):
    doc_dir = tmp_path / 'docs'
    doc_dir.mkdir()
    (doc_dir / 'X.WS').write_bytes(b'')
    target_dir = doc_dir
    for part in probe_dir.split('/'):
        target_dir = target_dir / part
    target_dir.mkdir(parents=True)
    target = target_dir / 'WORDSTAR.PIX'
    target.write_bytes(b'PIXDATA')

    got = resolve_pix(DOS_PATH, doc_dir / 'X.WS')
    assert got == str(target)


def test_resolve_basename_probe_walks_ancestors(tmp_path):
    # basename probing (not just tail-suffix probing) must also walk up
    # the ancestor chain, not just the document's own directory
    root = tmp_path
    doc_dir = root / 'APP' / 'SUB'
    doc_dir.mkdir(parents=True)
    (doc_dir / 'X.WS').write_bytes(b'')
    img_dir = root / 'media'
    img_dir.mkdir()
    target = img_dir / 'WORDSTAR.PIX'
    target.write_bytes(b'PIXDATA')

    got = resolve_pix(DOS_PATH, doc_dir / 'X.WS')
    assert got == str(target)


def test_resolve_case_insensitive_matching(tmp_path):
    doc_dir = tmp_path / 'ws'
    doc_dir.mkdir()
    (doc_dir / 'x.ws').write_bytes(b'')
    img_dir = doc_dir / 'inset' / 'pix'
    img_dir.mkdir(parents=True)
    target = img_dir / 'wordstar.pix'
    target.write_bytes(b'PIXDATA')

    # tag payload uses uppercase DOS convention; real files are lowercase
    got = resolve_pix(rb'C:\WS\INSET\PIX\WORDSTAR.PIX', doc_dir / 'x.ws')
    assert got == str(target)


def test_resolve_no_candidate_returns_none(tmp_path):
    doc_dir = tmp_path / 'docs'
    doc_dir.mkdir()
    (doc_dir / 'X.WS').write_bytes(b'')
    assert resolve_pix(DOS_PATH, doc_dir / 'X.WS') is None


def test_resolve_accepts_str_payload():
    # non-bytes payload, and a doc_path that doesn't exist at all --
    # resolve_pix must not raise, just report no match
    assert resolve_pix('C:\\WS\\INSET\\PIX\\WORDSTAR.PIX',
                        '/nonexistent/dir/DOC.WS') is None


def test_resolve_empty_payload_returns_none(tmp_path):
    assert resolve_pix(b'', tmp_path / 'X.WS') is None
    assert resolve_pix(b'\x00\x00\x00', tmp_path / 'X.WS') is None


# ============================================================== corpus gauntlet

CTRLKD_PIX_SAMPLES = os.environ.get('CTRLKD_PIX_SAMPLES')


@pytest.mark.skipif(not CTRLKD_PIX_SAMPLES, reason='CTRLKD_PIX_SAMPLES not set')
def test_corpus_samples_decode_without_error():
    paths = sorted(glob.glob(os.path.join(CTRLKD_PIX_SAMPLES, '*.PIX')) +
                    glob.glob(os.path.join(CTRLKD_PIX_SAMPLES, '*.pix')))
    assert paths, f'no .PIX files found under {CTRLKD_PIX_SAMPLES}'
    ok, text_mode = 0, 0
    for p in paths:
        data = open(p, 'rb').read()
        try:
            w, h, rgb = pix.decode(data)
        except pix.PixTextModeUnsupported:
            text_mode += 1
            continue
        assert w > 0 and h > 0
        assert len(rgb) == h
        assert all(len(row) == w for row in rgb)
        png = pix.to_png(data)
        assert png.startswith(b'\x89PNG\r\n\x1a\n')
        ok += 1
    assert ok + text_mode == len(paths)
    assert ok > 0
