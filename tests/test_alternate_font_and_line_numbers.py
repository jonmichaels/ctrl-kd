"""Planning #549: two Printed behaviours read from WS7's own runs.

E20 -- raw 01h (^PA) selects the printer's alternate font, 0Eh the normal one.
On LASERJET the alternate font is Gothic 10 point at 14.29 cpi (21 dots a
character); a bare tab after such text goes to the next 8-column stop by
distance, not by character count (WS7 teardown, `wordstar-dos/14-runs.md`,
run raw01-lj).

E27 -- `.l#` numbers every row of the page, the empty ones after the text too,
and draws a double bar at 504 decipoints and a single bar at 5328 beside each
number (`wordstar-dos/reference/drivera-map.txt`, run lnum-lj).
"""
import re
import zlib

from ctrlkd import core, pdf


def _ws7(body, driver=b'LASERJET'):
    head = bytearray(128)
    head[0:4] = b'\x1d}\x00\x00'
    head[4:5] = b'p'
    head[5:5 + len(driver)] = driver
    head[125:128] = b'}\x00\x1d'
    return core.parse(bytes(head) + body + b'\x1a' * 8, variant='ws5+')


def _lines(doc):
    return [ln for ln in pdf._doc_to_pagelines(doc, True)[0]
            if hasattr(ln, 'justify_right_x')]


def test_the_alternate_font_is_gothic_at_14_29_cpi_on_laserjet():
    doc = _ws7(b'\x01wwwwwwwwww\x01\tX in 01\r\n')
    fonts = pdf._render_fonts(doc)
    _, family, size, entry = pdf._span_render('w', frozenset({'altfont'}), fonts, 12)
    assert (size, family) == (10, 'Courier')
    assert pdf._span_pitch(entry, size) == 126 / 25            # 21 dots
    # the normal font after 0Eh is the document's own
    _, _, size, entry = pdf._span_render('w', frozenset(), fonts, 12)
    assert (size, entry) == (12, None)


def test_the_alternate_font_needs_the_laserjet_driver():
    doc = _ws7(b'\x01w\r\n', driver=b'DRAFT')
    assert pdf._render_fonts(doc).alt is None


def test_a_tab_after_alternate_font_text_goes_to_the_next_stop_by_distance():
    """Ten alternate-font characters are 7 columns of the 10-cpi ruler, so
    the tab stops at column 8 (57.6pt), not at column 16."""
    doc = _ws7(b'\x01wwwwwwwwww\x01\tX in 01\r\n')
    line = _lines(doc)[0]
    tabs = [st for _, st in line if any(t.startswith('tabhmi') for t in st)]
    assert len(tabs) == 1
    assert 'tabhmi1440' in tabs[0]                  # 1440/1800 inch = 8 columns
    out = pdf.emit_pdf(doc, mode='printed', page_numbers='off')
    streams = b''.join(zlib.decompress(m[1]) if m[1][:1] == b'x' else m[1]
                       for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', out, re.S))
    assert re.search(rb'115\.2 [\d.]+ Td \(X in 01\) Tj', streams)   # po 57.6 + 8 columns


def test_an_ordinary_tab_keeps_the_column_rule():
    doc = _ws7(b'wwwwwwwwww\tX\r\n')
    line = _lines(doc)[0]
    assert ''.join(t for t, _ in line) == 'wwwwwwwwww' + ' ' * 6 + 'X'


def test_line_numbers_run_to_the_end_of_the_page_with_bars():
    doc = _ws7(b'.l# 1\r\nline 01\r\nline 02\r\n')
    page = pdf._doc_to_pagelines(doc, True)[0]
    assert len(page) == 55
    labelled = [ln for ln in page if ln.line_no is not None]
    assert [ln.line_no[0] for ln in labelled] == [str(i) for i in range(1, 56)]
    assert labelled[0].line_no[1] == 21.6 and round(labelled[9].line_no[1], 1) == 14.4
    for ln in labelled:
        assert [c[:2] for c in ln.graphic_cells] == [('║', 50.4), ('│', 532.8)]
    assert page[-1].graphic_cells is not None


def test_numbering_turned_off_before_the_end_does_not_fill_the_page():
    doc = _ws7(b'.l# 1\r\nline 01\r\n\r\n.l# 0\r\nline 02\r\n')
    page = pdf._doc_to_pagelines(doc, True)[0]
    assert len(page) < 55
