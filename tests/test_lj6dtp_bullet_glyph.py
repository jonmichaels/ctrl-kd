"""LJ6DTP parity C9: the Features list (page 1) must draw a real round
bullet, not a middle dot.

Root cause: `core.parse_ws` already decodes the list marker correctly --
cp437 0x07 (WordStar's own control-position glyph, wrapped `<1B 07 1C>` in
the raw bytes) becomes U+2022 BULLET via `CP437_GRAPHICS`, exactly the
glyph LJ6DTP-p1.png shows. The defect was downstream, in `pdf._esc`'s own
`_ESC_FALLBACK` table: it mapped '•' (U+2022 BULLET) to the SAME target as
its lookalike '∙' (U+2219 BULLET OPERATOR, a math symbol) -- '·' (U+00B7
MIDDLE DOT). '∙' genuinely needs a fallback (cp1252 has no glyph for it at
all); '•' does not -- cp1252 carries a real bullet at 0x95, the same one
every base-14 face's own /WinAnsiEncoding already exposes. Removing '•'
from the fallback table is the whole fix.

The SECOND half of the reported defect -- the gap between the bullet and
the following word reads tighter than the reference -- traces to the
degraded-tab machinery (`core._tab_columns`/`_split_indent`, off limits
for this round per Jon's own note): the source's second `.tb`-derived tab
block (between the bullet and "proper") decodes to a single space
character, then renders at the PROPORTIONAL face's own natural (narrow)
space advance because it falls on the "interior whitespace" side of the
leading/interior split (_line_ops_printed's own documented rule) -- the
bullet itself already counts as real text. Measured against
LJ6DTP-p1.png at 300dpi (page-border left edge pixel-identical in both
renders, so directly comparable): the bullet's OWN indent from the body
margin is already close (ours 87px / ref 95px at 300dpi -- a font-metrics-
level difference, not a defect), but the bullet-to-text gap is ours 16px
vs the reference's 44px. Left untouched, as instructed, since it lives in
the tab-degradation code this round must not touch.
"""
import pytest

from ctrlkd import core, pdf


def _find_line(doc, needle):
    for block in doc.blocks:
        for line in getattr(block, 'lines', []):
            if needle in ''.join(s.text for s in line.spans):
                return line
    raise AssertionError(f'{needle!r} not found')


def test_esc_keeps_the_real_bullet_undowngraded():
    """'•' (U+2022) is genuinely cp1252-encodable (0x95) -- _esc must emit
    it as itself, not fall back to the middle dot."""
    assert pdf._esc('•') == b'\x95'


def test_esc_still_downgrades_the_math_bullet_operator():
    """'∙' (U+2219 BULLET OPERATOR) has no cp1252 code point at all --
    THIS is the character the fallback table exists for, and must keep
    falling back to the middle dot."""
    assert pdf._esc('∙') == b'\xb7'


def test_esc_fallback_table_no_longer_lists_the_real_bullet():
    assert '•' not in pdf._ESC_FALLBACK
    assert ord('∙') in pdf._ESC_FALLBACK          # str.maketrans keys are ordinals


@pytest.mark.sawyer
def test_lj6dtp_features_list_parses_a_real_bullet_character(require_sawyer_doc):
    """Tier 2 (sawyer): LJ6DTP.WS, one of the ten committed manifest
    documents (tests/SAWYER-CORPUS.md)."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    line = _find_line(doc, 'proper quotation marks')
    assert '•' in line.text()                 # the parser's own job,
                                                     # unaffected by this fix


@pytest.mark.sawyer
def test_lj6dtp_features_list_renders_a_real_bullet_not_a_middle_dot(require_sawyer_doc):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    out = pdf.emit_pdf(doc, mode='printed')
    assert b'(\x95) Tj' in out                      # the fix
    assert b'(\xb7) Tj' not in out                  # the bug, named directly
