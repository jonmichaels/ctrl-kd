"""HP PCL5's Transparent Print Data command (ESC & p <count> X) -- planning
#202 cause 9. Neither tools/pcl_text.py nor tools/pcl_render.py implemented
it: the next <count> bytes after the terminator are OPAQUE LITERAL data, not
PCL to parse and not a text run to place at the cursor. WordStar's LaserJet
driver uses this to draw each 0x00-0x1F control-character glyph in
sawyer/REF/ASCIITAB.WS one byte at a time -- and one of those bytes is 0x0C,
which both decoders misread as a real form-feed page eject (splitting one
real WS7 page into three), with the escape sequence right after it leaking
into the next "text run" as a literal string fragment.

Confirmed against the real corpus (2026-09-08): with this fix, both tools
report ASCIITAB.WS's real capture as ONE page (matching ctrl-kd's own
rendering exactly -- the fidelity gate goes fully clean), and three more
Transparent-Print-bearing documents' ground-truth page counts corrected
(sawyer/PRINTER.PS and its duplicate FONTCRIB.PS: 7 -> 3; sawyer/PRINTERS/
fontcrib.ws: 4 -> 1). This was always a capture-decoder bug, never a
WordStar-engine one -- ASCIITAB.WS's real page count was always 1."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

import pcl_text                                              # noqa: E402
import pcl_render                                             # noqa: E402


def _wrapped(data: bytes) -> bytes:
    """A minimal PCL preamble (cursor position) + `data`, so any text run
    inside it lands somewhere with a resolvable position."""
    return b'\x1b&a100H\x1b&a100V' + data


def test_transparent_print_data_is_skipped_not_parsed_pcl_text():
    # ESC & p 1 X <0x0C> -- one byte of opaque data that happens to be a
    # literal form-feed byte. Must NOT eject a page or appear as text.
    data = _wrapped(b'before\x1b&p1X\x0cafter')
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 1
    texts = [r['text'] for r in pages[0]]
    assert texts == ['before', 'after']


def test_transparent_print_data_skips_multiple_bytes_pcl_text():
    # ESC & p 3 X <3 opaque bytes, including an escape and a form feed> --
    # none of it should be parsed as PCL or text.
    data = _wrapped(b'before\x1b&p3X\x1b\x0c!after')
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 1
    texts = [r['text'] for r in pages[0]]
    assert texts == ['before', 'after']


def test_real_form_feed_outside_transparent_print_still_ejects_pcl_text():
    # A BARE 0x0C (not inside ESC&p#X) is still a real page eject -- this
    # fix must not swallow genuine form feeds anywhere else. Real PCL
    # always re-establishes cursor position after a form feed before
    # printing (the parser drops text with no known position -- see
    # parse_pcl's own "preamble text" comment), so this test does too.
    data = _wrapped(b'page one\x0c\x1b&a100H\x1b&a100Vpage two')
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 2
    assert [r['text'] for r in pages[0]] == ['page one']
    assert [r['text'] for r in pages[1]] == ['page two']


def test_transparent_print_data_is_skipped_pcl_render():
    data = _wrapped(b'before\x1b&p1X\x0cafter')
    pages, unhandled, recognized_not_rendered, meta = pcl_render.parse_pcl_extended(data)
    assert len(pages) == 1
    texts = [c['text'] for c in pages[0] if c.get('type', 'text') == 'text']
    assert texts == ['before', 'after']


def test_real_form_feed_outside_transparent_print_still_ejects_pcl_render():
    data = _wrapped(b'page one\x0c\x1b&a100H\x1b&a100Vpage two')
    pages, unhandled, recognized_not_rendered, meta = pcl_render.parse_pcl_extended(data)
    assert len(pages) == 2
