r"""planning #264 R1 (Jon, 2026-09-14): "Yes" -- RTF sections: newspaper
columns (A7), hard column break `.cb` (A9), head/foot redefined
mid-document (A13), one piece of work, both engines.

THE SHAPE OF THE ANSWER is packet section 3's own recommendation, and R6
settled the alternative the same morning: "Let's skip page breaks" -- no
imposed page positions. So a section opens where the DOCUMENT'S OWN
GEOMETRY changes and nowhere else, and an RTF reader still paginates
inside every section exactly as it did before.

  A7  `.co n, gutter` becomes `\sect\sectd\cols n\colsx <gutter>`.
  A9  `.cb` becomes `\column` -- a break to the next column INSIDE a
      section, never a section of its own.
  A13 a running head or foot redefined mid-document opens a section
      carrying its own `\header`/`\footer` groups. A slot defined ONCE,
      however late, is not a redefinition: that is the ordinary case
      section 1 already carried, with `\titlepg` when it starts after
      page 1.

BOTH MODES since M17b (2026-09-15). R1 built the column half Printed-only
on a standing ruling rather than a limitation: Modern PDF had no column
model at all, and 2026-08-05 ruled "Modern PDF needs to be the printed
version of the Modern RTF" -- a columnar Modern RTF would have been a
Modern RTF its own PDF could not render. M17 gave Modern PDF a column
model, so the same ruling read the same way now says the opposite, and
`\cols`/`\colsx`/`\column` reach Modern too. A13 always reached both
modes: Modern keeps running heads (ruling M5, 2026-08-06).

Synthetic fixtures only.
"""
import re

import pytest

from ctrlkd import core, emit

HARD = b'\x0d\x0a'


def _ws7(body, dots=b''):
    """A WS5+/WS7 document: the type-0 header block, then raw lines."""
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


def _sections(rtf):
    """Every `\\sect\\sectd ...` opener in the file, verbatim."""
    return re.findall(r'\\sect\\sectd[^\s]*', rtf)


def _section_cols(rtf):
    """Each section opener with its head/foot GAP stripped -- `\\headery`/
    `\\footery` are section properties `\\sectd` resets, so every section
    that draws anything in a margin restates them; what these rows are
    about is the column regime."""
    return [re.sub(r'\\headery\d+\\footery\d+', '', o) for o in _sections(rtf)]


# ------------------------------------------------------------------ A7

def test_a_columnar_region_opens_a_section_with_its_own_column_count():
    doc = _ws7(b'Opening paragraph.' + HARD
               + b'.co 3, 5' + HARD
               + b'Columnar text.' + HARD)
    rtf = emit.emit_rtf(doc, mode='printed')
    assert _section_cols(rtf) == [r'\sect\sectd\cols3\colsx720']


def test_the_gutter_is_print_columns_at_ten_cpi():
    """`.co n, g`'s gutter is the same unit `.po` uses -- 144 twips a
    column -- so `5` is half an inch and `10` is a full one."""
    for gutter, twips in ((5, 720), (10, 1440), (2, 288)):
        doc = _ws7(b'Opening.' + HARD + b'.co 2, %d' % gutter + HARD + b'Text.' + HARD)
        assert (r'\cols2\colsx%d' % twips) in emit.emit_rtf(doc, mode='printed')


def test_a_document_that_opens_in_columns_carries_them_in_the_page_setup():
    """`\\cols` is a section property and the page setup IS section 1's, so
    a document whose very first block is columnar needs no `\\sect` at
    all -- the corpus's REVIEW.DOC and BOOKLET.WS are this shape."""
    doc = _ws7(b'Columnar from the start.' + HARD, dots=b'.co 2, 10' + HARD)
    rtf = emit.emit_rtf(doc, mode='printed')
    assert r'\cols2\colsx1440' in rtf.split(r'\sect')[0]
    assert _sections(rtf) == []


def test_columns_off_closes_the_section_and_opens_a_plain_one():
    doc = _ws7(b'One.' + HARD + b'.co 2, 5' + HARD + b'Two.' + HARD
               + b'.co 1' + HARD + b'Three.' + HARD)
    assert _section_cols(emit.emit_rtf(doc, mode='printed')) == [
        r'\sect\sectd\cols2\colsx720', r'\sect\sectd']


