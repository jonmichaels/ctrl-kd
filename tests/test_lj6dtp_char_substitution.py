"""LJ6DTP parity C7: two divergences on pages 2-3, both rooted in the same
`_lj_substitute` character-substitution path.

Page 2 (kerning demo). WS7 types the identical `` `` `` / `''` pair TWICE,
once under `.kr off` and once under `.kr on`, specifically to demonstrate
that the pair only reads as a proper curly DOUBLE quote when kerned (its own
prose: "we've also added these two pairs to the PDF kerning tables" so the
pair prints "tucked closer together"). `.KR` was already parsed into
`state['kerning']` (core.py's `_parse_format_dot`, register C20) but nothing
downstream ever consumed it -- both examples fell through `_lj_substitute`
identically and rendered as two loose single curly quotes, showing nothing.

Fix: `.KR` is STATEFUL exactly like `.lh` (core.Line.lead_48's own
precedent) -- `close_line()` now captures `fmt.get('kerning', True)` onto
`core.Line.kerning`, threaded through `pdf.PageLine.kerning` into
`_line_ops_printed`'s `kerning` parameter and finally into
`_lj_substitute`. When kerning is on, the two SUBSTITUTED pairs ('single
open quote doubled' / 'single close quote doubled') collapse to the real
Unicode double curly quote -- the same visual result the kerned pair makes
on paper (measured against LJ6DTP-p2.png) -- without inventing an arbitrary
sub-glyph kern amount. Kerning off is unchanged from plain substitution.

Page 3 (rounded box corners). LJ6DTP's Univers-only substitution turns the
card-suit control chars ♥♦♣♠ into box-drawing corners for its own symbol
chart -- real WS7 draws these with a quarter-circle JOIN, not BOX_ARMS's
sharp right angle (its own chart literally labels them "upper-left ROUNDED
box corner (Univers only)", etc). `_LJ_SUBST_UNIVERS` used to map them onto
plain ┌┐└┘, which `_graphic_ops` draws as two rectangles meeting square.

Fix: the substitution now targets four NEW characters (╭╮╰╯, the standard
Unicode box-drawing ARC glyphs) that a new `pdf.ARC_CORNERS` table -- kept
deliberately separate from `BOX_ARMS`, never overlapping it -- renders as a
single stroked path: a short stub each direction, joined by a quarter-circle
Bezier. A REAL box-drawing ┌┐└┘, typed literally elsewhere in the document
(page 4's checkerboard, page 5's table), never touches this table and stays
exactly as square as before.
"""
import pytest

from ctrlkd import core, pdf

HARD = b'\x0d\x0a'

_UNIVERS = {'proportional': True, 'typestyle_name': 'Univers (also Zurich)'}
_TIMES = {'proportional': True, 'typestyle_name': 'Times New Roman'}


def _find_line(doc, needle):
    for block in doc.blocks:
        for line in getattr(block, 'lines', []):
            if needle in ''.join(s.text for s in line.spans):
                return line
    raise AssertionError(f'{needle!r} not found')


# --------------------------------------------------------- .KR state threading

def test_kr_dot_command_threads_into_line_kerning():
    """core.Line.kerning tracks `.KR` STATEFULLY, the same way Line.lead_48
    tracks `.lh` -- default True (WordStar's own stated default) until a
    `.kr off`/`.kr on` line changes it, and every later line keeps whatever
    was last in force."""
    data = (b'Opening paragraph with no explicit kr command anywhere yet.'
            + HARD +
            b'.kr off' + HARD +
            b'Loose line sits here under kerning turned off explicitly.'
            + HARD +
            b'.kr on' + HARD +
            b'Tight line sits here under kerning turned back on again.'
            + HARD)
    doc = core.parse_ws(data)
    assert _find_line(doc, 'Opening paragraph').kerning is True
    assert _find_line(doc, 'Loose line').kerning is False
    assert _find_line(doc, 'Tight line').kerning is True


def test_pageline_carries_kerning_from_core_line():
    """`_doc_to_pagelines` (the printed layout loop) reads Line.kerning onto
    the PageLine it builds -- the plumbing `_line_ops_printed` needs to see
    the state at all; furniture lines (no source Line) default True."""
    data = (b'.kr off' + HARD +
            b'Under kerning off this whole paragraph should read that way.'
            + HARD)
    doc = core.parse_ws(data)
    pages = pdf._doc_to_pagelines(doc, printed=True)
    found = [pl for page in pages for pl in page
             if any('Under kerning off' in t for t, _ in pl)]
    assert found and found[0].kerning is False


# --------------------------------------------------------- _lj_substitute

