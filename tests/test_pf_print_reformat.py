"""`.pf on` -- WordStar's PRINT-TIME paragraph realignment (planning #270
item 37, Jon's ruling 2026-09-13, triage Q5: "Yes, support it.").

MicroPro's own file-format reference (`WSFORMAT.TXT`, the `.PF` row): "When
ON, subsequent paragraphs are realigned as they are printed... using the
left, right, and paragraph margins currently in effect."

The reason a document can NEED it: WordStar's EDITOR is a character screen
and wraps at a COLUMN COUNT whatever face the text is set in; the printer
wraps at the real measure, in the real fonts, at print time. Two measured
cases from the v4 PRISTINE captures drive every rule here:

  `sawyer/REF/REFORM.DOT` -- Courier, `.rm 6.5"` printing but `.rm 5.0"`
  editing (its own `.if 1=0` block). The file stores "...in editing, but" +
  soft return + "another to occur during printing"; real WS7 prints ONE
  63-character line ending "...another to occur".

  `sawyer/PRINT.TST` -- every one of its 94 soft-wrapped lines prints
  EXACTLY as stored, hyphens and all ("custom-"/"ized", "de-"/"fault",
  "docu-"/"ment", "professional-"/"looking"), because nothing changed
  between edit time and print time. That document is this mechanism's real
  regression test: a re-wrap that does not reproduce it byte for byte is
  wrong, and it is the reason a discretionary hyphen has to be re-usable and
  a typed hyphen has to be a break point.

The fixtures below are synthetic so the rules stay covered without the
corpus; the numbers in them are the corpus's own.
"""
import pytest

from ctrlkd import core, pdf, emit


HARD = b'\x0d\x0a'
SOFT = b'\x8d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def font_block(w, h, style):
    """One type-2 Font symmetric block -- width (HMI), height (VMI),
    typestyle, three zeroed 'previous' words. Same construction as
    test_lj6dtp_heading_face.py's own `_font_block`."""
    return ws7_block(0x02, (w.to_bytes(2, 'little') + h.to_bytes(2, 'little')
                            + style.to_bytes(2, 'little') + b'\x00' * 6))


PROP_SANS = 49156       # PRINT.TST's own real typestyle word for Helv:
                        # proportional bit set, typestyle_number 4


def build(body, dots=b'.pf on' + HARD + b'.rm 6.5"' + HARD):
    return core.parse_ws(ws7_block(0x00) + dots + body)


def printed_lines(doc):
    """Every printed physical line of the document, in order, as text."""
    return [''.join(t for t, _ in pl)
            for page in pdf._doc_to_pagelines(doc, True) for pl in page]


# ---------------------------------------------------------------------------
# the gate: `.pf` decides, and nothing else moves


def test_pf_off_keeps_the_stored_physical_lines():
    """The 2.0.0 rule, untouched for every document that does not realign:
    a soft return is where WordStar broke the line on paper."""
    doc = build(b'Dots to have one thing display in editing, but' + SOFT
                + b'another to occur during printing' + HARD,
                dots=b'.pf off' + HARD + b'.rm 6.5"' + HARD)
    assert pdf.pf_rewrapped_lines(doc, doc.blocks[0]) is doc.blocks[0].lines
    assert printed_lines(doc)[:2] == [
        'Dots to have one thing display in editing, but',
        'another to occur during printing']


def test_pf_never_said_keeps_the_stored_physical_lines():
    """"Never said" is not "off" for the PARSE (it stays None) but it is the
    same answer here: only `on` realigns."""
    doc = build(b'Dots to have one thing display in editing, but' + SOFT
                + b'another to occur during printing' + HARD,
                dots=b'.rm 6.5"' + HARD)
    assert pdf.pf_rewrapped_lines(doc, doc.blocks[0]) is doc.blocks[0].lines


def test_pf_dis_is_not_on():
    """`dis` realigns only when merge data is substituted, and this engine
    never merge-prints. ZERO archive documents say `dis` (measured
    2026-09-14), so this changes no document's output by construction."""
    doc = build(b'Dots to have one thing display in editing, but' + SOFT
                + b'another to occur during printing' + HARD,
                dots=b'.pf dis' + HARD + b'.rm 6.5"' + HARD)
    assert pdf.pf_rewrapped_lines(doc, doc.blocks[0]) is doc.blocks[0].lines


# ---------------------------------------------------------------------------
# the measure


