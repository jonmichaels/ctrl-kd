"""WS7's LASERJET driver: which of its fonts a document's font prints in, and
where each piece of a proportional line goes.

The rules are the WS7 teardown's (report 11.17); the PCL tier
(`test_pcl_fidelity.py`) checks them against WS7's own captures. These pin
the arithmetic on small cases.
"""
from ctrlkd import laserjet as lj
from ctrlkd.laserjet_tables import BLOCKS, FONTS


def _font(name):
    return next(i for i, f in enumerate(FONTS) if f[0] == name)


def _block(name, variant=0):
    return BLOCKS[FONTS[_font(name)][4][variant]]


def test_a_font_record_prints_in_the_driver_font_match_picks():
    # (HMI, twips, typestyle word) as real documents record them
    assert lj.match(137, 240, 0xC605) == _font('Times PC ...')
    assert lj.match(138, 220, 0xC004) == _font('Univer PC ...')      # Helv
    assert lj.match(162, 240, 0xD234) == _font('Univer PC ...')      # Avant Garde
    assert lj.match(120, 240, 0xD25B) == _font('UniverC PC ...')     # Helv Narrow
    assert lj.match(153, 240, 0xD64A) == _font('Garamo PC ...')      # Palatino 12
    assert lj.match(142, 240, 0xC612) == _font('Garamo PC ...')


def test_a_character_is_rounded_to_whole_dots_on_its_own():
    # Times PC 12pt: 'W' is 8294 units, 8294 x 100 x 240 x 300 /
    # (20 x 8782 x 7231) = 47.0 dots; HP's point is 1/72.31 inch
    times = _block('Times PC ...')
    assert lj.char_dots(times, 240, ord('W')) == 47
    assert lj.width_dots('WWW', times, 240, kerning=False) == 3 * 47


def test_a_truetype_face_rounds_pixels_per_em_first():
    tnr = _block('TNRmn PC ...')
    ppem = (240 * 300 + 720) // 1440                     # 50
    w = tnr[6][ord('a')]
    assert lj.char_dots(tnr, 240, ord('a')) == (w * ppem + 1024) // 2048


def test_a_kerning_pair_splits_the_word_and_moves_the_rest():
    # A-V is -26/128 em in Times PC; at 12pt the size is floor(240 x 300 /
    # 1440) = 50 dots, so the pair moves V floor(26 x 50 / 128) = 10 dots in
    times = _block('Times PC ...')
    assert lj.kern_dots(times, 240, ord('A'), ord('V')) == -10
    a = lj.char_dots(times, 240, ord('A'))
    assert lj.pieces('AV', times, 240) == [('A', 0, a), ('V', a - 10, lj.char_dots(times, 240, ord('V')))]
    # .KR OFF: one piece, no move
    assert [p for p, _x, _w in lj.pieces('AV', times, 240, kerning=False)] == ['AV']


def test_no_pair_across_a_blank_and_a_blank_run_is_one_piece():
    times = _block('Times PC ...')
    got = lj.pieces('A  V', times, 240)
    assert [p for p, _x, _w in got] == ['A', '  ', 'V']
    assert got[2][1] == got[1][1] + 2 * lj.char_dots(times, 240, 32)


def test_a_script_is_measured_at_the_blocks_own_script_size():
    # Times 12 -> floor(240 x 175 / 256) = 164, floored to 5 twips: 8pt
    times = _block('Times PC ...')
    assert lj.twips(times, 12, script=True) == 160
    assert lj.twips(times, 12) == 240
