"""b28 note 6: the blank line ahead of the first ENDNOTE on a page that
also carries body text.

Jon, reviewing b27 against real WS7 output: "On the last page of Printed
from WS7, the endnotes go *immediately* after the text. In ours we add a
line return before the notes in our engine. Ours looks better but it's
not accurate."

The gap was introduced unconditionally in round 26 wave 3 on the strength
of a 2026-08-20 measurement of -SCREEN.pcl that read a 240-decipoint
advance as "24pt, one blank line". WS7's note face is 12-point, so ONE
note line IS 120dp and 240dp is two -- the measurement was right about
-SCREEN and wrong to generalise. Re-measured 2026-08-23 across both WS7
captures (jon_vault WordStar/ws7-prints/v1/):

    -SCREEN.pcl  "1. Footnote" V=7080 -> "(1) Endnote"  V=7320 = 240dp
                 = one blank line, endnotes joining a FOOTNOTE AREA.
    TESTING.pcl  last body line     V=3765 -> "(1)This..." V=3885 = 120dp
                 = NO blank line, endnotes following BODY TEXT.
    TESTING.pcl  endnote (1) V=3885 -> (2) V=4125 = 240dp = one blank
                 line BETWEEN entries (unchanged by this fix).

So the leading gap is conditional on `last_page_has_area`. Synthetic
fixtures only, per CLAUDE.md -- the two WS7 captures above are the
external evidence, these tests pin the resulting behaviour.
"""
from ctrlkd import core, pdf

HARD = b'\x0d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def ws7_note(cmd, text, number=1, line_count=1, number_format=3, convert_to=0):
    conv_flag = ((number_format & 0x0F) << 4) | (convert_to & 0x0F)
    content = (line_count.to_bytes(2, 'little') + number.to_bytes(2, 'little') +
               bytes([conv_flag]) + text)
    return ws7_block(cmd, content)


WS5_SEED = ws7_block(0x0B, b'\x00' * 4)
ENDNOTE, FOOTNOTE = 0x04, 0x03


def _pages(data):
    return pdf._doc_to_pagelines(core.parse_ws(data), True)


def _texts(page):
    """One joined string per PageLine, blank lines preserved as ''."""
    return [''.join(t for t, _ in line).rstrip() for line in page]


def _index_of(lines, needle):
    for i, t in enumerate(lines):
        if needle in t:
            return i
    raise AssertionError(f'{needle!r} not in {lines!r}')


def test_endnote_after_body_text_has_no_leading_blank_line():
    """WS7 TESTING.pcl: 120dp = one note line = the endnote butts straight
    up against the last body line. Fails before the fix (a '' line sat
    between them)."""
    data = (b'Body line one.' + HARD +
            b'Body line two carries the marker.' +
            ws7_note(ENDNOTE, b'This is our test endnote.') + HARD +
            WS5_SEED + b'\x1a')
    lines = _texts(_pages(data)[-1])
    body = _index_of(lines, 'Body line two')
    note = _index_of(lines, 'This is our test endnote.')
    assert note == body + 1, (
        'WS7 puts the first endnote on the very next line after body text; '
        f'got {note - body} lines of gap in {lines!r}')


def test_endnote_after_a_footnote_area_keeps_its_leading_blank_line():
    """WS7 -SCREEN.pcl: 240dp = two note lines = one blank line, because
    the endnote is joining the footnote AREA as one more entry. This must
    NOT regress when the body-text case above loses its gap."""
    data = (b'Body text with both marks.' +
            ws7_note(FOOTNOTE, b'Footnote body.') +
            ws7_note(ENDNOTE, b'Endnote body.') + HARD +
            WS5_SEED + b'\x1a')
    lines = _texts(_pages(data)[-1])
    fn = _index_of(lines, 'Footnote body.')
    en = _index_of(lines, 'Endnote body.')
    assert en == fn + 2 and lines[fn + 1] == '', (
        'an endnote joining a footnote area keeps exactly one blank line '
        f'above it; got {lines[fn:en + 1]!r}')


def test_successive_endnotes_keep_one_blank_line_between_them():
    """WS7 TESTING.pcl endnote (1) V=3885 -> (2) V=4125 = 240dp. The
    inter-entry gap is a separate rule from the leading one."""
    data = (b'Body text.' +
            ws7_note(ENDNOTE, b'First endnote.') +
            ws7_note(ENDNOTE, b'Second endnote.', number=2) + HARD +
            WS5_SEED + b'\x1a')
    lines = _texts(_pages(data)[-1])
    a = _index_of(lines, 'First endnote.')
    b = _index_of(lines, 'Second endnote.')
    assert b == a + 2 and lines[a + 1] == '', (
        f'expected one blank line between endnote entries; got {lines[a:b + 1]!r}')
