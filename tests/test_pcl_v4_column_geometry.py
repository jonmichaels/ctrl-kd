"""Two more mechanisms out of the ws7-prints/v4 set, 2026-09-12 (causes 7,
10-page-count, 11 and 15 of research/2026-09-12_pcl-v4-untriaged-triage.md).
Both are MEASURED against real WordStar 7 -- the PRISTINE.EXE captures in the
private corpus -- and the synthetic fixtures below reproduce the same shapes,
so the rules stay covered with no corpus at all.

  D. A PAGE'S BUDGET IS ITS REAL TEXT HEIGHT, NOT THAT HEIGHT ROUNDED DOWN
     TO WHOLE DEFAULT LEADS, and every line -- the first one included --
     spends its own lead out of it. `_printed_cap` has to floor (it answers
     "how many DEFAULT-lead lines fit"), and spending the floored count back
     out threw away up to one lead of real paper. Four corpus documents pair
     a fractional-inch `.mt` with `.lh 14pt` and open with two 12pt lines
     before that `.lh` takes effect, and every one of them lost exactly one
     line per column: `REF/WINGDING.CHT` (WS7 2 + 45 lines, engine 2 + 44),
     `REF/SYMBOL.CHT` (2 + 47 vs 2 + 46), `PRINTERS/fontcrib.ws` and
     `PRINTER.PS` (2 + 51 vs 2 + 50). `LSRBOX/LSRBOX.WS` ran to 9 pages
     against WS7's 7 for the same reason.

  E. A COLUMN GROUP SHARES ONE TOP, AND ONE COLUMN WIDTH.
     Top: every column of a sheet begins where the `.co n>1` REGION begins
     on that sheet, below whatever non-columnar prefix the sheet opened
     with -- WS7 opens WINGDING.CHT's columns 2-5 at 153.2pt, not at the
     sheet's own first text line (129.2pt), and gives them the same 45
     lines column 1's columnar part gets, not 46. `MICKEE/MICKEE.WS`
     overprinted its own section heading for the want of this.
     Width: `.rm` is stateful and documents move it INSIDE a live region
     (MICKEE.WS alternates `.rm 0.7"` with `.rm 6.5"`; fontcrib.ws and
     PRINTER.PS restate `.rm 6.9i` at the top of every sheet after the
     first). The region's own opening `.rm` fixes the grid for the whole
     region -- reading it off whichever columnar block a sheet happens to
     start with walked fontcrib's columns 2-5 out to x = 572/1123/1674/
     2225pt, right off the sheet.
"""
import collections
import re
import json

import pytest

from ctrlkd import core, layout, pdf


HARD = b'\r\n'


def _rows(doc):
    """{x_pt: [(y_top_pt, text), ...]} for the whole printed PDF, read back
    out of the emitter's own page streams -- the same quantity
    tools/fidelity_gate.py compares against WS7's decipoint positions,
    without needing that tool or any corpus."""
    pages = pdf._doc_to_pagelines(doc, True)
    out = []
    for page in pages:
        by_x = collections.defaultdict(list)
        top = pdf._printed_top(doc)
        page_h = pdf._resolved_page_height(doc, True)
        lead = pdf._printed_lead(doc)
        offset = getattr(page, 'column_top_offset_pt', None) or 0.0
        y = None
        prev_col = getattr(page[0], 'col', None) if page else None
        for n, line in enumerate(page):
            own = getattr(line, 'lead', None) or lead
            cur_col = getattr(line, 'col', None)
            if n == 0:
                y = top + own
            elif cur_col is not None and cur_col != prev_col:
                y = top + offset + own
            else:
                y += own
            prev_col = cur_col
            text = ''.join(t for t, _ in line).strip()
            if text:
                x = line.left if getattr(line, 'left', None) is not None \
                    else pdf._printed_left(doc, pdf._printed_size(doc))
                by_x[round(x, 1)].append((round(y, 1), text))
        out.append({x: sorted(v) for x, v in by_x.items()})
    return out


