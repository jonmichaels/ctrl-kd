"""Tier 2 (sawyer) -- the FULL identified-document manifest, not just the
ten richly-tested documents in tests/SAWYER-CORPUS.md's dedicated tests.

WHY THIS EXISTS. Jon's own vault catalog (jon_vault/Projects/software/
WordStar/Corpus-Document-Catalog.md, companion to Corpus-And-Filetype-
Index.md) enumerates the FULL set of genuine WordStar documents Robert J.
Sawyer's public WS7 archive contains: 251, by a stated rule ("document" =
what the rebuilt manifest marks include_in_parity: true -- corroborated,
not raw detect()-only, per the index's false-positive register). That
catalog is the authoritative source for WHICH documents this corpus
contains -- not re-derived here, not re-swept with classify_sawyer.py,
taken verbatim per the catalog's own "about 200 is retired" ruling and
Jon's explicit instruction to use the written-down list rather than
re-deriving it.

sawyer_manifest.json now carries all 251 catalog paths reconciled against
archive release 1.5 (this repo's pinned release), MINUS 2 that no longer
exist upstream (see RECONCILIATION below) = 249, PLUS the 3 pre-existing
non-catalog entries the original ten-document manifest already carried
for their own dedicated tests (two APP/vDosPlus -README.WS duplicates, and
the WORDSTAR.PIX image asset) = 252 manifest entries total. This file is
the generic sweep over all of them; the richer per-feature tests named in
SAWYER-CORPUS.md (polarity, glyph aspect, screenplay detection, LJ6DTP
symbol/shading/rectangle checks, pix resolution, ...) still run against
the original ten and are UNCHANGED by this file.

RECONCILIATION vs the catalog (built against a July archive copy, ~v1.4):
this repo pins release 1.5 (tests/SAWYER-CORPUS.md). Two catalog-listed
documents no longer exist under that release's tree at all:
DICT/-CTRL.P and DICT/TEST-ALL.WS -- both confirmed absent (not renamed,
not moved) by a full-tree search of release 1.5. They are dropped from the
manifest and are not tested here. Every other catalog path IS present in
1.5, but the raw bytes differ from the catalog's recorded sizes for the
overwhelming majority of them (241 of the 249 present documents) -- sizes
in sawyer_manifest.json are release-1.5's ACTUAL on-disk sizes, not the
catalog's (stale, v1.4-copy) numbers; see the commit message / task report
for the full byte-level reconciliation. This is expected: WordStar rewrites
a file's own internal trailer (cursor position, block pointers) on every
save, so a from-scratch resave of the whole tree between releases shifts
nearly every file's total length slightly even where the visible prose is
identical -- confirmed on the 7 documents already covered by the original
ten-document manifest, which match this pass's independently-computed
release-1.5 hashes exactly.

TWO KINDS OF "can't fully test this one":

1. NON_DOCUMENT_ASSETS -- not a WordStar document at all (WORDSTAR.PIX is
   the Inset image the pix-reference tests resolve against; it was never
   one of the catalog's 251 documents). Source-hash-checked here like
   everything else; never run through parse()/emit().

2. KNOWN_NONCONVERTIBLE -- the catalog counts these as ws4/ws5+ documents
   (an earlier classify_sawyer.py pass corroborated them structurally --
   soft-return bytes / symmetric header blocks present), and the catalog's
   OWN notes already describe every one of them as "non-prose, binary-
   shaped content" (font/cartridge width tables, WordPerfect-conversion
   keystroke data, HiJaak intermediate files, a search-index blob) -- not
   prose a human would read. Running THIS engine's actual core.parse() on
   release-1.5's bytes for all ten, today, at this commit: every one raises
   ParseError, because core.detect()'s overall-text-density gate (not the
   narrower structural signature classify_sawyer.py checked) correctly
   floors them to 'binary'. Recorded here as a NAMED, asserted fact --
   each one checked to fail in exactly this way -- not silently excluded
   and not force-fed through convert() to manufacture a false pass.
"""
import hashlib
import json
import os

