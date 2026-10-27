"""WS4's page counter and page furniture, as the WS4 teardown shows them
(planning #549; `wordstar4-dos/4-formatting-printing.md` 3.1/3.2,
`evidence/pass3/exe-static.md` 8 and 9). The rules live in `core.Era`
fields, so each test sets the same document against the WS4 and the WS7
era and states where they differ."""
from ctrlkd import core, pdf


def _doc(lines, variant):
    data = b''.join(ln + b'\r\n' for ln in lines) + b'\x1a'
    return core.parse(data, variant=variant)


def _page_sizes(lines, variant):
    pages = pdf._doc_to_pagelines(_doc(lines, variant), True)
    return [len(p) for p in pages]


def _numbered(prefix, n):
    return [b'%s%02d' % (prefix, i + 1) for i in range(n)]


def test_era_fields_name_the_ws4_rules():
    ws4, ws7 = core.era_for('ws4'), core.era_for('ws5+')
    assert (ws4.line_starts_in_room, ws4.geometry_acts_at_once) == (True, True)
    assert (ws7.line_starts_in_room, ws7.geometry_acts_at_once) == (False, False)
    assert ws4.pk_even_keeps_blank is False and ws7.pk_even_keeps_blank is True
    assert ws4.pc_default == 28 and ws7.pc_default == 33.5


def test_automatic_page_number_sits_at_pc_28_for_ws4_and_centred_for_ws7():
    # (po 8 + pc - 1) columns of 7.2pt: WS4 column 28, WS7's centred 33.5
    assert pdf._auto_pageno_x_pt(_doc([b'text'], 'ws4')) == 252.0
    assert pdf._auto_pageno_x_pt(_doc([b'text'], 'ws5+')) == 291.6
    # an explicit .pc wins in both
    assert pdf._auto_pageno_x_pt(_doc([b'.pc 10', b'text'], 'ws4')) == 122.4


def test_ctrl_k_in_a_header_on_an_even_page_drops_its_blanks_in_ws4_only():
    text = '\x0b     Pg #'
    assert pdf._ctrl_k_even_page(text, 2, keep_blank=False) == 'Pg #'
    assert pdf._ctrl_k_even_page('\x0b \t Pg #', 2, keep_blank=False) == 'Pg #'
    assert pdf._ctrl_k_even_page(text, 2) == ' Pg #'              # WS7 keeps one
    assert pdf._ctrl_k_even_page(text, 3, keep_blank=False) == text


def test_ws4_page_holds_ceil_h_over_lh_lines():
    # H = 440 units: 55 at LH 8 (both eras), 37 at LH 12 in WS4 (floor(439/12)
    # + 1) where WS7 fits only whole lines (36)
    body = _numbered(b'a', 80)
    assert _page_sizes(body, 'ws4')[0] == 55
    assert _page_sizes(body, 'ws5+')[0] == 55
    assert _page_sizes([b'.lh 12'] + body, 'ws4')[:2] == [37, 37]
    assert _page_sizes([b'.lh 12'] + body, 'ws5+')[0] == 36


def test_ws4_lh_change_mid_file_costs_each_line_its_own_lh():
    # run t43-lh: 30 lines at 8, `.LH 16`: page 1 ends after the 13th line at
    # 16 (R = 439 - 240 - 12 * 16 = 7, the 13th overruns)
    lines = _numbered(b'a', 30) + [b'.lh 16'] + _numbered(b'b', 30)
    assert _page_sizes(lines, 'ws4')[0] == 43


def test_ws4_mt_mb_read_mid_page_change_the_page_in_progress():
    # run t43-mtmb: `.MT 10 .MB 2` after 30 lines: H = 432, so page 1 holds
    # 54 lines although it opened at the factory margins
    lines = (_numbered(b'a', 30) + [b'.mt 10', b'.mb 2']
             + _numbered(b'b', 70))
    pages = pdf._doc_to_pagelines(_doc(lines, 'ws4'), True)
    assert len(pages[0]) == 54
    assert pages[0].mt_lines == 3.0         # printed with the opening margins
    assert pages[0].mb_lines == 2           # footer set from the margin at its end
    # a later `.MB 12` tightens the page it is read on (H = 408: 51 lines,
    # where WS7 never tightens a page)
    lines = _numbered(b'a', 70) + [b'.mb 12'] + _numbered(b'b', 70)
    sizes = _page_sizes(lines, 'ws4')
    assert sizes[0] == 55 and sizes[1] == 51


def test_ws4_cp_breaks_when_fewer_than_n_lines_remain_whatever_follows():
    # run w14-cpfoot: `.CP 10` after 50 lines leaves 5 lines of room and only
    # 3 lines follow the command; WS4 still breaks, the lines that follow are
    # not what is counted
    lines = _numbered(b'n', 50) + [b'.cp 10', b'x1', b'x2', b'x3']
    assert _page_sizes(lines, 'ws4') == [50, 3]
    # room for exactly n lines does not break
    lines = _numbered(b'n', 45) + [b'.cp 10', b'x1', b'x2', b'x3']
    assert _page_sizes(lines, 'ws4') == [48]


def test_ws7_cp_also_counts_the_lines_it_asks_for():
    # WS7 report 11.3/14.3: room / line height < n breaks (runs cp4-cp6); 5
    # lines of room, `.cp 6` breaks even with one line after it
    lines = _numbered(b'n', 50) + [b'.cp 6', b'x1']
    assert _page_sizes(lines, 'ws5+') == [50, 1]
    lines = _numbered(b'n', 50) + [b'.cp 5', b'x1']
    assert _page_sizes(lines, 'ws5+') == [51]