# ------------------------------------------------------------- mechanism D
def test_a_short_first_line_does_not_forfeit_the_pages_fractional_remainder():
    """WINGDING.CHT's own shape, with no corpus: `.mt 1.6"`/`.mb .3"` leaves
    655.2pt of text height, which is 46.8 lines at the document's `.lh 14pt`
    -- so `_printed_cap` floors to 46 and the old `(cap - 1) * lead` budget
    could only ever spend 644pt of it. The sheet opens with two 12pt lines
    (they precede the `.lh`), which leaves room for 45 fourteen-point lines,
    and that is what real WS7 prints."""
    src = (b'.mt 1.6"' + HARD + b'.mb .3"' + HARD + b'Title' + HARD + HARD
           + b'.lh 14pt' + HARD
           + HARD.join(b'r%03d' % n for n in range(1, 120)) + HARD)
    doc = core.parse_ws(src)
    cap, lead = pdf._printed_cap(doc), pdf._printed_lead(doc)
    assert cap * lead < 655.2, \
        'the floored line count cannot spend the whole text height'
    assert pdf._printed_budget_pt(doc, cap, lead) == pytest.approx(655.2), \
        'the budget IS the real text height: (66 - 9.6 - 1.8) lines x 12pt'
    page1 = pdf._doc_to_pagelines(doc, True)[0]
    assert len(page1) == 47, '2 twelve-point lines + 45 fourteen-point ones'
    # 127.0/769.0 rather than WS7's own 127.2/769.2: `_printed_top` reports
    # `.mt 1.6"` as a whole 115pt, the documented sub-point measurement floor
    # (cause 14 of the same triage), well inside this gate's 1.0pt bar.
    ys = [y for y, _ in sorted(_rows(doc)[0].popitem()[1])]
    assert ys[0] == pytest.approx(127.0) and ys[-1] == pytest.approx(769.0)


def test_a_uniform_lead_page_still_breaks_exactly_where_the_line_count_says():
    """The byte-identity half: with one lead on the page, `n` lines fit iff
    `n <= floor(height / lead)`, which IS `_printed_cap`. Nothing moves for
    any document that does not mix leads -- 385 of the 389 answer-key
    documents' printed PDFs are unchanged by mechanism D."""
    doc = core.parse_ws(HARD.join(b'line %d' % n for n in range(1, 200)) + HARD)
    cap = pdf._printed_cap(doc)
    assert cap == 55, "WordStar's own defaults: .pl 66 - .mt 3 - .mb 8"
    assert len(pdf._doc_to_pagelines(doc, True)[0]) == cap


def test_an_overprint_line_still_spends_nothing():
    """Unchanged by mechanism D: a line sharing the previous line's baseline
    costs no vertical room, on paper and in the budget."""
    doc = core.parse_ws(HARD.join(b'line %d' % n for n in range(1, 200)) + HARD)
    page = pdf._doc_to_pagelines(doc, True)[0]
    assert not any(getattr(l, 'overprint', False) for l in page)


# ------------------------------------------------------------- mechanism E
def _columns_fixture(rows=200):
    """WINGDING.CHT's own geometry: `.po .3"`, `.mt 1.6"`, `.mb .3"`, a
    title line and its blank at the default 12pt lead, then `.rm .88"` /
    `.lh 14pt` / `.co5, .75"` and the chart body."""
    src = b''
    src += b'.po .3"' + HARD + b'.mt 1.6"' + HARD + b'.mb .3"' + HARD
    src += b'Title' + HARD + HARD
    src += b'.rm .88"' + HARD + b'.lh 14pt' + HARD + b'.co5, .75"' + HARD
    src += HARD.join(b'r%03d' % n for n in range(1, rows + 1)) + HARD
    return core.parse_ws(src)


