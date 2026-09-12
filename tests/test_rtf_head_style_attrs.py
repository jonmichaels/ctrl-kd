"""planning #264 item 5: the head's OWN print attributes reach the RTF
header and footer groups.

THE DEFECT. A `.h#`/`.f#` argument can name a style-sheet entry, and that
entry's own bold/italic/underline belong to every run on the line -- exactly
the way a body paragraph's `style_attrs` do. Core has parsed them since
planning #255 (`Document.header_style_attrs`/`footer_style_attrs`, plus the
`_parity` siblings for a two-sided template) and the PDF has drawn them
since then (`_hf_natural_width_pt`'s own `styles | style_attrs`). RTF read
only the line's INLINE toggle bytes, so a head whose weight came from its
style printed light.

The archive's galley template is the worked example, and it carries no
toggle byte at all -- both its `.h1o` and its `.h1e` declare a bold style:

  before  {\\headerr \\pard\\plain \\qr\\f0\\fs22 {TITLE \\u8226? {\\chpgn }}\\par}
  after   {\\headerr \\pard\\plain \\qr\\f0\\fs22 {\\b TITLE \\u8226? {\\chpgn }}\\par}

Per LINE and per PARITY, the same "parity wins, plain is the fallback" rule
`_hf_attr` already applies to the head's face and its alignment.
"""
import pytest

from ctrlkd import core, emit


def _doc(events, parities, attrs=None):
    """`attrs`: {(which, line_no, parity): frozenset(...)} -- `which` is
    'header'/'footer', `parity` None for a plain (both-sides) declaration."""
    doc = core.Document(
        blocks=[core.Block('para', lines=[core.Line(spans=[core.Span('body')])])],
        meta={'variant': 'ws5+', 'page': {}})
    doc.hf_events = list(events)
    doc.hf_events_parity = list(parities)
    for kind, lno, txt, _anchor in events:
        (doc.headers if kind == 'H' else doc.footers)[lno] = txt
    for (which, lno, parity), value in (attrs or {}).items():
        if parity is None:
            getattr(doc, '%s_style_attrs' % which)[lno] = value
        else:
            getattr(doc, '%s_style_attrs_parity' % which).setdefault(
                lno, {})[parity] = value
    return doc


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_heads_own_bold_reaches_the_header_group(mode):
    out = emit.emit_rtf(
        _doc([('H', 1, 'TITLE', 0)], [None],
             attrs={('header', 1, None): frozenset({'b'})}), mode=mode)
    assert r'{\b TITLE}' in out


@pytest.mark.parametrize('attr,ctl', [('b', r'\b '), ('i', r'\i '),
                                      ('u', r'\ul ')])
def test_every_attribute_the_style_can_declare(attr, ctl):
    """Not just bold: the whole `style_attrs` set maps through the same
    `_RTF_ON` table a body run uses."""
    out = emit.emit_rtf(_doc([('H', 1, 'TITLE', 0)], [None],
                             attrs={('header', 1, None): frozenset({attr})}))
    assert ('{%sTITLE}' % ctl) in out


def test_a_footer_takes_the_same_treatment():
    out = emit.emit_rtf(_doc([('F', 1, 'FOOT', 0)], [None],
                             attrs={('footer', 1, None): frozenset({'b'})}))
    assert r'{\footer ' in out and r'{\b FOOT}' in out


def test_the_attributes_are_per_parity():
    """A two-sided template can declare a different style on each side, and
    a parity that names none does not inherit the other side's."""
    out = emit.emit_rtf(
        _doc([('H', 1, 'ODD', 0), ('H', 1, 'EVEN', 0)], ['O', 'E'],
             attrs={('header', 1, 'O'): frozenset({'b'})}))
    assert r'{\b ODD}' in out
    assert '{EVEN}' in out


def test_the_attributes_are_per_line():
    """A two-line head styles each line on its own."""
    out = emit.emit_rtf(
        _doc([('H', 1, 'FIRST', 0), ('H', 2, 'SECOND', 0)], [None, None],
             attrs={('header', 2, None): frozenset({'b'})}))
    assert '{FIRST}' in out
    assert r'{\b SECOND}' in out


def test_a_style_attribute_merges_with_an_inline_toggle():
    """The style's set is ORed into each run's own, so an italic toggle
    inside a bold-styled head comes out bold-italic -- and the run the
    toggle does not cover stays merely bold. 0x19 is WordStar's italic
    toggle (`hf_runs`' own `_HF_TOGGLES` table)."""
    out = emit.emit_rtf(
        _doc([('H', 1, 'PLAIN\x19ITAL\x19', 0)], [None],
             attrs={('header', 1, None): frozenset({'b'})}))
    assert r'{\b PLAIN}' in out
    assert r'{\b \i ITAL}' in out


def test_a_head_that_declares_no_style_is_byte_identical():
    """The overwhelming majority of documents: absence must add nothing."""
    assert (emit.emit_rtf(_doc([('H', 1, 'TITLE', 0)], [None]))
            == emit.emit_rtf(_doc([('H', 1, 'TITLE', 0)], [None], attrs={})))


def test_the_automatic_page_number_footer_carries_no_style():
    """WordStar's own stock automatic number is not a declared footer and
    has no style sheet behind it, so nothing here reaches it."""
    out = emit.emit_rtf(_doc([('H', 1, 'TITLE', 0)], [None],
                             attrs={('header', 1, None): frozenset({'b'})}))
    assert r'{\footer \pard\plain \qc\f0\fs22 {\chpgn }\par}' in out


# --------------------------------------------------- the real corpus (tier 2)

@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_galleys_heads_are_bold_on_both_sides(require_sawyer_doc, mode):
    """The worked example. Both variants declare a bold style and neither
    carries a toggle byte, so before this change both printed light."""
    with open(require_sawyer_doc('REF/GALLEYS.DOT'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert doc.header_style_attrs_parity[1] == {'O': frozenset({'b'}),
                                                'E': frozenset({'b'})}
    out = emit.emit_rtf(doc, mode=mode)
    assert r'{\b TITLE ' in out
    assert '\\u8226? ROBERT J. SAWYER}' in out
    assert r'{\b {\chpgn } ' in out
