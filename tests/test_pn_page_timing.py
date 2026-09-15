"""Triage Q12: which page reads a `.pn`, and what a leading blank run does
to the arithmetic.

WHY A PROBE. `sawyer/MACROS/HOLYMAC/-HOLYMAC.WS` printed an automatic `0`
at the foot of page 1 where real WS7 prints nothing. The document turns the
number off with `.op` in its opening dot block and turns it back on with a
later `.pn0` -- and that `.pn0` sits immediately after "Charles Maher", the
last line page 1 has room for, inside a front matter that is almost entirely
BLANK LINES. A blank line prints nothing, so no corpus document can show
where a page breaks inside one; only running WordStar can.

THE PROBES (2026-09-14, this repo's own DOSBox-X harness against a pristine
WordStar 7 install, decoded with tools/pcl_text.py). Ten text lines to a
page (`.pl 12`, `.mt 1`, `.mb 1`), a long run of blank lines, and one dot
command moved through it:

    .fo after  5 blanks   footer on page 1            (Q12B)
    .fo after 10 blanks   page 1 takes the AUTOMATIC number, footer from
                          page 2                       (Q12C)
    .fo after 15 blanks   same                         (Q12D)
    .fo after 25 blanks   pages 1-2 automatic, footer from page 3  (Q12E)
    .op + .pn0 after  9 blanks   page 1 numbered 0     (Q12M)
    .op + .pn0 after 10 blanks   page 1 silent, page 2 numbered 0   (Q12L)
    .op + an inked 10th line, then .pn0   page 1 silent, page 2 `0`  (Q12N)
    an inked 10th line, then .fo          page 1 automatic `1`, FP2  (Q12P)

and the same at WordStar's own 55-line default geometry (Q12H/J/K), which
agreed in every case.

THE RULE, and it is two sentences:

  A BLANK LINE OCCUPIES A PAGE LINE exactly as an inked one does. Nothing
  about a leading run is special: 25 blanks at ten lines to a page put the
  body on page 3, and the command inside the run is read on whichever page
  that arithmetic puts it on.

  A PAGE ENDS THE MOMENT IT IS FULL, so a command sitting exactly on the
  boundary is read on the NEW page. This is the same third clause triage Q9
  measured for `.he`/`.fo` (`_page_already_full`); Q12 says it governs `.pn`
  and `.op`/`.pg` too, which nothing had tested.

Q12G adds one more, and it is why `-HOLYMAC`'s pages 2-3 were already right:
a BARE `.fo` is a footer in use, it suppresses the automatic number from the
page it is read on, and a later `.pn0` does NOT bring the number back.

WHAT CHANGED IN THE ENGINE. `_pn_checkpoints`/`_pgnum_checkpoints` carry the
LINE INDEX within their block (`dot_positions`' own second field), and
`_checkpoints_by_page` walks the pages asking "has this block printed more
lines than came before the command yet?" -- one shared walk, so the number's
VALUE and the number's ON/OFF cannot disagree about where a `.pn` was read.

Tier 1 here is synthetic, at the probes' own geometry (CLAUDE.md: synthetic
fixtures only); the worked example is `-HOLYMAC.WS`, whose page 1 prints no
`0` and whose pages 2 onward are byte-identical to before.
"""
import re

from ctrlkd import core, pdf

HARD = b'\r\n'
# WordStar's own default geometry, 55 text lines to a page -- the same shape
# probes Q12H/J/K used, and the one this emitter draws a footer on.
DEF = (b'.pl 66' + HARD + b'.mt 3' + HARD + b'.mb 8' + HARD
       + b'.lm1' + HARD + b'.rm65' + HARD + b'.po1i' + HARD
       + b'.lh8' + HARD + b'.ps off' + HARD)
# The probes' own ten-lines-to-a-page geometry, for the boundary cases.
SMALL = (b'.pl 12' + HARD + b'.mt 1' + HARD + b'.mb 1' + HARD
         + b'.lm1' + HARD + b'.rm65' + HARD + b'.po1i' + HARD
         + b'.lh8' + HARD + b'.ps off' + HARD)


