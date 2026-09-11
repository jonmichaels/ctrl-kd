"""planning #263 follow-up: a blank after a TIGHTENED line advances by the
line's UNTIGHTENED leading.

Found and fixed in the Swift engine first (`PDFModernLayout.modernStreams`),
ported here so the two engines agree byte for byte.

THE RULE. Modern tightens a verse or centred line's own height
(`_modern_tight_h`) so a title block or a stanza reads as one unit rather
than as loosely-spaced prose. `_modern_streams` remembers the most recently
placed line's leading (`last_h`) and spends exactly that on the next 'blank'
item -- and it used to remember the TIGHTENED height. So the author's own
blank line after a tightened block came out compressed too, and a title
block closed tighter than the identical block would have closed without any
tightening at all.

Tightening is about how a line reads against the lines it sits BETWEEN. The
author's blank line after it is the paragraph break, and that gap belongs to
the body's ordinary leading. `last_h` therefore records `MODERN_LINE *
face_pt`, never `h`.

MEASURED. For the 14pt Modern body the two differ by 5.30pt (16.80
untightened, 11.50 tightened), so every blank following a tightened line
moves the rest of its page down by that much. Printed is untouched --
nothing on that path tightens anything.

Tier 1 here is synthetic (CLAUDE.md: synthetic fixtures only); the worked
example is tier 2 (`sawyer`), on the archive's own -README.WS title block --
three such blanks in a row, 15.90pt.
"""
import pytest

from ctrlkd import core, pdf

from test_modern_centring_clip import _centred, _lines, _modern, HARD

BODY_LEAD = pdf.MODERN_LINE * pdf.MODERN_BODY_PT          # 16.80pt


def _title_block_doc():
    """Prose, a blank, a hand-centred title (which Modern tightens), a
    blank, then more prose -- the shape every WordStar title block has."""
    return (b'An ordinary opening paragraph of prose, which gives the '
            b'document a routine body for the title block below it to be '
            b'read against, long enough to wrap onto a second visual line '
            b'of its own.' + HARD + HARD
            + _centred('WordStar Strengths') + HARD + HARD
            + b'A following paragraph of ordinary body prose, itself long '
              b'enough to wrap so its own internal line advance can be '
              b'measured too.' + HARD)


def test_a_blank_after_a_tightened_line_costs_the_untightened_leading():
    """The bug, stated as arithmetic: from the tightened title's baseline
    to the next body line's baseline is the blank (one body leading) plus
    that body line's own height (one body leading) -- both faces are the
    same, so their descents cancel and the gap is exactly two body
    leadings. It used to be one body leading plus one TIGHTENED height,
    5.30pt short.
    """
    rows = _lines(pdf.emit_pdf(_modern(_title_block_doc()), mode='modern'))
    title = next(r for r in rows if r[2].startswith('WordStar'))
    after = next(r for r in rows if r[2].startswith('Afollowing'))
    assert title[0] - after[0] == pytest.approx(2 * BODY_LEAD, abs=0.05)


def test_the_tightening_itself_is_untouched():
    """The fix is about the blank AFTER a tightened line, not about the
    tightening: the title still sits closer to the paragraph above it than
    an untightened line would, so nothing here quietly reverted planning
    #263's own rule."""
    rows = _lines(pdf.emit_pdf(_modern(_title_block_doc()), mode='modern'))
    before = [r for r in rows if r[2].startswith('visualline')][0]
    title = next(r for r in rows if r[2].startswith('WordStar'))
    assert before[0] - title[0] < 2 * BODY_LEAD


def test_an_ordinary_paragraph_gap_is_unchanged():
    """Two plain prose paragraphs either side of one blank: nothing about
    them is tightened, so this spacing must be byte-for-byte what it always
    was -- the fix touches only the tightened case."""
    data = (b'A first paragraph of ordinary prose, long enough to be a real '
            b'body paragraph rather than a heading.' + HARD + HARD
            + b'A second paragraph of ordinary prose, equally unremarkable '
              b'and equally untightened.' + HARD)
    rows = _lines(pdf.emit_pdf(_modern(data), mode='modern'))
    second_i = next(i for i, r in enumerate(rows)
                    if r[2].startswith('Asecond'))
    first_last = rows[second_i - 1]
    assert (first_last[0] - rows[second_i][0]
            == pytest.approx(2 * BODY_LEAD, abs=0.05))


def test_printed_mode_has_no_tightening_to_leak():
    """Stated so the claim "no Printed cell moves" is checked and not just
    asserted in a commit message: Printed spends the document's own lead on
    every line, tightened or not, so the same document's Printed page is
    identical whether or not Modern tightens anything."""
    doc = _modern(_title_block_doc())
    rows = _lines(pdf.emit_pdf(doc, mode='printed'))
    lead = pdf._printed_lead(doc)
    assert lead == 12.0
    # every inked line sits a whole number of leads below the one above it
    # (the blanks draw nothing, so a gap of two leads is one blank line) --
    # no tightened, sub-lead advance anywhere on this path.
    for a, b in zip(rows, rows[1:]):
        gap = a[0] - b[0]
        assert gap % lead == pytest.approx(0.0, abs=0.01), (gap, a[2], b[2])


@pytest.mark.sawyer
def test_readme_title_block_carries_the_full_delta(require_sawyer_doc):
    """The worked example. -README.WS opens with an image, then a title,
    subtitle, byline, email, version and date -- each its own tightened,
    hand-centred line, three of them followed by the author's own blank.
    Each of those three blanks now advances 5.30pt further than it did, so
    the material below the block sits 15.90pt lower on the page.

    The recorded y is the subtitle's, the first line below a tightened line
    plus blank: 541.40, where the tightened leading put it at 546.70.

    Tier 2 (sawyer): one of the committed manifest documents
    (tests/SAWYER-CORPUS.md).
    """
    path = require_sawyer_doc('-README.WS (root)')
    doc = core.parse(open(path, 'rb').read())
    rows = _lines(pdf.emit_pdf(doc, mode='modern'), 1)
    subtitle = next(r for r in rows if r[2].startswith('UsingandCustomizing'))
    assert subtitle[0] == pytest.approx(541.40, abs=0.05)
    body = next(r for r in rows if r[2].startswith('Thisdocumentisprovided'))
    assert body[0] == pytest.approx(353.50, abs=0.05)
