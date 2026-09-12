"""planning #264 item 5 (packet rows C3+C4): Modern RTF catches up.

C3 -- DEFINITION AND BULLET ROWS HANG. Modern RTF rendered both as plain
paragraphs, so the wrapped part of a definition returned to the left margin
instead of hanging under its own text. They are hanging paragraphs now
(`\\li` plus a negative `\\fi`) on the SAME ladder the Modern PDF lays --
`pdf.MODERN_LEVEL_STEP_COLS` (4 print columns per nesting level, level 1 at
the margin) and `pdf.MODERN_DEF_HANG_PT` (a fixed 72pt body column), the
app behaviour Jon ruled back into the engines on 2026-09-11 ("Definitely
backport. We spent a long time getting that looking nice."). A bullet's
hang is its own marker's advance instead, measured -- the PDF rejected a
whole-column hang there because a marker and its gap never land on a whole
monospace cell in a proportional face.

The HTML half of C3 is the stylesheet: `ul`/`dl`/`dt`/`dd` geometry read
from those same two constants, replacing the browser's defaults.

C4 -- LINES THE AUTHOR CENTRED BY TYPING SPACES. Modern RTF rendered the
typed padding literally, so the row sat off centre AND wrapped early (the
padding spends measure). The classifier has identified these rows for a
long time and HTML has used its verdict just as long; Modern RTF now
strips the padding and centres with `\\qc`. STRENGTH.WS's title, byline and
email are the worked example.

Both rules run off ONE document-wide classification (`_classify_modern_
blocks`) -- the same call, and therefore the same verdicts, emit_html
makes. Printed RTF is untouched: a facsimile's rows are already where the
author put them.
"""
import pytest

from ctrlkd import core, emit


def _doc(texts, align='left'):
    return core.Document(
        blocks=[core.Block('para', align=align, lines=[
            core.Line(spans=[core.Span(t)]) for t in texts])],
        meta={'variant': 'ws5+'})


# ------------------------------------------------------- C3: hanging rows

def test_a_definition_row_hangs_at_the_ruled_body_column():
    """72pt = 1440 twips: `\\li1440` with `\\fi-1440`."""
    out = emit.emit_rtf(_doc(['WS.EXE:  the program itself',
                              'WSMSGS.OVR:  its message overlay']),
                        mode='modern')
    assert r'\fi-1440 ' in out and r'\li1440 ' in out


def test_a_definition_row_is_rewritten_label_gap_body():
    """The author's own column padding goes; a two-space gap replaces it --
    `pdf._modern_def_runs`' rule, and what HTML's <dt>/<dd> already does."""
    out = emit.emit_rtf(_doc(['WS.EXE:        the program',
                              'WSMSGS.OVR:    its overlay']), mode='modern')
    assert '{WS.EXE:}  {the program}' in out
    assert 'WS.EXE:        ' not in out


def test_the_ladder_steps_four_columns_per_level():
    """Level 1 sits AT the margin; level 2 is 4 print columns (576 twips)
    past it, on top of the hang."""
    out = emit.emit_rtf(_doc(['* one', '* two',
                              '    * nested a', '    * nested b']),
                        mode='modern')
    li_values = sorted({int(v) for v in
                        __import__('re').findall(r'\\li(\d+) ', out)})
    assert li_values[0] < li_values[1]
    assert li_values[1] - li_values[0] == 576


def test_a_bullet_row_hangs_by_its_own_marker():
    """Not a column count: the marker's own measured advance."""
    from ctrlkd.afm import string_width_pt
    from ctrlkd.pdf import MODERN_BODY_PT
    out = emit.emit_rtf(_doc(['* one', '* two']), mode='modern')
    want = int(round(string_width_pt('* ', 'Times-Roman', MODERN_BODY_PT) * 20))
    assert (r'\fi-%d ' % want) in out and (r'\li%d ' % want) in out


def test_a_bullet_row_keeps_its_marker():
    """The marker is what hangs, so it stays in the text (unlike HTML,
    which hands the bullet itself to `<ul>`)."""
    out = emit.emit_rtf(_doc(['* one', '* two']), mode='modern')
    assert '{* one}' in out


