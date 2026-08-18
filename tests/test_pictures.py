"""ctrlkd.pictures tests -- synthetic fixtures only (no corpus content
ships here, same discipline as test_pix.py). Resolution/decode failure
paths are exercised directly; the real-corpus embed/export acceptance
tests live alongside the format-specific tests (test_ctrlkd.py /
test_pix.py), gated on the real WS7 tree being present.
"""
import os
import struct
import tempfile

import pytest

from ctrlkd import core, emit, pictures


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


# ======================================================= emitter wiring

def _ws_pix_block(payload, jump=None):
    if jump is None:
        jump = len(payload) + 4
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([0x10]) + payload + j + b'\x1d'


def _doc_with_one_pix(tmp_path, payload=br'C:\PIX\FIGURE1.PIX',
                      pix_bytes=None, name='FIGURE1.PIX'):
    """A parsed doc with one pix tag, its .PIX file written next to a
    fake source document 'DOC.WS' under tmp_path -- resolve_document_
    pictures walks from there. Returns (doc, pix_results, docpath)."""
    if pix_bytes is None:
        pix_bytes = _tiny_pix_bytes()
    (tmp_path / name).write_bytes(pix_bytes)
    docpath = tmp_path / 'DOC.WS'
    docpath.write_bytes(b'')
    block = _ws_pix_block(payload)
    doc = core.parse_ws(b'Before. ' + block + b' After.\r\n')
    results = pictures.resolve_document_pictures(doc, docpath)
    return doc, results, docpath


def test_rtf_off_mode_is_byte_identical_to_no_pix_results(tmp_path):
    doc, results, _ = _doc_with_one_pix(tmp_path)
    without = emit.emit_rtf(doc, mode='modern')
    off = emit.emit_rtf(doc, mode='modern', pictures='off', pix_results=results)
    assert without == off
    assert '[image: FIGURE1.PIX]' in off


def test_rtf_embed_replaces_placeholder_with_native_pict():
    with tempfile.TemporaryDirectory() as d:
        import pathlib
        doc, results, _ = _doc_with_one_pix(pathlib.Path(d))
        rtf = emit.emit_rtf(doc, mode='modern', pictures='embed', pix_results=results)
    assert r'\pict\pngblip' in rtf
    assert '[image: FIGURE1.PIX]' not in rtf


def test_rtf_embed_uses_print_options_size_when_present(tmp_path):
    prt = struct.pack('<15h', 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                      1440, 4680, 0) + bytes(range(16))
    doc, results, _ = _doc_with_one_pix(
        tmp_path, pix_bytes=_tiny_pix_bytes(prt_options_raw=prt))
    rtf = emit.emit_rtf(doc, mode='modern', pictures='embed', pix_results=results)
    # 6.5in -> 9360 twips, 2.0in -> 2880 twips
    assert r'\picwgoal9360' in rtf
    assert r'\pichgoal2880' in rtf


def test_rtf_miss_keeps_placeholder_even_with_pictures_embed(tmp_path):
    doc, results, _ = _doc_with_one_pix(tmp_path, payload=br'C:\PIX\NOPE.PIX',
                                        name='SOMETHING-ELSE.PIX')
    assert results[0].error == 'unresolved'
    rtf = emit.emit_rtf(doc, mode='modern', pictures='embed', pix_results=results)
    assert '[image: NOPE.PIX]' in rtf
    assert r'\pict' not in rtf


def test_html_off_mode_is_byte_identical_to_no_pix_results(tmp_path):
    doc, results, _ = _doc_with_one_pix(tmp_path)
    without = emit.emit_html(doc, mode='modern')
    off = emit.emit_html(doc, mode='modern', pictures='off', pix_results=results)
    assert without == off