def test_pf_on_pulls_the_next_stored_line_up_to_the_print_margin():
    """REFORM.DOT's own shape and its own numbers: 65 columns of measure, a
    63-character line, and "during" (7 more columns with its space) does not
    fit. Real WS7, page 1: "Dots"@57.6pt ... "occur"@475.2pt on one line,
    "during"@57.6pt on the next."""
    doc = build(b'Dots to have one thing display in editing, but' + SOFT
                + b'another to occur during printing' + HARD)
    assert printed_lines(doc)[:2] == [
        'Dots to have one thing display in editing, but another to occur ',
        'during printing']


def test_a_line_that_already_sits_at_the_measure_re_wraps_to_itself():
    """PRINT.TST's whole body is this case -- nothing changed between edit
    time and print time, so realignment reproduces the stored lines exactly.
    Byte-identical output is the point: the mechanism must be invisible
    wherever WordStar had nothing to re-decide."""
    stored = [b'WordStar is designed to take the best advantage of your printer'
              b"'s ",
              b'features.  This file (PRINT.TST) shows how the WordStar printing ',
              b'features work.  Print the file to see how the features work on ',
              b'your default printer.']
    doc = build(SOFT.join(stored[:-1]) + SOFT + stored[-1] + HARD)
    assert printed_lines(doc)[:4] == [s.decode() for s in stored]


def test_the_trailing_space_stays_on_the_line_it_ended():
    """WordStar stores the space it broke at on the line it finished, and the
    corpus is full of it. A re-wrap that dropped it would change the text and
    RTF exports of every realigning document for no reason on paper."""
    doc = build(b'aaaa bbbb' + SOFT + b'cccc dddd' + HARD,
                dots=b'.pf on' + HARD + b'.rm 1.5"' + HARD)   # 15 columns
    assert printed_lines(doc)[:2] == ['aaaa bbbb cccc ', 'dddd']


# ---------------------------------------------------------------------------
# hyphens


def test_a_discretionary_hyphen_disappears_when_its_break_does():
    """PRINT.TST's "Paragraph Indenta-"+"tion": WordStar activated the soft
    hyphen only BECAUSE it broke there. Re-decide the break and the hyphen
    goes with it -- real WS7 prints "Paragraph Indentation", one word."""
    doc = build(b'Paragraph Indenta\x1f' + SOFT + b'tion' + HARD)
    assert printed_lines(doc)[0] == 'Paragraph Indentation'


def test_a_discretionary_hyphen_is_re_used_when_the_break_is_still_needed():
    """The same document's body, which does NOT re-wrap: "...a menu of fonts
    custom-" / "ized...". "customized" is 66 columns against a 65-column
    measure, so the break stays, and the hyphen with it -- exactly what real
    WS7 prints."""
    doc = build(b'Choose fonts by name!  Press ^P= to see a menu of fonts '
                b'custom\x1f' + SOFT + b'ized for your default printer.' + HARD)
    assert printed_lines(doc)[:2] == [
        'Choose fonts by name!  Press ^P= to see a menu of fonts custom-',
        'ized for your default printer.']


def test_a_typed_hyphen_is_a_break_point_and_survives_it():
    """PRINT.TST's narrow `.co 3` column: "create professional-" / "looking
    newsletters". "professional-looking" is one word to a naive wrapper, 20
    columns of it fit and the whole 20-character word does too -- but the
    NEXT word does not, and WordStar breaks after the hyphen. Nothing is
    added or removed at a typed hyphen; it is text."""
    doc = build(b'create professional-' + SOFT
                + b'looking newsletters and presentations.' + HARD,
                dots=b'.pf on' + HARD + b'.rm 2.03"' + HARD)   # 20.3 columns
    assert printed_lines(doc)[:3] == ['create professional-',
                                      'looking newsletters ',
                                      'and presentations.']


# ---------------------------------------------------------------------------
# proportional text measures in points, not screen columns


def test_a_proportional_paragraph_measures_in_points_not_columns():
    """PRINT.TST's own heading case, with its own numbers: a 20.3-column
    (146.16pt) measure and an 11pt proportional face whose own declared width
    is 138 HMI = 5.52pt per character. 21 SCREEN columns overflow the
    measure, which is why the editor broke the word; 21 characters at 5.52pt
    is 115.9pt, which does not, which is why real WS7 joins it."""
    doc = build(font_block(138, 220, PROP_SANS)
                + b'Paragraph Indenta\x1f' + SOFT + b'tion' + HARD,
                dots=b'.pf on' + HARD + b'.rm 2.03"' + HARD)
    assert printed_lines(doc)[0] == 'Paragraph Indentation'
    # The SAME characters, the SAME measure, in the document's own 10-CPI
    # Courier: 21 columns is 151.2pt against 146.16pt, so the break stays --
    # and so does the discretionary hyphen it was activated for. One font
    # apart, two different right answers; the measure is the font's, never
    # the screen's column grid.
    doc = build(b'Paragraph Indenta\x1f' + SOFT + b'tion' + HARD,
                dots=b'.pf on' + HARD + b'.rm 2.03"' + HARD)
    assert printed_lines(doc)[:2] == ['Paragraph Indenta-', 'tion']


