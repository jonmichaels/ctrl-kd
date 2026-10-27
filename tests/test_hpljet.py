"""WS4's HPLJET driver: where it puts a WS4 file's lines and words.

The rules are the WS4 teardown's (`wordstar4-dos/4-formatting-printing.md`
15); the teardowns tier (`test_teardown_fixtures.py`) checks them against
WordStar 4's own captures. These pin the arithmetic on small hand-made lines.
"""
import re
import zlib

import pytest

from ctrlkd import core, hpljet, pdf

HARD = b'\x0d\x0a'
SOFT = b'\x8d\x0a'


def _ws4(body):
    return core.parse_ws(body, variant='ws4')


def _shows(pdf_bytes):
    """(x, y, text) of every Tj, page by page in order."""
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)endstream', pdf_bytes, re.S):
        body = m.group(1)
        try:
            body = zlib.decompress(body)
        except zlib.error:
            pass
        for t in re.finditer(rb'([\d.]+) ([\d.]+) Td \((.*?)\) Tj', body):
            out.append((float(t[1]), float(t[2]), t[3].decode('latin-1')))
    return out


def _y_of(shows, text):
    return next(y for _x, y, t in shows if t.strip() == text)


def _x_of(shows, text):
    return next(x for x, _y, t in shows if t.strip() == text)


def test_line_one_sits_the_vbias_below_the_top_margin_whatever_lh():
    # V = (MT·8 + 16)·15 decipoints: 600 at the factory .MT 3 (60pt from
    # the top), still 600 under .LH 12 (run hj-lh12top)
    for dots in (b'', b'.LH 12' + HARD):
        shows = _shows(pdf.emit_pdf(_ws4(dots + b'one' + HARD + b'two' + HARD), 'printed'))
        assert 792 - _y_of(shows, 'one') == pytest.approx(60.0)


def test_each_line_steps_by_the_lh_of_the_line_above():
    # a .LH changes the step below the next text line (run hj-lhmix)
    body = b'one' + HARD + b'.LH 16' + HARD + b'two' + HARD + b'three' + HARD
    shows = _shows(pdf.emit_pdf(_ws4(body), 'printed'))
    one, two, three = (_y_of(shows, t) for t in ('one', 'two', 'three'))
    assert one - two == pytest.approx(12.0)      # LH 8 in force on 'one'
    assert two - three == pytest.approx(24.0)    # LH 16 in force on 'two'


def test_ws7_printing_a_ws4_file_keeps_ws7s_origin():
    body = b'one' + HARD
    shows = _shows(pdf.emit_pdf(core.parse_ws(body, variant='ws4', printed_by='ws7'),
                                'printed'))
    assert 792 - _y_of(shows, 'one') == pytest.approx(48.0)


def test_the_slack_of_the_editors_soft_spaces_is_re_spread():
    # 'ab' + 20h + A0h + 'cd', b and d flagged, soft return, .CW 12: the
    # nominal width is 6 cells (72), the device width 5 (60, the A0 has
    # none), so S = 12/120"; S per blank 12 > THR 8, so each letter but the
    # last takes one unit (3), and the blank the other 9 (M5-M11)
    chars = [hpljet.Char(0x61), hpljet.Char(0x62, hib=True), hpljet.Char(0x20),
             hpljet.Char(0xA0), hpljet.Char(0x63), hpljet.Char(0x64, hib=True)]
    xs = [x for x, _ in hpljet.place_line(chars, 0, 12, False, 'dis', True)]
    assert xs == [0, 78, 156, 282, 282, 360]
    # a hard return, or .UJ off: the editor's cells
    for uj, soft in (('dis', False), ('off', True)):
        xs = [x for x, _ in hpljet.place_line(chars, 0, 12, False, uj, soft)]
        assert xs == [0, 72, 144, 216, 288, 360]


def test_text_before_the_first_flagged_word_keeps_its_cells():
    # M4: nothing flagged, nothing justified (run mj-nobit)
    chars = [hpljet.Char(c) for c in b'ab'] + [hpljet.Char(0x20), hpljet.Char(0xA0)] + [
        hpljet.Char(c) for c in b'cd']
    xs = [x for x, _ in hpljet.place_line(chars, 0, 12, False, 'dis', True)]
    assert xs == [0, 72, 144, 216, 288, 360]


def test_proportional_words_advance_by_ps14b():
    # §14: 'The ' is 252 units of 1/600" in PS14B; from x 576 (480 units)
    # the next word is at floor(732 x 1.2) = 878 decipoints
    chars = [hpljet.Char(c) for c in b'The quick']
    xs = [x for x, _ in hpljet.place_line(chars, 8, 12, True, 'dis', False)]
    assert xs[0] == 576 and xs[4] == 878


def test_a_justified_ws4_line_is_drawn_word_by_word():
    flagged = bytes([ord('b') | 0x80])
    body = (b'a' + flagged + b' ' + bytes([0xA0]) + b'c' + bytes([ord('d') | 0x80])
            + b' ' + b'ef' + bytes([ord('g') | 0x80]) + SOFT + b'end' + HARD)
    doc = _ws4(body)
    assert doc.blocks[0].lines[0].hibit == (1, 3, 5, 9)
    shows = _shows(pdf.emit_pdf(doc, 'printed'))
    # 'cd' leaves the 72 dp grid (it would sit at 57.6 + 4 x 7.2)
    assert _x_of(shows, 'cd') != pytest.approx(57.6 + 4 * 7.2)


def test_ps_text_is_drawn_in_the_cartridge_face():
    shows_pdf = pdf.emit_pdf(_ws4(b'.PS ON' + HARD + b'The quick' + HARD), 'printed')
    assert b'/BaseFont /Helvetica-Bold' in shows_pdf
    shows = _shows(shows_pdf)
    assert _x_of(shows, 'quick') == pytest.approx(57.6 + (878 - 576) / 10.0)


def test_compos_prints_box_drawing_as_ascii_and_overstrikes_a_cross():
    body = b'\x1b\xda\x1c\x1b\xc4\x1c\x1b\xc5\x1c' + HARD
    shows = _shows(pdf.emit_pdf(_ws4(body), 'printed'))
    texts = [t for _x, _y, t in shows]
    assert '/--' in texts                      # ┌ ─ ┼ as / - -
    assert '|' in texts                        # ┼'s second pass
    # WS7 printing the same file keeps the box glyphs (drawn as vector cells)
    ws7 = _shows(pdf.emit_pdf(core.parse_ws(body, variant='ws4', printed_by='ws7'),
                              'printed'))
    assert '/--' not in [t for _x, _y, t in ws7]
