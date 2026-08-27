"""LJ6DTP parity C1: a colour run must not leak past its restore.

Jon, 2026-08-23, asked for engine parity with real WS7 for LJ6DTP.WS. The
worst divergence found is on page 6: two full paragraphs are INVISIBLE in our
Printed output. They are not missing -- `pdftotext` extracts them -- they are
painted white on white. The PDF content stream shows `1.00 g` emitted for the
white-on-black "PRETTY NEAT, HUH?" line and never reset, so every later text
op on that page inherits white.

The document itself warns about exactly this hazard, in its own prose:
"When finished, select 'Black' from the ^P- menu (otherwise the rest of your
text will be invisible -- white letters on a white background)." Real WS7
prints those paragraphs in BLACK (gpcl6 render of v1/LJ6DTP.pcl, page 6), so
the document DOES issue the restore and we are failing to honour it.

The raw bytes carry both halves, as a WSFORMAT type-1 Color block
(current, previous):
    ...<1D 06 00 01 0F 00 06 00 1D>PRETTY NEAT, HUH?<1D 06 00 01 00 0F 06 00 1D>
i.e. set current=0x0F (White) before, restore current=0x00 (Black) after.

`core.parse_ws` records BOTH events correctly in `doc.colours` -- the defect is
downstream, where colour marks are applied to spans as `colourN` style tags
(core.py's `pending_colours`/`active` machinery). The restore is not reaching
the following blocks, so they keep `colour15`.

Fixture: the real LJ6DTP.WS. Tier 2 (sawyer): LJ6DTP.WS is one of the ten
committed manifest documents (tests/SAWYER-CORPUS.md) -- migrated 2026-08-26
from the old CTRLKD_WS7_DOCS/require_ws7 gate to CTRLKD_SAWYER_ARCHIVE, per
Jon's "no third bucket" ruling that day: a Sawyer-archive doc gets ONE tier,
not a divergent duplicate under tier 3.
"""
import pytest

from ctrlkd import core

pytestmark = pytest.mark.sawyer


def _doc(require_sawyer_doc):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        return core.parse_ws(fh.read())


def _line_colours(line):
    out = set()
    for span in line.spans:
        out |= {t for t in span.styles if t.startswith('colour')}
    return out


def _find_line(doc, needle):
    for block in doc.blocks:
        for line in getattr(block, 'lines', []):
            if needle in ''.join(s.text for s in line.spans):
                return line
    raise AssertionError(f'{needle!r} not found in LJ6DTP.WS')


def test_the_white_run_itself_is_still_white(require_sawyer_doc):
    """Guard the thing that already works: the knockout text on the black bar
    is genuinely colour 15, and must stay that way when the leak is fixed."""
    line = _find_line(_doc(require_sawyer_doc), 'PRETTY NEAT, HUH?')
    assert 'colour15' in _line_colours(line), (
        'the white-on-black bar text must keep its white knockout')


def test_colour_restore_ends_the_white_run(require_sawyer_doc):
    """The paragraph AFTER the restore block must be black -- no colour tag at
    all, which is how black is spelled here (colour 0 emits no tag)."""
    doc = _doc(require_sawyer_doc)
    for needle in ('WordStar reduces the point size',
                   'You can use a similar technique'):
        cols = _line_colours(_find_line(doc, needle))
        assert not cols, (
            f'{needle!r} must be BLACK after the type-1 restore block; '
            f'it carries {sorted(cols)}, so it paints white on white and the '
            'reader loses the paragraph entirely')