def _blanks(n):
    return HARD * n


def _drawn(prefix, data):
    """What each page actually draws, in page order -- read straight out of
    the emitted PDF's own per-page content streams."""
    out = pdf.emit_pdf(core.parse_ws(prefix + data), mode='printed')
    return [[m.group(1).decode('latin-1')
             for m in re.finditer(rb'\((.*?)\) Tj', stream)]
            for stream in re.findall(rb'stream\n(.*?)endstream', out, re.S)]


def _numbers(prefix, data):
    """(page numbers, automatic-number-on flags) -- the mechanism itself,
    for the geometries this emitter draws no footer on."""
    doc = core.parse_ws(prefix + data)
    pages = pdf._doc_to_pagelines(doc, printed=True)
    return (pdf._resolve_page_numbers(pdf._pn_checkpoints(doc), pages),
            pdf._pgnum_by_page(pdf._pgnum_checkpoints(doc), pages))


def test_a_pn_one_line_short_of_the_boundary_numbers_its_own_page():
    """Q12M. Nine blank lines then `.pn0`, at ten lines to a page: the
    command is still on page 1, so page 1 is numbered 0 and page 2 is 1."""
    nums, on = _numbers(SMALL, b'.pn0' + HARD + b'.op' + HARD + _blanks(9)
                        + b'.pn0' + HARD + _blanks(11) + b'MBODY' + HARD)
    assert on[0] is True, on
    assert nums[:3] == [0, 1, 2], nums


def test_a_pn_exactly_on_the_boundary_is_read_on_the_new_page():
    """Q12L, and the whole point of the round. Ten blank lines fill page 1
    exactly; the `.pn0` immediately after them belongs to page 2, so page 1
    stays silent under `.op` and page 2 carries the 0."""
    nums, on = _numbers(SMALL, b'.pn0' + HARD + b'.op' + HARD + _blanks(10)
                        + b'.pn0' + HARD + _blanks(10) + b'LBODY' + HARD)
    assert on[0] is False, on
    assert on[1] is True, on
    assert nums[1] == 0 and nums[2] == 1, nums


def test_an_inked_last_line_then_a_pn_is_the_holymac_shape():
    """Q12N -- `-HOLYMAC.WS`'s own arithmetic, in miniature. The tenth line
    carries ink, the `.pn0` follows it, and real WS7 prints nothing on page
    1 and 0 on page 2."""
    nums, on = _numbers(SMALL, b'.pn0' + HARD + b'.op' + HARD + _blanks(9)
                        + b'NLAST' + HARD + b'.pn0' + HARD
                        + _blanks(10) + b'NBODY' + HARD)
    assert on[0] is False, on
    assert on[1] is True and nums[1] == 0, (on, nums)


def test_a_blank_line_costs_a_page_line_like_an_inked_one():
    """Q12J/H, the half of the rule a corpus cannot show, at the geometry
    this emitter draws footers on. Five blanks then a `.fo` puts the footer
    on page 1; forty-five blanks then a `.fo` still puts it on page 1,
    because forty-five blank lines fit inside fifty-five."""
    early = _drawn(DEF, _blanks(5) + b'.fo FJ#' + HARD + _blanks(60)
                   + b'JBODY' + HARD)
    assert early[0] == ['FJ1'], early[0]
    late = _drawn(DEF, _blanks(45) + b'.fo FH#' + HARD + _blanks(20)
                  + b'HBODY' + HARD)
    assert late[0] == ['FH1'], late[0]


def test_a_pn_past_the_first_page_of_a_blank_run_numbers_the_second():
    """Q12K, the full-geometry twin of the boundary case: `.op` at the top,
    sixty blank lines, then `.pn0`. Page 1 holds fifty-five of those blanks
    and stays silent; the `.pn0` is read on page 2, which prints `0`."""
    drawn = _drawn(DEF, b'.pn0' + HARD + b'.op' + HARD + _blanks(60)
                   + b'.pn0' + HARD + _blanks(20) + b'KBODY' + HARD)
    assert drawn[0] == [], drawn[0]
    assert drawn[1] == ['0', 'KBODY'], drawn[1]


