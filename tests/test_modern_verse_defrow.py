"""planning #263: Modern PDF's verse/centre line-height tightening, its
leading spacer, and the def/bullet indent ladder and hang.

All three are BACKPORTS of rules Soft Return.app's Modern view already
shipped and Jon ruled should be shared (2026-09-11, verse: "Yes. I want it.
Backport it."; def rows: "Definitely backport. We spent a long time getting
that looking nice."). The app is the reference; this engine reproduces its
measured numbers, and where it cannot -- the app measures a real Mac face
through a real text stack, this engine sets base-14 and measures AFM data --
the residual is stated in the assertion rather than papered over.

Tier 1 here is synthetic (CLAUDE.md: synthetic fixtures only). The two
WORKED EXAMPLES from the spec are tier 2 (`sawyer`), against two documents
of Robert J. Sawyer's public WS7 archive that the committed manifest already
carries.
"""
import re
import zlib

import pytest

from ctrlkd import core, pdf

HARD = b'\r\n'
SOFT = b'\x8d\x0a'

TD = re.compile(rb'BT /\w+ \d+ Tf -?\d+ Ts (?:-?[\d.]+ Tz )?'
                rb'(-?[\d.]+) (-?[\d.]+) Td \((.*?)\) Tj ET', re.S)


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
    with no spaces in it: a whitespace token draws no text-showing
    operator at all (`_modern_line_ops`' own `if text.strip()`), so a line
    read back out of the PDF bytes is its visible glyphs, in order."""
    by_y = {}
    for m in TD.finditer(_streams(out)[page - 1]):
        x, y, t = float(m.group(1)), float(m.group(2)), m.group(3)
        by_y.setdefault(round(y, 3), []).append((x, _unesc(t)))
    rows = []
    for y in sorted(by_y, reverse=True):
        segs = sorted(by_y[y])
        rows.append((y, segs[0][0], ''.join(t for _, t in segs)))
    return rows


def _advances(out, page=1):
    """Baseline-to-baseline advance INTO each line after the first."""
    ys = [y for y, _x, _t in _lines(out, page)]
    return [round(a - b, 4) for a, b in zip(ys, ys[1:])]


def _modern(data):
    doc = core.parse_ws(data)
    doc.meta['variant'] = 'ws4'
    return doc


def pdf_ws7_block(cmd, content=b''):
    """One WS7 record -- same helper shape test_modern_box_regions.py and
    test_modern_line_spacing.py already use for synthetic WS7 fixtures."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _centred(title):
    pad = (65 - len(title)) // 2
    return (' ' * pad + title).encode()


# --------------------------------------------------- rule 1: the tightening

def test_natural_line_table_reproduces_the_app_s_two_measurements():
    """The two faces the app measured through its own text stack:
    Times New Roman 14 -> 17.5pt natural, Courier Prime 12 -> 14.0. A
    face-independent constant cannot do this -- against `MODERN_LINE * pt`
    the two ratios are 0.749 and 0.838, not one number."""
    assert 14 * pdf._MODERN_NATURAL_LINE['Times'] == 17.5
    assert 12 * pdf._MODERN_NATURAL_LINE['Courier'] == pytest.approx(14.0)
    assert pdf._modern_tight_h('Times', 14) == pytest.approx(12.578125)
    assert pdf._modern_tight_h('Courier', 12) == pytest.approx(10.0625)
    # ... and the two are NOT one ratio against `MODERN_LINE * pt`, which
    # is the whole reason this is a table: Times 14 comes to 0.749 of the
    # untightened advance, Courier Prime 12 to 0.699.
    assert (pdf._modern_tight_h('Times', 14) / (pdf.MODERN_LINE * 14)
            == pytest.approx(0.749, abs=0.0005))
    assert (pdf._modern_tight_h('Courier', 12) / (pdf.MODERN_LINE * 12)
            == pytest.approx(0.699, abs=0.0005))


def test_ordinary_prose_keeps_the_library_s_own_1_2_leading():
    data = (b'An ordinary sentence that ends with terminal punctuation.' + HARD
            + b'A second ordinary sentence, also ending in a full stop.' + HARD)
    out = pdf.emit_pdf(_modern(data), mode='modern')
    assert _advances(out) == [pytest.approx(16.8)]


def test_a_verse_unit_tightens_its_own_internal_lines():
    """Two short non-terminal lines are a stanza to `looks_like_verse` --
    the SAME verdict Modern RTF and Modern HTML already tighten on."""
    data = (b'     the first line of a stanza' + HARD
            + b'     and then the second one' + HARD)
    out = pdf.emit_pdf(_modern(data), mode='modern')
    assert _advances(out)[0] < pdf.MODERN_LINE * 14


def test_a_centred_paragraph_tightens_and_an_ordinary_one_does_not():
    data = (b'.oc on' + HARD + b'Centred.' + HARD + b'Also centred.' + HARD
            + b'.oc off' + HARD)
    out = pdf.emit_pdf(_modern(data), mode='modern')
    tight = _advances(out)[0]
    plain = (b'Ordinary prose here.' + HARD + b'More ordinary prose.' + HARD)
    assert tight < _advances(pdf.emit_pdf(_modern(plain), mode='modern'))[0]


def test_a_tightened_paragraph_that_wraps_reverts_to_the_body_leading():
    """Job 437: the tightening is about how a verse or centred LINE reads
    against its neighbours. A paragraph long enough to need a second visual
    line is prose that merely got classified, and compressing its own
    internal wrap crowds it -- so a tight paragraph that actually wraps
    renders at `MODERN_LINE * pt` throughout, and takes no spacer either."""
    long_centred = b'.oc on' + HARD + (b'word ' * 40).strip() + HARD
    out = pdf.emit_pdf(_modern(long_centred), mode='modern')
    rows = _lines(out)
    assert len(rows) > 1                       # it really did wrap
    assert _advances(out) == [pytest.approx(16.8)] * (len(rows) - 1)


# ------------------------------------------------- rule 1b: the job-434 spacer

def test_the_spacer_is_the_ink_deficit_plus_a_fixed_pad():
    """A tightened box loses its height off the ascent, so a line whose real
    ink rises above where the baseline now lands inside it needs that room
    reserved above -- deficit + `MODERN_SPACER_PAD`, never a guess."""
    toks = [('Tall (d)', frozenset(), 'Times', 14, None, 0.0)]
    ink = pdf._modern_ink_above_baseline(toks)
    base = pdf._modern_tight_baseline('Times', 14)
    assert ink > base                                    # this line needs it
    assert (pdf._modern_leading_spacer(toks, 'Times', 14)
            == pytest.approx(ink - base + pdf.MODERN_SPACER_PAD))


def test_no_spacer_when_the_ink_already_fits():
    """Zero or negative deficit reserves nothing -- a line of x-height
    letters at a size whose tight box still clears them."""
    toks = [('ooo', frozenset(), 'Times', 4, None, 0.0)]
    assert pdf._modern_ink_above_baseline(toks) < pdf._modern_tight_baseline(
        'Times', 4)
    assert pdf._modern_leading_spacer(toks, 'Times', 4) == 0.0


def test_ink_is_real_outline_extent_not_a_nominal_ascender():
    """A line of x-height letters and a line carrying an ascender must not
    measure the same -- the whole reason afm.INK_TOP exists."""
    low = [('worn once', frozenset(), 'Times', 14, None, 0.0)]
    high = [('world once', frozenset(), 'Times', 14, None, 0.0)]
    assert (pdf._modern_ink_above_baseline(high)
            > pdf._modern_ink_above_baseline(low))


def test_a_tightened_line_spends_its_spacer_above_itself():
    """The spacer rides on the line it belongs to: the advance INTO a
    tightened line is its own tight height plus its own spacer."""
    data = (b'Ordinary prose that ends in a full stop.' + HARD
            + _centred('Mixed Case Title') + HARD)
    out = pdf.emit_pdf(_modern(data), mode='modern')
    rows = _lines(out)
    tok = [('Mixed Case Title', frozenset(), 'Times', 14, None, 0.0)]
    expect = (pdf._modern_tight_h('Times', 14)
              + pdf._modern_leading_spacer(tok, 'Times', 14))
    assert rows[0][0] - rows[1][0] == pytest.approx(expect, abs=0.05)


def test_no_spacer_between_two_consecutive_graphic_rows():
    """A box's vertical rule has to read as one continuous stroke, not a
    dashed one, so two graphic rows in a row get no spacer between them."""
    top = '\u250c' + '\u2500' * 8 + '\u2510'
    side = '\u2502' + ' ' * 8 + '\u2502'
    # WS7-shaped, so the cp437 bytes survive parsing as graphic characters
    # (a bare WS4 read strips bit 7 off them) -- same fixture convention
    # test_modern_box_regions.py uses.
    data = (pdf_ws7_block(0x00) + top.encode('cp437') + HARD
            + (side.encode('cp437') + HARD) * 2)
    doc = core.parse_ws(data)
    flow = [i for i in pdf._modern_flow(
        doc, frozenset(('footnote', 'endnote', 'annotation')),
        text_width_pt=468.0) if i[0] == 'para']
    assert all(pdf._modern_para_is_graphic(i) for i in flow)
    assert all(i[9] for i in flow), 'box rows read as a stanza and tighten'
    # a graphic row in isolation WOULD take a spacer -- the vector cell's
    # own top edge is well above a tightened baseline
    lone = pdf._modern_leading_spacer(flow[0][1],
                                      *pdf._modern_line_face(flow[0][1]))
    assert lone > 0
    # ... and two such rows in a row stack at exactly one tight line
    # height, with nothing reserved between them. Measured on rows that
    # also carry a word, so the baselines are readable as text ops.
    labelled = (pdf_ws7_block(0x00)
                + ('\u2502 one    \u2502').encode('cp437') + HARD
                + ('\u2502 two    \u2502').encode('cp437') + HARD)
    out = pdf.emit_pdf(core.parse_ws(labelled), mode='modern')
    face = pdf._modern_line_face(
        [i for i in pdf._modern_flow(
            core.parse_ws(labelled),
            frozenset(('footnote', 'endnote', 'annotation')),
            text_width_pt=468.0) if i[0] == 'para'][0][1])
    # (the PDF writes its y positions at `%.1f`, so 0.05 is the floor any
    # assertion read back out of the bytes can hold to)
    assert _advances(out) == [pytest.approx(pdf._modern_tight_h(*face),
                                            abs=0.05)]


# ------------------------------------------------ rule 2: the ladder and hang

def _def_doc(extra=b''):
    body = (b'WS.EXE:  a mostly default installation with a description long '
            b'enough to wrap onto a second visual line of its own.')
    return _modern(b'Intro sentence.' + HARD + HARD + body + HARD + extra)


def test_a_level_one_def_row_starts_at_the_margin():
    out = pdf.emit_pdf(_def_doc(), mode='modern')
    rows = _lines(out)
    assert rows[1][1] == pytest.approx(72.0)


def test_a_def_row_continuation_hangs_a_fixed_72pt_past_the_margin():
    out = pdf.emit_pdf(_def_doc(), mode='modern')
    rows = _lines(out)
    assert rows[2][1] == pytest.approx(72.0 + pdf.MODERN_DEF_HANG_PT)


def test_a_def_row_renders_its_label_over_a_two_space_gap():
    """The author's own column padding between label and body is typewriter
    geometry, not content: Modern re-sets the row as a hanging label."""
    padded = b'WS.EXE:' + b' ' * 8 + b'body text of the entry.'
    flow = [i for i in _flow(b'Intro.' + HARD + HARD + padded + HARD)
            if i[0] == 'para']
    assert (''.join(t[0] for t in flow[-1][1])
            == 'WS.EXE:  body text of the entry.')


def test_the_ladder_steps_four_columns_per_nesting_level():
    """Level 1 sits AT the margin; each deeper level steps in by
    `MODERN_LEVEL_STEP_COLS`, whatever raw column the source used."""
    outer = b'OUTER:  the outer entry.'
    inner = b'    INNER:  the nested entry.'
    out = pdf.emit_pdf(_modern(b'Intro.' + HARD + HARD + outer + HARD
                                + inner + HARD), mode='modern')
    rows = _lines(out)
    col_pt = 12.0 * 0.6
    assert rows[1][1] == pytest.approx(72.0)
    assert rows[2][1] == pytest.approx(
        72.0 + pdf.MODERN_LEVEL_STEP_COLS * col_pt)


def test_the_row_s_own_declared_column_is_not_used():
    """Two level-1 blocks opened at different `.lm` values land together at
    the margin -- Jon's b17 ruling, the reason the ladder reads `level` and
    never `col`."""
    data = (b'.lm 15' + HARD + b'FIRST:  entry one.' + HARD
            + b'.lm 2' + HARD + b'SECOND:  entry two.' + HARD)
    rows = _lines(pdf.emit_pdf(_modern(data), mode='modern'))
    assert [r[1] for r in rows] == [pytest.approx(72.0)] * len(rows)


def test_a_bullet_row_hangs_by_its_own_marker_s_measured_advance():
    """A points hang, not a column count: the marker and its gap never land
    on a whole number of monospace cells in a proportional face."""
    item = (b'* a bulleted entry whose text is long enough that it has to '
            b'wrap onto a second visual line of its own.')
    data = (b'Intro.' + HARD + HARD + item + HARD
            + b'* a second bulleted entry, so the marker is evidence.' + HARD)
    rows = _lines(pdf.emit_pdf(_modern(data), mode='modern'))
    marker = pdf._natural_width_pt('* ', 'Times-Roman', pdf.MODERN_BODY_PT)
    assert rows[1][1] == pytest.approx(72.0)
    assert rows[2][1] == pytest.approx(72.0 + marker, abs=0.01)
    assert rows[2][1] != pytest.approx(72.0 + pdf.MODERN_DEF_HANG_PT)


def test_an_indented_bullet_hangs_by_its_marker_not_by_its_padding():
    """The row's residual leading spaces come off with the block's `.lm`
    when the ladder replaces it -- and they come off BEFORE the marker is
    measured, or an indented bullet's hang would be the width of its own
    padding instead of its own glyph."""
    item = (b'   * a bulleted entry whose text is long enough that it has to '
            b'wrap onto a second visual line of its own.')
    data = (b'Intro.' + HARD + HARD + item + HARD
            + b'   * a second bulleted entry, so the marker is evidence.' + HARD)
    rows = _lines(pdf.emit_pdf(_modern(data), mode='modern'))
    marker = pdf._natural_width_pt('* ', 'Times-Roman', pdf.MODERN_BODY_PT)
    assert rows[1][1] == pytest.approx(72.0)          # level 1, at the margin
    assert rows[2][1] == pytest.approx(72.0 + marker, abs=0.01)


def test_a_centred_structured_row_takes_the_tightening_not_the_ladder():
    """The centred reading wins: a centred row tightens unconditionally and
    never picks up a hang."""
    data = (b'Intro.' + HARD + HARD + _centred('MID:  a centred def-shaped row')
            + HARD)
    it = [i for i in _flow(data) if i[0] == 'para'][-1]
    assert it[9] is True                                   # tight
    assert it[10] == 0.0                                   # no hang


def _flow(data):
    return pdf._modern_flow(_modern(data),
                            frozenset(('footnote', 'endnote', 'annotation')),
                            text_width_pt=468.0)


# ------------------------------------------ the spec's own worked examples

@pytest.mark.sawyer
def test_versions_ws_page_one_reproduces_the_app_s_def_list(require_sawyer_doc):
    """Tier 2. The spec's worked example, measured in the app: first lines
    of a def row at x = 72.00, continuations at x = 144.00, on a 468pt
    measure -- against the library's own pre-backport page, where EVERY
    line sat at x = 180.00 on a 360pt measure.

    The first line's text is the app's, character for character. Its
    continuation starts exactly where the app's does; it breaks earlier
    because a hang narrows the continuation measure to 396pt (the app's own
    `headIndent` against its 468pt text container does the same), and
    468pt of the app's quoted second line does not fit in 396."""
    with open(require_sawyer_doc('VERSIONS.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    rows = _lines(pdf.emit_pdf(doc, mode='modern'), page=1)
    first = next(r for r in rows if r[2].startswith('WS.EXE:'))
    assert first[1] == pytest.approx(72.0)
    assert first[2] == ('WS.EXE:  a mostly default installation but with '
                        'minor customizations made by').replace(' ', '')
    cont = rows[rows.index(first) + 1]
    assert cont[1] == pytest.approx(144.0)
    assert cont[2].startswith(('Robert J. Sawyer, the person who compiled '
                               'this WordStar archive.').replace(' ', ''))
    # every def row on the page opens at the margin and hangs to 144
    starts = {round(r[1], 2) for r in rows if r[0] < first[0]}
    assert starts <= {72.0, 144.0}


@pytest.mark.sawyer
def test_readme_ws_page_four_centred_row_advance(require_sawyer_doc):
    """Tier 2. The spec's other worked example: the centred row
    "Upgrading from a Previous Release (WordStar 7).pdf" on page 4, and the
    blank line above it.

    The app measured that block at 31.29pt. This engine measures 33.50 --
    16.80 blank + 12.58 tight row + 4.12 spacer -- and the difference is
    NOT reproducible from base-14 metrics: 31.29 would need the row plus
    its spacer to come to 14.49, and the app's own spacer rule has a floor
    of `MODERN_SPACER_PAD` (2.0) the moment it fires at all, so its own
    smallest possible answer for a tightened 14pt Times row is 14.58. The
    parts this engine CAN check against the app it does: the blank above is
    the body's own 16.80, the row itself is the tightened 12.58, and the
    spacer is in the app's own measured 3.70-3.94 family (4.12 here; the
    ~0.25 is the gap between a Mac face's real glyph-path bounds and the
    AFM design bounding boxes this engine sets from)."""
    with open(require_sawyer_doc('-README.WS (root)'), 'rb') as fh:
        doc = core.parse(fh.read())
    rows = _lines(pdf.emit_pdf(doc, mode='modern'), page=4)
    i = next(i for i, r in enumerate(rows)
             if r[2].startswith('UpgradingfromaPreviousRelease'))
    block = rows[i - 1][0] - rows[i][0]
    blank, tight = pdf.MODERN_LINE * 14, pdf._modern_tight_h('Times', 14)
    assert blank == pytest.approx(16.8)
    assert tight == pytest.approx(12.578125)
    spacer = block - blank - tight
    assert block == pytest.approx(33.50, abs=0.05)
    assert spacer == pytest.approx(4.12, abs=0.05)
    # the app's own three measured spacers on this document are 3.70/3.71/
    # 3.94 -- the same family, ~0.25 apart for the reason the docstring
    # gives. The bound is what this engine can honestly claim, not 0.05.
    assert 3.5 < spacer < 4.5


# --------------------------------- which FACE a fontless run is measured in
#
# Jon's addendum, 2026-09-11: every measurement this port makes -- the
# natural line height a tightening is relative to, a bullet marker's own
# advance -- resolves its face through Modern's OWN existing rule (planning
# #252), never through Printed's unconditional Courier default. A run no
# font block covers reads in TIMES at the Modern body size; the one
# exception is a document that declares fonts somewhere AND declares its
# type non-proportional (`.ps off`), where an uncovered run reads in
# COURIER. The two faces have different natural line heights (1.25 em
# against 7/6) and very different marker advances, so the resolver is
# load-bearing for both rules, not just for which glyphs get drawn.

def _helv_typestyle():
    from ctrlkd.typestyles import TYPESTYLE_NAMES
    return next(k for k, v in TYPESTYLE_NAMES.items()
                if v.lower().startswith('helv'))


def _font_block(number, points=12.0, width=180):
    return pdf_ws7_block(0x02, round(width).to_bytes(2, 'little')
                         + round(points * 20).to_bytes(2, 'little')
                         + (number & 0x01FF).to_bytes(2, 'little') + bytes(6))


def _ps_doc(ps, body):
    """A WS7 document with an optional `.ps on|off`, the fixture `body`
    UNCOVERED by any font block, then a real font block so `doc.fonts` is
    non-empty (which is what makes `.ps off` mean anything at all --
    a fontless document stays Times regardless, the ruling's own carve-out)."""
    header = pdf_ws7_block(0x00, bytes([0x70]) + bytes(15))
    ps_line = (b'.ps %s' % ps.encode()) + HARD if ps else b''
    return (header + ps_line + body
            + _font_block(_helv_typestyle(), 12.0)
            + b'Covered line.' + HARD)


def _first_para(data):
    doc = core.parse_ws(data)
    return doc, [i for i in pdf._modern_flow(
        doc, frozenset(('footnote', 'endnote', 'annotation')),
        text_width_pt=468.0) if i[0] == 'para'][0]


# A spaces-centred row: `centered` is structure, so it tightens whatever
# the verse heuristic makes of the surrounding prose -- the point here is
# WHICH FACE the tightening measures against, not which rule selected it.
CENTRED = _centred('A Centred Title Row') + HARD


def test_fontless_tightened_row_measures_in_times_by_default():
    doc, para = _first_para(_ps_doc(None, CENTRED))
    assert doc.fonts                                    # declares fonts
    assert doc.meta['formatting'].get('proportional') is not False
    assert para[9] is True                              # tight
    assert pdf._modern_line_face(para[1]) == ('Times', pdf.MODERN_BODY_PT)
    assert pdf._modern_tight_h(*pdf._modern_line_face(para[1])) == pytest.approx(
        12.578125)


def test_ps_off_tightened_row_measures_in_courier():
    """`.ps off` with fonts declared: the uncovered row reads in Courier, so
    its tightening is relative to COURIER's natural line height (7/6 em),
    not Times' 1.25 -- a different number, which is the point of the
    per-face table."""
    doc, para = _first_para(_ps_doc('off', CENTRED))
    assert doc.meta['formatting']['proportional'] is False
    assert para[9] is True                              # still tight
    face = pdf._modern_line_face(para[1])
    assert face == ('Courier', pdf.MODERN_BODY_PT)
    assert pdf._modern_tight_h(*face) == pytest.approx(
        pdf.MODERN_BODY_PT * 7.0 / 6.0 * pdf.MODERN_VERSE_TIGHT)
    assert pdf._modern_tight_h(*face) != pytest.approx(12.578125)


BULLETS = (b'* a bulleted entry whose text is long enough to wrap onto a '
           b'second visual line of its own.' + HARD
           + b'* a second bulleted entry, so the marker is evidence.' + HARD)


def test_bullet_hang_measures_the_marker_in_the_resolved_face():
    """Same resolver, same load: the hang is the marker's REAL advance in
    the face that draws it, so `.ps off` moves it from Times' ~7.0pt to
    Courier's fixed-pitch 16.8pt at the 14pt body size."""
    _doc, times_para = _first_para(_ps_doc(None, BULLETS))
    _doc2, courier_para = _first_para(_ps_doc('off', BULLETS))
    assert times_para[10] == pytest.approx(
        pdf._natural_width_pt('* ', 'Times-Roman', pdf.MODERN_BODY_PT))
    assert courier_para[10] == pytest.approx(
        pdf._natural_width_pt('* ', 'Courier', pdf.MODERN_BODY_PT))
    assert courier_para[10] > times_para[10]