def test_turning_columns_off_and_on_again_with_a_new_gutter_is_two_sections():
    """`.co1`'s own gutter argument is noise -- columns are off -- so it
    normalises away and only the real regime changes count."""
    doc = _ws7(b'One.' + HARD + b'.co 2, 5' + HARD + b'Two.' + HARD
               + b'.co 1, 9' + HARD + b'Three.' + HARD
               + b'.co 1, 3' + HARD + b'Four.' + HARD)
    assert _section_cols(emit.emit_rtf(doc, mode='printed')) == [
        r'\sect\sectd\cols2\colsx720', r'\sect\sectd']


def test_modern_rtf_carries_the_column_regime_too():
    """SUPERSEDED AND RE-PINNED, M17b (2026-09-15). This test was
    `test_modern_rtf_stays_one_column` and read "Not an omission: Modern
    PDF has no column model, and Modern PDF is ruled to be the printed
    form of the Modern RTF." The first half stopped being true when M17
    gave Modern PDF a column model, and the second half then says the
    opposite of what it used to: a ONE-column Modern RTF is the one its
    own PDF cannot print. Renamed rather than silently changed, the same
    treatment planning #256 gave `test_style_leading.py`'s pair."""
    doc = _ws7(b'One.' + HARD + b'.co 3, 5' + HARD + b'Two.' + HARD)
    rtf = emit.emit_rtf(doc, mode='modern')
    assert _section_cols(rtf) == [r'\sect\sectd\cols3\colsx720']


def test_a_document_with_no_co_at_all_opens_no_section():
    doc = _ws7(b'Just prose.' + HARD + b'More prose.' + HARD)
    for mode in ('printed', 'modern'):
        rtf = emit.emit_rtf(doc, mode=mode)
        assert r'\sect' not in rtf and r'\cols' not in rtf


# ------------------------------------------------------------------ A9

def test_cb_becomes_a_column_break_inside_a_columnar_region():
    doc = _ws7(b'.co 2, 5' + HARD + b'First column.' + HARD
               + b'.cb' + HARD + b'Second column.' + HARD)
    rtf = emit.emit_rtf(doc, mode='printed')
    assert r'\column ' in rtf
    assert rtf.index('First column.') < rtf.index(r'\column ') < rtf.index('Second column.')


def test_cb_outside_a_columnar_region_writes_nothing():
    """WordStar never put one there, and in a single-column section the
    control would mean "page break" to a reader -- which `.cb` is not."""
    doc = _ws7(b'One.' + HARD + b'.cb' + HARD + b'Two.' + HARD)
    assert r'\column' not in emit.emit_rtf(doc, mode='printed')


def test_cb_is_a_column_break_in_modern_too():
    """SUPERSEDED AND RE-PINNED, M17b (2026-09-15): was
    `test_cb_writes_nothing_in_modern`. Modern PDF's own column cursor
    takes `.cb` to the next column since M17, so its RTF says so."""
    doc = _ws7(b'.co 2, 5' + HARD + b'One.' + HARD + b'.cb' + HARD + b'Two.' + HARD)
    rtf = emit.emit_rtf(doc, mode='modern')
    assert r'\column ' in rtf
    assert rtf.index('One.') < rtf.index(r'\column ') < rtf.index('Two.')


def test_a_pa_inside_a_columnar_region_is_absorbed():
    """The identical reading the Printed PDF has carried since planning
    #227 -- WINGDING.CHT's author used `.pa` as a manual column simulation
    and honouring them fragments one real column into two short pages.
    RTF had no columns to fragment before the spine; now it has."""
    doc = _ws7(b'.co 2, 5' + HARD + b'One.' + HARD + b'.pa' + HARD + b'Two.' + HARD)
    assert r'\page' not in emit.emit_rtf(doc, mode='printed')


