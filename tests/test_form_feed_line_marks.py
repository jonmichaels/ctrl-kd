"""A form feed on a physical line no longer throws that line's marks away
(planning #270, triage round 2026-09-14, item 2 -- the real answer to Q8).

Q8 asked which of a font block's "two records" governs the text after it.
There are no two records: WSFORMAT.TXT's type-2 Font is six words -- the
CURRENT width/height/typestyle and then the PREVIOUS three, which is why the
CLOSING block of a pair carries the same pair reversed. This engine has always
read the first three, i.e. the right ones.

What was actually wrong is one level up. `sawyer/PRINT.TST`'s "Paragraph
Indentation" heading is `.cb` + a bare form feed + ^B + its own font block
(Helv 11pt, HMI 138), and `lines_pass` split that physical line at the form
feed and decoded the pieces with NO marks at all -- so the font block never
reached the text and the heading was measured in the Courier carried over from
the previous line. Real WS7 sets it in Helv: 54.4pt for "Paragraph " on the v4
PRISTINE capture, page 2 y=288.0pt, which is Helvetica 11pt's own width for
those ten characters.

The same loss took every other span-level mark on such a line: colour changes,
note references, index entries, print controls and tab targets. All of them are
now carried into the piece they belong to, re-based to its own first byte.

Type 15h (Alternate/Normal font change) is the same family and is covered here
too: WSFORMAT gives it a state flag before the font triples, and this engine
read the flag bytes as a width.
"""
import os

import pytest

from ctrlkd import core, pdf


HARD = b'\x0d\x0a'
FF = b'\x0c'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def font_block(w, h, style, prev=(180, 240, 17411)):
    return ws7_block(0x02, (w.to_bytes(2, 'little') + h.to_bytes(2, 'little')
                            + style.to_bytes(2, 'little')
                            + prev[0].to_bytes(2, 'little')
                            + prev[1].to_bytes(2, 'little')
                            + prev[2].to_bytes(2, 'little')))


def alt_font_block(w, h, style, flag=1, prev_flag=0,
                   prev=(180, 240, 17411)):
    """Type 15h: "Byte: Normal = 0, Alternate = 1", paired new-then-previous
    exactly as the font triples that follow it are."""
    return ws7_block(0x15, (bytes([flag, prev_flag])
                            + w.to_bytes(2, 'little') + h.to_bytes(2, 'little')
                            + style.to_bytes(2, 'little')
                            + prev[0].to_bytes(2, 'little')
                            + prev[1].to_bytes(2, 'little')
                            + prev[2].to_bytes(2, 'little')))


HELV_11 = (138, 220, 49156)      # PRINT.TST's own heading font, verbatim
LINEPRINTER = (108, 170, 16384)  # CODES.WS's own 15h font, verbatim


def build(body):
    return core.parse_ws(ws7_block(0x00) + body)


def span_fonts(doc):
    """(text, font entry) for every span that carries a font tag."""
    out = []
    for b in doc.blocks:
        for line in b.lines:
            for s in line.spans:
                idx = next((int(t[4:]) for t in s.styles
                            if t.startswith('font') and t[4:].isdigit()), None)
                out.append((s.text, None if idx is None else doc.fonts[idx]))
    return out


def test_a_font_block_after_a_form_feed_reaches_the_text():
    doc = build(b'Body' + HARD + FF + font_block(*HELV_11) + b'Heading' + HARD)
    fonts = dict((t, f) for t, f in span_fonts(doc) if t == 'Heading')
    assert fonts['Heading']['points'] == 11.0
    assert fonts['Heading']['proportional'] is True


def test_a_mark_before_the_form_feed_stays_on_its_own_piece():
    """The bounds partition the line: a mark can reach one piece and one
    only, and the form-feed byte itself belongs to the piece before it."""
    doc = build(font_block(*HELV_11) + b'First' + FF + b'Second' + HARD)
    got = {t: (f or {}).get('points') for t, f in span_fonts(doc)}
    assert got['First'] == 11.0
    assert got['Second'] == 11.0          # modal: the font stays in force


