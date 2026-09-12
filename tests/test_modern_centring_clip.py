"""planning #263: Modern PDF's undeclared (spaces-padded) CENTRING, and the
rows that refuse to wrap.

Both are BACKPORTS of rules Soft Return.app's Modern view already shipped,
ruled 2026-09-11 on the standing principle that the engine works the way the
app does. The app is the reference; these tests state the rule as the app
states it, including the thresholds.

  rule 5, job 456's cousin (the app's b17 rule): a line the author centred
      by TYPING leading spaces carries no `.oc` and no align tag, so it
      arrives left-aligned with its padding still in the text. It is
      recognised (`layout.classify_rows`, already shared), its padding comes
      off, and the row is centred on its own measure. STRENGTH.WS's
      title/byline/email are the worked example.

  rule 6, job 456: a row carrying more than one box-drawing/cp437 graphic
      character is set as ONE line, even when it runs past the measure --
      the app clips such a row rather than wrapping it. BOXES.WS's legend
      rows and LJ6DTP.WS's character-substitution tables are the worked
      examples; ordinary word wrapping folds both at the perfectly legal
      space between a label and its glyph.

  planning #264 item 3 (packet row B4), 2026-09-12: the SAME rule reaches
      HTML, where the fold was equally visible -- a border, a legend or a
      substitution-table row broke in the middle of a narrow browser window
      and stopped being the picture it drew. The rule itself now lives in
      `core.graphic_row_clips`, called by both emitters; HTML drops its
      third branch (a row with nowhere to break), because a browser never
      breaks inside a word on its own, and expresses the other two as
      `white-space:nowrap` on the row.

Tier 1 here is synthetic (CLAUDE.md: synthetic fixtures only). The worked
examples are tier 2 (`sawyer`), against three documents of Robert J.
Sawyer's public WS7 archive that the committed answer key already carries.
"""
import re
import zlib

import pytest

from ctrlkd import core, emit, pdf

HARD = b'\r\n'

TD = re.compile(rb'BT /\w+ \d+ Tf -?\d+ Ts (?:-?[\d.]+ Tz )?'
                rb'(-?[\d.]+) (-?[\d.]+) Td \((.*?)\) Tj ET', re.S)

MARGIN = 72.0
MEASURE = 468.0


def _streams(out):
    """Every page content stream of a ctrl-kd PDF, decompressed."""
    objs = {int(m.group(1)): m.group(2)
            for m in re.finditer(rb'(\d+) 0 obj(.*?)endobj', out, re.S)}
    kids = re.search(rb'/Type\s*/Pages\s*/Kids\s*\[(.*?)\]', out, re.S)
    out_streams = []
    for num in (int(n) for n in re.findall(rb'(\d+) 0 R', kids.group(1))):
        body = objs[num]
        cbody = objs[int(re.search(rb'/Contents (\d+) 0 R', body).group(1))]
        raw = re.search(rb'stream\r?\n(.*?)\r?\nendstream', cbody, re.S).group(1)
        out_streams.append(zlib.decompress(raw)
                           if b'/FlateDecode' in cbody else raw)
    return out_streams


def _unesc(b):
    return (b.replace(b'\\(', b'(').replace(b'\\)', b')')
             .replace(b'\\\\', b'\\').decode('cp1252', 'replace'))


def _lines(out, page=1):
    """[(y, x, text), ...] top to bottom for one page -- one entry per
    visual line, its x the leftmost INK on it, its text the line's own INK
    with no spaces in it (a whitespace token draws no text-showing operator
    at all)."""
    by_y = {}
    for m in TD.finditer(_streams(out)[page - 1]):
        x, y, t = float(m.group(1)), float(m.group(2)), m.group(3)
        by_y.setdefault(round(y, 3), []).append((x, _unesc(t)))
    rows = []
    for y in sorted(by_y, reverse=True):
        segs = sorted(by_y[y])
        rows.append((y, segs[0][0], ''.join(t for _, t in segs)))
    return rows


def _modern(data):
    doc = core.parse_ws(data)
    doc.meta['variant'] = 'ws4'
    return doc


def _flow(data):
    return [i for i in pdf._modern_flow(
        _modern(data), frozenset(('footnote', 'endnote', 'annotation')),
        text_width_pt=MEASURE) if i[0] == 'para']