def test_printed_rtf_is_untouched():
    out = emit.emit_rtf(_doc(['WS.EXE:  the program',
                              'WSMSGS.OVR:  its overlay']), mode='printed')
    assert r'\fi-1440' not in out
    assert 'WS.EXE:  the program' in out


# --------------------------------------------------- C4: typed centring

def test_a_spaces_centred_row_is_centred_and_stripped():
    rows = ['x' * 60,
            'y' * 60,
            'z' * 60,
            '                         A Centred Title',
            'w' * 60]
    out = emit.emit_rtf(_doc(rows), mode='modern')
    assert r'\qc ' in out
    assert '{A Centred Title}' in out
    assert '   A Centred Title' not in out


def test_a_spaces_centred_row_gets_the_tight_line():
    """Same "wrapped centered unit" spacing the tag-centred rows already
    take (round 20, slate item 4) -- one named constant, both paths."""
    rows = ['x' * 60, 'y' * 60, 'z' * 60,
            '                         A Centred Title', 'w' * 60]
    out = emit.emit_rtf(_doc(rows), mode='modern')
    assert (r'\sl%d\slmult0 ' % emit._rtf_verse_tight_sl_twips()) in out


def test_an_ordinary_indented_paragraph_is_not_centred():
    """The document's own routine first-line indent is excluded by the
    classifier (`body_indent`), and must stay a paragraph indent."""
    rows = ['     ' + 'x' * 55, '     ' + 'y' * 55, '     ' + 'z' * 55,
            '     ' + 'w' * 55]
    out = emit.emit_rtf(_doc(rows), mode='modern')
    assert r'\qc ' not in out


# ------------------------------------------------------- the HTML half

def test_the_stylesheet_carries_the_same_ladder():
    out = emit.emit_html(_doc(['* one', '* two']), mode='modern')
    assert 'ul{margin:0 0 1em;padding-left:0.40in}' in out
    assert 'dd{margin:0 0 0 1.00in}' in out


def test_a_document_with_no_list_pays_no_css_for_one():
    out = emit.emit_html(_doc(['just a plain paragraph of prose']),
                         mode='modern')
    assert 'dd{margin' not in out


def test_the_css_reads_the_engines_own_constants():
    from ctrlkd.pdf import MODERN_LEVEL_STEP_COLS, MODERN_DEF_HANG_PT
    css = emit._list_css()
    assert 'padding-left:%.2fin' % (MODERN_LEVEL_STEP_COLS * 0.1) in css
    assert 'margin:0 0 0 %.2fin' % (MODERN_DEF_HANG_PT / 72.0) in css


# ---------------------------------------------------- the real corpus (tier 2)

@pytest.mark.sawyer
def test_strength_centres_its_title_byline_and_email(require_sawyer_doc):
    """The packet's worked example: "three rows that have never sat where
    their author put them". Before, the title carried `\\fi3456` and the
    byline `\\fi3312` with a literal 23-space run before the email."""
    with open(require_sawyer_doc('STRENGTH.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    out = emit.emit_rtf(doc, mode='modern')
    assert r'\qc ' in out
    assert r'\fi3456' not in out and r'\fi3312' not in out
    assert '{sawyer@sfwriter.com}\\par' in out
    assert '{                       }' not in out


@pytest.mark.sawyer
def test_strength_bullets_hang(require_sawyer_doc):
    with open(require_sawyer_doc('STRENGTH.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    out = emit.emit_rtf(doc, mode='modern')
    import re
    fis = {int(v) for v in re.findall(r'\\fi-(\d+) ', out)}
    assert fis, 'no hanging indent anywhere'


@pytest.mark.sawyer
def test_readme_definition_rows_hang(require_sawyer_doc):
    with open(require_sawyer_doc('-README.WS (root)'), 'rb') as fh:
        doc = core.parse(fh.read())
    out = emit.emit_rtf(doc, mode='modern')
    assert r'\fi-1440 ' in out and r'\li1440 ' in out