def test_a_tab_target_on_a_form_feed_line_survives():
    tab = ws7_block(0x09, b'\x00\x00' + (900).to_bytes(2, 'little')
                    + b'\x20' + b'\x00')
    doc = build(b'Body' + HARD + FF + tab + b'     Space:' + HARD)
    tabbed = [s for b in doc.blocks for line in b.lines for s in line.spans
              if any(t.startswith('tabhmi') for t in s.styles)]
    assert tabbed and 'tabhmi900' in tabbed[0].styles


def test_a_note_reference_on_a_form_feed_line_survives():
    doc = build(b'Body' + HARD + FF + b'Tail'
                + ws7_block(0x03, b'\x00' * 8 + b'the note') + HARD)
    marks = [s.text for b in doc.blocks for line in b.lines for s in line.spans
             if 'fnref' in s.styles]
    assert marks == ['1']


def test_an_alternate_font_block_reads_past_its_two_state_bytes():
    doc = build(b'Body' + alt_font_block(*LINEPRINTER) + b'Alt' + HARD)
    entry = dict(span_fonts(doc))['Alt']
    assert (entry['width_1800'], entry['height_1440']) == (108, 170)
    assert entry['points'] == 8.5
    assert entry['typestyle_name'] == 'LinePrinter'


# ---------------------------------------------------------------------------
# the measured documents

pytestmark_archive = pytest.mark.skipif(
    not os.environ.get('CTRLKD_SAWYER_ARCHIVE'),
    reason='CTRLKD_SAWYER_ARCHIVE unset -- the measured documents live there')


@pytestmark_archive
@pytest.mark.sawyer
@pytest.mark.parametrize('rel', ['PRINT.TST', 'DEFAULT/PRINT.TST'])
def test_print_tst_sets_its_heading_in_helv_like_ws7(rel):
    """The v4 PRISTINE capture: "Paragraph"@218.1pt, "Indentation"@272.6pt,
    page 2 y=288.0pt -- a 54.4pt advance for "Paragraph ", Helvetica 11pt's
    own width for those ten characters. And with the heading measured in its
    real face, `.pf on` joins it to one line, as WS7 prints it."""
    path = os.path.join(os.environ['CTRLKD_SAWYER_ARCHIVE'], rel)
    doc = core.parse_ws(open(path, 'rb').read())
    heading = [(s.text, s.styles) for b in doc.blocks for line in b.lines
               for s in line.spans if 'Paragraph Indenta' in s.text
               or s.text == 'Paragraph Indentation']
    assert heading, 'the heading line moved -- re-measure before editing this'
    idx = next(int(t[4:]) for t in heading[0][1]
               if t.startswith('font') and t[4:].isdigit())
    entry = doc.fonts[idx]
    assert entry['points'] == 11.0
    assert entry['typestyle_name'].startswith('Helv')
    lines = [''.join(t for t, _ in pl)
             for page in pdf._doc_to_pagelines(doc, True) for pl in page]
    assert any('Paragraph Indentation' in ln for ln in lines)


@pytestmark_archive
@pytest.mark.sawyer
def test_no_font_block_in_print_tst_is_left_unapplied():
    """Every font block the file declares governs some span. `font 0` is the
    document's own header default and has no mark of its own, so it is the one
    entry legitimately never tagged."""
    path = os.path.join(os.environ['CTRLKD_SAWYER_ARCHIVE'], 'PRINT.TST')
    doc = core.parse_ws(open(path, 'rb').read())
    used = {int(t[4:]) for b in doc.blocks for line in b.lines
            for s in line.spans for t in s.styles
            if t.startswith('font') and t[4:].isdigit()}
    assert set(range(1, len(doc.fonts))) - used == set()


@pytestmark_archive
@pytest.mark.sawyer
@pytest.mark.parametrize('rel,expected', [
    ('REF/CODES.WS', [(108, 170), (180, 240)]),
    ('REF/-TOC-TAG.WS', [(180, 240), (108, 170), (180, 210), (180, 240)]),
])
def test_the_two_archive_documents_with_15h_blocks_read_real_fonts(rel, expected):
    path = os.path.join(os.environ['CTRLKD_SAWYER_ARCHIVE'], rel)
    doc = core.parse_ws(open(path, 'rb').read())
    got = [(f['width_1800'], f['height_1440']) for f in doc.fonts]
    assert got == expected
