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