def test_a_bare_fo_silences_the_number_and_a_later_pn_does_not_undo_it():
    """Q12G. A bare `.fo` is a footer IN USE, and WSFORMAT's own text says
    the automatic number is "active only when the footers are not in use".
    The `.pn0` further down the run does not bring it back."""
    drawn = _drawn(DEF, b'.pn0' + HARD + b'.op' + HARD + _blanks(5)
                   + b'.fo' + HARD + _blanks(50) + b'.pn0' + HARD
                   + _blanks(20) + b'GBODY' + HARD)
    assert drawn[0] == [], drawn[0]
    assert all(d not in (['0'], ['1']) for d in drawn), drawn


def test_the_checkpoints_carry_their_line_position():
    """The mechanism, not just its effect: a `.pn` records how many of its
    own block's lines came before it, which is what lets the boundary case
    above be answered at all -- and two `.pn` commands inside ONE block are
    now two checkpoints, not one, because their positions differ."""
    doc = core.parse_ws(SMALL + b'.pn3' + HARD + b'A' + HARD + b'B' + HARD
                        + b'.pn7' + HARD + b'C' + HARD)
    cps = pdf._pn_checkpoints(doc)
    assert [c[2] for c in cps][-2:] == [3, 7], cps
    assert cps[-1][1] > cps[-2][1], cps      # the later one read further in


# ====== the footnote path reads the document's own `.op` (2026-09-15) ======
#
# Research: "Why real WS7 prints no page number on some documents"
# (jon_vault, 2026-09-15). Real WordStar 7 numbers every page unless the
# document says otherwise, and `.op` is one of the four things that say
# otherwise. `samples/LYING.WS` carries `.op` AND a footnote, and the
# positional walk this file's own Q12 tests introduced printed a number on
# all three of its pages: a page built by the FOOTNOTE paginator got no
# `read_pos`, the walk's inner loop never ran, and the answer stayed on the
# seeded "numbering ON" checkpoint 0 -- the `.op` was never consulted.
# Across all 308 WS7 captures no document carrying `.op` prints a number,
# with zero counter-examples, and a whole-corpus sweep finds exactly three
# documents carrying both a footnote and a numbering-off command (LYING,
# and two private ones), so these are the whole blast radius.

import os

SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'samples')

# WordStar's own default geometry again, but with no `.ps off`: a document
# whose ONLY dot command is the one under test, so nothing else can be
# blamed for the answer.
PLAIN = b'.pl 66' + HARD + b'.mt 3' + HARD + b'.mb 8' + HARD + b'.po1i' + HARD