def test_a_pa_outside_a_columnar_region_is_still_a_page_break():
    doc = _ws7(b'One.' + HARD + b'.pa' + HARD + b'Two.' + HARD)
    assert r'\page ' in emit.emit_rtf(doc, mode='printed')


# ----------------------------------------------------------------- A13

def _head_texts(rtf):
    return re.findall(r'\{\\header \\pard\\plain [^{]*\{([^}]*)\}', rtf)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_head_redefined_mid_document_opens_a_section_with_its_own_head(mode):
    doc = _ws7(b'.he First Head' + HARD + b'Chapter one.' + HARD
               + b'.pa' + HARD
               + b'.he Second Head' + HARD + b'Chapter two.' + HARD)
    rtf = emit.emit_rtf(doc, mode=mode)
    assert len(_sections(rtf)) == 1
    assert _head_texts(rtf) == ['First Head', 'Second Head']


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_head_defined_once_however_late_opens_no_section(mode):
    """The ordinary "this document has a running head" case -- section 1
    carries it, with `\\titlepg` for the page before it."""
    doc = _ws7(b'Title page.' + HARD + b'.pa' + HARD
               + b'.he The Only Head' + HARD + b'Body.' + HARD)
    rtf = emit.emit_rtf(doc, mode=mode)
    assert _sections(rtf) == []
    assert _head_texts(rtf) == ['The Only Head']
    assert r'\titlepg' in rtf


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_head_redefined_to_the_same_text_is_not_a_redefinition(mode):
    doc = _ws7(b'.he Same' + HARD + b'One.' + HARD + b'.pa' + HARD
               + b'.he Same' + HARD + b'Two.' + HARD)
    assert _sections(emit.emit_rtf(doc, mode=mode)) == []


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_footer_redefined_mid_document_opens_a_section_too(mode):
    doc = _ws7(b'.fo First Foot' + HARD + b'One.' + HARD + b'.pa' + HARD
               + b'.fo Second Foot' + HARD + b'Two.' + HARD)
    rtf = emit.emit_rtf(doc, mode=mode)
    assert len(_sections(rtf)) == 1
    assert 'First Foot' in rtf and 'Second Foot' in rtf


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_later_section_restates_the_head_gap_sectd_reset(mode):
    """`\\sectd` resets every section property, `\\headery`/`\\footery`
    among them, so a section that draws a head has to say where it sits."""
    doc = _ws7(b'.he One' + HARD + b'A.' + HARD + b'.pa' + HARD
               + b'.he Two' + HARD + b'B.' + HARD)
    rtf = emit.emit_rtf(doc, mode=mode)
    opener = _sections(rtf)[0]
    assert (r'\headery' in opener) == (r'\headery' in rtf.split(r'\sect')[0])


def test_headers_off_gives_a_later_section_no_head_either():
    doc = _ws7(b'.he One' + HARD + b'A.' + HARD + b'.pa' + HARD
               + b'.he Two' + HARD + b'B.' + HARD)
    rtf = emit.emit_rtf(doc, mode='printed', headers=False)
    assert _head_texts(rtf) == []
    assert 'One' not in rtf and 'Two' not in rtf


# -------------------------------------------------- the two together

def test_a_columns_change_and_a_head_change_at_one_block_open_one_section():
    doc = _ws7(b'One.' + HARD + b'.co 2, 5' + HARD + b'.he A Head' + HARD
               + b'Two.' + HARD + b'.pa' + HARD + b'.he B Head' + HARD
               + b'Three.' + HARD)
    rtf = emit.emit_rtf(doc, mode='printed')
    openers = _sections(rtf)
    assert len(openers) == 2
    assert openers[0].endswith(r'\cols2\colsx720')


def test_every_section_opener_is_well_formed():
    """`\\sect` ends the previous section and `\\sectd` resets the next
    one's properties; the pair is never written apart."""
    doc = _ws7(b'One.' + HARD + b'.co 2, 5' + HARD + b'Two.' + HARD
               + b'.co 1' + HARD + b'Three.' + HARD)
    rtf = emit.emit_rtf(doc, mode='printed')
    assert rtf.count(r'\sect') == rtf.count(r'\sect\sectd') * 2
