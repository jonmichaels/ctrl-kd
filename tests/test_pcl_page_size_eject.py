"""HP PCL5 Page Size (`ESC & l # A`) and Paper Source (`ESC & l # H`)
commands eject the current physical page, unconditionally -- planning
#227's `PRINTERS/fontcrib.ws` residual. Neither tools/pcl_text.py nor
tools/pcl_render.py treated anything but a literal 0x0C as a page eject
before this fix.

`sawyer/PRINTERS/fontcrib.ws` restates its `.co5` columnar region
mid-document for a second font-crib chart ("Normal Fonts" immediately
after "WingDings"). The `.pa` at that boundary is silently absorbed by
WordStar's own driver while the columns state is still active (the same
real behavior already established for WINGDING.CHT's own per-column
`.pa` markers -- research/2026-09-08_columns-rule.md section 7), so no
literal 0x0C fires there. But WordStar's driver still re-emits its
per-page setup preamble (`ESC&l2a1h0E` -- Page Size 2, Paper Source 1,
Top Margin 0, byte-identical to the one at true document start) at that
internal page boundary, and a real LaserJet treats THAT as the eject
signal. Both decoders previously measured this document's real WS7
page count as 1; it is actually 2 -- this repo's own engine AND the
Swift port already rendered it as 2 pages and were right all along
(their PDFs for this document are byte-identical to each other).
Verified against the full corpus (291 v4 + 39 v1/v3/legacy
captures, 2026-09-09): this fix moves exactly one document's measured
page count -- this one, 1 -> 2 -- every other capture is byte-for-byte
unchanged (in particular `sawyer/PRINTERS/FONTCRIB.PS` and
`sawyer/PRINTER.PS` stay at 3, and `sawyer/ARTICLES/FORMFEED.WS` --
which restates ONLY orientation, not page size/paper source, at its own
internal page boundaries, and deliberately suppresses form feeds with
`.xl 00`, planning #15's own "formfeed-off" exclusion -- stays at 5).

Orientation (`ESC & l # O`) is deliberately NOT a trigger: it is
re-issued at the top of every internal WordStar page regardless of
whether a real eject already happened moments earlier via a literal
0x0C, so treating it as an independent trigger over-counts on any
document (like FORMFEED.WS) where form feeds are suppressed but the
orientation reset still fires."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

import pcl_text                                              # noqa: E402
import pcl_render                                             # noqa: E402


def _wrapped(data: bytes) -> bytes:
    """A minimal PCL preamble (cursor position) + `data`, so any text run
    inside it lands somewhere with a resolvable position."""
    return b'\x1b&a100H\x1b&a100V' + data


def test_page_size_command_ejects_current_page_pcl_text():
    data = _wrapped(b'chart one\x1b&l2A\x1b&a100H\x1b&a100Vchart two')
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 2
    assert [r['text'] for r in pages[0]] == ['chart one']
    assert [r['text'] for r in pages[1]] == ['chart two']


def test_paper_source_command_ejects_current_page_pcl_text():
    data = _wrapped(b'chart one\x1b&l1H\x1b&a100H\x1b&a100Vchart two')
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 2
    assert [r['text'] for r in pages[0]] == ['chart one']
    assert [r['text'] for r in pages[1]] == ['chart two']


def test_combined_page_size_and_paper_source_group_ejects_once_pcl_text():
    # WordStar's own driver combines both fields in ONE escape sequence,
    # exactly as fontcrib.ws's real capture does: ESC&l2a1h0E (Page Size
    # 2, continues; Paper Source 1, continues; Top Margin 0, ends). Two
    # eject-worthy fields in the SAME group must still only flush once
    # (the second field's flush is a no-op: cur_runs is already empty).
    data = _wrapped(b'chart one\x1b&l2a1h0E\x1b&a100H\x1b&a100Vchart two')
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 2
    assert [r['text'] for r in pages[0]] == ['chart one']
    assert [r['text'] for r in pages[1]] == ['chart two']


def test_orientation_command_does_not_eject_pcl_text():
    # `.xl 00` (form-feeds-off) documents like sawyer/ARTICLES/FORMFEED.WS
    # restate orientation at internal page boundaries without a real
    # eject -- ESC&l#O must never be treated as an independent trigger.
    data = _wrapped(b'chart one\x1b&l0O\x1b&a100H\x1b&a100Vchart two')
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 1
    assert [r['text'] for r in pages[0]] == ['chart one', 'chart two']


def test_page_size_command_before_any_content_is_not_an_eject_pcl_text():
    # The SAME page-size/paper-source preamble is always present at the
    # true start of every capture, before any text is drawn. Must not
    # fabricate a spurious blank leading page.
    data = b'\x1b&l2a1h0E' + _wrapped(b'only page')
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 1
    assert [r['text'] for r in pages[0]] == ['only page']


def test_page_size_command_ejects_current_page_pcl_render():
    data = _wrapped(b'chart one\x1b&l2A\x1b&a100H\x1b&a100Vchart two')
    pages, unhandled, recognized_not_rendered, meta = pcl_render.parse_pcl_extended(data)
    assert len(pages) == 2
    texts = lambda pg: [c['text'] for c in pg if c.get('type', 'text') == 'text']
    assert texts(pages[0]) == ['chart one']
    assert texts(pages[1]) == ['chart two']


def test_paper_source_command_ejects_current_page_pcl_render():
    data = _wrapped(b'chart one\x1b&l1H\x1b&a100H\x1b&a100Vchart two')
    pages, unhandled, recognized_not_rendered, meta = pcl_render.parse_pcl_extended(data)
    assert len(pages) == 2
    texts = lambda pg: [c['text'] for c in pg if c.get('type', 'text') == 'text']
    assert texts(pages[0]) == ['chart one']
    assert texts(pages[1]) == ['chart two']


def test_orientation_command_does_not_eject_pcl_render():
    data = _wrapped(b'chart one\x1b&l0O\x1b&a100H\x1b&a100Vchart two')
    pages, unhandled, recognized_not_rendered, meta = pcl_render.parse_pcl_extended(data)
    assert len(pages) == 1
    texts = [c['text'] for c in pages[0] if c.get('type', 'text') == 'text']
    assert texts == ['chart one', 'chart two']


def test_page_size_command_before_any_content_is_not_an_eject_pcl_render():
    data = b'\x1b&l2a1h0E' + _wrapped(b'only page')
    pages, unhandled, recognized_not_rendered, meta = pcl_render.parse_pcl_extended(data)
    assert len(pages) == 1
    texts = [c['text'] for c in pages[0] if c.get('type', 'text') == 'text']
    assert texts == ['only page']
