r"""M16 (2026-09-15): WHERE A RUNNING HEAD'S LINES GO.

Jon, reviewing sawyer/REF/BOOKLET.WS: "REF/BOOKLET.WS seems broken. Native
and Printed show very different things. I don't think Printed is showing
the right-hand header in the correct spot, but I can't easily check it
against the WordStar output."

Checked against the WordStar output. Real WS7 prints that document's two
header lines -- `.h1 Header Odd #` and `.h2 Header Even #` -- on ONE row at
y = 0.57in, "Header Even 1" starting at x = 0.20in and "Header Odd 1" at
x = 9.21in on an 11in landscape sheet. The engine stacked them on two rows
and put "Header Odd 1" 3.71in in.

SIX PROBES, printed by real WordStar 7 under DOSBox-X against the pristine
`PRISTINE.EXE` install, each one byte-editing a scratch copy of the
document so the file length (and therefore its style-library pointer) never
moves. Every one of them is reproduced exactly by the engine as this file
leaves it; the numbers are recorded in
`vault WordStar/research/2026-09-15_booklet-heads-under-columns.md`.

  B0  the document as it stands, driver patched to LASERJET (its own GOTH
      is not in the pristine install's table). Both heads at y = 0.57in,
      x = 0.20 and 9.21. Reproduces the `ws7-prints/v4` capture exactly,
      which is what makes the other five trustworthy.
  B1  `.lh 0` commented out, columns left alone -> TWO rows, 0.40 and 0.57,
      the x values unchanged. So the columns do not collapse the lines.
  B2  `.co 2  1.00"` commented out, `.lh 0` left alone -> ONE row, the x
      values unchanged. So the line height does collapse them, and the x
      is not the column grid's doing either.
  B3  `.co 3  1.00"` with `.rm 2.50"` instead of `.co 2` with `.rm 4.50"`
      -> the heads do not move at all. So the x is not `.rm`'s doing.
  B4  `.po` 0.2in -> 1.2in: both heads move by exactly 1.00in, "Header Odd
      1" landing at 10.21in, past the right edge of an 11in sheet. So the
      x is measured from `.po`.
  B5  `.h2` commented out, `.lh 0` also out: the ONE remaining head line
      prints at 0.57in -- the row the SECOND of two occupies, not the
      first. So the block is anchored on its last line.

THE TWO RULES, with zero counter-examples in 308 WS7 captures and 6 probes:

  1. A right- or centre-aligned head/foot line aligns against `.po` plus
     ITS OWN STYLE's right margin. BOOKLET.WS's "Header Odd" style
     declares 18000 HMI = 100 columns = 10.00in, and 0.2 + 10.00 = 10.20in
     is where its last glyph ends. Every other corpus document with an
     aligned head declares a style right margin equal to its own `.rm`,
     which is why reading `.rm` was right everywhere else.
  2. The step between head lines is the `.lh` in force at each line's own
     command -- 1/6in by default, and 0 when the document says `.lh 0`.

Synthetic fixtures for the arithmetic; the archive document for the
measured numbers.
"""
import re

import pytest

from ctrlkd import core, pdf


def _mediabox_h(out):
    m = re.search(rb'/MediaBox \[0 0 (\d+) (\d+)\]', out)
    return int(m.group(2))


def _drawn(out):
    """{(y_in, x_in): text} for page 1, y measured from the TOP."""
    h = _mediabox_h(out)
    st = [s.split(b'\nendstream')[0]
          for s in out.split(b'>>\nstream\n')[1:]][0]
    return {(round((h - float(y)) / 72.0, 2), round(float(x) / 72.0, 2)):
            t.decode('latin-1')
            for x, y, t in re.findall(rb'Ts ([\d.]+) ([\d.]+) Td \((.*?)\) Tj', st)}


# ------------------------------------------------------- the arithmetic

class _Doc:
    """The two fields these helpers read, and nothing else."""
    def __init__(self, style_rm=None, leads=None):
        self.header_style_rm = dict(style_rm or {})
        self.footer_style_rm = {}
        self.header_leads = dict(leads or {})
        self.footer_leads = {}


def test_a_line_with_no_style_right_margin_keeps_the_documents_own_edge():
    doc = _Doc()
    assert pdf._hf_line_right(doc, 'H', 1, 14.4, 338.4) == 338.4


def test_a_style_right_margin_is_measured_from_this_pages_po():
    """BOOKLET.WS's own numbers: `.po` 0.2in (14.4pt) + 100 columns."""
    doc = _Doc(style_rm={1: 100.0})
    assert pdf._hf_line_right(doc, 'H', 1, 14.4, 338.4) == \
        pytest.approx(14.4 + 100.0 * pdf._PDF_PT_PER_COL)
    assert pdf._hf_line_right(doc, 'H', 1, 14.4, 338.4) == pytest.approx(734.4)


def test_the_step_defaults_to_wordstars_own_sixth_of_an_inch():
    assert pdf._hf_line_step_pt(_Doc(), 'H', 1) == 12.0


def test_a_zero_line_height_is_a_zero_step():
    assert pdf._hf_line_step_pt(_Doc(leads={1: 0.0}), 'H', 1) == 0.0


def test_a_declared_line_height_is_the_step():
    """`.lh12` is 12/48in = 18pt."""
    assert pdf._hf_line_step_pt(_Doc(leads={1: 12.0}), 'H', 1) == 18.0


# --------------------------------------------------- the measured document

@pytest.mark.sawyer
def test_booklet_heads_land_where_real_ws7_puts_them(require_sawyer_doc):
    """Probe B0, reproduced. Both head lines on ONE row at 0.57in, "Header
    Even 1" at 0.20in and "Header Odd 1" at 9.21in -- the same numbers the
    `ws7-prints/v4` capture carries, to the hundredth of an inch."""
    with open(require_sawyer_doc('REF/BOOKLET.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    drawn = _drawn(pdf.emit_pdf(doc, mode='printed'))
    assert drawn.get((0.57, 0.20)) == 'Header Even 1', sorted(drawn)[:6]
    assert drawn.get((0.57, 9.21)) == 'Header Odd 1', sorted(drawn)[:6]


@pytest.mark.sawyer
def test_booklets_own_style_and_line_height_are_what_the_engine_reads(
        require_sawyer_doc):
    """The two IR fields the placement rests on, read off the real file so
    a parser change that silently drops either is caught here rather than
    in a coordinate that happens to still look right."""
    with open(require_sawyer_doc('REF/BOOKLET.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert doc.header_style_rm == {1: 100.0}        # 18000 HMI / 180
    assert doc.header_leads == {1: 0.0, 2: 0.0}     # its own `.lh 0`


@pytest.mark.sawyer
def test_a_default_two_line_head_is_untouched(require_sawyer_doc):
    """The corpus's other multi-line heads declare no `.lh` and no style
    right margin, so they keep the rows and the left edge they had: this
    one's two lines a sixth of an inch apart, both at `.po`."""
    with open(require_sawyer_doc('MAILLIST/PROOF.LST'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert doc.header_leads == {}
    assert doc.header_style_rm == {}
