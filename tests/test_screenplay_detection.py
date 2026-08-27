"""Round 20b (slate item 13): screenplay preservation, the detection
half. core.detect_screenplay_blocks anchors on a genuine INT./EXT.
slugline (case-sensitive, optional scene number, optional WordStar
merge-var scene marker) and grows the region forward to cover the
scene's own action/character/dialogue/parenthetical content, stopping at
the next slugline, a heading, a pagebreak/condpage, or a generous block
cap.

ACCEPTANCE (Jon's own framing, non-negotiable): "The zero-false-positive
corpus gate is acceptance, not garnish -- if the heuristic can't clear
it, report the failure shape honestly rather than loosening the gate."
`test_corpus_wide_zero_false_positives` is that gate; the synthetic tests
below pin the mechanism without it.

NARROWED 2026-08-26 (Jon's ruling, tier 2/sawyer): this gate used to glob
every `.WS` in the whole real archive (~86 files at the time). Tier 2 tests
an explicit, committed doc list only, never a directory sweep -- see
tests/SAWYER-CORPUS.md. The gate is now: every OTHER document in the
committed manifest (the ten in sawyer_manifest.json, minus SCRIPT.WS
itself, minus WORDSTAR.PIX which isn't a WordStar document at all) must
show zero detected screenplay blocks, and SCRIPT.WS must show some. This is
a real reduction in exhaustiveness (9 documents, not ~86) -- traded
deliberately for zero private-directory-shape leakage into this public
repo, per the ruling.
"""
import pytest

from ctrlkd import core

HARD = b'\x0d\x0a'


def _ws_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


# ============================================================== synthetic

def test_no_slugline_no_region():
    data = b'Just an ordinary paragraph of prose, nothing screenplay-shaped.\r\n'
    doc = core.parse_ws(data)
    assert core.detect_screenplay_blocks(doc) == frozenset()


def test_bare_int_slugline_detected():
    data = b"INT. HOUSE - DAY\r\n\r\nSome action description here.\r\n"
    doc = core.parse_ws(data)
    region = core.detect_screenplay_blocks(doc)
    assert 0 in region


def test_bare_ext_slugline_detected():
    data = b"EXT. STREET - NIGHT\r\n\r\nRain falls.\r\n"
    doc = core.parse_ws(data)
    region = core.detect_screenplay_blocks(doc)
    assert 0 in region


def test_scene_numbered_slugline_detected():
    data = b"12    INT. HOUSE - DAY                                        12\r\n"
    doc = core.parse_ws(data)
    assert 0 in core.detect_screenplay_blocks(doc)


def test_merge_var_anchored_slugline_detected():
    # WordStar merge-var scene marker (&n/s&) immediately before the
    # slugline -- slate's own named "merge-var scene markers" signal.
    data = b"&n/s& INT. WRITER'S OFFICE - DAY\r\n"
    doc = core.parse_ws(data)
    assert 0 in core.detect_screenplay_blocks(doc)


def test_lowercase_int_is_not_a_slugline():
    # case-sensitive by design -- "int." is a plausible real abbreviation
    # in ordinary prose ("this is an int. value") and must NEVER match.
    data = b'This function returns an int. Not a big deal.\r\n'
    doc = core.parse_ws(data)
    assert core.detect_screenplay_blocks(doc) == frozenset()


def test_int_mid_word_is_not_a_slugline():
    data = b'This is an INTERESTING sentence about EXTRA things.\r\n'
    doc = core.parse_ws(data)
    assert core.detect_screenplay_blocks(doc) == frozenset()


def test_region_grows_to_include_following_blocks():
    data = (b'INT. HOUSE - DAY\r\n\r\n'
            b'JOHN stares at the door.\r\n\r\n'
            b'                    JOHN\r\n'
            b'          What is that noise?\r\n\r\n')
    doc = core.parse_ws(data)
    region = core.detect_screenplay_blocks(doc)
    assert region == frozenset(range(len(doc.blocks)))