def test_html_embed_uses_data_uri():
    with tempfile.TemporaryDirectory() as d:
        import pathlib
        doc, results, _ = _doc_with_one_pix(pathlib.Path(d))
        html = emit.emit_html(doc, mode='modern', pictures='embed', pix_results=results)
    assert 'data:image/png;base64,' in html
    assert '[image: FIGURE1.PIX]' not in html


def test_html_export_uses_relative_link_from_image_links(tmp_path):
    doc, results, _ = _doc_with_one_pix(tmp_path)
    html = emit.emit_html(doc, mode='modern', pictures='export', pix_results=results,
                          image_links={0: 'DOC-images/FIGURE1.png'})
    assert 'src="DOC-images/FIGURE1.png"' in html
    assert 'data:image/png;base64,' not in html


def test_html_miss_keeps_placeholder(tmp_path):
    doc, results, _ = _doc_with_one_pix(tmp_path, payload=br'C:\PIX\NOPE.PIX',
                                        name='SOMETHING-ELSE.PIX')
    html = emit.emit_html(doc, mode='modern', pictures='embed', pix_results=results)
    assert '[image: NOPE.PIX]' in html


def test_html_embed_sets_explicit_size_from_print_options(tmp_path):
    prt = struct.pack('<15h', 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                      1440, 4680, 0) + bytes(range(16))
    doc, results, _ = _doc_with_one_pix(
        tmp_path, pix_bytes=_tiny_pix_bytes(prt_options_raw=prt))
    html = emit.emit_html(doc, mode='modern', pictures='embed', pix_results=results)
    assert 'width:6.500in' in html
    assert 'height:2.000in' in html


def test_md_modern_off_is_byte_identical_to_no_pix_results(tmp_path):
    doc, results, _ = _doc_with_one_pix(tmp_path)
    for mode in ('modern', 'printed'):
        without = emit.emit_markdown(doc, mode=mode)
        off = emit.emit_markdown(doc, mode=mode, pictures='off', pix_results=results)
        assert without == off


def test_md_printed_fence_is_untouched_by_pictures_regardless_of_mode(tmp_path):
    # a fenced facsimile is the emitter saying "verbatim" (round 17b's own
    # fence-scoping lesson) -- pix substitution must never reach inside it,
    # same "TXT: skip entirely" scope cut MD's own printed body inherits
    # for free from emit_text.
    doc, results, _ = _doc_with_one_pix(tmp_path)
    printed_off = emit.emit_markdown(doc, mode='printed', pictures='off', pix_results=results)
    printed_embed = emit.emit_markdown(doc, mode='printed', pictures='embed',
                                       pix_results=results,
                                       image_links={0: 'DOC-images/FIGURE1.png'})
    assert printed_off == printed_embed
    assert 'FIGURE1.PIX' in printed_off       # placeholder text still present


def test_md_modern_embed_renders_relative_link_when_image_links_given(tmp_path):
    doc, results, _ = _doc_with_one_pix(tmp_path)
    md = emit.emit_markdown(doc, mode='modern', pictures='embed', pix_results=results,
                            image_links={0: 'DOC-images/FIGURE1.png'})
    assert '![FIGURE1.PIX](DOC-images/FIGURE1.png)' in md


def test_md_modern_export_renders_the_same_relative_link_shape(tmp_path):
    doc, results, _ = _doc_with_one_pix(tmp_path)
    md = emit.emit_markdown(doc, mode='modern', pictures='export', pix_results=results,
                            image_links={0: 'DOC-images/FIGURE1.png'})
    assert '![FIGURE1.PIX](DOC-images/FIGURE1.png)' in md


def test_md_modern_embed_without_image_links_falls_back_to_placeholder(tmp_path):
    # a library caller that asked for 'embed' but never wrote the file
    # (no image_links) must never get a link to a file that doesn't
    # exist -- degrades to the unchanged placeholder text instead.
    doc, results, _ = _doc_with_one_pix(tmp_path)
    md = emit.emit_markdown(doc, mode='modern', pictures='embed', pix_results=results)
    assert '![' not in md
    assert 'FIGURE1.PIX' in md


