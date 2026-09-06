#!/usr/bin/env python3
"""pcl_tolerance.py -- font-class tolerances and the named-divergence report
for the `pcl` pytest tier (tests/test_pcl_fidelity.py).

WHY THIS EXISTS
---------------
tools/fidelity_gate.py computes raw coordinate residuals between our own
Printed PDF and a real WS7 LaserJet capture, but treats every proportional
font the same way. That is too strict: our PDFs use ONLY the PDF base-14
fonts (Jon's ruling, 2026-09-05: "no dependencies -- PDFs that only use
base 14 fonts plus our created Symbol and Zapf Dingbats"), while real WS7
printed with CG Times, Univers, Albertus, Line Printer and other HP-resident
faces. A word-for-word coordinate match is only a meaningful pass/fail
signal once the tolerance accounts for WHICH class of font-substitution
error is expected:

  - fixed-pitch (Courier, and any face WS7 selected via PCL's fixed-pitch
    field) -- our Courier is metrically identical, so this tier is
    checked to (near-)exact equality.
  - CG Times -> Times, Univers -> Helvetica -- these are the two
    substitutions we actually chose as "close enough": the per-word x
    position is allowed a BOUNDED drift that grows with distance into the
    line (more preceding characters means more accumulated width-metric
    error) and resets at every new line (a fresh line starts the
    accumulation over).
  - every other WS7 typeface (Albertus, Garamond Antiqua, Clarendon,
    Antique Olive, CG Omega, Coronet -- collectively "no substitute"
    faces) -- we have no metrically-close base-14 stand-in, so per-word x
    position is not checked at all for these chunks; only the things that
    are layout decisions, not glyph widths, are: the line's start x, its
    baseline y, and its word count.
  - Line starts, baselines, page breaks and page counts are checked to
    (near-)exact equality for EVERY font, substituted or not -- per the
    finalization plan, those are our own pagination/margin logic, not
    glyph metrics.

WHY THE RAW .PCL, NOT MEASUREMENTS.JSON'S OWN 'font' FIELD
------------------------------------------------------------
tools/pcl_render.py already substitutes every WS7 typeface ID down to a
base-14 name before it ever reaches measurements.json's `chunks[].font`
field (see pcl_render.TYPEFACE_FAMILY) -- so from measurements.json alone,
CG Times, Albertus, Garamond, and Clarendon are ALL indistinguishable
("Times"), and Univers/CG Omega/Antique Olive are all "Helvetica". That
collapse happens (correctly) for pcl_render's own PNG-rendering purposes,
but it destroys exactly the distinction this tolerance model needs. So
this module re-parses each doc's own raw .pcl (already captured, already
shipped in the private corpus -- no new data, no corpus write) with
pcl_render.parse_pcl_extended() and reads its internal `_T` field (the
PCL typeface-family ID BEFORE substitution) for each text chunk, in the
same emission order pcl_render used to build measurements.json's own
`chunks` list -- so the two line up index-for-index without re-deriving
or guessing anything. A page whose re-parsed chunk count disagrees with
the committed measurements.json is reported as its own divergence
(`pcl-reparse-mismatch`) rather than silently misaligning.

That re-parse also caught a real bug in pcl_render.py: its TYPEFACE_FAMILY
table's own docstring narrated typeface ID 4148 (Univers) as "kept,
corrected...mapped to Helvetica", but the literal dict entry was missing,
so an unmapped 4148 fell through to the proportional-spacing default
("Times") -- fixed alongside this module (see pcl_render.py's own comment
at that line). LJ6DTP.measurements.json, generated before that fix, still
records Univers chunks as Times-Roman/-Bold; not regenerated here (the
corpus is read-only from this repo) -- flagged for the corpus-
regeneration pass (planning #196). This module's tier lookup uses the raw
typeface ID directly, so it is unaffected by that JSON's stale 'font'
strings either way.

TOLERANCE EVIDENCE (2026-09-05, all 18 v1 captures, 12 with a resolvable
.WS source -- see CAPTURED_DOCS / KNOWN_MISSING_SOURCE_DOCS below)
-------------------------------------------------------------------
Numbers below are from matched same-page word pairs, residual after each
PAGE's own median frame offset (engine vs WS7) is removed -- the same
frame-offset math tools/fidelity_gate.py already performs; this module
only adds the tier lookup and the per-line "distance since line start"
measurement on top of it.

  EXACT tier (fixed-pitch + the two real-Helvetica-match cases; typeface
  IDs {3, 4099, 4}), non-line-start word pairs, n=7095: 94.35% land within
  0.1pt of WS7 (decipoint-quantization noise; 1 decipoint = 0.1pt); the
  next cluster is >5pt away. EXACT_EPS_PT = 0.2 sits just above that
  quantization noise.

  Line starts, ALL tiers combined, n=1184: |residual dx| p90=1.9pt,
  p95=2.35pt, then a heavy tail (p99=116.7pt, max=462.2pt) -- a handful of
  real indent/margin bugs, not quantization. LINE_START_EPS_PT = 2.5
  covers the ordinary case and still catches the tail.

  Baselines (dy), ALL tiers, ALL same-page pairs, n=11876: p50=p90=0.0pt,
  then a real ~12pt cluster from p95 onward (one or more whole lines
  shifted by a line-height in some document) plus larger anomalies up to
  180pt. BASELINE_EPS_PT = 1.0 catches that cluster and any larger one
  while tolerating float rounding.

  CG-Times-substituted (typeface ID 4101) word pairs, non-line-start,
  n=1606, bucketed by distance since line start (pt):
      [0,25)    n=45   p95=3.35   [200,400)  n=670  p95=8.10
      [25,50)   n=95   p95=3.50   [400,+)    n=115  p95=8.35
      [50,100)  n=185  p95=4.10
      [100,200) n=399  p95=5.30
  A linear fit through these (CGTIMES_DRIFT_BASE_PT=3.5,
  CGTIMES_DRIFT_RATE_PT_PER_PT=0.02) sits at or above every bucket's p95
  -- generous enough to absorb ordinary substitution drift at any line
  position while still flagging the bucket outliers (12-58pt) as real
  divergences.

  Univers-substituted (typeface ID 4148) word pairs, non-line-start,
  n=21 (all from LJ6DTP, the only doc that uses Univers in this corpus):
  max residual 2.1pt -- far too little data to fit an independent curve.
  Shares the CG-Times bound (UNIVERS_DRIFT_* = CGTIMES_DRIFT_*), which is
  already generous relative to what little Univers data exists; revisit
  with its own fit once planning #196 captures more Univers-bearing
  documents.

  No-substitute tier (typeface IDs 4362, 4197, 4140, 4168, 4113, 4116):
  word-level x is not evaluated at all (see module docstring) -- the
  residuals ARE large (p50=2.0pt, p95=94.4pt, max=462.2pt, n=3154), which
  is exactly the expected signature of a face with no base-14 metric
  match, not evidence of anything to fix.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fidelity_gate as fg  # noqa: E402
import pcl_render as pr  # noqa: E402

# --------------------------------------------------------------- doc list
# A committed, explicit list -- never a directory sweep -- same convention
# as tests/SAWYER-CORPUS.md's tier-2 manifest. Update this list (and
# regenerate the manifest, see `--record` below) only when planning #196
# adds or removes a v1 capture; this file is the review point for that.
CAPTURED_DOCS = [
    'BOXES', 'DOCA', 'DOCB', 'DOCC', 'DOCD', 'LJ6DTP', 'LYING', 'OCAPTAIN',
    'DOCE', 'PREVIEW', '-README', 'SAWYER', '-SCREEN', 'SCRIPT', 'DOCF',
    'TWAINLET', 'VERSIONS', 'WARPRAYR',
]

# These six captures are real WS7 LaserJet prints of documents whose WS4
# originals live in a separate, personal source archive the vault
# Corpus-Registry documents apart from the three groups this tool
# resolves sources from (sawyer/, pd-samples/authored/, ws7-private/) --
# and whose document names are themselves private per that registry
# (never public, never used as a fixture name). Their ground-truth
# measurements.json/.pcl exist in the private corpus, but this repo has
# nowhere it is allowed to resolve a .WS source from -- so they are named
# here, permanently, as a documented gap rather than silently absent from
# CAPTURED_DOCS. `doc_report()` returns verdict 'source-missing' for
# these; the test skips them BY NAME.
KNOWN_MISSING_SOURCE_DOCS = {'DOCA', 'DOCB', 'DOCC', 'DOCD', 'DOCE', 'DOCF'}

MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'tests', 'pcl_fidelity_manifest.json')

# ------------------------------------------------------------- font tiers
# WS7 PCL typeface-family ID (pcl_render.py's own `_T` field, BEFORE
# base-14 substitution) -> tolerance tier. IDs and identities per
# pcl_render.py's own TYPEFACE_FAMILY/TYPEFACE_FAMILY_SOURCE_NOTE
# (HP "PCL 5 Comparison Guide" citations); tiers per this module's
# docstring and the finalization plan's font-class rule.
TIER_EXACT = 'exact'
TIER_CGTIMES = 'cgtimes'
TIER_UNIVERS = 'univers'
TIER_NO_SUBSTITUTE = 'no_substitute'
TIER_UNKNOWN = 'unknown'

FONT_TIER_BY_TYPEFACE_ID = {
    3: TIER_EXACT,      # Courier, bitmap
    4099: TIER_EXACT,   # Courier, scalable
    4: TIER_EXACT,      # Helvetica, real (unobserved in this corpus) -- no substitution error
    4101: TIER_CGTIMES,      # CG Times -> Times
    4148: TIER_UNIVERS,      # Univers -> Helvetica
    4362: TIER_NO_SUBSTITUTE,  # Albertus
    4197: TIER_NO_SUBSTITUTE,  # Garamond Antiqua
    4140: TIER_NO_SUBSTITUTE,  # Clarendon
    4168: TIER_NO_SUBSTITUTE,  # Antique Olive
    4113: TIER_NO_SUBSTITUTE,  # CG Omega
    4116: TIER_NO_SUBSTITUTE,  # Coronet
}


def tier_for_typeface(tid) -> str:
    if tid is None:
        return TIER_UNKNOWN
    return FONT_TIER_BY_TYPEFACE_ID.get(tid, TIER_UNKNOWN)


# --------------------------------------------------------- tolerances (pt)
# See module docstring "TOLERANCE EVIDENCE" for the data behind every
# number below. ONE constants block, as the finalization plan asks --
# nothing here comes from tools/fidelity_gate.py, and nothing in
# fidelity_gate.py depends on these (that file stays font-tier-agnostic).
EXACT_EPS_PT = 0.2
LINE_START_EPS_PT = 2.5
BASELINE_EPS_PT = 1.0
CGTIMES_DRIFT_BASE_PT = 3.5
CGTIMES_DRIFT_RATE_PT_PER_PT = 0.02
# Shared with CG Times -- see docstring, too little independent Univers
# data (n=21) to fit its own curve yet.
UNIVERS_DRIFT_BASE_PT = CGTIMES_DRIFT_BASE_PT
UNIVERS_DRIFT_RATE_PT_PER_PT = CGTIMES_DRIFT_RATE_PT_PER_PT


def cgtimes_tolerance_pt(dist_into_line_pt: float) -> float:
    return CGTIMES_DRIFT_BASE_PT + CGTIMES_DRIFT_RATE_PT_PER_PT * dist_into_line_pt


def univers_tolerance_pt(dist_into_line_pt: float) -> float:
    return UNIVERS_DRIFT_BASE_PT + UNIVERS_DRIFT_RATE_PT_PER_PT * dist_into_line_pt


# Divergence entries are capped per (doc, reason) in the checked-in
# manifest so it stays reviewable -- `counts_by_reason` is always the
# EXACT total regardless of the cap (see doc_report()'s docstring).
MAX_LISTED_PER_REASON = 40


# --------------------------------------------------------- WS7 token load
# WS7's own driver prints box/rule/shading characters (IBM CP437's box-
# drawing set, table borders, solid-block fills) as real printer-font TEXT
# glyphs -- pcl_render.py's own `text = bytes(...).decode("cp437", ...)`
# confirms the raw .pcl really does carry them as printable characters,
# one WS7 "chunk" per contiguous run. Our engine, since the PDF base-14
# fonts have no box-drawing glyphs at all (Jon's base-14-only ruling, see
# module docstring), draws the SAME boxes/rules as PDF vector rectangles
# (pdf.py emits `X Y W H re f`), never as text runs -- confirmed by
# reading BOXES's own rendered content stream (2026-09-05 check: its box
# borders are 100% `re f` operators, zero corresponding text ops). A pure
# box/rule/shading WS7 chunk therefore has NO text-run counterpart to
# align to at all, by design on our side, not a placement bug -- so it is
# excluded from word-matching entirely here, the same way this module
# already treats no-substitute-tier word position as out of this check's
# scope. (Table/rectangle fidelity has its own dedicated tests --
# tests/test_lj6dtp_pcl_rectangles.py and siblings -- this coordinate gate
# is text-only by construction, see fidelity_gate.py's own docstring.)
_BOX_DRAWING_RANGES = (
    (0x2500, 0x2580),  # Box Drawing
    (0x2580, 0x25A0),  # Block Elements
    (0x25A0, 0x2600),  # Geometric Shapes
)


def _is_box_drawing_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return all(any(lo <= ord(ch) < hi for lo, hi in _BOX_DRAWING_RANGES)
               for ch in stripped)


# fg.match_doc aligns WHOLE-DOCUMENT token streams purely by text equality
# (difflib.SequenceMatcher) -- sound for ordinary words, but WordStar's own
# driver frequently emits short punctuation as its OWN standalone PCL
# chunk (a comma, a closing paren, a bare "A"/"B"/"C" list marker), split
# from the word it visually follows -- something our engine's word
# splitter never does (`_TOKEN_RE` keeps "Hello," together). A doc with
# many such chunks has dozens of identical 1-2 character tokens with no
# positionally-correct engine counterpart to pick from; SequenceMatcher
# pairs them anyway (LCS alignment has to pick SOME occurrence), producing
# huge, meaningless "residuals" -- confirmed 2026-09-05 by inspection:
# SCRIPT/SAWYER/PREVIEW's worst 'exact' divergences were entirely
# comma/period/single-letter tokens with residuals landing on exact
# multiples of one Courier character width (7.2pt at 10cpi), the
# signature of "matched the wrong occurrence," not a placement bug. Real
# multi-character words (e.g. -README's "see my summary of..." run, all
# sharing one genuine +28.8pt shift) are unaffected by this filter and
# still reported. Threshold: stripped length <= 2, or no alphanumeric
# character at all (catches ",", ".", "),", ".]", ":", "!", single
# letters, "'s") -- kept deliberately simple and generic rather than a
# WordStar-specific punctuation table.
def _is_unreliable_to_align(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) <= 2:
        return True
    return not any(ch.isalnum() for ch in stripped)


def load_ws7_tokens(pcl_path: str, measurements_path: str):
    """[{text, x, y_top, size, basefont, font_class, page, tid, tier,
    dist_into_line_pt, is_line_start}, ...] -- fg.ws7_page_tokens()'s own
    shape, plus the typeface-ID-derived fields this module adds. Pure
    box/rule/shading chunks (_is_box_drawing_text) and short/punctuation
    chunks difflib can't reliably align (_is_unreliable_to_align) are left
    out of the returned list entirely -- they still fix where a line
    visually starts (`dist_into_line_pt` on later tokens is measured from
    them), but never become a checkable token themselves. Also returns the
    list of WS7 page
    numbers where a fresh parse_pcl_extended pass over the .pcl disagrees
    with measurements.json's own chunk count for that page (see module
    docstring) -- those pages contribute zero tokens (nothing to safely
    zip against) and are reported by the caller as a `pcl-reparse-mismatch`
    divergence instead."""
    ws7 = json.load(open(measurements_path))
    pcl_bytes = open(pcl_path, 'rb').read()
    pages, _unhandled, _rnr, _meta = pr.parse_pcl_extended(pcl_bytes)

    tokens = []
    mismatched_pages = []
    for pidx, chunks in enumerate(pages, start=1):
        text_chunks = [c for c in chunks if c.get('type', 'text') == 'text']
        pub = next((p['chunks'] for p in ws7['pages'] if p.get('page') == pidx), None)
        if pub is None:
            continue
        if len(pub) != len(text_chunks):
            mismatched_pages.append(pidx)
            continue
        by_y = defaultdict(list)
        for pc, tc in zip(pub, text_chunks):
            by_y[pc['y_decipoints']].append((pc, tc))
        for _y, items in by_y.items():
            items.sort(key=lambda pt: pt[0]['x_decipoints'])
            line_start_x = items[0][0]['x_decipoints'] / fg.DECIPT_PER_PT
            checkable_idx = 0
            for pc, tc in items:
                if _is_box_drawing_text(pc['text']) or _is_unreliable_to_align(pc['text']):
                    continue
                x_pt = pc['x_decipoints'] / fg.DECIPT_PER_PT
                y_top = pc['y_decipoints'] / fg.DECIPT_PER_PT
                tid = tc.get('_T')
                tokens.append({
                    'text': pc['text'], 'x': x_pt, 'y_top': y_top, 'size': pc['size_pt'],
                    'basefont': pc.get('font'), 'font_class': fg.classify_font(pc.get('font')),
                    'page': pidx, 'tid': tid, 'tier': tier_for_typeface(tid),
                    'dist_into_line_pt': round(x_pt - line_start_x, 3),
                    'is_line_start': checkable_idx == 0,
                })
                checkable_idx += 1
    return tokens, mismatched_pages


# ------------------------------------------------------------ doc report
def _relative_source(path):
    """PUBLIC-REPO SAFETY: never return an absolute filesystem path -- this
    corpus lives outside the repo at a maintainer-chosen location named
    only by $CTRLKD_PRIVATE_CORPUS / $CTRLKD_SAWYER_ARCHIVE, and this
    value is written into the checked-in manifest. Reports the path
    relative to whichever corpus root it resolved under (sawyer/ or
    pd-samples/authored/, per the module docstring), falling back to the
    bare filename if it is ever outside both."""
    roots = []
    if fg._PRIVATE_CORPUS_ROOT:
        roots.append(fg._PRIVATE_CORPUS_ROOT)
    archive_root = os.environ.get(fg.ARCHIVE_ENV)
    if archive_root:
        roots.append(archive_root)
    for root in roots:
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            continue
        if not rel.startswith('..'):
            return rel
    return os.path.basename(path)


def _divergence(doc, page, line_y, words, ws7_pos, pdf_pos, font_class, reason, detail):
    return {
        'doc': doc, 'page': page, 'line_y_top_pt': line_y, 'words': words,
        'ws7_pos': ws7_pos, 'pdf_pos': pdf_pos, 'font_class': font_class,
        'reason': reason, 'detail': detail,
    }


def doc_report(doc_name: str) -> dict:
    """The full named-divergence report for one captured document:
    {doc, verdict, source_ws, counts_by_reason, divergences, ...}.

    verdict is one of:
      'source-missing'  -- see KNOWN_MISSING_SOURCE_DOCS
      'clean'           -- zero divergences with a non-font-substitution reason
      'divergent'       -- at least one real (non-font-substitution) divergence

    `divergences` is capped at MAX_LISTED_PER_REASON entries per reason
    (documents, page, words, both positions, font class, reason -- never a
    bare bucket); `counts_by_reason` is always the exact total. Only
    OUT-OF-TOLERANCE residuals are divergences at all (an in-tolerance
    font-substitution drift is not logged -- that is what the tolerance
    means); no-substitute-tier word positions are not evaluated at all
    (see module docstring), so they never appear here except via the
    line-start/baseline/word-count checks every tier gets.
    """
    if doc_name in KNOWN_MISSING_SOURCE_DOCS:
        return {'doc': doc_name, 'verdict': 'source-missing', 'source_ws': None,
                'counts_by_reason': {}, 'divergences': [],
                'reason': ('WS4 original from a personal source archive outside sawyer/, '
                           'pd-samples/authored/, and ws7-private/ -- see '
                           'KNOWN_MISSING_SOURCE_DOCS')}

    ws_path, measurements_path, pcl_path = fg.resolve_doc_paths(doc_name)
    if ws_path is None:
        return {'doc': doc_name, 'verdict': 'source-missing', 'source_ws': None,
                'counts_by_reason': {}, 'divergences': [],
                'reason': f'${fg.ARCHIVE_ENV} unset (Sawyer-archive-only document)'}
    if not os.path.exists(ws_path):
        return {'doc': doc_name, 'verdict': 'source-missing',
                'source_ws': _relative_source(ws_path),
                'counts_by_reason': {}, 'divergences': [],
                'reason': f'source not found at {_relative_source(ws_path)}'}

    ws7_tokens, mismatched_pages = load_ws7_tokens(pcl_path, measurements_path)
    ws7_meta = json.load(open(measurements_path))
    n_ws7_pages = len(ws7_meta['pages'])

    pdf_bytes = fg.render_engine_pdf(ws_path)
    engine_pages = fg.extract_pages(pdf_bytes)
    n_engine_pages = len(engine_pages)
    eng_tokens = []
    for i, p in enumerate(engine_pages):
        eng_tokens.extend(fg.engine_page_tokens(p, i + 1))
    # Same two exclusions as the WS7 side (box-drawing has no text-run
    # counterpart on either side by construction; short/punctuation tokens
    # are unreliable to align via whole-document text matching either
    # direction) -- applied here too, or an engine-side "," that no
    # longer has a WS7 "," to match against (now excluded above) would
    # misreport as a genuine `extra-word-in-engine` bug instead of simply
    # being outside what this alignment method can check.
    eng_tokens = [t for t in eng_tokens
                 if not (_is_box_drawing_text(t['text']) or _is_unreliable_to_align(t['text']))]

    counts = Counter()
    by_reason = defaultdict(list)

    def add(reason, *args, detail=None):
        counts[reason] += 1
        if len(by_reason[reason]) < MAX_LISTED_PER_REASON:
            by_reason[reason].append(_divergence(doc_name, *args, reason=reason, detail=detail))

    if n_ws7_pages != n_engine_pages:
        add('page-count-mismatch', None, None, None, None, None, None,
            detail=f'WS7 {n_ws7_pages} pages, engine {n_engine_pages} pages')

    for pidx in mismatched_pages:
        add('pcl-reparse-mismatch', pidx, None, None, None, None, None,
            detail='raw .pcl re-parse chunk count disagrees with the committed '
                   'measurements.json for this page -- the corpus data is stale '
                   'relative to tools/pcl_render.py, or the .pcl file changed')

    m = fg.match_doc(ws7_tokens, eng_tokens)
    deltas = fg.pair_deltas(m['pairs'])

    for t in m['unmatched_ws7']:
        add('word-unmatched', t['page'], round(t['y_top'], 1), [t['text']],
            [round(t['x'], 1), round(t['y_top'], 1)], None, t['tier'],
            detail='WS7 word has no corresponding word anywhere in the engine output')

    for t in m['unmatched_engine']:
        add('extra-word-in-engine', t['page'], round(t['y_top'], 1), [t['text']],
            None, [round(t['x'], 1), round(t['y_top'], 1)], t['font_class'],
            detail='engine word has no corresponding word anywhere in the WS7 capture')

    by_page = defaultdict(list)
    for (w, e), d in zip(m['pairs'], deltas):
        by_page[d['ws7_page']].append((w, e, d))

    no_substitute_word_count = 0
    for page, items in sorted(by_page.items()):
        page_deltas = [d for (_, _, d) in items]
        offset = fg.frame_offset(page_deltas)
        mx = offset['median_dx'] if offset['median_dx'] is not None else 0.0
        my = offset['median_dy'] if offset['median_dy'] is not None else 0.0
        for w, e, d in items:
            if not d['same_page']:
                continue  # pagination drift; already reflected in page-count-mismatch above
            resid_dx = d['dx'] - mx
            resid_dy = d['dy'] - my
            tier = w['tier']
            ws7_pos = [round(w['x'], 2), round(w['y_top'], 2)]
            pdf_pos = [round(e['x'], 2), round(e['y_top'], 2)]
            words = [w['text'], e['text']]

            # Baseline exactness applies to EVERY font (layout, not glyph width).
            if abs(resid_dy) > BASELINE_EPS_PT:
                add('baseline-shift', page, round(w['y_top'], 1), words, ws7_pos, pdf_pos, tier,
                    detail=f'baseline residual {resid_dy:+.2f}pt (tolerance {BASELINE_EPS_PT}pt)')
                continue

            # Line-start x applies to EVERY font too (margin/indent, not glyph width).
            if w['is_line_start']:
                if abs(resid_dx) > LINE_START_EPS_PT:
                    add('line-start-shift', page, round(w['y_top'], 1), words, ws7_pos, pdf_pos,
                        tier, detail=f'line-start residual {resid_dx:+.2f}pt '
                                     f'(tolerance {LINE_START_EPS_PT}pt)')
                continue

            if tier == TIER_EXACT:
                if abs(resid_dx) > EXACT_EPS_PT:
                    add('exact-drift', page, round(w['y_top'], 1), words, ws7_pos, pdf_pos, tier,
                        detail=f'residual {resid_dx:+.2f}pt (tolerance {EXACT_EPS_PT}pt, '
                               f'exact/fixed-pitch font)')
            elif tier == TIER_CGTIMES:
                tol = cgtimes_tolerance_pt(w['dist_into_line_pt'])
                if abs(resid_dx) > tol:
                    add('cgtimes-drift-exceeds-tolerance', page, round(w['y_top'], 1), words,
                        ws7_pos, pdf_pos, tier,
                        detail=f'residual {resid_dx:+.2f}pt at {w["dist_into_line_pt"]:.1f}pt '
                               f'into the line (tolerance {tol:.2f}pt)')
            elif tier == TIER_UNIVERS:
                tol = univers_tolerance_pt(w['dist_into_line_pt'])
                if abs(resid_dx) > tol:
                    add('univers-drift-exceeds-tolerance', page, round(w['y_top'], 1), words,
                        ws7_pos, pdf_pos, tier,
                        detail=f'residual {resid_dx:+.2f}pt at {w["dist_into_line_pt"]:.1f}pt '
                               f'into the line (tolerance {tol:.2f}pt)')
            elif tier == TIER_NO_SUBSTITUTE:
                # Word-level x is not evaluated for this tier, by rule (see module
                # docstring) -- only counted, so the manifest can show how many
                # words fell outside this check's scope without spamming entries.
                no_substitute_word_count += 1
            else:
                add('unclassified-font-tier', page, round(w['y_top'], 1), words, ws7_pos,
                    pdf_pos, tier, detail=f'WS7 typeface id {w.get("tid")!r} has no tier mapping')

    real_reasons = [r for r in counts if r != 'font-substitution']
    verdict = 'divergent' if any(counts[r] for r in real_reasons) else 'clean'

    return {
        'doc': doc_name, 'verdict': verdict, 'source_ws': _relative_source(ws_path),
        'n_ws7_pages': n_ws7_pages, 'n_engine_pages': n_engine_pages,
        'no_substitute_word_count': no_substitute_word_count,
        'counts_by_reason': dict(sorted(counts.items())),
        'divergences': [d for r in sorted(by_reason) for d in by_reason[r]],
    }


# --------------------------------------------------------------- manifest
def regenerate_manifest(doc_names=None) -> dict:
    doc_names = doc_names or CAPTURED_DOCS
    documents = {}
    for name in doc_names:
        print(f'pcl_tolerance: running {name}...', file=sys.stderr)
        documents[name] = doc_report(name)
    manifest = {
        'generator': 'tools/pcl_tolerance.py --record',
        'note': ('Checked-in answer key for tests/test_pcl_fidelity.py (the `pcl` pytest '
                 'tier). Regenerate with the command above whenever a real engine or '
                 'tolerance change is expected to move these numbers -- review the diff, '
                 'never regenerate inside the test run itself.'),
        'documents': documents,
    }
    return manifest


def load_manifest() -> dict:
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--record', action='store_true',
                    help='regenerate tests/pcl_fidelity_manifest.json from a live run '
                         '(requires CTRLKD_PRIVATE_CORPUS, and CTRLKD_SAWYER_ARCHIVE for '
                         'the sawyer-group documents) -- writes the file, does not print a diff')
    ap.add_argument('--doc', help='print one document\'s live report (no manifest write)')
    a = ap.parse_args(argv)

    if a.doc:
        print(json.dumps(doc_report(a.doc), indent=2))
        return 0

    if a.record:
        manifest = regenerate_manifest()
        with open(MANIFEST_PATH, 'w') as f:
            json.dump(manifest, f, indent=2, sort_keys=False)
            f.write('\n')
        print(f'wrote {MANIFEST_PATH}', file=sys.stderr)
        for name, entry in manifest['documents'].items():
            print(f"  {name}: {entry['verdict']}  {entry.get('counts_by_reason', {})}")
        return 0

    ap.error('need --record or --doc NAME')


if __name__ == '__main__':
    raise SystemExit(main())