def test_every_column_of_a_group_starts_at_the_regions_own_top():
    """Real WS7 opens WINGDING.CHT's columns 2-5 at 153.2pt -- `.mt 1.6"`
    (115.2) plus the prefix's 12 + 12 plus their own 14pt lead -- and NOT at
    the sheet's own first text line, 129.2pt."""
    doc = _columns_fixture()
    page = pdf._doc_to_pagelines(doc, True)[0]
    assert page.columns == 5
    assert page.column_top_offset_pt == pytest.approx(24.0), \
        'the prefix is two 12pt lines'
    by_x = _rows(doc)[0]
    xs = sorted(by_x)
    assert xs[0] == pytest.approx(21.6), '`.po .3"`'
    assert [round(x, 1) for x in xs] == [21.6, 139.0, 256.3, 373.7, 491.0], \
        'column pitch is `.rm` + gutter = 63.36 + 54'
    for x in xs[1:]:
        assert by_x[x][0][0] == pytest.approx(153.0), \
            'a later column starts at the region top, not the sheet top'
    assert by_x[xs[0]][0][0] == pytest.approx(127.0), 'the title is unmoved'


def test_a_later_column_holds_no_more_lines_than_the_first_ones_body():
    """The same rule seen as room: the prefix comes out of EVERY column's
    budget, so column 2 gets 45 lines like column 1's columnar part -- WS7's
    own count. It used to get the whole sheet's 46."""
    doc = _columns_fixture()
    by_x = _rows(doc)[0]
    xs = sorted(by_x)
    assert len(by_x[xs[0]]) == 46, 'the title plus 45 body lines'
    for x in xs[1:4]:
        assert len(by_x[x]) == 45
        assert by_x[x][-1][0] == pytest.approx(769.0), 'and the same bottom'


def test_a_region_that_owns_its_sheet_outright_has_no_offset():
    """`REVIEW.DOC`'s shape -- `.co2` on the document's very first line.
    The offset is 0.0 and every column starts at the sheet's own top, which
    is what the reset used to assume for every document."""
    src = (b'.rm 3.13"' + HARD + b'.co2, .25"' + HARD
           + HARD.join(b'r%03d' % n for n in range(1, 120)) + HARD)
    doc = core.parse_ws(src)
    page = pdf._doc_to_pagelines(doc, True)[0]
    assert page.columns == 2 and page.column_top_offset_pt == 0.0
    by_x = _rows(doc)[0]
    tops = {x: v[0][0] for x, v in by_x.items()}
    assert len(set(round(t, 1) for t in tops.values())) == 1


def _mid_region_rm_fixture():
    """fontcrib.ws / PRINTER.PS's own shape: a `.co5` region the author
    breaks with `.pa` (absorbed inside a live region), restating `.rm 6.9i`
    right after it and before restating `.rm .88"` and the `.co5`."""
    def grp(start, n=255):
        return HARD.join(b'c%03d' % k for k in range(start, start + n)) + HARD
    src = (b'.po .3"' + HARD + b'.mt .4"' + HARD + b'.mb .3"' + HARD
           + b'.rm 6.9i' + HARD + b'Title' + HARD + HARD
           + b'.rm .88"' + HARD + b'.lh 14pt' + HARD + b'.co5, .75"' + HARD
           + grp(1)
           + b'.pa' + HARD + b'.rm 6.9i' + HARD + b'.lh 12pt' + HARD
           + b'restated' + HARD
           + b'.rm .88"' + HARD + b'.lh 14pt' + HARD + b'.co5, .75"' + HARD
           + grp(300))
    return core.parse_ws(src)


