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


# ------------------------------------- planning #260: cited-offset regression pins
#
# Three real, byte-verified spots in the real LJ6DTP.WS (offsets confirmed by direct
# hex inspection, 2026-09-10, alongside the matching real WS7 LaserJet PCL capture
# ws7-prints/v1/LJ6DTP.pcl and Jon's own paper scan of that printout -- see
# tools/pcl_symbol_sets.py's docstring for the PCL-side half of this evidence). These
# were ALREADY correctly handled by `_LJ_SUBST`/`_lj_substitute` before planning #260 --
# these tests exist to LOCK that in against the exact cited bytes/offsets, not to fix a
# new bug in this engine (the bug planning #260 actually found was in the PCL ground-
# truth decoder, tools/pcl_text.py / pcl_render.py, fixed separately).

@pytest.mark.sawyer
def test_lj6dtp_color_heading_quotes_at_offset_0x4859(require_sawyer_doc):
    """Offset 0x4859: `1B AE 1C 43 6F 6C 6F 72 1B AF 1C` -- the extended-character
    triples <ESC><AE><FS> and <ESC><AF><FS> bracketing "Color" in the page-5 "Color
    Mappings" heading. `_LJ_SUBST` maps cp437 '«'(AE)/'»'(AF) -> curly double
    quotes; this heading is Univers (proportional), so the substitution must fire.
    Matches the real WS7 LaserJet capture (ws7-prints/v1/LJ6DTP.pcl, ESC(7J<B0>/<B1>
    bracketing "Color") and the paper scan (curly double quotes, not guillemets)."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        data = fh.read()
    assert data[0x4859 - 3:0x4859 + 8] == b'\x1b\xae\x1cColor\x1b\xaf\x1c', (
        'fixture offset moved -- re-locate before trusting this test')
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='printed')
    # cp1252 0x93/0x94 = curly double open/close (/WinAnsiEncoding, see the kerning
    # test above for the same encoding note).
    assert b'(\x93Color\x94) Tj' in out


@pytest.mark.sawyer
def test_lj6dtp_copyright_cluster_at_offset_0x3da(require_sawyer_doc):
    """Offset 0x3da+20 (right after "Copyright "): a font-change block then
    `1B 02 1C` -- the extended-character triple wrapping cp437 0x02 (☻, the
    smiley WordStar's own PC-8 screen glyph for this slot). `_LJ_SUBST` maps
    '☻' -> '©' (c). This is the title bar's SANS copyright (Univers,
    matching the real capture's `ESC(5M<E3>` sans-serif slot -- see
    tools/pcl_symbol_sets.py's "5M's 0xE3 CORRECTION"); the body-text serif
    occurrences (`ESC(5M<D3>`) go through the same '☻'->'©' substitution
    and are covered implicitly by every other 'copyright' Tj this document emits."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        data = fh.read()
    assert data[0x3da:0x3da + 9] == b'Copyright', (
        'fixture offset moved -- re-locate before trusting this test')
    triple_at = data.index(b'\x1b\x02\x1c', 0x3da)
    assert triple_at - 0x3da < 40, 'the (c) triple should follow "Copyright " closely'
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='printed')
    assert b'(\xa9) Tj' in out  # cp1252 0xa9 == Latin-1 == (c), U+00A9


@pytest.mark.sawyer
def test_lj6dtp_wordstars_apostrophe_curly_on_proportional_face(require_sawyer_doc):
    """"WordStar's" (plain typed apostrophe, 0x27) on a PROPORTIONAL face (Times/
    Univers body text) prints curly -- matching the real WS7 capture, where the
    driver brackets that one byte with `ESC(7J<27>` between two `ESC(10U` runs
    (curly per the DeskTop symbol set's own $27 slot) rather than leaving it under
    plain PC-8 (straight). `_LJ_SUBST` maps plain "'" -> U+2019 for any proportional
    entry, matching this without needing per-symbol-set tracking on the .WS side."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        data = fh.read()
    doc = core.parse_ws(data)
    out = pdf.emit_pdf(doc, mode='printed')
    assert b'(WordStar\x92s)' in out  # cp1252 0x92 == U+2019 RIGHT SINGLE QUOTATION MARK


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
