r"""planning #264 R2 (Jon, 2026-09-14): "Yes add it" -- A8 keep-with-next
for `.cp`/`.cc` in RTF, both engines.

WHAT WORDSTAR ASKED FOR. `.cp n` says "break to a new page unless at
least n lines still fit here"; `.cc n` says the same of a column. The
author's purpose is never the break itself: it is that the n lines AFTER
the command arrive together -- `.cp` exists precisely so a heading is not
stranded at the foot of a page.

WHAT RTF CAN SAY. Not "break here": R6 declined imposed page positions
outright the same morning, and a reader paginating with its own fonts and
margins would fight one anyway. It can say `\keepn` (keep this paragraph
with the next) and `\keep` (do not split this paragraph across a page) --
CONSTRAINTS the reader honours while paginating rather than positions
imposed on it. That is the packet's own reason A8 works where A12 does
not.

BOTH MODES. The rule reads the same blocks either way, and a stranded
heading is as wrong in a reflowed export as in a facsimile.

Synthetic fixtures only.
"""
import re

import pytest

from ctrlkd import core, emit

HARD = b'\x0d\x0a'


def _ws7(body, dots=b''):
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


def _keeps(rtf):
    """Every keep control in document order, `\\keep0`/`\\keepn0` included."""
    return re.findall(r'\\keepn?0? ', rtf)


HEADING_AND_TWO = (b'.cp 3' + HARD + b'A Heading' + HARD + HARD
                   + b'Body line one.' + HARD + b'Body line two.' + HARD)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_cp_keeps_the_heading_with_what_follows(mode):
    """The packet's own example: "Don't strand this heading"."""
    rtf = emit.emit_rtf(_ws7(HEADING_AND_TWO), mode=mode)
    assert _keeps(rtf)[:2] == [r'\keep ', r'\keepn ']
    assert rtf.index(r'\keepn ') < rtf.index('A Heading')


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_the_last_paragraph_of_the_run_is_kept_but_not_kept_with_next(mode):
    """`\\keepn` on the last one would bind the run to text the author
    never asked for."""
    rtf = emit.emit_rtf(_ws7(HEADING_AND_TWO), mode=mode)
    assert r'\keepn0 ' in rtf
    assert rtf.index(r'\keepn0 ') < rtf.index('Body line one.')


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_the_run_ends_and_the_properties_are_turned_back_off(mode):
    """`\\keep`/`\\keepn` persist across `\\par` like every other paragraph
    property, so a paragraph outside the run has to say so."""
    doc = _ws7(HEADING_AND_TWO + HARD + b'Unrelated later prose.' + HARD)
    rtf = emit.emit_rtf(doc, mode=mode)
    assert r'\keep0 ' in rtf
    assert rtf.index(r'\keep0 ') < rtf.index('Unrelated later prose.')


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_document_with_no_cp_writes_no_keep_control_at_all(mode):
    rtf = emit.emit_rtf(_ws7(b'Just prose.' + HARD + b'More prose.' + HARD), mode=mode)
    assert _keeps(rtf) == []


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_cc_is_read_exactly_as_cp_is(mode):
    """WSFORMAT.TXT: "Like the .CP command, but works with columnar breaks
    instead." The request is the same request."""
    cp = emit.emit_rtf(_ws7(HEADING_AND_TWO), mode=mode)
    cc = emit.emit_rtf(_ws7(HEADING_AND_TWO.replace(b'.cp 3', b'.cc 3')), mode=mode)
    assert _keeps(cp) == _keeps(cc)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_run_satisfied_by_one_paragraph_is_kept_but_not_bound_onward(mode):
    """The n lines the author asked for are already inside that one
    paragraph, so nothing needs holding to what follows."""
    doc = _ws7(b'.cp 2' + HARD + b'Line one.' + HARD + b'Line two.' + HARD
               + HARD + b'A separate paragraph.' + HARD)
    rtf = emit.emit_rtf(doc, mode=mode)
    assert _keeps(rtf)[0] == r'\keep '
    assert r'\keepn ' not in rtf


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_bigger_n_reaches_further_down_the_document(mode):
    """`.cp 6` over three one-line paragraphs holds all three."""
    body = (b'.cp 6' + HARD + b'One.' + HARD + HARD + b'Two.' + HARD + HARD
            + b'Three.' + HARD + HARD + b'Four.' + HARD)
    rtf = emit.emit_rtf(_ws7(body), mode=mode)
    assert _keeps(rtf).count(r'\keepn ') == 1        # set once, held across
    assert _keeps(rtf).count(r'\keepn0 ') == 1       # released once


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_page_break_ends_the_run(mode):
    """`.cp` cannot ask for lines that are on the other side of a break the
    author put there himself."""
    doc = _ws7(b'.cp 9' + HARD + b'One.' + HARD + b'.pa' + HARD
               + b'Two.' + HARD)
    rtf = emit.emit_rtf(doc, mode=mode)
    assert r'\keepn ' not in rtf                     # nothing to keep it with
    assert r'\keep ' in rtf


def test_the_plan_names_exactly_the_blocks_it_holds():
    """The unit under the export, so the mapping can be read directly."""
    doc = _ws7(HEADING_AND_TWO)
    plan = emit._rtf_keep_plan(doc)
    kept = sorted(plan)
    assert [plan[k] for k in kept] == [(True, True), (True, False)]