def test_md_modern_miss_keeps_placeholder(tmp_path):
    doc, results, _ = _doc_with_one_pix(tmp_path, payload=br'C:\PIX\NOPE.PIX',
                                        name='SOMETHING-ELSE.PIX')
    md = emit.emit_markdown(doc, mode='modern', pictures='embed', pix_results=results,
                            image_links={0: 'DOC-images/NOPE.png'})
    assert '![' not in md
    assert 'NOPE.PIX' in md


# ============================================================== PDF wiring

def test_pdf_printed_off_is_byte_identical_to_no_pix_results(tmp_path):
    from ctrlkd import pdf
    doc, results, _ = _doc_with_one_pix(tmp_path)
    without = pdf.emit_pdf(doc, mode='printed')
    off = pdf.emit_pdf(doc, mode='printed', pictures='off', pix_results=results)
    assert without == off


def _doc_with_isolated_pix(tmp_path, pix_bytes=None):
    """Like _doc_with_one_pix, but the pix tag sits ALONE on its own
    paragraph (blank lines before and after) -- the real-corpus shape
    (confirmed against all 5 acceptance documents: a picture reference is
    never mid-sentence), and the shape PDF's own block-level substitution
    requires (see _doc_to_pagelines's "other_text" safety check)."""
    if pix_bytes is None:
        pix_bytes = _tiny_pix_bytes()
    (tmp_path / 'FIGURE1.PIX').write_bytes(pix_bytes)
    docpath = tmp_path / 'DOC.WS'
    docpath.write_bytes(b'')
    block = _ws_pix_block(br'C:\PIX\FIGURE1.PIX')
    doc = core.parse_ws(b'Before.\r\n\r\n' + block + b'\r\n\r\nAfter.\r\n')
    results = pictures.resolve_document_pictures(doc, docpath)
    return doc, results, docpath


def test_pdf_printed_embed_places_an_image_xobject(tmp_path):
    from ctrlkd import pdf
    doc, results, _ = _doc_with_isolated_pix(tmp_path)
    out = pdf.emit_pdf(doc, mode='printed', pictures='embed', pix_results=results)
    assert b'/Subtype /Image' in out
    assert b'/Im0 Do' in out


def test_pdf_printed_off_never_emits_an_xobject(tmp_path):
    from ctrlkd import pdf
    doc, results, _ = _doc_with_isolated_pix(tmp_path)
    out = pdf.emit_pdf(doc, mode='printed', pictures='off', pix_results=results)
    assert b'/Subtype /Image' not in out
    assert b'/Im0 Do' not in out


def test_pdf_printed_miss_keeps_placeholder_text_no_xobject(tmp_path):
    from ctrlkd import pdf
    doc, results, _ = _doc_with_one_pix(tmp_path, payload=br'C:\PIX\NOPE.PIX',
                                        name='SOMETHING-ELSE.PIX')
    out = pdf.emit_pdf(doc, mode='printed', pictures='embed', pix_results=results)
    assert b'/Im0 Do' not in out
    assert b'NOPE.PIX' in out


def test_pdf_printed_text_sharing_the_line_prevents_substitution(tmp_path):
    # safety rule: never silently drop real text -- a pix tag that (in a
    # hypothetical document) shares its physical line with other prose
    # falls back to the ordinary placeholder-text rendering instead of
    # embedding, rather than risk losing the prose.
    from ctrlkd import pdf
    pix_bytes = _tiny_pix_bytes()
    (tmp_path / 'FIGURE1.PIX').write_bytes(pix_bytes)
    docpath = tmp_path / 'DOC.WS'
    docpath.write_bytes(b'')
    block = _ws_pix_block(br'C:\PIX\FIGURE1.PIX')
    doc = core.parse_ws(b'Caption text ' + block + b'\r\n')
    results = pictures.resolve_document_pictures(doc, docpath)
    out = pdf.emit_pdf(doc, mode='printed', pictures='embed', pix_results=results)
    assert b'/Im0 Do' not in out
    assert b'FIGURE1.PIX' in out
    assert b'Caption text' in out