def test_the_regions_opening_rm_fixes_the_column_grid():
    """A `.rm` inside a live region moves ordinary lines' right edge, as
    `.rm` always does, and must not re-cut the columns: `.rm 6.9i` gives a
    496.8pt column against this region's real 63.36pt one."""
    doc = _mid_region_rm_fixture()
    wide = [i for i, b in enumerate(doc.blocks)
            if (b.columns or 1) > 1 and b.right_margin == 69.0]
    assert wide, 'the fixture really does restate .rm 6.9i inside the region'
    assert pdf._region_first_bi(doc, wide[0]) == 1, \
        "the region's own opening block, not the sheet's first columnar one"
    for page in pdf._doc_to_pagelines(doc, True):
        if getattr(page, 'columns', None):
            assert page.column_width_pt == pytest.approx(63.36), \
                '`.rm .88"` in 10-CPI print columns'


def test_the_region_walk_steps_over_pagebreak_sentinels():
    """`pagebreak`/`colbreak`/`condpage` blocks carry no columns state at
    all, and fontcrib.ws's region is broken by a `.pa` every 51 blocks --
    treating one as the region's edge is what made the mid-region `.rm`
    win."""
    doc = _mid_region_rm_fixture()
    sentinels = [i for i, b in enumerate(doc.blocks) if b.kind != 'para']
    assert sentinels, 'the fixture really does carry an absorbed `.pa`'
    last = max(i for i, b in enumerate(doc.blocks) if (b.columns or 1) > 1)
    assert pdf._region_first_bi(doc, last) == 1


def test_a_real_co1_does_end_the_region():
    """The walk stops at a genuine non-columnar block, so a second region
    gets its own `.rm`."""
    src = (b'.rm .88"' + HARD + b'.co3, .5"' + HARD
           + HARD.join(b'a%03d' % n for n in range(1, 30)) + HARD
           + b'.co1' + HARD + b'between' + HARD
           + b'.rm 2.0"' + HARD + b'.co3, .5"' + HARD
           + HARD.join(b'b%03d' % n for n in range(1, 30)) + HARD)
    doc = core.parse_ws(src)
    starts = sorted({pdf._region_first_bi(doc, i)
                     for i, b in enumerate(doc.blocks)
                     if b.kind == 'para' and (b.columns or 1) > 1})
    assert len(starts) == 2, 'two regions, two opening blocks'
    assert doc.blocks[starts[0]].right_margin == 8.8
    assert doc.blocks[starts[1]].right_margin == 20.0


def test_the_layout_json_publishes_the_column_top_offset():
    """version 8 of the layout contract: a consumer that resets its
    vertical cursor on a `col` change must reset it to `top +
    column_top_offset_pt`. Without the field it cannot know where."""
    doc = _columns_fixture()
    out = json.loads(layout.emit_layout(doc, mode='printed'))
    assert out['version'] == 10
    pages = [p for p in out['printed']['pages'] if p.get('columns')]
    assert pages and pages[0]['column_top_offset_pt'] == pytest.approx(24.0)


# ------------------------------------------------------------- mechanism F
def _pctl_control(shown, payload, hmi=0):
    """A 0x0F USER PRINT CONTROL block, exactly WSFORMAT.TXT's own shape and
    `sawyer/LSRBOX/LSRBOX.WS`'s: a word of HMIs, a byte of display-string
    length, the display string itself, then the raw printer payload
    ("the remaining bytes ... will be sent directly to the printer")."""
    content = hmi.to_bytes(2, 'little') + bytes([len(shown)]) + shown + payload
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + b'\x0f' + content + count + b'\x1d'


_RULE_PCL = b'\x1b*p0062x0145Y\x1b*c0010a3000bg0P'


