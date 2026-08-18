"""ctrlkd.pictures tests -- synthetic fixtures only (no corpus content
ships here, same discipline as test_pix.py). Resolution/decode failure
paths are exercised directly; the real-corpus embed/export acceptance
tests live alongside the format-specific tests (test_ctrlkd.py /
test_pix.py), gated on the real WS7 tree being present.
"""
import struct

import pytest

from ctrlkd import pictures


def _tiny_pix_bytes(gcols=8, grows=1, prt_options_raw=None):
    """A minimal, structurally valid, single-row MONO .PIX: row 0 is
    always stored raw (no vertical-RLE compression needed for one row),
    so this needs none of test_pix.py's tile-encoding machinery."""
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


class _FakeDoc:
    def __init__(self, graphics):
        self.graphics = graphics


def test_resolve_document_pictures_decodes_a_real_file(tmp_path):
    img_dir = tmp_path / 'INSET' / 'PIX'
    img_dir.mkdir(parents=True)
    (img_dir / 'WORDSTAR.PIX').write_bytes(_tiny_pix_bytes())
    doc = _FakeDoc([r'C:\WS\INSET\PIX\WORDSTAR.PIX'])
    results = pictures.resolve_document_pictures(doc, tmp_path / 'DOC.WS')
    assert len(results) == 1
    r = results[0]
    assert r.ok
    assert r.error is None
    assert r.gcols == 8 and r.grows == 1
    assert r.png.startswith(b'\x89PNG\r\n\x1a\n')
    assert r.resolved_path.lower().endswith('wordstar.pix')


def test_resolve_document_pictures_reports_unresolved_when_missing(tmp_path):
    doc = _FakeDoc([r'C:\WS\INSET\PIX\NOPE.PIX'])
    results = pictures.resolve_document_pictures(doc, tmp_path / 'DOC.WS')
    assert results[0].error == 'unresolved'
    assert not results[0].ok


def test_resolve_document_pictures_reports_unresolved_with_no_doc_path():
    doc = _FakeDoc([r'C:\WS\INSET\PIX\WORDSTAR.PIX'])
    results = pictures.resolve_document_pictures(doc, None)
    assert results[0].error == 'unresolved'


def test_resolve_document_pictures_reports_text_mode(tmp_path):
    data = bytearray(_tiny_pix_bytes())
    # flip htype bit0 off -> alphanumeric/text mode (find the mode blob's
    # own offset-1 byte inside the assembled file: header(4) + one index
    # entry(8) * however many items precede DataID 0 -- DataID 0 is
    # always first here, so its data starts right after the index table)
    rev, nitems = struct.unpack_from('<HH', data, 0)
    did, dlen, dloc = struct.unpack_from('<HHI', data, 4)
    assert did == 0
    data[dloc + 1] = 0     # htype bit0 clear
    (tmp_path / 'WORDSTAR.PIX').write_bytes(bytes(data))
    doc = _FakeDoc([r'C:\WORDSTAR.PIX'])
    results = pictures.resolve_document_pictures(doc, tmp_path / 'DOC.WS')
    assert results[0].error == 'text-mode'
    assert not results[0].ok


def test_resolve_document_pictures_reports_format_error(tmp_path):
    (tmp_path / 'BAD.PIX').write_bytes(b'not a real pix file')
    doc = _FakeDoc([r'C:\BAD.PIX'])
    results = pictures.resolve_document_pictures(doc, tmp_path / 'DOC.WS')
    assert results[0].error == 'format-error'


def test_report_misses_writes_one_line_per_miss(tmp_path):
    import io
    doc = _FakeDoc([r'C:\NOPE.PIX', r'C:\ALSO-MISSING.PIX'])
    results = pictures.resolve_document_pictures(doc, tmp_path / 'DOC.WS')
    buf = io.StringIO()
    pictures.report_misses(results, 'DOC.WS', tmp_path / 'DOC.WS', file=buf)
    out = buf.getvalue()
    assert "NOPE.PIX' not found" in out
    assert "ALSO-MISSING.PIX' not found" in out
    assert out.count('\n') == 2


def test_report_misses_silent_on_full_success(tmp_path):
    import io
    (tmp_path / 'WORDSTAR.PIX').write_bytes(_tiny_pix_bytes())
    doc = _FakeDoc([r'C:\WORDSTAR.PIX'])
    results = pictures.resolve_document_pictures(doc, tmp_path / 'DOC.WS')
    buf = io.StringIO()
    pictures.report_misses(results, 'DOC.WS', tmp_path / 'DOC.WS', file=buf)
    assert buf.getvalue() == ''


def test_write_export_images_writes_pngs_and_dedupes_names(tmp_path):
    (tmp_path / 'WORDSTAR.PIX').write_bytes(_tiny_pix_bytes())
    doc = _FakeDoc([r'C:\A\WORDSTAR.PIX', r'C:\B\WORDSTAR.PIX'])
    # both tags resolve to files with the same basename (a real scenario:
    # two different pix tags pointing at same-named files in different
    # source directories) -- second one deliberately unresolved here to
    # keep the fixture simple; dedupe is exercised via two DIFFERENT
    # basenames colliding after sanitizing instead:
    import dataclasses
    base = pictures.resolve_document_pictures(
        _FakeDoc([r'C:\WORDSTAR.PIX']), tmp_path / 'DOC.WS')[0]
    # two independent occurrences of a tag with the same basename
    results = [dataclasses.replace(base, index=0), dataclasses.replace(base, index=1)]
    out_dir = tmp_path / 'DOC-images'
    written = pictures.write_export_images(results, str(out_dir))
    assert len(written) == 2
    assert len(set(written.values())) == 2   # deduped, distinct filenames
    for name in written.values():
        assert (out_dir / name).exists()
        assert (out_dir / name).read_bytes().startswith(b'\x89PNG\r\n\x1a\n')


def test_write_export_images_skips_failed_results(tmp_path):
    doc = _FakeDoc([r'C:\NOPE.PIX'])
    results = pictures.resolve_document_pictures(doc, tmp_path / 'DOC.WS')
    out_dir = tmp_path / 'DOC-images'
    written = pictures.write_export_images(results, str(out_dir))
    assert written == {}
    assert not out_dir.exists()


def _prt_options(row_dp=0, col_dp=0):
    fields = [100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, row_dp, col_dp, 0]
    return struct.pack('<15h', *fields) + bytes(range(16))


def test_physical_size_flows_through_when_print_options_present(tmp_path):
    # 4680 dp / 720 = 6.5in, 1440 dp / 720 = 2.0in
    data = _tiny_pix_bytes(prt_options_raw=_prt_options(row_dp=1440, col_dp=4680))
    (tmp_path / 'SIZED.PIX').write_bytes(data)
    doc = _FakeDoc([r'C:\SIZED.PIX'])
    results = pictures.resolve_document_pictures(doc, tmp_path / 'DOC.WS')
    r = results[0]
    assert r.ok
    assert r.width_in == pytest.approx(6.5)
    assert r.height_in == pytest.approx(2.0)


def test_physical_size_is_none_when_print_options_absent(tmp_path):
    data = _tiny_pix_bytes()
    (tmp_path / 'UNSIZED.PIX').write_bytes(data)
    doc = _FakeDoc([r'C:\UNSIZED.PIX'])
    results = pictures.resolve_document_pictures(doc, tmp_path / 'DOC.WS')
    r = results[0]
    assert r.ok
    assert r.width_in is None
    assert r.height_in is None