def test_region_stops_at_the_next_slugline():
    data = (b'INT. HOUSE - DAY\r\n\r\n'
            b'Action one.\r\n\r\n'
            b'EXT. STREET - NIGHT\r\n\r\n'
            b'Action two.\r\n\r\n')
    doc = core.parse_ws(data)
    region = core.detect_screenplay_blocks(doc)
    # both sluglines anchor their own region -- every block still ends
    # up covered, but via TWO scenes, not one that swallowed the second
    # slugline's own action line into scene one's growth silently
    slug_bi = [bi for bi, b in enumerate(doc.blocks) if core._block_has_slugline(b)]
    assert len(slug_bi) == 2
    assert region == frozenset(range(len(doc.blocks)))


def test_region_stops_at_a_pagebreak():
    block = _ws_block(0x0C)          # symmetric pagebreak marker (DOT_PAGEBREAK-equivalent)
    data = (b'INT. HOUSE - DAY\r\n\r\n'
            b'Action one.\r\n\r\n.pa\r\n'
            b'Unrelated content after the page break.\r\n')
    doc = core.parse_ws(data)
    region = core.detect_screenplay_blocks(doc)
    pb_indices = [bi for bi, b in enumerate(doc.blocks) if b.kind == 'pagebreak']
    assert pb_indices, 'fixture did not produce a pagebreak block'
    assert all(bi < pb_indices[0] for bi in region)


def test_region_stops_at_a_heading():
    # Constructing a REAL style-library-resolved heading is more
    # machinery than this stopping-condition test needs -- the heading
    # detector itself is already covered elsewhere; this only proves
    # detect_screenplay_blocks's own region-growth loop respects
    # `b.heading` once set, whatever set it.
    data = (b"INT. HOUSE - DAY\r\n\r\n"
            b'Action one.\r\n\r\n'
            b'A Real Section Heading\r\n\r\n'
            b'Unrelated article prose that follows the heading.\r\n')
    doc = core.parse_ws(data)
    heading_bi = next(bi for bi, b in enumerate(doc.blocks)
                      if 'Real Section Heading' in ''.join(
                          s.text for line in b.lines for s in line.spans))
    doc.blocks[heading_bi].heading = 1
    region = core.detect_screenplay_blocks(doc)
    assert all(bi < heading_bi for bi in region)


# =================================================== real-corpus acceptance

# The nine committed manifest documents (sawyer_manifest.json) that are
# actual WordStar documents and are NOT SCRIPT.WS itself -- WORDSTAR.PIX is
# an Inset image, not a WordStar document, so it's excluded here.
_NON_SCRIPT_MANIFEST_DOCS = [
    'RJS.WS', 'CONVERT.WS', 'LJ6DTP.WS', 'PREVIEW.WS', '-SCREEN.WS',
    '-README.WS (root)', '-README.WS (APP)', '-README.WS (APP/vDosPlus)',
]


@pytest.mark.sawyer
def test_corpus_wide_zero_false_positives(require_sawyer_doc):
    """THE acceptance gate (Jon's own words): "if the heuristic can't
    clear it, report the failure shape honestly rather than loosening
    the gate." Of the ten committed tier-2 manifest documents, exactly one
    may trigger detection: SCRIPT.WS, an article about scripting WordStar
    for screenplays with two worked example scenes. Every other manifest
    document -- fiction, articles, reference material, printer drivers --
    must show zero detected blocks.

    NARROWED 2026-08-26 from an 86-file whole-archive sweep to these nine
    -- see this module's docstring."""
    hits = {}
    for name in _NON_SCRIPT_MANIFEST_DOCS:
        path = require_sawyer_doc(name)
        try:
            data = open(path, 'rb').read()
            doc = core.parse(data)
            region = core.detect_screenplay_blocks(doc)
        except Exception as e:
            hits[name] = f'error: {e!r}'
            continue
        if region:
            hits[name] = sorted(region)
    assert not hits, hits


@pytest.mark.sawyer
def test_script_ws_both_scenes_detected(require_sawyer_doc):
    path = require_sawyer_doc('SCRIPT.WS')
    data = open(path, 'rb').read()
    doc = core.parse(data)
    region = core.detect_screenplay_blocks(doc)
    # the "rendered example" scenes (Figure 1 / Figure 2) -- confirmed by
    # direct inspection to be blocks 76-80 and 81-83/84
    assert {76, 77, 78, 79, 80}.issubset(region)
    assert {81, 82, 83}.issubset(region)