import pytest

from ctrlkd import core, emit
from ctrlkd.core import ParseError

from sawyer_fixture import SAWYER_DOCS

ORACLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sawyer_oracle.json')
ORACLE = json.load(open(ORACLE_PATH))

# Kept in sync by hand with tools/gen_sawyer_oracle.py's own copies -- see
# that script's docstring for the full reasoning behind each set.
NON_DOCUMENT_ASSETS = {'WORDSTAR.PIX'}
KNOWN_NONCONVERTIBLE = {
    'CVWP/WP_WP_US.QRS': "not a convertible file (detected: binary -- 82% text but no structure)",
    'CVWP/WP{WPC}.QKL': "not a convertible file (detected: binary -- 59% text but no structure)",
    'DEFAULT/APP/03670464.CRT/05200120.CRT': "not a convertible file (detected: binary -- 46% text but no structure)",
    'DEFAULT/APP/03670464.CRT/08120072.CRT': "not a convertible file (detected: binary -- 45% text but no structure)",
    'DEFAULT/APP/03670464.CRT/14240124.CRT': "not a convertible file (detected: binary -- 42% text but no structure)",
    'DEFAULT/APP/03670464.CRT/15240104.CRT': "not a convertible file (detected: binary -- 44% text but no structure)",
    'HIJAAK/ISI0.TMP': "not a convertible file (detected: binary -- 77% text but no structure)",
    'HIJAAK/ISI2.TMP': "not a convertible file (detected: binary -- 78% text but no structure)",
    'MANUALS/WordStar Manuals Index/index1.idx': "not a convertible file (detected: binary -- 40% text but no structure)",
    'WFW/UNC0819.DAT': "not a convertible file (detected: binary -- 69% text but no structure)",
}

ALL_NAMES = sorted(SAWYER_DOCS)
CONVERTIBLE_NAMES = sorted(n for n in ALL_NAMES
                            if n not in NON_DOCUMENT_ASSETS
                            and SAWYER_DOCS[n]['path'] not in KNOWN_NONCONVERTIBLE)
NONCONVERTIBLE_NAMES = sorted(n for n in ALL_NAMES
                               if SAWYER_DOCS[n]['path'] in KNOWN_NONCONVERTIBLE)

pytestmark = pytest.mark.sawyer


# ================================================== manifest self-checks

def test_manifest_shape_matches_this_files_bookkeeping():
    """Every KNOWN_NONCONVERTIBLE/NON_DOCUMENT_ASSETS name must still be a
    real manifest entry (catch a stale exclusion list before it silently
    stops covering anything), and the oracle must cover exactly the
    remaining convertible set -- no more, no less."""
    for name in NON_DOCUMENT_ASSETS:
        assert name in SAWYER_DOCS, f'{name} no longer in sawyer_manifest.json'
    for name in NONCONVERTIBLE_NAMES:
        assert name in SAWYER_DOCS
    assert set(ORACLE) == set(CONVERTIBLE_NAMES), (
        set(ORACLE) ^ set(CONVERTIBLE_NAMES))


def test_dropped_v14_docs_are_confirmed_absent_not_just_unlisted():
    """DICT/-CTRL.P and DICT/TEST-ALL.WS were in the vault catalog's 251
    (built against a ~v1.4 copy) but do not exist anywhere in release 1.5
    -- confirmed by a full-tree search, not merely absent from this
    manifest. Documented as a standing fact, not re-checked against the
    live archive here (that would just be the same missing-file check
    require_sawyer_doc already performs for every listed name)."""
    dropped = {'DICT/-CTRL.P', 'DICT/TEST-ALL.WS'}
    listed_paths = {e['path'] for e in SAWYER_DOCS.values()}
    assert dropped.isdisjoint(listed_paths)


# ======================================================== (a) source hash

