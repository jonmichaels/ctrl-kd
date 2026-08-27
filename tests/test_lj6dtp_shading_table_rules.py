"""LJ6DTP parity C11: the thin rules above "Black" and below "White" on
page 5 are NOT a parity defect -- they are genuine typed content.

The reported symptom: our render draws a thin horizontal rule bounding the
"Color Mappings" shading table (above the first "Black" row, below the
last "White" row) and the claim was that WS7 draws neither. Measured
against the real ground truth (ws7-prints/gpcl6-renders/LJ6DTP-p5.png):
WS7 draws BOTH rules, in the same place ours does. The premise does not
hold for this document.

Root cause, traced to the actual bytes: LJ6DTP.WS types a run of ~40
repeated cp437 0xC4 characters (wrapped `<1B C4 1C>` triples -- box-
drawing '─', HORIZONTAL LINE) immediately before "Black" and again
immediately after "White", each its own font block. `core.parse_ws`
decodes each run as one Line whose only Span is a string of '─'
characters (see the block below "Color Mappings", first and last lines);
`pdf._graphic_ops`'s existing BOX_ARMS renderer already draws a run of
'─' as a thin horizontal vector rule, same as it draws any other
box-drawing character. There is no synthetic table-bounding code in this
engine at all -- the "rules" are the document's own typed characters,
read and drawn like any other content.

(Incidentally, while tracing this, position-checking the rule against the
label text below it surfaced a REAL, separate divergence: this whole
block sits under a `.po 1.8i` page-offset change, and `core.py` currently
treats `.po` as a first-occurrence-wins page-geometry constant rather
than a stateful, re-appliable command like `.lm`/`.kr` -- the document
changes `.po` five times (.7", 2.5", .7i, 1.8i, .7i). That is a distinct,
unscoped defect (out of this round's five classes) and is deliberately
NOT touched here; reported alongside this finding for Jon's awareness,
not fixed.)
"""
import pytest

from ctrlkd import core, pdf


def _shading_table_block(doc):
    for b in doc.blocks:
        lines = getattr(b, 'lines', [])
        texts = [''.join(s.text for s in ln.spans) for ln in lines]
        if any('Black' in t for t in texts) and any('White' in t for t in texts):
            return lines
    raise AssertionError('shading table block not found')


@pytest.mark.sawyer
def test_bounding_rules_are_literal_typed_rule_characters(require_sawyer_doc):
    """The FIRST and LAST lines of the shading-table block are pure runs
    of '─' (box-drawing horizontal line) -- real typed content, not a
    synthetic decoration this engine invented.

    Tier 2 (sawyer): LJ6DTP.WS, one of the ten committed manifest documents
    (tests/SAWYER-CORPUS.md)."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    lines = _shading_table_block(doc)
    top_rule = ''.join(s.text for s in lines[0].spans)
    bottom_rule = ''.join(s.text for s in lines[-1].spans)
    assert top_rule and set(top_rule) == {'─'}
    assert bottom_rule and set(bottom_rule) == {'─'}
    assert len(top_rule) > 30 and len(bottom_rule) > 30


def test_box_arms_renders_a_run_of_rule_characters_as_a_thin_line():
    """The renderer's own general box-drawing path (BOX_ARMS, shared with
    every other box character) is what draws these -- no table-specific
    bounding-rule code exists to remove."""
    ops = pdf._graphic_ops('─' * 10, 0.0, 100.0, 7.2, 12.0)
    joined = b'\n'.join(ops)
    assert b're f' in joined                    # BOX_ARMS's own fill path
    assert b' c' not in joined                   # not an arc corner
    assert b'S' not in joined                    # not a stroked path either
