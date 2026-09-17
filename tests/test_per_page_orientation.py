"""M31: `.pr or=l` / `.pr or=p` is a PER-PAGE sheet, not one flag for the
whole document.

WHAT WAS WRONG. `.pr or=` was captured once, at parse time, into
`doc.meta['formatting']['orientation']` -- whatever value the file happened
to set LAST. That is the same defect class core.py already names and
excludes for `po_cols` and `lead_48` ("a third copy here would be the LAST
value the file happened to set, which means nothing"); it simply never
reached `.pr`. A file that asks for landscape on one page and portrait on
the rest therefore printed every page portrait, and a landscape page's
content ran off the right edge of a page too narrow to hold it -- silently,
because a PDF viewer clips at the MediaBox without complaining.

THE TIMING RULE IS MEASURED, not inferred. Real WordStar 7 under DOSBox-X,
printing through the LASERJET driver to PCL5, 2026-09-17:

  MIDPAGE probe -- two lines of text, then `.pr or=l`, then a third line,
  then `.pa`:
      offset 0x0030  ESC&l0O   portrait, written at the top of page 1
      offset 0x0128  0x0c      form feed ending page 1
      offset 0x0129  ESC&l1O   landscape, one byte AFTER that form feed
  All THREE of page 1's lines -- including the one after `.pr or=l` --
  printed under the portrait setting. WS7 emits no orientation escape
  mid-page at all; it queues the change to the next page boundary.

  TOPPAGE probe -- `.pr or=l` immediately after a `.pa`, before that
  page's text:
      0x008c  0x0c      form feed ending page 1
      0x008d  ESC&l1O   landscape, before page 2's own text
      0x00cc  0x0c      form feed ending page 2
      0x00cd  ESC&l0O   portrait again, before page 3's text
  Each command applies to the page it OPENS.

So: the orientation in force at the position a page OPENS at is that page's
sheet, and a command reached later in the page belongs to the next one. The
position is `(block, how many lines of that block earlier pages took)` --
the block alone cannot tell the two probes apart, because a `.pr` typed
between two lines of a paragraph sits in the SAME block the page opened at.

SYNTHETIC ONLY, per this repo's own rule -- every document below is
constructed bytes. The real-world document this was found on
(`ARTICLES/FORMFEED.WS`, whose ruler-diagram page asks for landscape and
whose sample pages ask for portrait back) lives in the private corpus and
is covered by the shared answer key, not here.
"""
import re

from ctrlkd import core, emit
from ctrlkd.pdf import emit_pdf

HARD = b'\r\n'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


# The WS5+ seed block every real WS5/6/7 document opens with. Without it a
# short, plainly-laid-out synthetic file classifies as a `printstream`, and
# `emit.emit_rtf` then renders a `printstream` PRINTED whatever mode it is
# asked for (a documented, long-standing rule) -- which would make the
# Modern half of the RTF test below assert nothing at all.
WS5_SEED = ws7_block(0x0B, b'\x00' * 4)

_MEDIABOX = re.compile(rb'/MediaBox \[0 0 (\d+) (\d+)\]')


def _boxes(pdf_bytes):
    """(width_pt, height_pt) for every page, in page order."""
    return [(int(w), int(h)) for w, h in _MEDIABOX.findall(pdf_bytes)]


def _printed(data):
    return emit_pdf(core.parse_ws(data), mode='printed')


def _body(tag, lines=3):
    return b''.join(b'%s line %d.' % (tag, i) + HARD for i in range(1, lines + 1))


PORTRAIT = (612, 792)
LANDSCAPE = (792, 612)


# ------------------------------------------------------- the two probe shapes

def test_a_page_top_command_lands_on_the_page_it_opens():
    """TOPPAGE, reproduced: `.pr or=l` after a `.pa` and before that page's
    own text is THAT page's sheet, and `.pr or=p` after the next `.pa` puts
    the page after it back."""
    data = (_body(b'ONE')
            + b'.pa' + HARD + b'.pr or=l' + HARD + _body(b'TWO')
            + b'.pa' + HARD + b'.pr or=p' + HARD + _body(b'THREE'))
    assert _boxes(_printed(data)) == [PORTRAIT, LANDSCAPE, PORTRAIT]