# ---------------------------------------------------------------------------
# what realignment leaves alone


def test_a_paragraph_carrying_a_print_control_is_left_exactly_as_stored():
    """A 0x0F print control PLACES something. Moving one across a line break
    moves the thing it places, so a paragraph carrying one keeps the lines
    WordStar stored."""
    shown = b'EMPTY 3-dot rule'
    pctl = ws7_block(0x0F, (900).to_bytes(2, 'little') + bytes([len(shown)])
                     + shown + b'\x1b*c2370a0003b0P')
    doc = build(b'aaaa bbbb' + pctl + SOFT + b'cccc dddd' + HARD,
                dots=b'.pf on' + HARD + b'.rm 1.5"' + HARD)
    b = doc.blocks[0]
    assert pdf.pf_rewrapped_lines(doc, b) is b.lines


def test_word_wrap_off_is_never_re_wrapped():
    """Register C23: with `.aw off` the author is positioning lines by hand."""
    doc = build(b'aaaa bbbb' + SOFT + b'cccc dddd' + HARD,
                dots=b'.pf on' + HARD + b'.rm 1.5"' + HARD + b'.aw off' + HARD)
    b = next(x for x in doc.blocks if x.kind == 'para')
    assert pdf.pf_rewrapped_lines(doc, b) is b.lines


def test_a_single_stored_line_is_left_alone():
    """A paragraph WordStar never broke is not re-broken: nothing in the
    corpus stores a line longer than its own print measure, and inventing a
    break there would be a guess. Scope cut, stated."""
    doc = build(b'aaaa bbbb cccc dddd eeee' + HARD,
                dots=b'.pf on' + HARD + b'.rm 1.5"' + HARD)
    assert printed_lines(doc)[0] == 'aaaa bbbb cccc dddd eeee'


# ---------------------------------------------------------------------------
# justification: the paragraph is the unit


def test_under_pf_on_only_a_paragraphs_last_line_is_ragged():
    """`.oj on` justifies every line of a paragraph but its last. Without
    `.pf` this engine has no paragraph structure on the printed page and uses
    the BLOCK's last line instead (unchanged); with `.pf on` the re-wrap says
    exactly where each paragraph ends, and REFORM.DOT is the document that
    proves it matters -- its one-line paragraphs print RAGGED on real WS7
    under a live `.oj on`, and this engine justified them."""
    doc = build(b'aaaa bbbb' + SOFT + b'cccc dddd eeee' + HARD
                + b'This one is a whole paragraph.' + HARD,
                dots=b'.pf on' + HARD + b'.rm 1.5"' + HARD + b'.oj on' + HARD)
    pages = pdf._doc_to_pagelines(doc, True)
    got = [(''.join(t for t, _ in pl), pl.justify_right_x is not None)
           for pl in pages[0] if ''.join(t for t, _ in pl).strip()]
    assert got == [('aaaa bbbb cccc ', True), ('dddd eeee', False),
                   ('This one is a whole paragraph.', False)], got


# ---------------------------------------------------------------------------
# every printed surface renders the same physical lines


@pytest.mark.parametrize('call, needle', [
    (lambda d: emit.emit_text(d, mode='printed'),
     'in editing, but another to occur'),
    (lambda d: emit.emit_html(d, mode='printed'),
     'in editing, but another to occur'),
    (lambda d: emit.emit_rtf(d, mode='printed'),
     'in editing, but another to occur'),
])
def test_every_printed_export_follows_the_same_wrap(call, needle):
    """Printed text, printed HTML and Printed RTF are facsimiles of the
    printed page -- they render the SAME physical lines the PDF does, so they
    ask `pf_rewrapped_lines` the same question. One test per surface so a
    regression names the surface that broke."""
    doc = build(b'Dots to have one thing display in editing, but' + SOFT
                + b'another to occur during printing' + HARD)
    assert needle in call(doc)


def test_a_pf_off_document_is_byte_identical_across_every_surface():
    """The blast-radius guard: with realignment off, every export is exactly
    what it was before this mechanism existed."""
    body = (b'Dots to have one thing display in editing, but' + SOFT
            + b'another to occur during printing' + HARD)
    doc = build(body, dots=b'.rm 6.5"' + HARD)
    for call in (lambda d: emit.emit_text(d, mode='printed'),
                 lambda d: emit.emit_html(d, mode='printed'),
                 lambda d: emit.emit_rtf(d, mode='printed')):
        out = call(doc)
        assert 'in editing, but another' not in out