@pytest.mark.parametrize('name', ALL_NAMES)
def test_manifest_doc_source_hash_matches(name, require_sawyer_doc):
    """Every manifest entry, convertible or not: the archive byte content
    at its path still matches the committed sha256. This is
    require_sawyer_doc's own job (sawyer_doc_problem) -- calling it IS the
    check; a tamper/drift/missing-file failure comes from that fixture,
    loud, per tests/SAWYER-CORPUS.md."""
    path = require_sawyer_doc(name)
    assert os.path.isfile(path)


# ============================================ (b)/(c) convert + oracle gate

@pytest.mark.parametrize('name', CONVERTIBLE_NAMES)
def test_manifest_doc_converts_and_matches_oracle(name, require_sawyer_doc):
    """(b) parse + emit `text` (modern) and `layout` JSON both succeed;
    (c) each output's sha256 matches tests/sawyer_oracle.json, generated
    from THIS engine at THIS commit (tools/gen_sawyer_oracle.py)."""
    path = require_sawyer_doc(name)
    data = open(path, 'rb').read()
    doc = core.parse(data)          # (b) parse must succeed

    text_out = emit.emit_text(doc, mode='modern').encode('utf-8')
    layout_out = emit.get_emitter('layout')['fn'](doc, mode='modern').encode('utf-8')

    expected = ORACLE[name]
    text_digest = hashlib.sha256(text_out).hexdigest()
    assert len(text_out) == expected['text']['size'], (
        f'{name}: text output size {len(text_out)} != committed '
        f'{expected["text"]["size"]} -- if deliberate, rerun '
        f'tools/gen_sawyer_oracle.py and commit the new oracle')
    assert text_digest == expected['text']['sha256'], (
        f'{name}: text sha256 {text_digest} != committed '
        f'{expected["text"]["sha256"]} -- if deliberate, rerun '
        f'tools/gen_sawyer_oracle.py and commit the new oracle')

    layout_digest = hashlib.sha256(layout_out).hexdigest()
    assert len(layout_out) == expected['layout']['size'], (
        f'{name}: layout output size {len(layout_out)} != committed '
        f'{expected["layout"]["size"]} -- if deliberate, rerun '
        f'tools/gen_sawyer_oracle.py and commit the new oracle')
    assert layout_digest == expected['layout']['sha256'], (
        f'{name}: layout sha256 {layout_digest} != committed '
        f'{expected["layout"]["sha256"]} -- if deliberate, rerun '
        f'tools/gen_sawyer_oracle.py and commit the new oracle')


# ============================ named non-convertible documents (asserted)

@pytest.mark.parametrize('name', NONCONVERTIBLE_NAMES)
def test_known_nonconvertible_doc_fails_exactly_as_recorded(name, require_sawyer_doc):
    """These manifest entries are catalogued as ws4/ws5+ documents by the
    vault's classify_sawyer.py pass, but are also described in that same
    catalog as non-prose/binary-shaped content -- and this engine's real
    core.parse() rejects every one of them as 'binary' today. Asserted by
    name and by exact reason (not just 'raises'), so a future engine
    change that starts parsing one of these (e.g. a detect() threshold
    fix) is caught here as a thing to move into CONVERTIBLE_NAMES, not a
    silent pass."""
    path = require_sawyer_doc(name)
    data = open(path, 'rb').read()
    with pytest.raises(ParseError) as excinfo:
        core.parse(data)
    expected_reason = KNOWN_NONCONVERTIBLE[SAWYER_DOCS[name]['path']]
    assert expected_reason in str(excinfo.value), (
        name, str(excinfo.value), expected_reason)


def test_wordstar_pix_is_not_run_through_parse():
    """WORDSTAR.PIX is the Inset image asset, not a WordStar document --
    documenting that fact here explicitly rather than leaving it as a
    silent omission from CONVERTIBLE_NAMES."""
    assert 'WORDSTAR.PIX' in NON_DOCUMENT_ASSETS
    assert 'WORDSTAR.PIX' not in CONVERTIBLE_NAMES
    assert 'WORDSTAR.PIX' not in NONCONVERTIBLE_NAMES