def test_a_mid_page_command_waits_for_the_next_page():
    """MIDPAGE, reproduced: text, then `.pr or=l`, then MORE text on the
    same page. Real WS7 printed all of that page portrait and only turned
    landscape on after the form feed -- so page 1 stays portrait here and
    page 2 is the landscape one."""
    data = (b'ONE line 1.' + HARD + b'ONE line 2.' + HARD
            + b'.pr or=l' + HARD
            + b'ONE line 3, after the landscape command.' + HARD
            + b'.pa' + HARD + _body(b'TWO'))
    boxes = _boxes(_printed(data))
    assert boxes == [PORTRAIT, LANDSCAPE]


def test_an_orientation_declared_before_any_text_owns_page_one():
    """The overwhelmingly common real shape -- a landscape template whose
    `.pr or=l` sits in its opening dot block -- is unchanged: every page
    landscape, exactly as the document-wide flag already gave it."""
    data = b'.pr or=l' + HARD + _body(b'ONE') + b'.pa' + HARD + _body(b'TWO')
    assert _boxes(_printed(data)) == [LANDSCAPE, LANDSCAPE]


def test_a_document_that_never_mentions_pr_is_untouched():
    """No `.pr` anywhere: one sheet, every page, same as before M31."""
    data = _body(b'ONE') + b'.pa' + HARD + _body(b'TWO') + b'.pa' + HARD + _body(b'THREE')
    assert _boxes(_printed(data)) == [PORTRAIT] * 3


# ------------------------------------------------------------- the other surfaces

def test_the_layout_json_publishes_the_sheet_only_where_it_differs():
    """Layout schema version 13: a printed page carries its own `size` ONLY
    when its orientation differs from the document's. A page without one is
    the document's own sheet (the top-level `page` object)."""
    import json
    data = (_body(b'ONE')
            + b'.pa' + HARD + b'.pr or=l' + HARD + _body(b'TWO')
            + b'.pa' + HARD + b'.pr or=p' + HARD + _body(b'THREE'))
    out = json.loads(emit.get_emitter('layout')['fn'](core.parse_ws(data), 'printed'))
    assert out['version'] == 13
    sizes = [pg.get('size') for pg in out['printed']['pages']]
    assert sizes[0] is None and sizes[2] is None
    assert sizes[1] == {'width_pt': 792, 'height_pt': 612,
                        'orientation': 'landscape'}


def test_printed_rtf_opens_a_landscape_section_and_modern_does_not():
    r"""RTF's page size is a section property as well as a document one, so
    the Printed RTF says per section what the Printed PDF says per page.
    Modern deliberately does NOT: Modern PDF composes every page on one
    sheet (ruled 2026-09-15), and Modern PDF is the printed form of the
    Modern RTF (ruled 2026-08-05), so a landscape section there would be an
    RTF its own PDF does not print."""
    data = (WS5_SEED + _body(b'ONE')
            + b'.pa' + HARD + b'.pr or=l' + HARD + _body(b'TWO')
            + b'.pa' + HARD + b'.pr or=p' + HARD + _body(b'THREE'))
    doc = core.parse_ws(data)
    assert not emit._printed(doc), 'fixture must not classify as a print stream'
    printed_rtf = emit.emit_rtf(doc, mode='printed')
    assert r'\pgwsxn15840\pghsxn12240\lndscpsxn' in printed_rtf
    assert emit.emit_rtf(doc, mode='modern').count(r'\lndscpsxn') == 0


def test_html_and_text_are_untouched_by_orientation():
    """Neither is a paged surface; neither has a sheet to change."""
    flat = _body(b'ONE') + b'.pa' + HARD + _body(b'TWO')
    turned = (_body(b'ONE') + b'.pa' + HARD + b'.pr or=l' + HARD + _body(b'TWO'))
    for fmt in ('text', 'html'):
        fn = emit.get_emitter(fmt)['fn']
        a, b = fn(core.parse_ws(flat)), fn(core.parse_ws(turned))
        assert a == b, fmt
