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

TOLERANCE EVIDENCE (2026-09-05, all 18 v1 captures, every one with a
source resolvable through ws7-prints/v1/sources.json -- see CAPTURED_DOCS
below)
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

RASTER TOLERANCE EVIDENCE (planning #211, 2026-09-06 -- mechanism L
revisited)
----------------------------------------------------------------------
tools/PCL-DIVERGENCE-TRIAGE.md mechanism L excluded a picture placeholder
from the TEXT comparison (real WS7 has no "[image: NAME]" text at all --
it printed the actual raster), which correctly stopped it from being
misread as a word-position bug, but also meant the raster itself was
never checked against anything. render_engine_pdf now renders with
`pictures='embed'` (fg.render_engine_pdf's own docstring), so every
picture-bearing captured document with a WS7-side raster measurement
(measurements.json's own `pages[].rasters`, pcl_render.py's
ESC*r#A/ESC*rB capture) gets its raster's own position/size compared,
mechanically -- keyed off the capture's own data, same "no doc-name
allowlist" discipline as resolve_doc_paths' v2/v3 preference.

n=3 rasters measured directly (all three of this corpus's picture-bearing
documents that currently have a raster-bearing v3 capture: PREVIEW,
-SCREEN, -README -- all three reference the SAME picture,
INSET/PIX/WORDSTAR.PIX): x matches to 0.0pt on all three (the image's own
left edge tracks `.po` exactly, same margin logic as everything else on
the page); width/height residuals are under 0.6pt on all three (px/dpi
rounding, not a real size bug). The vertical position (dy, engine y_top
minus WS7 y_top) is NOT zero on any of the three -- a consistent small
cluster: PREVIEW -2.70pt, -SCREEN -3.00pt, -README -3.00pt. Same sign,
same order of magnitude, on three independent documents/pages -- almost
certainly ONE real, small, shared root cause in the image's own
"reserved band" vertical placement (`src/ctrlkd/pdf.py`'s image-drawing
branch, `img_y = y + (reserved - h_pt)`), not three coincidences. Not
diagnosed further or fixed this round (out of this task's scope --
mechanism L revisited only asks to ADD the comparison); named as a new
open finding, see tools/PCL-DIVERGENCE-TRIAGE.md's own mechanism Y entry.

RASTER_X_EPS_PT reuses LINE_START_EPS_PT (2.5pt) -- the raster's own left
edge is conceptually the same "where does content start on this line"
measurement a line-start x already is, and the measured evidence (0.0pt
on all 3) sits far inside it. RASTER_Y_EPS_PT reuses BASELINE_EPS_PT
(1.0pt) -- deliberately the SAME tight, near-exact-equality standard
applied to every text baseline regardless of font (module docstring:
"Line starts, baselines, page breaks and page counts are checked to
(near-)exact equality for EVERY font, substituted or not"); a raster's
own vertical position is exactly that kind of layout fact, not a glyph
metric, so it gets the same rigor rather than a looser bound picked to
make the n=3 evidence above pass. All three measured documents therefore
show a real `raster-position-shift` divergence at this tolerance -- see
mechanism Y. RASTER_SIZE_EPS_PT (1.0pt) is a generous but still
meaningful bound above the largest measured size residual (0.58pt).
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


# ------------------------------------------------------------ reason vocabulary
# The literal 'reason' strings doc_report() ever emits into a divergence or
# counts_by_reason entry -- a constants block, not a docstring promise. A
# docstring promise is exactly what silently rotted last time:
# tests/test_pcl_fidelity.py used to pass a document only if it had no
# divergence whose reason equalled the literal 'font-substitution' -- a
# string doc_report() never actually emitted (its real font-substitution
# reasons are REASON_CGTIMES_DRIFT_EXCEEDS_TOLERANCE /
# REASON_UNIVERS_DRIFT_EXCEEDS_TOLERANCE below). The filter therefore
# matched nothing, ever, and every document carrying an accepted-by-design
# font-substitution residual FAILED the tier for a class of divergence
# Jon's ruling says should pass. See tools/PCL-DIVERGENCE-TRIAGE.md
# mechanism I. Every `add(...)` call in doc_report() below passes one of
# these constants -- never a bare string literal -- so this block is the
# one place that can ever drift from what the function actually emits.
REASON_PAGE_COUNT_MISMATCH = 'page-count-mismatch'
REASON_PCL_REPARSE_MISMATCH = 'pcl-reparse-mismatch'
REASON_WORD_UNMATCHED = 'word-unmatched'
REASON_EXTRA_WORD_IN_ENGINE = 'extra-word-in-engine'
REASON_BASELINE_SHIFT = 'baseline-shift'
REASON_LINE_START_SHIFT = 'line-start-shift'
REASON_EXACT_DRIFT = 'exact-drift'
REASON_CGTIMES_DRIFT_EXCEEDS_TOLERANCE = 'cgtimes-drift-exceeds-tolerance'
REASON_UNIVERS_DRIFT_EXCEEDS_TOLERANCE = 'univers-drift-exceeds-tolerance'
REASON_UNCLASSIFIED_FONT_TIER = 'unclassified-font-tier'
# A pristine-install (PRISTINE.EXE, no WSCHANGE customization) capture's
# own absolute, line-start, same-page frame offset should be 0.0pt against
# this engine's stock-default rendering -- unlike a sawyer-wschange
# capture, where a nonzero offset is EXPECTED and reported-only (see
# document_frame_offset_pt's own docstring/mechanism S). This reason is
# real (never a FONT_SUBSTITUTION_REASONS member): a nonzero offset here
# means either this doc's own `.po`/margin handling regressed, or the
# capture wasn't actually made against a stock install after all.
REASON_PRISTINE_FRAME_OFFSET = 'pristine-frame-offset-exceeds-tolerance'
# Planning #211 (mechanism L revisited): the raster (embedded-picture)
# axis -- see this module's own "RASTER TOLERANCE EVIDENCE" docstring
# section and tools/PCL-DIVERGENCE-TRIAGE.md mechanism Y. Never a
# FONT_SUBSTITUTION_REASONS member: a raster's own position/size is this
# engine's own layout logic, not a font-metric substitution.
REASON_RASTER_POSITION_SHIFT = 'raster-position-shift'
REASON_RASTER_SIZE_MISMATCH = 'raster-size-mismatch'
REASON_RASTER_COUNT_MISMATCH = 'raster-count-mismatch'

ALL_REASONS = frozenset({
    REASON_PAGE_COUNT_MISMATCH, REASON_PCL_REPARSE_MISMATCH,
    REASON_WORD_UNMATCHED, REASON_EXTRA_WORD_IN_ENGINE,
    REASON_BASELINE_SHIFT, REASON_LINE_START_SHIFT, REASON_EXACT_DRIFT,
    REASON_CGTIMES_DRIFT_EXCEEDS_TOLERANCE,
    REASON_UNIVERS_DRIFT_EXCEEDS_TOLERANCE, REASON_UNCLASSIFIED_FONT_TIER,
    REASON_PRISTINE_FRAME_OFFSET, REASON_RASTER_POSITION_SHIFT,
    REASON_RASTER_SIZE_MISMATCH, REASON_RASTER_COUNT_MISMATCH,
})

# Mechanism I (tools/PCL-DIVERGENCE-TRIAGE.md): real CG-Times/Univers
# font-substitution drift that exceeds the modelled per-line-distance
# tolerance. Accepted by design -- a base-14-only PDF cannot metrically
# match an HP-resident face -- so a document whose ONLY divergences carry
# one of these two reasons PASSES the `pcl` tier (the count is still
# reported in counts_by_reason, never silently dropped). No other reason
# belongs in this set: a no-substitute-tier face's word-level x isn't even
# evaluated (see doc_report's own no_substitute_word_count), so it never
# produces a divergence reason at all, font-substitution or otherwise.
FONT_SUBSTITUTION_REASONS = frozenset({
    REASON_CGTIMES_DRIFT_EXCEEDS_TOLERANCE,
    REASON_UNIVERS_DRIFT_EXCEEDS_TOLERANCE,
})


def is_font_substitution_reason(reason: str) -> bool:
    """True for exactly the two reasons mechanism I names (see
    FONT_SUBSTITUTION_REASONS) -- the test for whether a divergence is an
    accepted-by-design font-substitution residual rather than a real bug."""
    return reason in FONT_SUBSTITUTION_REASONS


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
# See module docstring's "RASTER TOLERANCE EVIDENCE" section (planning
# #211) for the n=3 measurements behind these three.
RASTER_X_EPS_PT = LINE_START_EPS_PT
RASTER_Y_EPS_PT = BASELINE_EPS_PT
RASTER_SIZE_EPS_PT = 1.0


def cgtimes_tolerance_pt(dist_into_line_pt: float) -> float:
    return CGTIMES_DRIFT_BASE_PT + CGTIMES_DRIFT_RATE_PT_PER_PT * dist_into_line_pt


def univers_tolerance_pt(dist_into_line_pt: float) -> float:
    return UNIVERS_DRIFT_BASE_PT + UNIVERS_DRIFT_RATE_PT_PER_PT * dist_into_line_pt


def pristine_offset_exceeds_tolerance(install: str, median_dx) -> bool:
    """True when a PRISTINE-install document's absolute (line-start,
    same-page) frame-offset median exceeds the ordinary line-start
    tolerance -- the engine models WordStar 7's own stock defaults, so a
    pristine capture's expected offset is 0.0pt (unlike a sawyer-wschange
    capture, where mechanism S's own +7.2pt is real, expected, and
    report-only). Reuses LINE_START_EPS_PT rather than a new constant:
    this IS a line-start-shaped measurement (fg.frame_offset restricted to
    is_line_start pairs, see doc_report's own document_frame_offset_pt),
    just measured absolutely across the whole doc instead of per-page.
    `median_dx` is None when there were no line-start same-page pairs to
    measure at all (frame_offset's own empty-input shape) -- never a
    divergence in that case, nothing was measured either way."""
    return install == 'pristine' and median_dx is not None and abs(median_dx) > LINE_START_EPS_PT


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


# ------------------------------------------------- WS7 chunk-splitting fixes
# WS7's own PCL driver splits a handful of things across separate print
# chunks that fg.match_doc's whole-document text-equality aligner can only
# ever match word-for-word -- see tools/PCL-DIVERGENCE-TRIAGE.md mechanisms
# C and D. Both functions below operate on ONE WS7 print line's own (pc, tc)
# pairs (pc = measurements.json's committed chunk dict, tc = this module's
# own fresh pcl_render reparse of that same chunk -- load_ws7_tokens keeps
# the two in lockstep by zipping them in emission order), already sorted by
# x, BEFORE _is_box_drawing_text/_is_unreliable_to_align ever run on the
# result -- so a reconstructed word is judged (and, when genuinely short,
# filtered) as the ONE token it visually is, never as separate fragments
# too short to align reliably.
KERNING_MERGE_EPS_PT = 1.5  # generous vs decipoint quantization + AFM rounding.
                            # NOT widened further despite one confirmed
                            # miss (WARPRAYR's title 'War' in the
                            # ws7-prints/v2 recapture kerns 2.0pt short, just
                            # outside this bound -- the same title matched
                            # inside 1.5pt against the older v1 capture) --
                            # tried 2.0 and 2.5pt directly against the full
                            # 10-document set and BOTH made every other
                            # document worse (WARPRAYR itself 13->24/65,
                            # LYING 41->42/157, LJ6DTP worse at every step):
                            # real inter-word gaps in this corpus's smaller
                            # CG-Times/Univers-substituted running sizes get
                            # that close too, so widening the bound merges
                            # genuine separate words far more often than it
                            # catches real kerning-pair splits. WARPRAYR's
                            # 'War'/'country'/similar residuals are left
                            # NAMED, not fixed, rather than regress the rest
                            # of the corpus to chase one document's own
                            # kerning-pair magnitude.


DOUBLE_STRIKE_EPS_PT = 2.0  # generous vs the ~1.4pt slant offset a faux-italic
                            # double-strike sometimes carries (PREVIEW.WS's
                            # own "Italic" duplicate, measured x=344.6pt/
                            # 346.0pt -- WS7 fakes italic AND bold on the
                            # same double-strike pass, offsetting the second
                            # strike slightly to simulate the slant, not
                            # printing it at the identical position the way
                            # a plain bold double-strike does), while nowhere
                            # near a real word-to-word gap (BOXES/SAWYER/
                            # VERSIONS's own EXACT-position duplicates, and
                            # any genuine adjacent word, are all comfortably
                            # outside it).


def _strip_leading_box_drawing_chunks(items):
    """Mechanism N (triage 2026-09-06 residuals round): a WS7 print chunk
    that combines a box-drawing/table-border character directly against a
    real word with no space (SCRIPT.WS's own '│Figure', a
    table-bordered figure caption) is, for WS7's own driver, one literal
    character run -- the LaserJet's resident Courier charset draws
    box-drawing glyphs as ordinary text, same font, same advance, no
    different from any other character. Our own engine draws a
    box-drawing character as a VECTOR (`_graphic_ops`, Jon's ruling:
    box/rule fidelity is a real drawn line, not a font glyph standing in
    for one) and keeps it entirely separate from the adjoining text span
    (`_split_graphics`) -- so the two sides' text streams can never
    literally match on a chunk like this no matter how correct the
    position: our own 'Figure' token never carries a box character, and
    never will. Strips a WS7 chunk's own LEADING box-drawing/block/
    geometric run (`_BOX_DRAWING_RANGES`) before matching, correcting its
    x forward by the stripped run's own natural AFM width -- the same
    "this is what our engine's own text stream would show" normalization
    mechanisms C/J/K already give this driver's other representation
    differences. A chunk that is NOTHING BUT box-drawing characters is
    left alone -- `_is_box_drawing_text`'s own territory, applied later in
    `load_ws7_tokens`."""
    out = []
    for pc, tc in items:
        text = pc['text']
        i = 0
        while i < len(text) and any(lo <= ord(text[i]) < hi
                                    for lo, hi in _BOX_DRAWING_RANGES):
            i += 1
        if i == 0 or i == len(text):
            out.append((pc, tc))
            continue
        prefix, rest = text[:i], text[i:]
        shift_dp = round(fg.afm.string_width_pt(prefix, pc.get('font'),
                                                 pc['size_pt']) * fg.DECIPT_PER_PT)
        out.append((dict(pc, text=rest, x_decipoints=pc['x_decipoints'] + shift_dp), tc))
    return out


def _dedupe_double_strike_chunks(items, eps_pt=DOUBLE_STRIKE_EPS_PT):
    """Mechanism D: WS7's HP-resident-font double-strike fake-bold/italic
    technique prints the identical chunk TWICE at (near-)identical position
    (confirmed duplicate (text, x, font) chunks in BOXES/SAWYER/VERSIONS's
    own measurements.json -- bolded filenames/command names -- and, with a
    small slant offset rather than an exact one, PREVIEW's own faux-italic
    "Italic" label). Our engine renders bold/italic as one real glyph run,
    never a doubled strike (the correct choice under Jon's base-14-only
    ruling), so the SECOND copy has no engine counterpart to align to at
    all -- drop it (keep the first) before matching, so it stops reporting
    as `word-unmatched`. A pair counts as a duplicate only when text, size,
    WS7's own post-substitution font name AND the pre-substitution PCL
    typeface id all match exactly, and x is within `eps_pt` of the most
    recent kept chunk in that same group -- identity AND (near-)position,
    never text alone (two different words can share an x by coincidence,
    and two genuinely different words never land within so small a gap)."""
    out = []
    last_x = {}
    eps_dp = eps_pt * fg.DECIPT_PER_PT
    for pc, tc in items:
        key = (pc['text'], pc['size_pt'], pc.get('font'), tc.get('_T'))
        x = pc['x_decipoints']
        prev_x = last_x.get(key)
        if prev_x is not None and abs(x - prev_x) <= eps_dp:
            continue
        last_x[key] = x
        out.append((pc, tc))
    return out


def _merge_kerning_split_chunks(items, eps_pt=KERNING_MERGE_EPS_PT):
    """Mechanism C: WS7's own driver splits certain words at a kerning pair
    ('War' -> 'W' + 'ar', 'You' -> 'Y' + 'ou', 'Twain' -> 'T' + 'wain') into
    two touching print chunks with no space between them -- confirmed on
    WARPRAYR's title (measurements.json: 'W' at x=259.6, 'ar' at x=273.6,
    abutting exactly at 'W's own natural glyph width). `items` is one WS7
    print line's (pc, tc) pairs, already sorted by x. Two consecutive
    chunks merge into one when they share the same size and font (both the
    post-substitution name and the pre-substitution PCL typeface id) and
    the next chunk's own x lands within `eps_pt` of where the running
    merged text's own AFM natural width (fg.afm.string_width_pt -- the SAME
    metric this repo's other engine/WS7 comparisons already use) says it
    should end -- i.e. WS7 printed them as one continuous run with no
    visible gap, just split into separate PCL text chunks. The merged
    chunk keeps the FIRST chunk's own position/font/size and gets the
    concatenated text; nothing downstream of this function ever reads a
    merged chunk's 'width', only its 'text'/'x'/'y'."""
    merged = []
    i = 0
    n = len(items)
    while i < n:
        pc, tc = items[i]
        text = pc['text']
        start_x = pc['x_decipoints']
        j = i + 1
        while j < n:
            npc, ntc = items[j]
            if (npc['size_pt'] != pc['size_pt'] or npc.get('font') != pc.get('font')
                    or ntc.get('_T') != tc.get('_T')):
                break
            expected_end_dp = start_x + (
                fg.afm.string_width_pt(text, pc.get('font'), pc['size_pt']) * fg.DECIPT_PER_PT)
            if abs(npc['x_decipoints'] - expected_end_dp) > eps_pt * fg.DECIPT_PER_PT:
                break
            text += npc['text']
            j += 1
        merged.append((dict(pc, text=text), tc))
        i = j
    return merged


TRAILING_PUNCT_MERGE_EPS_PT = 3.0  # wider than KERNING_MERGE_EPS_PT (1.5pt)
                                   # on purpose: a real inter-word GAP never
                                   # shows up as a WS7 chunk containing
                                   # NOTHING but punctuation (that shape is
                                   # unique to a word's own trailing mark),
                                   # so widening it here carries none of
                                   # mechanism C's own risk of swallowing a
                                   # genuine short word -- confirmed against
                                   # the full 10-document set below.
_TRAILING_PUNCT_CHARS = frozenset(',.;:!?\'")]-')


def _is_pure_punctuation(text: str) -> bool:
    """True for a chunk that is NOTHING but trailing-punctuation characters
    (never a real standalone word -- a lone letter or digit chunk is
    excluded on purpose, see `_merge_trailing_punctuation_chunks`)."""
    return bool(text) and all(ch in _TRAILING_PUNCT_CHARS for ch in text)


def _merge_trailing_punctuation_chunks(items, eps_pt=TRAILING_PUNCT_MERGE_EPS_PT):
    """Mechanism K (triage 2026-09-06 residuals round): WS7's own driver
    sometimes emits a word's trailing punctuation (a comma, period, closing
    quote/paren...) as its OWN separate print chunk, close behind but not
    always within mechanism C's own tighter kerning-pair bound. Confirmed
    on WARPRAYR.WS ('country' at x=92.4pt, natural AFM width 36.66pt at
    12pt Times-Roman would put a continuation at 129.06pt, but WS7's own
    ',' chunk actually starts at 131.0pt -- a 1.94pt gap, just outside
    `KERNING_MERGE_EPS_PT`) and LYING.WS's own similar trailing-comma/
    period splits. Our engine always attaches trailing punctuation to its
    word (one span, one Tj), so the split WS7 chunk has no engine
    counterpart to align to UNLESS it is re-fused first -- the same
    "capture artifact, not a real position" treatment as mechanisms C/D/J.

    Deliberately its OWN function with its OWN wider epsilon rather than
    just widening `KERNING_MERGE_EPS_PT`: widening that bound to cover this
    gap directly was tried and reverted (see its own docstring) because it
    also merges genuinely separate short WORDS elsewhere in the corpus.
    That risk does not apply here -- the chunk being merged INTO the
    running word must be PURE punctuation (`_is_pure_punctuation`, e.g. a
    lone ',' or '."'), a shape a real standalone word's own chunk never
    takes, so this can never mistake two adjacent short words for a
    word-plus-its-own-trailing-mark."""
    merged = []
    i = 0
    n = len(items)
    while i < n:
        pc, tc = items[i]
        text = pc['text']
        start_x = pc['x_decipoints']
        j = i + 1
        while j < n:
            npc, ntc = items[j]
            if not _is_pure_punctuation(npc['text']):
                break
            if (npc['size_pt'] != pc['size_pt'] or npc.get('font') != pc.get('font')
                    or ntc.get('_T') != tc.get('_T')):
                break
            expected_end_dp = start_x + (
                fg.afm.string_width_pt(text, pc.get('font'), pc['size_pt']) * fg.DECIPT_PER_PT)
            if abs(npc['x_decipoints'] - expected_end_dp) > eps_pt * fg.DECIPT_PER_PT:
                break
            text += npc['text']
            j += 1
        merged.append((dict(pc, text=text), tc))
        i = j
    return merged


def _correct_toggle_boundary_chunks(items):
    """Mechanism J (triage 2026-09-06 residuals round), extended for the
    underline case (page-5 URL trace, `-README` v3 pristine, planning
    task): WS7's own LaserJet driver only re-emits a fresh
    `ESC&a<n>H` (absolute horizontal position) before a text run when its
    OWN internal logic decides to -- immediately after a bold toggle with
    no space (mechanism J's original BOXES evidence) or around an inline
    UNDERLINE toggle (`ESC&dD`/`ESC&d@`, which carry no position field of
    their own at all). Confirmed on `-README`'s own page 5, raw `.pcl`:

        ...&a1512H(\\x1b&dDhttp://www.vdosplus.org\\x1b&d@)\\x1b&a3384Hor...

    "(" gets its own real `H` (1512dp = 151.2pt); the underlined URL and
    the closing ")" get NONE -- both simply inherit whatever `cursor_x`
    was last set to, i.e. "("'s own position, in measurements.json. This
    is a real property of WS7's PCL stream, not a real print position: a
    physical LaserJet auto-advances its own pen after every glyph
    regardless of whether the driver ever re-states its coordinate, so
    the true positions are recovered by chaining each glued run's own
    natural AFM width forward from the last chunk that DID carry a real,
    distinct `H`. Verified exactly on this example: "(" (151.2, real) ->
    URL corrected to 151.2+7.2=158.4 (matches this engine's own already-
    correct `pdf_pos` -- the engine was right all along) -> ")" corrected
    to 158.4+24*7.2=331.2 -> "or"'s own real, distinct `H` at 338.4 =
    331.2+7.2 exactly, closing the loop with zero residual. This is a
    capture/measurement-tool artifact (the same "not a real position"
    class as mechanisms C/D/J's other driver quirks), not an engine bug
    and NOT mechanism S's `.po` corpus-provenance question -- the pristine
    capture disagrees with itself, mid-page, only at these two toggle
    boundaries; a real `.po` offset would show on every line.

    Scoped tightly to the two confirmed shapes: a chunk's x is corrected
    only when it is EXACTLY equal to the immediately preceding WS7
    chunk's own (uncorrected/raw) x on the same printed line -- a full
    character's advance dropped outright, not the small kerning-style gap
    `_merge_kerning_split_chunks` already owns -- AND either its font OR
    its `underline` flag differs from that preceding chunk's (a style
    toggle boundary, not two chunks of the same run WS7 happened to split
    -- mechanism C's own territory, and not two genuinely coincident
    same-style chunks, which this must never touch). `items` is one WS7
    print line's (pc, tc) pairs, already sorted by x and already through
    `_dedupe_double_strike_chunks`/`_merge_kerning_split_chunks`/
    `_merge_trailing_punctuation_chunks`.

    Corrections CHAIN: each chunk's own corrected ("real") x, font, text
    and underline state feed forward as the base a LATER glued chunk
    advances from, while glue-DETECTION still compares against the
    preceding chunk's own RAW (uncorrected) x -- required for a run of
    MORE than one glued chunk in a row (the URL-then-")" pair above is
    exactly this shape: ")"'s raw x equals the URL's raw x, not the URL's
    corrected x, so detection must use the raw value even as advancement
    uses the corrected one). A single-pair chain -- mechanism J's own
    original BOXES case -- is the n=1 special case of the same loop."""
    out = []
    prev_raw_x = None
    prev_real_x = None
    prev_real_text = None
    prev_real_font = None
    prev_real_size = None
    prev_underline = None
    for pc, tc in items:
        cur = dict(pc)
        raw_x = pc['x_decipoints']
        toggled = (prev_raw_x is not None and raw_x == prev_raw_x
                   and (pc.get('font') != prev_real_font
                        or bool(pc.get('underline')) != bool(prev_underline)))
        if toggled:
            prev_end_dp = prev_real_x + (
                fg.afm.string_width_pt(prev_real_text, prev_real_font, prev_real_size)
                * fg.DECIPT_PER_PT)
            cur['x_decipoints'] = round(prev_end_dp)
        out.append((cur, tc))
        prev_raw_x = raw_x
        prev_real_x = cur['x_decipoints']
        prev_real_text = pc['text']
        prev_real_font = pc.get('font')
        prev_real_size = pc['size_pt']
        prev_underline = pc.get('underline')
    return out


def _reconcile_glued_ws7_chunks(eng_tokens, unmatched_ws7, unmatched_engine):
    """Mechanism P (triage 2026-09-06, second residuals round): a WS7
    word-unmatched chunk that is the EXACT concatenation of two ADJACENT
    (in the engine's own reading-order token stream, no other word
    between them) still-unmatched engine words, with no separator, is a
    correct match this gate's own text-equality alignment (fg.match_doc,
    difflib.SequenceMatcher over two FLAT word lists) can never make on
    its own -- it only ever compares one WS7 token against one engine
    token, never a WS7 token against a multi-token engine run.

    Confirmed real (not a guess at the shape): LYING.WS's own
    'lies--everyday;' (WS7) / 'lies--every'+'day;' (engine),
    'failing--awholly' / 'failing--a'+'wholly', 'case--aspersonal' /
    'case--as'+'personal'; WARPRAYR.WS's own '"Blessour' /
    '"Bless'+'our' -- checked directly (mechanism C's own
    `_merge_kerning_split_chunks`, whose confirmed-correct territory is
    a WS7 driver kerning-pair split): in EVERY one of these four, mechanism
    C's own x-gap epsilon test genuinely passes for the WS7 measurement
    (a coincidentally tight inter-word gap in this corpus's CG-Times-
    substituted running sizes, not a kerning-pair split at all -- both
    fragments are already complete, real, separate words on their own),
    which is what glued them into one WS7 chunk with no space character
    in the first place; nothing about that decision is reversible from
    the WS7 side alone (the merge already happened by the time this gate
    ever sees the token), and the confirmed shape (two real words with
    no space) is fundamentally indistinguishable from mechanism C's own
    genuine kerning splits using x-gap alone -- KERNING_MERGE_EPS_PT
    stays exactly where mechanism C's own docstring already argues it
    must (widening it regresses the rest of the corpus). Reconciling
    against the ENGINE's own already-correct word split, post-match, is
    the one place this can be caught without touching that epsilon at
    all -- the same "capture-artifact, not a real position" treatment as
    every other mechanism in this file, just applied one stage later,
    directly against `fg.match_doc`'s own leftover unmatched lists
    instead of the WS7 chunk stream `load_ws7_tokens` builds.

    `eng_tokens` is the FULL (already box-drawing/`_is_unreliable_to_align`
    -filtered, same list `doc_report` builds) engine token stream in
    document reading order -- the adjacency check walks THIS list's own
    consecutive indices, not `unmatched_engine`'s (which drops the
    ordering a merge needs the instant anything between two candidates
    already matched). `unmatched_ws7`/`unmatched_engine` are
    `fg.match_doc`'s own leftover lists. Returns
    `(new_unmatched_ws7, new_unmatched_engine)` with every resolved
    token removed from both -- resolved pairs are not added to `pairs`
    (position-level comparison for a glued WS7 chunk is not meaningful:
    there is no single correct x for the boundary between two words
    inside one PCL chunk, the same reasoning `_merge_trailing_
    punctuation_chunks`'s own merged chunk already carries for its own
    x). A token is consumed by at most one reconciliation."""
    idx_of = {id(t): i for i, t in enumerate(eng_tokens)}
    unmatched_eng_ids = {id(t) for t in unmatched_engine}
    resolved_ws7_ids, resolved_eng_ids = set(), set()
    for w in unmatched_ws7:
        for e1 in unmatched_engine:
            if id(e1) in resolved_eng_ids or e1['page'] != w['page']:
                continue
            i = idx_of.get(id(e1))
            if i is None or i + 1 >= len(eng_tokens):
                continue
            e2 = eng_tokens[i + 1]
            if (id(e2) in resolved_eng_ids or id(e2) not in unmatched_eng_ids
                    or e2['page'] != w['page']
                    or abs(e2['y_top'] - e1['y_top']) > 0.5):
                continue
            if e1['text'] + e2['text'] != w['text']:
                continue
            resolved_ws7_ids.add(id(w))
            resolved_eng_ids.add(id(e1))
            resolved_eng_ids.add(id(e2))
            break
    new_unmatched_ws7 = [w for w in unmatched_ws7 if id(w) not in resolved_ws7_ids]
    new_unmatched_engine = [e for e in unmatched_engine if id(e) not in resolved_eng_ids]
    return new_unmatched_ws7, new_unmatched_engine


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
            items = _strip_leading_box_drawing_chunks(items)  # mechanism N
            items = _dedupe_double_strike_chunks(items)   # mechanism D, before C
            items = _merge_kerning_split_chunks(items)    # mechanism C
            items = _merge_trailing_punctuation_chunks(items)  # mechanism K
            items = _correct_toggle_boundary_chunks(items)  # mechanism J
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


# Corpus groups (ws7-prints/v1/sources.json's own "group" field on each
# capture) whose exact relative source path is safe to publish verbatim in
# THIS PUBLIC repo's checked-in manifest: Robert J. Sawyer's own public WS7
# archive, and this repo's own public-domain/authored sample corpus -- both
# already named throughout this codebase (PRIVATE_DOCS, DEFAULT_AUTHORED_ROOT)
# because there is nothing private about either one. The corpus's index can
# name other groups too (its own internal source-provenance bookkeeping,
# living entirely in the PRIVATE corpus) -- this repo has no business
# repeating one of THOSE group names or folder layouts anywhere in its own
# tracked files (CLAUDE.md: "never name private groups/paths in code -- the
# index carries them"), so only these two are allowlisted; anything else
# falls through to _source_ws_for_report's redaction below, by omission,
# never by matching a private name.
PUBLIC_SOURCE_GROUPS = {'sawyer', 'pd-samples'}


def _source_ws_for_report(doc_name: str, ws_path):
    """The 'source_ws' value safe to put in a report/manifest for
    `doc_name`, resolved via ws_path. When the corpus's sources.json index
    says this capture's source lives in a PUBLIC_SOURCE_GROUPS group (or no
    index exists at all -- the pre-index legacy resolution only ever
    reaches those same two groups), this is the real corpus-relative path,
    same as always. For any other group, the exact path is WITHHELD --
    this repo names only the (already-public, per CAPTURED_DOCS) doc name,
    never a private corpus group's internal folder layout."""
    if ws_path is None:
        return None
    if fg._PRIVATE_CORPUS_ROOT:
        prints_dir = os.path.join(fg._PRIVATE_CORPUS_ROOT, 'ws7-prints', fg.PRINTS_SUBDIR)
        index = fg._load_sources_index(prints_dir)
        if index is not None:
            entry = index.get('captures', {}).get(doc_name)
            if entry is not None and entry.get('group') not in PUBLIC_SOURCE_GROUPS:
                return f'{doc_name}: source path withheld (non-public corpus group)'
    return _relative_source(ws_path)


def _divergence(doc, page, line_y, words, ws7_pos, pdf_pos, font_class, reason, detail):
    return {
        'doc': doc, 'page': page, 'line_y_top_pt': line_y, 'words': words,
        'ws7_pos': ws7_pos, 'pdf_pos': pdf_pos, 'font_class': font_class,
        'reason': reason, 'detail': detail,
    }


def doc_report(doc_name: str, engine_words: dict = None) -> dict:
    """The full named-divergence report for one captured document:
    {doc, verdict, source_ws, capture_set, install, counts_by_reason,
    divergences, ...}.

    verdict is one of:
      'source-missing'  -- ws7-prints/v1/sources.json has no resolvable
                           source for this capture yet (see
                           fg.resolve_doc_capture), or the path it names
                           isn't actually there
      'clean'           -- zero divergences with a non-font-substitution reason
      'divergent'       -- at least one real (non-font-substitution) divergence

    `capture_set` ('v3'/'v2'/'v1') and `install` ('pristine'/
    'sawyer-wschange'/...) name which capture round actually supplied
    this report's measurements/.pcl and that round's own provenance --
    see fg.resolve_doc_capture. This is per-document (not a single
    manifest-header note) because the corpus is captured incrementally: a
    future v3 recapture of some documents and not others must be
    reflected document by document, never averaged into one header claim
    covering the whole manifest.

    `divergences` is capped at MAX_LISTED_PER_REASON entries per reason
    (documents, page, words, both positions, font class, reason -- never a
    bare bucket); `counts_by_reason` is always the exact total. Only
    OUT-OF-TOLERANCE residuals are divergences at all (an in-tolerance
    font-substitution drift is not logged -- that is what the tolerance
    means); no-substitute-tier word positions are not evaluated at all
    (see module docstring), so they never appear here except via the
    line-start/baseline/word-count checks every tier gets.

    `engine_words`, when given, is a dict already matching the engine-words
    JSON schema `fg.load_engine_words()` documents (fg = tools/
    fidelity_gate.py) -- this SKIPS rendering/parsing a PDF entirely and
    uses those pre-extracted words/rasters instead, so a PDF written by an
    emitter this repo cannot parse as its own (Quartz `Tm`/`TJ` output over
    subset fonts, e.g.) can still be judged by this exact tolerance model,
    reason vocabulary, and manifest comparison -- unmodified. Default
    (None) renders `ws_path` with this repo's own engine, same as ever.
    """
    capture = fg.resolve_doc_capture(doc_name)
    ws_path = capture['ws_path']
    measurements_path, pcl_path = capture['measurements_path'], capture['pcl_path']
    capture_set, install = capture['capture_set'], capture['install']
    if ws_path is None:
        return {'doc': doc_name, 'verdict': 'source-missing', 'source_ws': None,
                'counts_by_reason': {}, 'divergences': [],
                'capture_set': capture_set, 'install': install,
                'reason': f'${fg.ARCHIVE_ENV} unset (Sawyer-archive-only document)'}
    if not os.path.exists(ws_path):
        published_source = _source_ws_for_report(doc_name, ws_path)
        return {'doc': doc_name, 'verdict': 'source-missing',
                'source_ws': published_source,
                'counts_by_reason': {}, 'divergences': [],
                'capture_set': capture_set, 'install': install,
                'reason': f'source not found at {published_source}'}

    ws7_tokens, mismatched_pages = load_ws7_tokens(pcl_path, measurements_path)
    ws7_meta = json.load(open(measurements_path))
    n_ws7_pages = len(ws7_meta['pages'])

    if engine_words is not None:
        loaded = fg.load_engine_words(engine_words)
        n_engine_pages = loaded['n_engine_pages']
        eng_tokens = loaded['eng_tokens']
        eng_rasters_by_page = loaded['eng_rasters_by_page']
    else:
        pdf_bytes = fg.render_engine_pdf(ws_path)
        engine_pages = fg.extract_pages(pdf_bytes)
        n_engine_pages = len(engine_pages)
        eng_tokens = []
        for i, p in enumerate(engine_pages):
            eng_tokens.extend(fg.engine_page_tokens(p, i + 1))
        eng_rasters_by_page = {i + 1: fg.engine_page_rasters(p, i + 1)
                               for i, p in enumerate(engine_pages)}
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
        add(REASON_PAGE_COUNT_MISMATCH, None, None, None, None, None, None,
            detail=f'WS7 {n_ws7_pages} pages, engine {n_engine_pages} pages')

    for pidx in mismatched_pages:
        add(REASON_PCL_REPARSE_MISMATCH, pidx, None, None, None, None, None,
            detail='raw .pcl re-parse chunk count disagrees with the committed '
                   'measurements.json for this page -- the corpus data is stale '
                   'relative to tools/pcl_render.py, or the .pcl file changed')

    # Planning #211 (mechanism L revisited): raster (embedded-picture)
    # position/size, for every page whose WS7 capture records at least one
    # raster (fg.ws7_page_rasters -- measurements.json's own `rasters`
    # field). Mechanical, keyed off the capture's own data: a document
    # with no raster in its capture contributes zero raster checks here,
    # no allowlist involved. See module docstring's "RASTER TOLERANCE
    # EVIDENCE" section and tools/PCL-DIVERGENCE-TRIAGE.md mechanism Y.
    for i, p in enumerate(ws7_meta['pages']):
        pn = p.get('page', i + 1)
        ws7_r = fg.ws7_page_rasters(p, pn)
        eng_r = eng_rasters_by_page.get(pn, [])
        if not ws7_r and not eng_r:
            continue
        for idx in range(max(len(ws7_r), len(eng_r))):
            w = ws7_r[idx] if idx < len(ws7_r) else None
            e = eng_r[idx] if idx < len(eng_r) else None
            if w is None or e is None:
                ws7_pos = [round(w['x'], 2), round(w['y_top'], 2)] if w else None
                pdf_pos = [round(e['x'], 2), round(e['y_top'], 2)] if e else None
                add(REASON_RASTER_COUNT_MISMATCH, pn, None, [f'raster#{idx}'],
                    ws7_pos, pdf_pos, None,
                    detail=f'WS7 has {len(ws7_r)} raster(s) on page {pn}, engine has '
                           f'{len(eng_r)}')
                continue
            dx, dy = round(e['x'] - w['x'], 3), round(e['y_top'] - w['y_top'], 3)
            dw, dh = round(e['w_pt'] - w['w_pt'], 3), round(e['h_pt'] - w['h_pt'], 3)
            ws7_pos = [round(w['x'], 2), round(w['y_top'], 2)]
            pdf_pos = [round(e['x'], 2), round(e['y_top'], 2)]
            if abs(dx) > RASTER_X_EPS_PT or abs(dy) > RASTER_Y_EPS_PT:
                add(REASON_RASTER_POSITION_SHIFT, pn, round(w['y_top'], 1), [f'raster#{idx}'],
                    ws7_pos, pdf_pos, None,
                    detail=f'raster position residual dx={dx:+.2f}pt dy={dy:+.2f}pt '
                           f'(tolerance dx {RASTER_X_EPS_PT}pt, dy {RASTER_Y_EPS_PT}pt)')
            elif abs(dw) > RASTER_SIZE_EPS_PT or abs(dh) > RASTER_SIZE_EPS_PT:
                add(REASON_RASTER_SIZE_MISMATCH, pn, round(w['y_top'], 1), [f'raster#{idx}'],
                    ws7_pos, pdf_pos, None,
                    detail=f'raster size residual dw={dw:+.2f}pt dh={dh:+.2f}pt '
                           f'(tolerance {RASTER_SIZE_EPS_PT}pt)')

    m = fg.match_doc(ws7_tokens, eng_tokens)
    deltas = fg.pair_deltas(m['pairs'])

    # Mechanism P: reconcile a WS7 chunk that glues two adjacent engine
    # words together with no space (LYING/WARPRAYR's own residual
    # 'lies--everyday;'/'"Blessour' shape) BEFORE either leftover list
    # becomes a divergence -- see _reconcile_glued_ws7_chunks's own
    # docstring. `pairs`/`deltas` are unaffected (nothing resolved here
    # has a meaningful single x to compare).
    unmatched_ws7, unmatched_engine = _reconcile_glued_ws7_chunks(
        eng_tokens, m['unmatched_ws7'], m['unmatched_engine'])

    for t in unmatched_ws7:
        add(REASON_WORD_UNMATCHED, t['page'], round(t['y_top'], 1), [t['text']],
            [round(t['x'], 1), round(t['y_top'], 1)], None, t['tier'],
            detail='WS7 word has no corresponding word anywhere in the engine output')

    for t in unmatched_engine:
        add(REASON_EXTRA_WORD_IN_ENGINE, t['page'], round(t['y_top'], 1), [t['text']],
            None, [round(t['x'], 1), round(t['y_top'], 1)], t['font_class'],
            detail='engine word has no corresponding word anywhere in the WS7 capture')

    by_page = defaultdict(list)
    for (w, e), d in zip(m['pairs'], deltas):
        by_page[d['ws7_page']].append((w, e, d))

    # ABSOLUTE (not per-page-normalized) frame offset for the whole
    # document -- restricted to line-start words, since those are pure
    # left-margin measurements (the page's own resolved `.po`) and aren't
    # diluted by mid-line font-substitution width drift the way an
    # arbitrary word's dx would be. For a sawyer-wschange capture this is
    # report-only -- it exists so a real, corpus-wide, systematic shift
    # (mechanism S's own reversal, tools/PCL-DIVERGENCE-TRIAGE.md: every
    # ws7-prints/v1/v2 capture was made on Robert J. Sawyer's own
    # WSCHANGE-customized WordStar 7 install, whose `.po` factory default
    # is one column, 7.2pt, off stock WS7's) stays VISIBLE here instead of
    # being silently absorbed the way the per-page median-dx calibration
    # below absorbs it before anything downstream ever sees it. For a
    # PRISTINE-install (v3) capture, though, this same number is expected
    # to be 0.0pt -- the engine models stock WordStar 7 -- so it graduates
    # from report-only to a real FAIL below (pristine_offset_exceeds_
    # tolerance / REASON_PRISTINE_FRAME_OFFSET).
    line_start_same_page_deltas = [d for (w, e), d in zip(m['pairs'], deltas)
                                   if w['is_line_start'] and d['same_page']]
    _doc_offset = fg.frame_offset(line_start_same_page_deltas)
    document_frame_offset_pt = {'n': _doc_offset['n_dx'],
                                'median_dx': _doc_offset['median_dx'],
                                'iqr_dx': _doc_offset['iqr_dx']}

    if pristine_offset_exceeds_tolerance(install, document_frame_offset_pt['median_dx']):
        add(REASON_PRISTINE_FRAME_OFFSET, None, None, None, None, None, None,
            detail=f"pristine-install absolute frame offset "
                   f"{document_frame_offset_pt['median_dx']:+.2f}pt exceeds the line-start "
                   f"tolerance ({LINE_START_EPS_PT}pt) -- a stock/pristine capture is expected "
                   f"to match this engine's stock-default rendering at 0.0pt")

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
                add(REASON_BASELINE_SHIFT, page, round(w['y_top'], 1), words, ws7_pos, pdf_pos,
                    tier, detail=f'baseline residual {resid_dy:+.2f}pt '
                                 f'(tolerance {BASELINE_EPS_PT}pt)')
                continue

            # Line-start x applies to EVERY font too (margin/indent, not glyph width).
            if w['is_line_start']:
                if abs(resid_dx) > LINE_START_EPS_PT:
                    add(REASON_LINE_START_SHIFT, page, round(w['y_top'], 1), words, ws7_pos,
                        pdf_pos, tier, detail=f'line-start residual {resid_dx:+.2f}pt '
                                     f'(tolerance {LINE_START_EPS_PT}pt)')
                continue

            if tier == TIER_EXACT:
                if abs(resid_dx) > EXACT_EPS_PT:
                    add(REASON_EXACT_DRIFT, page, round(w['y_top'], 1), words, ws7_pos, pdf_pos,
                        tier, detail=f'residual {resid_dx:+.2f}pt (tolerance {EXACT_EPS_PT}pt, '
                               f'exact/fixed-pitch font)')
            elif tier == TIER_CGTIMES:
                tol = cgtimes_tolerance_pt(w['dist_into_line_pt'])
                if abs(resid_dx) > tol:
                    add(REASON_CGTIMES_DRIFT_EXCEEDS_TOLERANCE, page, round(w['y_top'], 1), words,
                        ws7_pos, pdf_pos, tier,
                        detail=f'residual {resid_dx:+.2f}pt at {w["dist_into_line_pt"]:.1f}pt '
                               f'into the line (tolerance {tol:.2f}pt)')
            elif tier == TIER_UNIVERS:
                tol = univers_tolerance_pt(w['dist_into_line_pt'])
                if abs(resid_dx) > tol:
                    add(REASON_UNIVERS_DRIFT_EXCEEDS_TOLERANCE, page, round(w['y_top'], 1), words,
                        ws7_pos, pdf_pos, tier,
                        detail=f'residual {resid_dx:+.2f}pt at {w["dist_into_line_pt"]:.1f}pt '
                               f'into the line (tolerance {tol:.2f}pt)')
            elif tier == TIER_NO_SUBSTITUTE:
                # Word-level x is not evaluated for this tier, by rule (see module
                # docstring) -- only counted, so the manifest can show how many
                # words fell outside this check's scope without spamming entries.
                no_substitute_word_count += 1
            else:
                add(REASON_UNCLASSIFIED_FONT_TIER, page, round(w['y_top'], 1), words, ws7_pos,
                    pdf_pos, tier, detail=f'WS7 typeface id {w.get("tid")!r} has no tier mapping')

    real_reasons = [r for r in counts if not is_font_substitution_reason(r)]
    verdict = 'divergent' if any(counts[r] for r in real_reasons) else 'clean'

    return {
        'doc': doc_name, 'verdict': verdict,
        'source_ws': _source_ws_for_report(doc_name, ws_path),
        'capture_set': capture_set, 'install': install,
        'n_ws7_pages': n_ws7_pages, 'n_engine_pages': n_engine_pages,
        'no_substitute_word_count': no_substitute_word_count,
        'counts_by_reason': dict(sorted(counts.items())),
        'divergences': [d for r in sorted(by_reason) for d in by_reason[r]],
        'document_frame_offset_pt': document_frame_offset_pt,
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
                 'never regenerate inside the test run itself. Install provenance used to '
                 'be one blanket header note (every ws7-prints/v1 capture was produced '
                 "through Robert J. Sawyer's own WSCHANGE-customized WordStar 7 install, "
                 'confirmed NOT stock via a direct PRISTINE.EXE probe, Jon\'s ruling '
                 '2026-09-06) -- it is now PER-DOCUMENT (each entry below carries its own '
                 "`capture_set`/`install`), since the corpus is captured incrementally and a "
                 'future v3 (PRISTINE.EXE) recapture of some documents and not others would '
                 'make one blanket claim wrong the moment it happened. A sawyer-wschange '
                 "document's real, expected, install-specific +7.2pt (one Courier column) "
                 "frame offset against this engine's stock-default rendering is still visible "
                 "per document at `document_frame_offset_pt` (absolute, NOT the per-page-"
                 'normalized residuals `counts_by_reason` reports on) -- see '
                 'tools/PCL-DIVERGENCE-TRIAGE.md mechanism S\'s reversal for the full trace. '
                 'A pristine-install document with the same kind of nonzero offset is a real '
                 "FAIL (`pristine-frame-offset-exceeds-tolerance`), not a report-only note --"
                 ' see pcl_tolerance.pristine_offset_exceeds_tolerance.'),
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
    ap.add_argument('--engine-words', help='with --doc: judge a PRE-EXTRACTED engine-words '
                    'JSON file (see fidelity_gate.py\'s "engine-words (JSON)" schema comment) '
                    'instead of rendering/parsing this repo\'s own PDF for that document -- '
                    'e.g. a words file produced from a Quartz-emitted PDF this repo cannot '
                    'parse as its own. Not valid with --record.')
    a = ap.parse_args(argv)

    if a.engine_words and a.record:
        ap.error('--engine-words is not valid with --record')

    if a.doc:
        engine_words = json.load(open(a.engine_words)) if a.engine_words else None
        print(json.dumps(doc_report(a.doc, engine_words=engine_words), indent=2))
        return 0

    if a.record:
        manifest = regenerate_manifest()
        with open(MANIFEST_PATH, 'w') as f:
            json.dump(manifest, f, indent=2, sort_keys=False)
            f.write('\n')
        print(f'wrote {MANIFEST_PATH}', file=sys.stderr)
        for name, entry in manifest['documents'].items():
            offset = entry.get('document_frame_offset_pt') or {}
            print(f"  {name}: [{entry.get('capture_set')}/{entry.get('install')}] "
                 f"{entry['verdict']}  {entry.get('counts_by_reason', {})}  "
                 f"abs_offset_dx={offset.get('median_dx')}pt (n={offset.get('n')})")
        return 0

    ap.error('need --record or --doc NAME')


if __name__ == '__main__':
    raise SystemExit(main())
