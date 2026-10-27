"""WS7's vertical page flow in Printed, as the teardown runs show it (WS7 report
14.3, 14.5, 15.1, 15.10). Each case builds a small WS7 document and asserts
what lands on which page, and where -- the fixtures in
`tests/test_teardown_fixtures.py` carry the same shapes against the real
captures; these keep the rules covered without the teardowns checkout.

  a blank line after a full page, or after a trailing `.pa`, is a text line
  and makes a page that prints its number (pg55b, pa3);
  a `.pa` on a page that holds nothing yet is ignored (patop, paful);
  empty soft-return lines at the top of a page ended for room are swallowed,
  hard-return ones are not (sb8d, blank3);
  a page ended by a bare form feed prints no foot (ff2);
  under `.lh a` a line is led by the font it starts in and nothing carries
  further (lead3, lead5), and a line whose font raises its height stays at
  the page bottom when the rise fits the room left (tall24, tall36);
  the automatic number's baseline does not move with `.cw` (w16-cwtab).
"""
import re

from ctrlkd import core, pdf
from ctrlkd.typestyles import TYPESTYLE_NAMES

HARD = b'\x0d\x0a'
SOFT = b'\x8d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _fblock(number, points, proportional=True):
    ts = (number & 0x01FF) | (0x8000 if proportional else 0)
    return ws7_block(0x02, (180).to_bytes(2, 'little')
                     + round(points * 20).to_bytes(2, 'little')
                     + ts.to_bytes(2, 'little') + bytes(6))


def _face(prefix):
    return next(k for k, v in TYPESTYLE_NAMES.items() if v.lower().startswith(prefix))


def _doc(body, dots=b''):
    """A WS7 document: the header block makes it read as one, never as plain
    text."""
    return core.parse_ws(ws7_block(0x00) + dots + body)


def _lines(n, first=1):
    return HARD.join(b'line %02d' % k for k in range(first, first + n)) + HARD


def _pages(doc):
    return pdf._doc_to_pagelines(doc, True)


def _texts(page):
    return [''.join(t for t, _ in ln).strip() for ln in page]


def _page_count(data):
    return len(re.findall(rb'/Type\s*/Page\b', data))


# ---------------------------------------------------------------- blank lines
def test_a_blank_line_after_a_full_page_makes_a_page_that_prints_its_number():
    doc = _doc(_lines(55) + HARD)
    assert doc.meta['eof_blank_lines'] == 1
    pages = _pages(doc)
    assert [len(pg) for pg in pages] == [55, 0]
    assert pages[1].explicit_break          # a page, though nothing is left on it
    assert pages[1].auto_pageno['text'] == '2'


def test_a_blank_line_that_fits_makes_no_page():
    pages = _pages(_doc(_lines(54) + HARD))
    assert [len(pg) for pg in pages] == [54]


def test_a_blank_line_after_a_trailing_pa_makes_a_page():
    pages = _pages(_doc(_lines(10) + b'.pa' + HARD + HARD))
    assert len(pages) == 2 and not pages[1]
    assert pages[1].auto_pageno['text'] == '2'


def test_a_trailing_pa_alone_makes_no_page():
    assert len(_pages(_doc(_lines(10) + b'.pa' + HARD))) == 1


def test_modern_still_drops_the_empty_trailing_page():
    data = pdf.emit_pdf(_doc(_lines(55) + HARD), mode='modern')
    assert _page_count(data) == 2          # 55 lines of Modern text spill by themselves
    short = pdf.emit_pdf(_doc(_lines(3) + HARD + HARD), mode='modern')
    assert _page_count(short) == 1


def test_the_old_era_keeps_dropping_the_trailing_blank_run():
    doc = core.parse_ws(_lines(55) + HARD, variant='ws4')
    assert doc.meta['variant'] == 'ws4'
    assert [len(pg) for pg in _pages(doc)] == [55]


# ---------------------------------------------------------------- .pa
def test_a_pa_as_the_first_line_adds_no_empty_page():
    pages = _pages(_doc(b'.pa' + HARD + _lines(3)))
    assert len(pages) == 1 and _texts(pages[0])[0] == 'line 01'


def test_a_pa_right_after_a_pa_adds_no_empty_page():
    pages = _pages(_doc(b'One.' + HARD + b'.pa' + HARD + b'.pa' + HARD + b'Two.' + HARD))
    assert [_texts(pg) for pg in pages] == [['One.'], ['Two.']]


def test_a_pa_after_a_form_feed_adds_no_empty_page():
    pages = _pages(_doc(b'One.\x0c' + HARD + b'.pa' + HARD + b'Two.' + HARD))
    assert [_texts(pg) for pg in pages] == [['One.'], ['Two.']]


def test_a_pa_after_a_full_page_still_breaks_once():
    pages = _pages(_doc(_lines(55) + b'.pa' + HARD + b'after' + HARD))
    assert [len(pg) for pg in pages] == [55, 1]


# ---------------------------------------------------------------- soft blanks
def test_empty_soft_return_lines_are_swallowed_at_a_room_break():
    soft = _doc(_lines(55) + SOFT * 3 + b'x' + HARD)
    pages = _pages(soft)
    assert [_texts(pg) for pg in pages][1] == ['x']