def test_a_print_controls_display_string_never_reaches_a_running_head():
    """A 0x0F user print control's display string is SCREEN-ONLY -- on paper
    WordStar sends the raw printer payload instead. The body path has done
    that since register C2; a running head kept the string and PRINTED it.
    Measured on `sawyer/LSRBOX/LSRBOX.WS`, whose `.h1` IS one such control
    (a full-page shaded frame, HMI 0): real WS7 prints no header text at all
    on any of its 7 pages, and this engine printed
    `«Shaded ...  0-dot-wide lines»` across the top of every one."""
    ctrl = _pctl_control(b'\xaeShaded 00.500"h\xaf', _RULE_PCL)
    src = b'.h1' + ctrl + HARD + HARD.join(b'body %d' % n for n in range(1, 60)) + HARD
    doc = core.parse(src)
    assert doc.headers[1] == '', 'the display string is not header text'
    assert doc.header_pcl[1] == [(0, 0, 0)], '(char_idx, hmi, pcl_idx)'
    assert len(doc.pcl_programs) == 1
    out = pdf.emit_pdf(doc, mode='printed')
    assert b'Shaded' not in out


def test_a_running_heads_print_control_draws_its_own_rectangles():
    """...and what WS7 actually sends is drawn. LSRBOX.WS's own later `.h1`
    carries TWO rule controls beside its real text, and real WS7 puts 2
    rectangles on every page that head governs; this engine drew none."""
    ctrl = _pctl_control(b'\xaeVrtLin\xaf', _RULE_PCL)
    src = (b'.h1 Sawyer' + ctrl + HARD
           + HARD.join(b'body %d' % n for n in range(1, 130)) + HARD)
    doc = core.parse(src)
    assert doc.headers[1].strip() == 'Sawyer', 'the real words stay'
    out = pdf.emit_pdf(doc, mode='printed')
    streams = re.findall(rb'stream\n(.*?)\nendstream', out, re.S)
    assert len(streams) >= 2
    for s in streams[:2]:
        assert len(re.findall(rb'\bre\b', s)) == 1, 'one rule per page'


def test_a_header_with_no_control_draws_nothing_new():
    """The negative: an ordinary running head is byte-identical to before
    this existed -- no rectangle, no empty header line, no extra op."""
    src = b'.h1 Plain head' + HARD + HARD.join(b'body %d' % n
                                               for n in range(1, 60)) + HARD
    doc = core.parse(src)
    assert not doc.header_pcl.get(1)
    out = pdf.emit_pdf(doc, mode='printed')
    assert not re.findall(rb'\bre\b', out)


def test_a_fill_with_an_omitted_value_is_solid_black():
    """HP's parameterized escapes are VALUE+LETTER pairs and an omitted
    value means zero, so `...bg0P` is pattern 0, fill type 0 -- solid black.
    `_PCL_FILL_RE` required a digit there and dropped 16 of LSRBOX.WS's own
    fills (its thin rules and vertical lines) as unrecognised."""
    assert pdf._parse_pcl_program(b'\x1b*c0010a3000bg0P') == [
        ('fill', 10, 3000, 0.0)]
    # unchanged: the two shapes that already parsed
    assert pdf._parse_pcl_program(b'\x1b*c2250a0003b0P') == [
        ('fill', 2250, 3, 0.0)]
    shaded = pdf._parse_pcl_program(b'\x1b*c0075a3000b0015g2P')
    assert shaded[0][0] == 'fill' and abs(shaded[0][3] - 0.85) < 1e-9


# ---------------------------------------------------------------------------
# F. <0D 8C> IS A COLUMN BREAK'S OWN TERMINATOR, NOT A BARE-CR OVERPRINT.
#
# WordStar records a column break by closing the line it happened on with a
# FLAGGED form feed -- <0D 8C> in the file, de-flagged to <0D 0C> by core's
# own `_FLAGGED` translate -- exactly as it closes a soft-wrapped line with a
# flagged line feed. Counted in Robert J. Sawyer's own WS7 archive the tally
# is the column-break tally, document for document: REF/WINGDING.CHT 4 (one
# sheet, `.co5`), PRINTERS/fontcrib.ws 8 (two sheets), PRINTER.PS 12 (three),
# LSRBOX/LSRBOX.WS 1, and MICKEE.WS 6 / ARTICLES/FORMFEED.WS 1 each directly
# after an explicit `.cb`.
#
# Read as a BARE CR it is ^PM Overprint Line instead, and the line in front
# of every column break spends no vertical room at all (`pdf._cost` credits
# the line AFTER an overprint with a free lead). Measured on LSRBOX.WS page 7
# against the ws7-prints/v4 PRISTINE.EXE capture: real WS7 ends column 1
# after its tenth `.lh 1"` line -- 720pt of a 766.8pt text height, the
# eleventh line's own 55.44pt lead not fitting -- and this engine spent 0pt
# on the tenth, swallowed four more lines out of column 2, and printed two of
# them off the foot of the sheet at the left margin.
# ---------------------------------------------------------------------------

