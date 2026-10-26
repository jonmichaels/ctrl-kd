"""Planning #577 (ruling R-130): in Printed mode a document WITH notes lays
out exactly like one WITHOUT, apart from the note area itself. There is one
paginator for both (`_doc_to_pagelines`); a note is a feature it runs when
the document has one. These tests state that as behaviour: the same text,
with and without a footnote on its last line, gets the same page furniture
and the same line geometry.
"""
from ctrlkd import core, pdf


def _ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _ws7_note(cmd, text, number=1, line_count=1, number_format=3, convert_to=0):
    conv_flag = ((number_format & 0x0F) << 4) | (convert_to & 0x0F)
    content = (line_count.to_bytes(2, 'little') + number.to_bytes(2, 'little') +
               bytes([conv_flag]) + text)
    return _ws7_block(cmd, content)


# Dot commands that each took a different path with notes before the routes
# were one: space before/after, `.pm` first-line indent, `.sr` roll, even/odd
# page offset, a running head, and a changed top margin.
_FURNISHED_DOTS = (b'.psb .2"\r\n.psa .1"\r\n.pm 4\r\n.sr 6\r\n.poe .5"\r\n'
                   b'.poo 1"\r\n.he RUNNING\r\n.mt 2\r\n')


def _furnished(with_note):
    data = _FURNISHED_DOTS + b'Alpha line.\r\n\r\nBeta line'
    if with_note:
        data += _ws7_note(0x03, b'A note.', number=0)
    return core.parse_ws(data + b'.\r\n')


def _pages(doc):
    return pdf._doc_to_pagelines(doc, True)


def _body(page):
    """Every line the source supplied (they carry a block index): everything
    but the note area's own lines."""
    return [ln for ln in page if getattr(ln, 'bi', None) is not None]


def test_a_document_with_a_note_gets_the_same_line_geometry_as_one_without():
    plain, noted = _pages(_furnished(False)), _pages(_furnished(True))
    assert len(plain) == len(noted) == 1
    want, got = _body(plain[0]), _body(noted[0])
    assert len(got) == len(want)
    for a, b in zip(got, want):
        assert a.lead == b.lead                 # space before/after, style leads
        assert a.fi == b.fi                     # .pm first-line indent
        assert a.pm_active == b.pm_active
        assert a.roll == b.roll                 # .sr roll
        assert a.left == b.left                 # .po/.poe/.poo
        assert a.parity_left == b.parity_left
    # The spacing really is in force on both, or the comparison proves nothing.
    assert any((ln.lead or 0) > pdf._printed_lead(_furnished(False)) for ln in want)


def test_a_page_with_a_note_carries_the_same_stamps_and_running_head_as_one_without():
    plain = _pages(_furnished(False))[0]
    noted = _pages(_furnished(True))[0]
    assert noted.headers == plain.headers
    assert noted.headers[1] == 'RUNNING'
    assert noted.footers == plain.footers
    assert noted.mt_lines == plain.mt_lines     # the page's own .mt
    assert noted.mb_lines == plain.mb_lines
    assert noted.pl_lines == plain.pl_lines
    assert noted.po_cols == plain.po_cols       # .poo resolved for the page's parity
    assert noted.auto_pageno_po == plain.auto_pageno_po


def test_the_note_area_is_the_only_thing_a_page_with_a_note_adds():
    plain = _pages(_furnished(False))[0]
    noted = _pages(_furnished(True))[0]
    area = [ln for ln in noted if getattr(ln, 'bi', None) is None]
    assert all(getattr(ln, 'bi', None) is not None for ln in plain)
    assert any('A note.' in ''.join(t for t, _ in ln) for ln in area)
    assert len(noted) == len(plain) + len(area)