def test_empty_hard_return_lines_carry_over_to_the_top_of_the_next_page():
    pages = _pages(_doc(_lines(55) + HARD * 3 + b'x' + HARD))
    assert _texts(pages[1]) == ['', '', '', 'x']


def test_soft_blanks_after_a_pa_are_not_swallowed():
    pages = _pages(_doc(_lines(3) + b'.pa' + HARD + SOFT * 2 + b'x' + HARD))
    assert _texts(pages[1]) == ['', '', 'x']


# ---------------------------------------------------------------- form feed
def test_a_page_ended_by_a_bare_form_feed_prints_no_number():
    pages = _pages(_doc(_lines(5) + b'\x0c' + _lines(5, 6)))
    assert [_texts(pg) for pg in pages] == [[f'line {k:02d}' for k in range(1, 6)],
                                             [f'line {k:02d}' for k in range(6, 11)]]
    assert pages[0].ended_by_form_feed and pages[0].auto_pageno is None
    assert not pages[1].ended_by_form_feed and pages[1].auto_pageno['text'] == '2'


def test_a_form_feed_page_prints_no_footer_either():
    doc = _doc(b'.fo Foot #' + HARD + _lines(5) + b'\x0c' + _lines(5, 6))
    pages = _pages(doc)
    assert not pages[0].footer_lines
    assert [ln['text'] for ln in pages[1].footer_lines] == ['Foot 2']


def test_a_pa_page_still_prints_its_number():
    pages = _pages(_doc(_lines(5) + b'.pa' + HARD + _lines(5, 6)))
    assert pages[0].auto_pageno['text'] == '1'


# ---------------------------------------------------------------- .lh a
def _leads(doc):
    return [ln.lead for ln in _pages(doc)[0]]


def _auto_doc(body):
    return _doc(body, b'.lh a' + HARD)


def test_a_line_is_led_by_the_font_it_starts_in_and_nothing_carries_further():
    """lead3: line 3 is Times 24, closed before its return; line 4 is Courier
    again and advances 12."""
    times, courier = _face('tms'), _face('courier')
    body = (b'line 01' + HARD + b'line 02' + HARD
            + _fblock(times, 24) + b'line 03' + _fblock(courier, 12, proportional=False) + HARD
            + b'line 04' + HARD + b'line 05' + HARD)
    assert _leads(_auto_doc(body))[:5] == [12.0, 12.0, 24.0, 12.0, 12.0]


def test_a_font_that_runs_into_the_next_line_leads_it_too():
    """lead5: the 24-pt font runs from mid line 3 into line 4."""
    times, courier = _face('tms'), _face('courier')
    body = (b'line 01' + HARD + b'line 02' + HARD
            + b'line 03 ' + _fblock(times, 24) + b'BIG' + HARD
            + b'line 04 big' + _fblock(courier, 12, proportional=False) + b' small' + HARD
            + b'line 05' + HARD)
    assert _leads(_auto_doc(body))[:5] == [12.0, 12.0, 24.0, 24.0, 12.0]


def test_a_blank_line_takes_the_font_the_line_above_ended_in():
    times = _face('tms')
    body = (b'line 01' + HARD + _fblock(times, 24) + b'BIG' + HARD + HARD
            + b'tail' + HARD)
    assert _leads(_auto_doc(body))[:4] == [12.0, 24.0, 24.0, 24.0]


def test_the_font_in_force_at_the_end_of_a_line_counts_a_trailing_record():
    times, courier = _face('tms'), _face('courier')
    doc = _auto_doc(b'line 01' + HARD + _fblock(times, 24) + b'big'
                    + _fblock(courier, 12, proportional=False) + HARD + b'small' + HARD)
    _, first, second = [ln for ln in doc.blocks[0].lines if ln.spans][:3]
    assert doc.fonts[first.font_out]['points'] == 12.0
    assert doc.fonts[second.font_out]['points'] == 12.0


def _tall_page_one(points):
    times, courier = _face('tms'), _face('courier')
    body = (_lines(54) + _fblock(times, points) + b'line 55' + _fblock(courier, 12, proportional=False) + HARD
            + b'line 56' + HARD)
    pages = _pages(_auto_doc(body))
    return [_texts(pg)[-1] for pg in pages]


def test_a_line_whose_rise_fits_the_room_left_stays_and_overhangs():
    """tall24: line 55 starts in a font that raises it by exactly the room
    left."""
    assert _tall_page_one(24) == ['line 55', 'line 56']


def test_a_line_whose_rise_exceeds_the_room_moves_to_the_next_page():
    """tall36: the rise is more than the room left."""
    assert _tall_page_one(36) == ['line 54', 'line 56']


# ---------------------------------------------------------------- .cw
def test_the_automatic_number_does_not_move_with_cw():
    plain = _pages(_doc(_lines(3)))[0].auto_pageno
    wide = _pages(_doc(_lines(3), b'.cw 20' + HARD))[0].auto_pageno
    assert plain['y'] == wide['y']


def test_the_old_era_number_row_still_follows_the_type_size():
    plain = _pages(core.parse_ws(_lines(3), variant='ws4'))[0].auto_pageno
    wide = _pages(core.parse_ws(b'.cw 20' + HARD + _lines(3), variant='ws4'))[0].auto_pageno
    assert plain['y'] != wide['y']
