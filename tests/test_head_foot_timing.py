"""WHEN a running head or foot starts governing -- triage Q9.

THE RULE, derived on the real thing. Nine probe documents were authored
and printed through this repo's own DOSBox-X harness
(`tools/wordstar_harness.sh ws7`) against a pristine WordStar 7 install
and decoded with `tools/pcl_text.py`: a `.he`/`.fo` in a page's opening
dot block, after one blank line, after two, after a line of text, at the
very top of the file, several on one page, and the same positions on
pages opened by `.pa` and by organic overflow, at two page geometries
(a 14-line page and WordStar's own 55-line default).

    A `.he` governs the page it is read on only when NOTHING has been
    printed on that page yet -- and a blank line counts as printed.
    Otherwise it governs the next page. A `.fo` governs the page it is
    read on wherever it sits, because a footer is drawn at the bottom,
    after everything else on the page. And a page ENDS THE MOMENT IT IS
    FULL, not when the next line turns out not to fit, so a dot command
    sitting exactly on that boundary is read on the NEW page.

Every probe agreed, with no exceptions: a head redefined after any line
-- blank, inked, one or twenty-four of them, on a `.pa` page or an
overflow page -- always reached the following page, and a foot always
reached its own.

`sawyer/MACROS/HOLYMAC/-HOLYMAC.WS` appeared to contradict that on three
of its 302 pages (17, 177 and 184, where real WS7 applies a `.he` to the
page it sits on). It does not: the commands were being read in the wrong
PLACE. This file tests the two things that were wrong.
"""
from ctrlkd import core, pdf

HARD = b'\r\n'
SOFT = b'\x8d\n'
PGMARK = b'\r\x8a'          # WordStar's own stored page-break line ending