COLBRK = b'\r\x8c'          # as it appears in a real WS7 file


def test_f_a_column_break_terminator_is_not_an_overprint():
    """The mechanism, at its smallest: the line closed by <0D 8C> is an
    ordinary line, and the one after it pays its own lead."""
    src = b'first' + COLBRK + b'second' + HARD
    doc = core.parse(src)
    lines = [ln for b in doc.blocks for ln in getattr(b, 'lines', [])]
    texts = [''.join(s.text for s in ln.spans) for ln in lines]
    assert 'first' in texts[0]
    assert not lines[0].overprint, '<0D 8C> is a terminator, not a bare CR'


def test_f_a_genuine_bare_cr_still_overprints():
    """The negative that keeps ^PM Overprint Line working: a <0D> with
    anything but a form feed after it is unchanged. (Same document shape as
    the case above -- the 0x8C in its own tail is what makes `detect()` read
    both as a WS document, where `overprint_cr` is on.)"""
    src = b'under\rover' + HARD + b'tail' + COLBRK + b'end' + HARD
    doc = core.parse(src)
    lines = [ln for b in doc.blocks for ln in getattr(b, 'lines', [])]
    assert lines[0].overprint, 'a real bare CR is still ^PM'


def test_f_the_form_feed_still_leads_the_next_line():
    """The 0x0C is deliberately NOT consumed as part of the break: it stays
    the next line's leading byte, where planning #246's own form-feed peel
    (measured on PRINT.TST, where WS7 prints no `.pm1` text at all, only the
    page eject) turns it into a page break and re-tests what follows it for
    dot-command-ness."""
    doc = core.parse(b'body' + COLBRK + b'.pm1' + HARD + b'after' + HARD)
    kinds = [b.kind for b in doc.blocks]
    assert 'pagebreak' in kinds, 'the form feed still ejects'
    out = pdf.emit_pdf(doc, mode='printed')
    assert b'.pm1' not in out, 'and what follows it is still a dot command'


def test_f_a_column_breaks_last_line_pays_its_lead():
    """LSRBOX.WS page 7's shape, synthetic: a `.co2` region whose column 1
    is filled by ten 72pt lines, the last of them closed by <0D 8C>, and
    whose next line's own lead (`.lh .77"`, 55.44pt) does not fit in what
    the page has left. Column 1 must hold exactly those ten lines."""
    head = (b'.mt .35"' + HARD + b'.mb 0' + HARD + b'.lh 1"' + HARD
            + b'.rm 2.75"' + HARD + b'.co2, 1.00"' + HARD)
    rows = HARD.join(b'row %02d' % n for n in range(1, 10))
    tail = (COLBRK + b'.lh .77"' + HARD + HARD + b'.lh 12pt' + HARD + HARD
            + HARD.join(b'col two line %02d' % n for n in range(1, 20)) + HARD)
    doc = core.parse_ws(head + rows + HARD + b'row 10' + tail)
    page = pdf._doc_to_pagelines(doc, True)[0]
    cols = [getattr(ln, 'col', 0) for ln in page]
    first_col2 = cols.index(1)
    texts = [''.join(t for t, _ in ln) for ln in page]
    assert first_col2 == 10, (first_col2, texts[:13])
    assert texts[9].strip() == 'row 10'