def _ws7_block(cmd, content=b''):
    """One WS7 0x1D-delimited block -- the shape
    tests/test_note_rulings_20260824.py already builds notes with."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _footnote(text, number=1):
    """A one-line FOOTNOTE (note command 0x03) -- the kind that sends a
    document down `_paginate_printed_notes`, which is the paginator that
    lost the `.op`."""
    return _ws7_block(0x03, (1).to_bytes(2, 'little')
                      + number.to_bytes(2, 'little') + bytes([0x30]) + text)


def _foot_digits(data):
    """Per page, the digit-only chunks drawn on that page's LOWEST print
    line -- the research note's own install-independent test for "is there
    an automatic page number here", which assumes no fixed x or y (`.pl`,
    `.mb`, `.po` and `.pc` all move the real one)."""
    out = pdf.emit_pdf(core.parse_ws(data), mode='printed')
    pages = []
    for stream in re.findall(rb'stream\n(.*?)endstream', out, re.S):
        rows = {}
        for x, y, t in re.findall(rb'([\d.]+) ([\d.]+) Td\s*\((.*?)\) Tj', stream):
            rows.setdefault(float(y), []).append(t.decode('latin-1'))
        if not rows:
            pages.append([])
            continue
        foot = rows[min(rows)]                  # PDF y grows UPWARD: lowest line
        pages.append([t for t in foot if t.strip().isdigit()])
    return pages


def test_lying_ws_prints_no_automatic_page_number_on_any_page():
    """The regression itself, pinned on the bundled public-domain sample.
    LYING.WS's `.op` is the FIRST LINE OF THE FILE -- it follows the header
    block's closing 0x1D with no CR LF before it -- and it turns the
    automatic number off for the whole document. Real WS7's own capture
    (ws7-prints/v3) prints no number on any of the three pages."""
    data = open(os.path.join(SAMPLES_DIR, 'LYING.WS'), 'rb').read()
    doc = core.parse_ws(data)
    assert doc.notes, 'LYING.WS is the fixture BECAUSE it has a footnote'
    pages = pdf._doc_to_pagelines(doc, printed=True)
    on = pdf._pgnum_by_page(pdf._pgnum_checkpoints(doc), pages)
    assert on == [False] * len(pages), on
    assert _foot_digits(data) == [[], [], []], _foot_digits(data)


def test_a_footnote_document_that_omits_numbers_reads_its_own_op():
    """The same shape synthetically, so the rule is pinned even if the
    sample ever changes: `.op`, a footnote, two pages of body."""
    data = (PLAIN + b'.op' + HARD + b'OPBODY' + _footnote(b'A footnote.')
            + HARD + _blanks(80) + b'OPTAIL' + HARD)
    assert _foot_digits(data) == [[], []], _foot_digits(data)


def test_a_footnote_document_with_pn_is_still_numbered():
    """The control, and the half a too-broad fix would break: footnotes have
    NOTHING to do with the automatic number. 28 numbered WS7 captures carry
    real footnotes. `.pn` says number the pages, and it still does."""
    data = (PLAIN + b'.pn 1' + HARD + b'PNBODY' + _footnote(b'A footnote.')
            + HARD + _blanks(80) + b'PNTAIL' + HARD)
    assert _foot_digits(data) == [['1'], ['2']], _foot_digits(data)


def test_the_footnote_paginator_records_where_each_page_read_to():
    """The first half of the mechanism: a page built by the notes-aware
    paginator now carries its own `read_pos`, so it answers the walk
    directly instead of falling through to the seeded default."""
    for name, dot in (('LYING.WS', None), (None, b'.pn 1'), (None, b'.op')):
        if name:
            data = open(os.path.join(SAMPLES_DIR, name), 'rb').read()
        else:
            data = (PLAIN + dot + HARD + b'XBODY' + _footnote(b'A footnote.')
                    + HARD + _blanks(80) + b'XTAIL' + HARD)
        doc = core.parse_ws(data)
        assert pdf._has_placeable_notes(doc), (name, dot)
        positions = [getattr(pg, 'read_pos', None)
                     for pg in pdf._doc_to_pagelines(doc, printed=True)]
        assert all(p is not None for p in positions), (name, dot, positions)
        assert positions == sorted(positions), (name, dot, positions)


def test_a_page_with_no_read_position_falls_back_to_the_block_range_rule():
    """The second half, and the belt to that brace: a page that carries no
    read position at all -- a synthetic or degenerate page, from any future
    paginator -- is answered by block range (the last checkpoint at or
    before the highest block the page carries), not by the seeded
    checkpoint 0. Checkpoints here: ON at block 0, OFF at block 2."""
    checkpoints = [(0, 0, True), (2, 0, False)]
    early, late = pdf.PageLine([('x', None)]), pdf.PageLine([('y', None)])
    early.bi, late.bi = 1, 3
    assert pdf._checkpoints_by_page(checkpoints, [[early], [late]]) == [0, 1]
    assert pdf._checkpoints_by_page(checkpoints, [[late]]) == [1]
    # No `.bi` anywhere on the page: nothing to range over, walk unchanged.
    assert pdf._checkpoints_by_page(checkpoints, [[]]) == [0]