def _pages(out):
    return len(re.findall(rb'/Type\s*/Page[^s]', out))


def ws7_block(cmd, content=b''):
    """One WS7 record -- the same helper shape the other Modern suites use
    for synthetic WS7 fixtures (a bare WS4 read strips bit 7 off the cp437
    graphic bytes; a WS7 document keeps them)."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _centred(text, width=65):
    """One line hand-centred the way a WordStar author does it: leading
    spaces, no tag, no trailing padding necessarily -- WordStar's own
    centring rounds an odd leftover column toward the left."""
    return (' ' * ((width - len(text)) // 2) + text).encode('cp437')


# ------------------------------------- rule 5: undeclared, spaces-padded centring

def test_a_spaces_padded_row_is_centred_on_the_measure():
    """The row arrives `align == 'left'` with its padding in the text. It
    leaves centred, with the padding gone -- so the line's own ink starts
    where a centred line's ink starts, not where the author's spaces
    happened to put it."""
    data = (b'An ordinary opening paragraph of prose, which gives the '
            b'document a routine body to be read against.' + HARD + HARD
            + _centred('WordStar Strengths') + HARD)
    it = _flow(data)[-1]
    assert it[2] == 'center'
    assert ''.join(t[0] for t in it[1]) == 'WordStar Strengths'   # no padding
    rows = _lines(pdf.emit_pdf(_modern(data), mode='modern'))
    title = rows[-1]
    width = pdf._natural_width_pt('WordStar Strengths', 'Times-Roman',
                                  pdf.MODERN_BODY_PT)
    assert title[1] == pytest.approx(MARGIN + (MEASURE - width) / 2, abs=0.6)


def test_the_padding_is_stripped_from_the_styled_runs_not_just_the_text():
    """The strip happens on the row's own tokens, so a styled row keeps its
    styles: a bold byline sheds its spaces without losing its bold."""
    data = (b'An ordinary opening paragraph of prose, long enough to be the '
            b'document body this row is read against.' + HARD + HARD
            + _centred('\x02by Robert J. Sawyer\x02') + HARD)
    it = _flow(data)[-1]
    assert ''.join(t[0] for t in it[1]) == 'by Robert J. Sawyer'
    assert any('b' in t[1] for t in it[1]), 'the bold survived the strip'


def test_an_ordinary_indented_paragraph_is_not_centred():
    """The classifier's own guards, restated where this rule consumes them:
    the document's routine first-line indent is habit, not centring, and a
    row that fills its measure has nowhere to be off-centre."""
    body = (b'     a paragraph opening at the document routine indent, with '
            b'enough words in it to run the full measure of the line.')
    data = (body + HARD + body + HARD + body + HARD)
    for it in _flow(data):
        assert it[2] == 'left'


def test_a_tag_declared_centred_row_is_unchanged_by_the_strip():
    """A `.oc` row reaches the same branch, and both steps are no-ops on it:
    `layout.modern_flow` stripped that padding upstream (M3) and its align
    is already 'center'."""
    data = (b'.oc on' + HARD + b'A Centred Heading' + HARD + b'.oc off' + HARD)
    it = _flow(data)[0]
    assert it[2] == 'center'
    assert ''.join(t[0] for t in it[1]) == 'A Centred Heading'


def test_a_centred_row_keeps_a_two_sided_block_s_own_measure():
    """Centring is on the row's OWN measure, indent and cut included -- the
    same numbers the app passes its centred paragraph style."""
    data = (b'.lm 11' + HARD + b'.rm 55' + HARD
            + b'An ordinary quoted paragraph, indented on both sides, long '
              b'enough to establish the block.' + HARD
            + b' ' * 10 + _centred('Inside The Quote', width=45) + HARD)
    it = _flow(data)[-1]
    assert it[2] == 'center'
    indent, cut = it[4], it[5]
    assert indent > 0 and cut > 0
    rows = _lines(pdf.emit_pdf(_modern(data), mode='modern'))
    width = pdf._natural_width_pt('Inside The Quote', 'Times-Roman',
                                  pdf.MODERN_BODY_PT)
    assert rows[-1][1] == pytest.approx(
        MARGIN + indent + (MEASURE - indent - cut - width) / 2, abs=0.6)


# --------------------------------------------- rule 6: the rows that do not wrap

LEGEND = ('LL: └ LR: ┘ LC: └┘ Joins: ├┬┴┤ Mixed: ╞╥╨╢ Crosses: ┼╪╫╬ '
          'Verticals: │║ Horizontals: ─═ Corners: ┌┐ H: ─')


def test_a_legend_row_carrying_two_graphic_chars_does_not_wrap():
    """Job 456's own rule. The row is far wider than the measure and has
    perfectly legal wrap points in it; it is still set as ONE line."""
    data = ws7_block(0x00) + LEGEND.encode('cp437') + HARD
    it = _flow(data)[0]
    assert it[6] is True, 'no_wrap'
    rows = _lines(pdf.emit_pdf(core.parse_ws(data), mode='modern'))
    assert len(rows) == 1
    # ... and it really does run past the measure, which is the clip
    assert sum(t[5] for t in it[1]) > MEASURE


def test_one_incidental_graphic_char_is_not_enough():
    """The threshold is TWO, not one -- an ordinary paragraph carrying a
    single symbol (a list marker) is prose and still wraps like prose."""
    prose = ('■ an ordinary bulleted paragraph whose text runs well past '
             'the measure of the line and therefore has to wrap somewhere, '
             'like any other sentence in the document.')
    data = ws7_block(0x00) + prose.encode('cp437') + HARD
    it = _flow(data)[0]
    assert it[6] is False, 'no_wrap'
    assert len(_lines(pdf.emit_pdf(core.parse_ws(data), mode='modern'))) > 1


def test_a_wholly_graphic_row_does_not_wrap():
    """A box border has no space to break at, so this branch and the
    2+-graphic-chars one were always the same answer for such a row -- it is
    stated because a renderer that CAN break a word must not break this.
    (A border row draws as VECTORS, not text-showing operators, so it is
    read off the flow rather than off the page's own text ops.)"""
    border = '┌' + '─' * 88 + '┐'
    data = ws7_block(0x00) + border.encode('cp437') + HARD
    it = _flow(data)[0]
    assert it[6] is True
    assert len(it[1]) == 1                     # one token, nothing to break
    assert len(pdf._modern_wrap(it[1], MEASURE)) == 1


def test_the_three_branches_of_the_rule_as_the_app_states_them():
    def toks(text):
        return [(text, frozenset(), 'Times', 12, None, 0.0)]

    # wholly graphic: graphic characters and spaces, nothing else
    assert pdf._modern_clips_row(toks('│    │'))
    # 2+ graphic chars anywhere on the row, prose or not
    assert pdf._modern_clips_row(toks('LL: └ LR: ┘'))
    # nowhere to break
    assert pdf._modern_clips_row(toks('sawyer@sfwriter.com'))
    # ... and the negatives
    assert not pdf._modern_clips_row(toks('■ one marker, ordinary prose'))
    assert not pdf._modern_clips_row(toks('ordinary prose, no glyphs at all'))
    assert not pdf._modern_clips_row([])


def test_a_clipped_row_is_decided_on_the_row_s_final_tokens():
    """The rule reads the text the page will actually carry: a centred row
    has shed its padding and a def row has gained its label/gap prefix
    before the question is asked."""
    row = 'Mixed: ╞╥'
    data = ws7_block(0x00) + _centred(row) + HARD
    it = _flow(data)[0]
    assert ''.join(t[0] for t in it[1]) == row     # stripped first
    assert it[6] is True                            # ... then clipped


# ------------------------------------------ the spec's own worked examples

@pytest.mark.sawyer
def test_strength_ws_centres_its_title_byline_and_email(require_sawyer_doc):
    """Tier 2, rule 5's worked example (the app's b17 field report). The
    three head rows are hand-centred with typed spaces and no tag at all.
    Each one leaves the flow padding-free and centred on the 468pt measure;
    before this rule they rendered as ordinary left-aligned paragraphs with
    the padding baked into a proportional face, so none of the three sat
    where the author put it."""
    data = open(require_sawyer_doc('STRENGTH.WS'), 'rb').read()
    doc = core.parse_ws(data)
    flow = [i for i in pdf._modern_flow(
        doc, frozenset(('footnote', 'endnote', 'annotation')),
        text_width_pt=MEASURE) if i[0] == 'para']
    head = [''.join(t[0] for t in i[1]) for i in flow[:3]]
    assert head == ['WordStar Strengths', 'by Robert J. Sawyer',
                    'sawyer@sfwriter.com']
    assert all(i[2] == 'center' for i in flow[:3])
    rows = _lines(pdf.emit_pdf(core.parse_ws(data), mode='modern'))[:3]
    for (_, x, text), item in zip(rows, flow[:3]):
        width = sum(t[5] for t in item[1])
        assert x == pytest.approx(MARGIN + (MEASURE - width) / 2, abs=0.6)
    # the three are centred on the same axis, which is the whole look
    centres = [x + sum(t[5] for t in i[1]) / 2
               for (_, x, _t), i in zip(rows, flow[:3])]
    assert max(centres) - min(centres) < 0.6


@pytest.mark.sawyer
def test_boxes_ws_sets_each_legend_row_as_one_line(require_sawyer_doc):
    """Tier 2, rule 6's first worked example -- the field report behind job
    456 ("they have line returns in the middle"). Each legend row carries a
    prose label and several box-drawing glyphs, and ordinary wrapping folds
    it at the space before the last label."""
    data = open(require_sawyer_doc('BOXES.WS'), 'rb').read()
    doc = core.parse_ws(data)
    flow = [i for i in pdf._modern_flow(
        doc, frozenset(('footnote', 'endnote', 'annotation')),
        text_width_pt=MEASURE) if i[0] == 'para']
    legends = [i for i in flow
               if ''.join(t[0] for t in i[1]).lstrip().startswith(('LL', 'UL'))]
    assert legends, 'the legend rows are still in the document'
    assert all(i[6] for i in legends), 'every legend row is clipped'
    # ... and the rule is what is holding them together: measured against
    # the 468pt measure, these rows do not fit, so ordinary wrapping folds
    # the last label ('H: \u2550') onto a line of its own -- the exact shape
    # of the field report.
    folded = [i for i in legends if len(pdf._modern_wrap(i[1], MEASURE)) > 1]
    assert folded, 'a legend row that would otherwise have wrapped'


@pytest.mark.sawyer
def test_lj6dtp_ws_sets_each_substitution_table_row_as_one_line(
        require_sawyer_doc):
    """Tier 2, rule 6's second worked example, and the measured cost of it:
    the character-substitution tables (pages 9-11) are rows of real labels
    and real numbers between double rules, far wider than the measure.
    Ordinary wrapping sets each as two lines; the app clips each to one, and
    the document loses a whole page (10 pages against 11)."""
    data = open(require_sawyer_doc('LJ6DTP.WS'), 'rb').read()
    doc = core.parse_ws(data)
    flow = [i for i in pdf._modern_flow(
        doc, frozenset(('footnote', 'endnote', 'annotation')),
        text_width_pt=MEASURE) if i[0] == 'para']
    table = [i for i in flow
             if ''.join(t[0] for t in i[1]).count('║') > 1]
    assert len(table) > 20, 'the substitution tables are still in the document'
    assert all(i[6] for i in table), 'every table row is clipped'
    out = pdf.emit_pdf(core.parse_ws(data), mode='modern')
    assert _pages(out) == 10


# ------------------------------- packet row B4: the same rule, in HTML

def _html_row(text, mode='modern'):
    doc = core.Document(
        blocks=[core.Block('para', lines=[core.Line(spans=[core.Span(text)])])],
        meta={'variant': 'ws5+'})
    return emit.emit_html(doc, mode=mode)


def test_html_keeps_a_wholly_graphic_row_on_one_line():
    out = _html_row('\u250c\u2500\u2500\u2500\u2510')
    assert 'class="ws-nowrap"' in out
    assert 'span.ws-nowrap{white-space:nowrap}' in out


def test_html_keeps_a_mixed_legend_row_on_one_line():
    """The field report's own shape: a prose label and its glyphs, which
    ordinary wrapping folds at the perfectly legal space between them."""
    assert 'class="ws-nowrap"' in _html_row('LL: \u2514 LR: \u2518 H: \u2550')


def test_html_leaves_one_incidental_glyph_alone():
    """The threshold is TWO, so an ordinary paragraph carrying a single
    list marker still wraps like the prose it is."""
    out = _html_row('\u25a0 one marker, and then ordinary prose that wraps')
    assert 'ws-nowrap' not in out


def test_html_does_not_mark_a_row_that_merely_has_nowhere_to_break():
    """The rule's third branch is deliberately dropped in HTML: a browser
    never breaks inside a word on its own, so the class would be markup
    that changes nothing -- and every one-word row in every document would
    carry it."""
    assert 'ws-nowrap' not in _html_row('sawyer@sfwriter.com')
    assert pdf._modern_clips_row([('sawyer@sfwriter.com', frozenset(),
                                   'Times', 12, None, 0.0)])


def test_html_marks_the_row_in_printed_mode_too():
    """A picture is a picture in either view. The fixed-pitch block is
    `white-space:pre-wrap`, where plain `nowrap` would also collapse the
    column spacing that block exists to preserve -- so the rule inside it
    is `pre`, `pre-wrap`'s non-wrapping twin."""
    out = _html_row('\u250c\u2500\u2500\u2500\u2510', mode='printed')
    assert 'class="ws-nowrap"' in out
    assert 'p.ws-native span.ws-nowrap{white-space:pre}' in out


def test_a_document_with_no_picture_row_pays_no_css_for_one():
    """Same discipline as the `.ws-nonprop` and list rules: the stylesheet
    grows only when a row actually used the class."""
    out = _html_row('ordinary prose, no glyphs at all')
    assert 'ws-nowrap' not in out


def test_html_and_the_pdf_read_one_shared_rule():
    """`core.graphic_row_clips` is the single implementation; `pdf._modern_
    clips_row` is its token-shaped adapter and `emit._html_row_is_nowrap`
    its HTML-shaped one."""
    for text in ('\u2502    \u2502', 'LL: \u2514 LR: \u2518',
                 '\u25a0 ordinary prose', 'no glyphs here at all'):
        toks = [(text, frozenset(), 'Times', 12, None, 0.0)]
        assert pdf._modern_clips_row(toks) == core.graphic_row_clips(text)


def test_the_two_surfaces_ask_about_two_different_character_sets():
    """The PDF's `GRAPHIC_CHARS` is the union of its own per-glyph DRAWING
    tables and holds two things the content classification deliberately
    does not: the four arc corners (produced only by the LJ6DTP Univers
    substitution at render time, never decoded from a file) and `\u20a7`,
    the peseta -- drawn as geometry because no base-14 face carries it
    (planning #266), but an ordinary currency character in prose.

    A price row is the case that matters: the archive's own printer
    character charts carry rows like `158  \u20a7 \u20a7`, which the
    drawing set reads as TWO graphic characters (a picture) and the content
    set reads as none (prose). HTML must ask the content set -- the same
    one `_is_graphic_text` and `split_graphic_spans` read -- or every such
    row gets a nowrap it should never have had."""
    row = '158  \u20a7 \u20a7'
    assert '\u20a7' in pdf.GRAPHIC_CHARS
    assert '\u20a7' not in core.GRAPHIC_CHARS
    assert core.graphic_row_clips(row) is False
    assert core.graphic_row_clips(row, pdf.GRAPHIC_CHARS) is True
    assert 'ws-nowrap' not in _html_row(row)
    # ... and the PDF's own adapter keeps asking the drawing set, unchanged.
    assert pdf._modern_clips_row([(row, frozenset(), 'Times', 12, None, 0.0)])


@pytest.mark.sawyer
def test_boxes_ws_html_keeps_every_legend_row_on_one_line(require_sawyer_doc):
    """Tier 2, the worked example, in HTML this time: every legend row the
    Modern PDF clips carries the class here."""
    data = open(require_sawyer_doc('BOXES.WS'), 'rb').read()
    out = emit.emit_html(core.parse_ws(data), mode='modern')
    rows = [ln for ln in out.splitlines() if 'LL: ' in ln or 'UL: ' in ln]
    assert rows, 'the legend rows are still in the document'
    assert all('ws-nowrap' in ln for ln in rows)