def test_pdf_modern_mode_pictures_flag_is_a_documented_scope_cut(tmp_path):
    # Modern PDF is a separate reflow pipeline (_modern_streams); pix
    # embedding is scoped to Printed PDF only this round -- verify the
    # scope cut is real (byte-identical) rather than silently half-applied.
    from ctrlkd import pdf
    doc, results, _ = _doc_with_one_pix(tmp_path)
    without = pdf.emit_pdf(doc, mode='modern')
    on = pdf.emit_pdf(doc, mode='modern', pictures='embed', pix_results=results)
    assert without == on


def test_pdf_printed_embed_scales_to_print_options_size(tmp_path):
    from ctrlkd import pdf
    prt = struct.pack('<15h', 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                      144, 288, 0) + bytes(range(16))    # 0.2in x 0.4in -- small, no cap
    doc, results, _ = _doc_with_isolated_pix(
        tmp_path, pix_bytes=_tiny_pix_bytes(prt_options_raw=prt))
    out = pdf.emit_pdf(doc, mode='printed', pictures='embed', pix_results=results)
    # 0.4in -> 28.8pt width, 0.2in -> 14.4pt height in the `cm` operator
    assert b'28.80 0 0 14.40' in out


@pytest.mark.skipif(
    not os.path.exists('<PRIVATE-SAWYER-ROOT>/WS/PREVIEW.WS'),
    reason='real WS7 corpus not present on this machine')
def test_real_corpus_acceptance_all_five_resolve_four_of_five_embed():
    """Round 19 acceptance (RULINGS-LEDGER PIX row): the 5 real documents
    that reference WORDSTAR.PIX -- -SCREEN.WS, PREVIEW.WS, and the 3
    distinct -README.WS documents -- all resolve it via the ancestor walk
    from their real tree positions. 4 of 5 actually EMBED (Printed PDF, the
    main pagination path); -SCREEN.WS is a KNOWN, DOCUMENTED gap (its own
    footnotes route it through `_paginate_printed_notes`, a structurally
    different, line-count pagination path this round does not extend --
    same class of documented gap as round 17b's .pm/.psa/.psb) -- it still
    degrades safely to the placeholder text, never fails."""
    from ctrlkd import pdf
    paths = {
        '-README.WS (root)': '<PRIVATE-SAWYER-ROOT>/WS/-README.WS',
        '-SCREEN.WS': '<PRIVATE-SAWYER-ROOT>/WS/-SCREEN.WS',
        'PREVIEW.WS': '<PRIVATE-SAWYER-ROOT>/WS/PREVIEW.WS',
        '-README.WS (APP)': '<PRIVATE-SAWYER-ROOT>/WS/APP/-README.WS',
        '-README.WS (APP/vDosPlus)':
            '<PRIVATE-SAWYER-ROOT>/WS/APP/vDosPlus/-README.WS',
    }
    known_gap = {'-SCREEN.WS'}
    for label, path in paths.items():
        doc = core.parse(open(path, 'rb').read())
        results = pictures.resolve_document_pictures(doc, path)
        assert len(results) == 1, label
        assert results[0].ok, (label, results[0].error)
        assert results[0].resolved_path.upper().endswith('WORDSTAR.PIX'), label
        out = pdf.emit_pdf(doc, mode='printed', pictures='embed', pix_results=results)
        embedded = b'/Im0 Do' in out
        if label in known_gap:
            assert not embedded, f'{label} unexpectedly embedded -- gap may be closed, update this test'
            assert b'WORDSTAR.PIX' in out    # placeholder still present, never fails
        else:
            assert embedded, label