def _ws7_block(cmd, content=b''):
    """Copied from tests/test_fidelity_gate.py, per test_ctrlkd.py's own
    "copy, don't import" guidance."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _doc(body):
    return core.parse_ws(_ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)


def _page_heads(doc):
    return [pg.headers.get(1) for pg in pdf._doc_to_pagelines(doc, True)]


def _page_feet(doc):
    return [pg.footers.get(1) for pg in pdf._doc_to_pagelines(doc, True)]


def _geometry():
    """A 12-line sheet with 2-line margins: 8 body lines a page, so a
    handful of lines is a page and the probes' own arithmetic fits in a
    test."""
    return b'.pl 12' + HARD + b'.mt 2' + HARD + b'.mb 2' + HARD


# --------------------------------------------------- the rule itself
def test_a_head_read_after_a_line_governs_the_next_page():
    """The probes' own answer, and this engine's behaviour before any of
    this: one line on the page -- here a blank -- is enough."""
    body = (_geometry() + b'.he FIRST' + HARD
            + b''.join(b'L%d' % i + HARD for i in range(1, 9))   # page 1
            + HARD                                              # page 2, blank
            + b'.he SECOND' + HARD
            + b''.join(b'M%d' % i + HARD for i in range(1, 9)))
    heads = _page_heads(_doc(body))
    assert heads[0] == 'FIRST' and heads[1] == 'FIRST'
    assert heads[2] == 'SECOND'


def test_a_foot_read_anywhere_on_a_page_governs_that_page():
    """A footer is drawn at the bottom, so it is never too late for it --
    the same probes, the same pages, the opposite answer."""
    body = (_geometry() + b'.fo FIRST' + HARD
            + b''.join(b'L%d' % i + HARD for i in range(1, 5))   # page 1, 4 lines
            + b'.fo SECOND' + HARD
            + b''.join(b'M%d' % i + HARD for i in range(1, 5)))
    feet = _page_feet(_doc(body))
    assert feet[0] == 'SECOND'


# ------------------------------------ 1: read where the author typed it
def test_a_head_redefined_mid_paragraph_is_read_there():
    """`-HOLYMAC.WS` pages 177 and 184: the author redefines the running
    head BETWEEN two physical lines of one paragraph. The command's
    position used to be recorded as a whole BLOCK ("the paragraph after
    this one"), which deferred it past every remaining line of that
    paragraph -- and, when the paragraph straddled a page break, onto the
    page after the one WS7 gives it.
    """
    body = (_geometry() + b'.he FIRST' + HARD
            + b''.join(b'L%d' % i + HARD for i in range(1, 7))
            + b'P1' + SOFT + b'P2' + PGMARK      # page 1's last two lines
            + b'.he SECOND' + HARD               # -- and the command after them
            + b'P3' + SOFT + b'P4' + HARD)       # the paragraph's tail, page 2
    doc = _doc(body)
    assert [w for w in doc.hf_events_within if w is not None], \
        'the command sits inside a block and must record where'
    heads = _page_heads(doc)
    assert heads[0] == 'FIRST'
    assert heads[1] == 'SECOND', heads


def test_a_head_between_blocks_still_records_no_position():
    """The common case is unchanged: a command with nothing open in front
    of it is a plain block-boundary event, exactly as before."""
    doc = _doc(b'.he ONLY' + HARD + b'text' + HARD)
    assert doc.hf_events_within == [None]


# --------------------------------- 2: a page ends the moment it is full
def test_a_foot_read_on_a_full_page_belongs_to_the_next_one():
    """`sawyer/MACROS/HOLYMAC/8MAC`: page 1 fills exactly, and a bare
    `.fo` -- the one that turns the running foot off -- sits immediately
    after its last line. Real WS7 prints `286` at the foot of page 1 and
    nothing on pages 2-10, so WordStar had already closed page 1 when it
    read that command. This engine breaks lazily, when the next line
    turns out not to fit, and so read it while page 1 was still open and
    silenced page 1's own footer.
    """
    body = (_geometry() + b'.fo KEEP' + HARD
            + b''.join(b'L%d' % i + HARD for i in range(1, 9))   # page 1 full
            + b'.fo' + HARD
            + b''.join(b'M%d' % i + HARD for i in range(1, 5)))
    feet = _page_feet(_doc(body))
    assert feet[0] == 'KEEP', feet
    assert feet[1] is None, feet


def test_a_foot_read_before_a_page_is_full_still_governs_it():
    """The guard above must not fire early: the same document with room
    left on page 1 keeps the old, correct answer."""
    body = (_geometry() + b'.fo KEEP' + HARD
            + b''.join(b'L%d' % i + HARD for i in range(1, 5))   # page 1, 4 lines
            + b'.fo' + HARD
            + b''.join(b'M%d' % i + HARD for i in range(1, 5)))
    assert _page_feet(_doc(body))[0] is None


# ---------------------------- the same Q9 rule in MODERN (2026-09-15)
#
# Modern snapshotted BOTH head and foot at the moment a page took its first
# content -- the HEADER rule, applied to footers as well -- so a `.fo` read
# part-way down a page put its text on the NEXT one. Printed has read Q9
# correctly since the 8MAC measurement above; these are the twins of the two
# tests either side of this comment, on Modern's own pages.

def _modern_feet(doc):
    """The text drawn on each Modern page's own footer row (y 44.0)."""
    import re as _re
    out = []
    pdfbytes = pdf.emit_pdf(doc, mode='modern')
    pat = _re.compile(rb'Ts ([\d.]+) (44\.0) Td \((.*?)\) Tj')
    for chunk in pdfbytes.split(b'>>\nstream\n')[1:]:
        stream = chunk.split(b'\nendstream')[0]
        out.append(''.join(t.decode('latin-1')
                           for _x, _y, t in pat.findall(stream)).strip() or None)
    return out


# BLANK-SEPARATED PARAGRAPHS ON PURPOSE. Modern's flow is BLOCK-granular
# (`layout.modern_flow` walks `enumerate(doc.blocks)` and hangs each `hf`
# event on its anchor block), so a `.fo` typed between two physical lines
# of ONE paragraph has no block of its own to hang on and never reaches
# the Modern flow at all. That is a separate, pre-existing limit of the
# flow's own contract -- named here so these fixtures' shape is not
# mistaken for an accident -- and it is why every corpus document this
# rule moves (the HOLYMAC family) anchors its `.fo` at a block boundary.
_MODERN_FILLER = b''.join(b'The quick brown fox jumps over the lazy dog, and '
                          b'keeps running until this line has to wrap.'
                          + HARD + HARD for _ in range(40))


def test_modern_reads_a_mid_page_foot_onto_that_page():
    """A `.fo` read after the page has already taken content governs THAT
    page in Modern too -- a footer is drawn at the bottom, after everything
    else, and Modern's pages are no different from Printed's in that."""
    body = (b'.fo FIRST' + HARD
            + b'Opening line.' + HARD + HARD
            + b'.fo SECOND' + HARD
            + _MODERN_FILLER)
    feet = _modern_feet(_doc(body))
    assert len(feet) > 1, feet
    assert feet[0] == 'SECOND', feet


def test_modern_reads_a_foot_after_a_full_page_onto_the_next_one():
    """The other half of Q9, and the reason this is a PENDING state rather
    than a snapshot taken at the command: a footer read when the page can
    take no more content belongs to the next page. Printed peeks at the
    next line to decide (`_page_already_full`); Modern waits and lets the
    page that actually takes the next piece of content claim it."""
    body = (b'.fo FIRST' + HARD + _MODERN_FILLER
            + b'.fo SECOND' + HARD + _MODERN_FILLER)
    feet = _modern_feet(_doc(body))
    assert feet[0] == 'FIRST', feet
    assert feet[-1] == 'SECOND', feet


def test_modern_reads_a_foot_typed_just_before_a_page_break_onto_that_page():
    """An explicit `.pa` is not "the page was full": the `.fo` in front of
    it is read while the page is still open, so it governs THAT page.
    Printed says the same -- its own `_page_already_full` peeks at the next
    LINE, and a page break is not one -- and this is why only the OVERFLOW
    close leaves the pending footer behind."""
    body = (b'.fo FIRST' + HARD + b'Opening line.' + HARD + HARD
            + b'.fo SECOND' + HARD + b'.pa' + HARD
            + b'Second page.' + HARD)
    feet = _modern_feet(_doc(body))
    assert feet[0] == 'SECOND', feet


def test_modern_still_reads_a_head_only_at_the_top():
    """The header half is UNCHANGED: a `.he` read after the page's first
    line cannot reach it, in Modern exactly as in Printed."""
    import re as _re
    body = (b'.he FIRST' + HARD + b'Opening line.' + HARD + HARD
            + b'.he SECOND' + HARD + _MODERN_FILLER)
    pdfbytes = pdf.emit_pdf(_doc(body), mode='modern')
    pat = _re.compile(rb'Ts ([\d.]+) ([\d.]+) Td \((.*?)\) Tj')
    heads = []
    for chunk in pdfbytes.split(b'>>\nstream\n')[1:]:
        stream = chunk.split(b'\nendstream')[0]
        top = [t.decode('latin-1') for _x, y, t in pat.findall(stream)
               if abs(float(y) - 748.0) < 0.05]
        heads.append(''.join(top).strip() or None)
    assert heads[0] == 'FIRST', heads
    assert heads[1] == 'SECOND', heads