def test_lj_substitute_leaves_pairs_loose_when_kerning_off():
    segs = [("``These are too loose.''", frozenset(), 'Times', 12, _TIMES)]
    out = pdf._lj_substitute(segs, kerning=False)
    assert out[0][0] == '\u2018\u2018These are too loose.\u2019\u2019'


def test_lj_substitute_collapses_pairs_to_real_double_quotes_when_kerning_on():
    segs = [("``These are just right.''", frozenset(), 'Times', 12, _TIMES)]
    out = pdf._lj_substitute(segs, kerning=True)
    assert out[0][0] == '\u201cThese are just right.\u201d'


def test_lj_substitute_default_kerning_matches_documents_own_default():
    """WordStar's own prose: "kerning is on, which is the default" --
    calling `_lj_substitute` with no explicit `kerning` argument must
    behave as if it were on."""
    segs = [("``x''", frozenset(), 'Times', 12, _TIMES)]
    assert pdf._lj_substitute(segs) == pdf._lj_substitute(segs, kerning=True)


def test_lj_substitute_only_touches_proportional_entries():
    """The gate is unchanged by this fix: a fixed-pitch entry (or no font
    block at all) never gets substituted, kerning state notwithstanding."""
    fixed = {'proportional': False, 'typestyle_name': 'Courier'}
    segs = [("``x''", frozenset(), 'Courier', 12, fixed)]
    assert pdf._lj_substitute(segs, kerning=True)[0][0] == "``x''"


@pytest.mark.sawyer
def test_lj6dtp_document_kerning_lines_render_differently(require_sawyer_doc):
    """End-to-end: the real LJ6DTP.WS document's own two demo lines must
    reach the PDF content stream with genuinely different text -- the bug
    this whole register exists for ("both examples come out identically").

    Tier 2 (sawyer): LJ6DTP.WS, one of the ten committed manifest documents
    (tests/SAWYER-CORPUS.md)."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    loose = _find_line(doc, 'too loose because kerning is turned off')
    tight = _find_line(doc, 'just right because kerning is turned on')
    assert loose.kerning is False
    assert tight.kerning is True
    out = pdf.emit_pdf(doc, mode='printed')
    # cp1252: single open/close 0x91/0x92 (loose, unchanged: the pair stays
    # two separate glyphs), real double open/close 0x93/0x94 (tight, the
    # fix: the pair collapses to one) -- see _esc's own declared
    # /WinAnsiEncoding. Each word is its own Tj piece (proportional layout,
    # `_line_ops_printed`), so the opening pair sits at the head of the
    # first word's own parenthesized string.
    assert b'(\x91\x91These) Tj' in out
    assert b'(\x93But) Tj' in out


# --------------------------------------------------------- rounded corners

def test_univers_substitution_targets_arc_corners_not_box_arms():
    """The Univers table must land on the NEW arc characters, never on the
    plain box-drawing set a real (literally-typed) box border also uses --
    otherwise a genuine ┌┐└┘ elsewhere in the document would round too."""
    mapped = '♥♦♣♠'.translate(pdf._LJ_SUBST_UNIVERS)
    assert mapped == '\u256d\u256e\u2570\u256f'          # ╭╮╰╯
    assert set(mapped) <= set(pdf.ARC_CORNERS)
    assert not (set(mapped) & set(pdf.BOX_ARMS))
    assert not (set('┌┐└┘') & set(pdf.ARC_CORNERS))


def test_arc_corners_cover_all_four_orientations():
    assert pdf.ARC_CORNERS == {
        '\u256d': ('down', 'right'),
        '\u256e': ('down', 'left'),
        '\u2570': ('up', 'right'),
        '\u256f': ('up', 'left'),
    }


def test_graphic_ops_draws_a_stroked_arc_for_rounded_corners():
    ops = pdf._graphic_ops('\u256d', 0.0, 100.0, 12.0, 12.0)
    joined = b'\n'.join(ops)
    assert b' c' in joined or joined.endswith(b'c')      # a bezier curve op
    assert b'S' in joined                                # stroked, not filled
    assert b're f' not in joined


def test_graphic_ops_leaves_real_box_corners_square():
    """Regression guard: an ORDINARY typed ┌ (real box borders, page 4/5)
    must keep drawing as two filled rectangles meeting square -- the arc
    path must never accidentally catch BOX_ARMS's own characters."""
    ops = pdf._graphic_ops('┌', 0.0, 100.0, 12.0, 12.0)
    joined = b'\n'.join(ops)
    assert b're f' in joined
    assert b' c' not in joined
    assert b' S' not in joined and not joined.rstrip().endswith(b'S')
