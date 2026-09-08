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
CAPTURED_DOCS_V1V3 = [
    'BOXES', 'DOCA', 'DOCB', 'DOCC', 'DOCD', 'LJ6DTP', 'LYING', 'OCAPTAIN',
    'DOCE', 'PREVIEW', '-README', 'SAWYER', '-SCREEN', 'SCRIPT', 'DOCF',
    'TWAINLET', 'VERSIONS', 'WARPRAYR',
]
# planning #180 phase 2 ("tests expanded", 2026-09-08): the 243-document
# ws7-prints/v4/ expansion -- single source of truth is
# fg.CAPTURED_DOCS_V4 (fidelity_gate.py, alongside fg.resolve_v4_capture,
# since that's where the v4 dispatch/resolution lives; this module just
# re-exports it so every existing `pt.CAPTURED_DOCS_V4` reference some
# callers may already expect from this module keeps working). CAPTURED_DOCS
# below is the full 261-document pytest-parametrize list: the 18 original
# v1/v3 documents (unchanged, still checked to the same fail-by-name
# standard test_pcl_fidelity.py always has) PLUS the 243 v4 ones (run in
# that same test's own "inventory" mode -- see INVENTORY_MODE_DOCS below
# and that test file's own docstring update).
CAPTURED_DOCS_V4 = fg.CAPTURED_DOCS_V4
CAPTURED_DOCS = CAPTURED_DOCS_V1V3 + CAPTURED_DOCS_V4
# The set test_pcl_fidelity.py checks to decide whether a document's own
# non-font-substitution divergences fail the tier by name (the original
# 18's own law, unchanged) or are report-only pending Jon's per-cause
# ruling (every v4 document -- planning #180 phase 2 Task 6: "do not mark
# anything as expected/known/skipped to make a suite green ... run in
# inventory mode ... but the test output must still name every divergent
# document"). A manifest DRIFT (live != recorded) still fails for BOTH
# sets unconditionally -- that catches an engine regression regardless of
# which set a document is in; only the "real bug already known and
# unruled" bar is different.
INVENTORY_MODE_DOCS = frozenset(CAPTURED_DOCS_V4)

# ----------------------------------------------------------- v4 exclusions
# (planning #224/#226, ruled 2026-09-08). Five classes beyond the 48 merge
# files already absent from CAPTURED_DOCS_V4 above: 'postscript' (3 real
# PostScript-targeted documents + their 2 fixtures-ws5 duplicates -- an
# unclassified PS typeface ID, not a placement bug -- Jon's ruling 2026-09-08
# 06:13), 'freeze' (OLDTIMES.WS + its fixtures-ws5 duplicate -- WordStar itself
# freezes printing this document), 'duplicate' (the non-canonical half of 19
# of the 42 byte-identical pairs recorded in the corpus's own
# ws7-prints/v4/exclusions.json -- the other 23 pairs' duplicate half was
# already one of the 48 merge files, or is one of the 5 postscript/freeze
# names above, so isn't repeated here), 'formfeed-off' (2 documents that turn
# form feeds off with the .xl dot command, so real WS7 overprints multiple
# pages onto one physical sheet -- unrepresentable as PDF pages; standing
# parked issue planning #15, this exclusion does not open a new issue -- see
# EXCLUDED_V4's own two entries for which two documents and how they were
# found), and 'parked' (planning #228, Jon's ruling 2026-09-08: an
# investigated-but-unresolved single document, unconnected to any standing
# parked issue -- see EXCLUDED_V4's own entry for detail. Named in every run,
# same as the rest of this dict, so a future fix removes it from this list
# rather than the gate silently going green on an unreviewed change).
# Full detail (sha256, which half was kept, cross-references) lives
# in the PRIVATE corpus repo's own ws7-prints/v4/exclusions.json -- this dict
# only carries what this PUBLIC repo needs: the doc_name these tests already
# use (real key or public_alias, same resolution CAPTURED_DOCS_V4 itself
# uses) and a reason safe to publish (a fixtures-ws5/jon-floppies/ws7-private
# document's OWN real path never appears here -- only the public sawyer/
# document it duplicates, same privacy rule PRINTS_SUBDIR_V4's docstring
# states for divergence reports).
#
# These names STAY in CAPTURED_DOCS_V4/CAPTURED_DOCS (the pytest tier still
# collects a case for each -- 261 total, unchanged) so the gate skips them BY
# NAME with this reason printed, every run, rather than silently shrinking the
# parametrize list. The ACTIVE tier size (the denominator that matters for a
# pass-rate claim) is 261 - 29 = 232 (28 postscript/freeze/duplicate/
# formfeed-off + 1 parked, as of planning #228) -- regenerate_manifest below writes a
# verdict='excluded' placeholder for each (never a real doc_report()), so a
# future `--record` run reproduces the skip without recomputing anything, and
# a future v4 capture round finds these names pre-excluded rather than
# rediscovering the same ruling.
EXCLUDED_V4 = {
    'sawyer__REF__PS_EXT_TST': "postscript: PostScript-targeted document (sawyer/REF/PS.TST) -- excluded from the PCL tier, Jon's ruling 2026-09-08 06:13 (planning #224)",
    'privgroup-c-v4-007': "postscript: PostScript-targeted document, byte-identical duplicate of sawyer/REF/PS.TST -- excluded from the PCL tier, Jon's ruling 2026-09-08 06:13 (planning #224)",
    'sawyer__PSPRINT_EXT_TST': "postscript: PostScript-targeted document (sawyer/PSPRINT.TST) -- excluded from the PCL tier, Jon's ruling 2026-09-08 06:13 (planning #224)",
    'sawyer__RTF-RJS__NOVEL_EXT_WS': "postscript: PostScript-targeted document (sawyer/RTF-RJS/NOVEL.WS) -- excluded from the PCL tier, Jon's ruling 2026-09-08 06:13 (planning #224)",
    'privgroup-c-v4-005': "postscript: PostScript-targeted document, byte-identical duplicate of sawyer/RTF-RJS/NOVEL.WS -- excluded from the PCL tier, Jon's ruling 2026-09-08 06:13 (planning #224)",
    'sawyer__OLDTIMES_EXT_WS': "freeze: WordStar itself freezes printing sawyer/OLDTIMES.WS -- excluded from the PCL tier, Jon's ruling 2026-09-08 (planning #224)",
    'privgroup-c-v4-006': "freeze: WordStar itself freezes printing this document (byte-identical duplicate of sawyer/OLDTIMES.WS) -- excluded from the PCL tier, Jon's ruling 2026-09-08 (planning #224)",
    'privgroup-c-v4-001': "duplicate: byte-identical duplicate of sawyer/REF/-ATTRIB.TST -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'privgroup-c-v4-003': "duplicate: byte-identical duplicate of sawyer/RTF-RJS/MARKUP.WS -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'privgroup-c-v4-004': "duplicate: byte-identical duplicate of sawyer/REF/NOTES.TST -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'privgroup-c-v4-008': "duplicate: byte-identical duplicate of sawyer/RTF-RJS/RTFDS.WS -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'privgroup-c-v4-009': "duplicate: byte-identical duplicate of sawyer/REF/SUB-SUPE.TST -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'privgroup-c-v4-011': "duplicate: byte-identical duplicate of sawyer/REF/WSFORMAT.WS -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__BOX': "duplicate: byte-identical duplicate of sawyer/BOX.WS (sawyer/DEFAULT/BOX is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__DEFAULT_EXT_WS': "duplicate: byte-identical duplicate of sawyer/REGULAR.WS (sawyer/DEFAULT/DEFAULT.WS is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__INSET__GRAPHICS_EXT_DOC': "duplicate: byte-identical duplicate of sawyer/INSET/GRAPHICS.DOC (sawyer/DEFAULT/INSET/GRAPHICS.DOC is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__LIST_EXT_DOC': "duplicate: byte-identical duplicate of sawyer/LIST.DOC (sawyer/DEFAULT/LIST.DOC is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__MAILING_EXT_DOC': "duplicate: byte-identical duplicate of sawyer/MAILING.DOC (sawyer/DEFAULT/MAILING.DOC is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__PLAYBILL_EXT_DOC': "duplicate: byte-identical duplicate of sawyer/PLAYBILL.DOC (sawyer/DEFAULT/PLAYBILL.DOC is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__PLAYS_EXT_DOC': "duplicate: byte-identical duplicate of sawyer/PLAYS.DOC (sawyer/DEFAULT/PLAYS.DOC is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__REVIEW_EXT_DOC': "duplicate: byte-identical duplicate of sawyer/REVIEW.DOC (sawyer/DEFAULT/REVIEW.DOC is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__SHAKE_EXT_DOC': "duplicate: byte-identical duplicate of sawyer/SHAKE.DOC (sawyer/DEFAULT/SHAKE.DOC is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__DEFAULT__SPELL_EXT_DOC': "duplicate: byte-identical duplicate of sawyer/SPELL.DOC (sawyer/DEFAULT/SPELL.DOC is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__PRINTERS__FONTCRIB_EXT_PS': "duplicate: byte-identical duplicate of sawyer/PRINTER.PS (sawyer/PRINTERS/FONTCRIB.PS is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__REF__BOOKLET_EXT_RJS': "duplicate: byte-identical duplicate of sawyer/REF/-HOW-TO.RJS (sawyer/REF/BOOKLET.RJS is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__TAGS__OK': "duplicate: byte-identical duplicate of sawyer/TAGS/CHECKED (sawyer/TAGS/OK is the excluded half) -- excluded from the PCL tier so duplicate content isn't judged twice, Jon's ruling 2026-09-08 (planning #226)",
    'sawyer__ARTICLES__FORMFEED_EXT_WS': "formfeed-off: turns form feeds off with .xl 00 (and back on with .xl 0c) -- real WS7 overprints multiple pages onto one physical sheet, unrepresentable as PDF pages; standing parked issue planning #15, Jon's ruling 2026-09-08",
    'sawyer__REF__ROUNDED_EXT_BRD': "formfeed-off: sets .xl 00 (form feeds off) at the top of the document -- a continuous-label/border template for unbroken stationery, found by scanning the rest of the v4 batch for the same dot command; standing parked issue planning #15, Jon's ruling 2026-09-08",
    # planning #228: investigated alongside the trailing-`.pa` rule (same
    # visible symptom -- a footer-only final page -- but ruled OUT as that
    # mechanism: its own `.pa` trailer is the standard byte-for-byte shape
    # every "no extra page" document shares, none of the saved-blank-
    # paragraph signature PAGESIZE.WS has). Best available explanation:
    # this document's embedded absolute-position raster graphics (a
    # LaserJet box/shading demo, 5,288 bytes of PCL on page 1 alone)
    # overrun the printable area and WS7's driver ejects a page as a side
    # effect -- a document-specific quirk of this one `.BRD` file, not
    # evidence about `.pa` in general. See
    # research/2026-09-08_trailing-pa-rule.md's own "CHECKER.BRD" section.
    'sawyer__LSRBOX__CHECKER_EXT_BRD': "parked: unexplained extra page, graphics overflow suspected — Jon 2026-09-08",
}

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
    # ---- ADDED planning #225 (2026-09-08): the four PostScript-document IDs
    # -- see pcl_render.TYPEFACE_FAMILY's own comments for the identity
    # citations (IBM technote, groff devlj4, HP PCL5 TRM Part 1). Tier
    # choice per research's own proposal (research/2026-09-08_ws7-
    # postscript-typeface-ids-B.md "Tier-fit proposal"), ledger ruling
    # "PostScript-document typefaces: mapping approved, all font targets".
    0: TIER_EXACT,       # LinePrinter -- real resident fixed-pitch bitmap
                          # font (not a substitution), same class as Courier
                          # bitmap ID 3.
    16602: TIER_UNIVERS,  # Arial, substituted for WS "Triumvirate" (175) --
                          # Arial is a metric-compatible Helvetica clone
                          # (Monotype, licensed to HP), the same
                          # substitution-quality class this project already
                          # accepts for Univers->Helvetica (ID 4148); shares
                          # that tier's bound rather than a new curve (no
                          # independent word-pair data for 16602 yet).
    16686: TIER_EXACT,   # Symbol -- not a substitution at all: WordStar
                          # requests the printer's real resident Symbol font
                          # by this exact HP ID, and our own PDF draws the
                          # project's real base-14 Symbol face (afm.py) --
                          # same "requested face IS the rendered face" status
                          # as ID 4 (Helvetica, real). Monotype's cut (this
                          # PCL ID) vs. Adobe's base-14 cut are different
                          # vendors' metrics for the same encoding -- flagged
                          # by the research as unmeasured, same epistemic
                          # status as ID 4's own "documented but unobserved"
                          # note; revisit with real word-pair data once a
                          # PostScript document re-enters the tier (#224).
    31402: TIER_NO_SUBSTITUTE,  # Wingdings, substituted for WS
                          # "ZapfDingbats" (82) -- a DIFFERENT pi-font from
                          # WordStar's own name (different glyph-to-code
                          # map); this project's PDF draws real ZapfDingbats,
                          # not a Wingdings clone, so there is no honest
                          # metric floor for a word-position check, same
                          # reasoning as the existing no-substitute group.
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
#
# FIX 2 ("one rule in one place for every input", 2026-09-07): what counts
# as box-drawing is now defined ONCE, in fg (fidelity_gate.py's own
# `_BOX_DRAWING_RANGES`/`_is_box_drawing_char`/`_is_box_drawing_text`) --
# the engine side's `_op_chars`/`_external_chars_to_tokens` need the exact
# same test, at CHARACTER granularity, to drop a box-drawing glyph fused
# onto real text (e.g. the app's own Native-facsimile '│Figure'); this
# module keeps its own name bound to that single definition rather than a
# second copy that could drift from it.
_BOX_DRAWING_RANGES = fg._BOX_DRAWING_RANGES
_is_box_drawing_text = fg._is_box_drawing_text


# fg.match_doc aligns WHOLE-DOCUMENT token streams purely by text equality
# (difflib.SequenceMatcher) -- sound for ordinary words, but WordStar's own
# driver frequently emits short punctuation as its OWN standalone PCL
# chunk (a comma, a closing paren, a bare "A"/"B"/"C" list marker), split
# from the word it visually follows -- something our engine's word
# splitter never does (`fg.segment_words_from_chars` keeps "Hello," together). A doc with
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


def _strip_box_drawing_chunk_edges(items):
    """Mechanism N (triage 2026-09-06 residuals round; generalized to both
    edges 2026-09-07, FIX 2, "one rule in one place for every input"): a
    WS7 print chunk that combines a box-drawing/table-border character
    directly against a real word with no space (SCRIPT.WS's own
    '│Figure', a table-bordered figure caption) is, for WS7's own driver,
    one literal character run -- the LaserJet's resident Courier charset
    draws box-drawing glyphs as ordinary text, same font, same advance,
    no different from any other character. Our own engine draws a
    box-drawing character as a VECTOR (`_graphic_ops`, Jon's ruling:
    box/rule fidelity is a real drawn line, not a font glyph standing in
    for one) and keeps it entirely separate from the adjoining text span
    (`_split_graphics`) -- so the two sides' text streams can never
    literally match on a chunk like this no matter how correct the
    position: our own 'Figure' token never carries a box character, and
    never will.

    Strips a WS7 chunk's own LEADING **and TRAILING** box-drawing/block/
    geometric run (`_BOX_DRAWING_RANGES`) before matching -- the same
    symmetry `fg._op_chars`/`fg._external_chars_to_tokens` apply to a
    character list on the engine side (drop the box-drawing character
    wherever it sits, leading or trailing, and keep the rest positioned
    exactly where it already was). A LEADING run's removal corrects the
    chunk's own x forward by the stripped run's own natural AFM width --
    the same "this is what our engine's own text stream would show"
    normalization mechanisms C/J/K already give this driver's other
    representation differences; a TRAILING run needs no such correction
    at all (the chunk's own x, its left edge, is unchanged by removing
    characters off its right end). A chunk that is NOTHING BUT
    box-drawing characters (the leading and trailing strips meet in the
    middle) is left alone -- `_is_box_drawing_text`'s own territory,
    applied later in `load_ws7_tokens`."""
    out = []
    for pc, tc in items:
        text = pc['text']
        i = 0
        while i < len(text) and any(lo <= ord(text[i]) < hi
                                    for lo, hi in _BOX_DRAWING_RANGES):
            i += 1
        j = len(text)
        while j > i and any(lo <= ord(text[j - 1]) < hi
                            for lo, hi in _BOX_DRAWING_RANGES):
            j -= 1
        if i == 0 and j == len(text):
            out.append((pc, tc))
            continue
        if i >= j:
            out.append((pc, tc))  # nothing but box-drawing -- left alone
            continue
        prefix, core = text[:i], text[i:j]
        shift_dp = round(fg.afm.string_width_pt(prefix, pc.get('font'),
                                                 pc['size_pt']) * fg.DECIPT_PER_PT)
        out.append((dict(pc, text=core, x_decipoints=pc['x_decipoints'] + shift_dp), tc))
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
    and two genuinely different words never land within so small a gap).

    Mechanism Z's own residuals round (2026-09-07) moved mechanism J
    (toggle-boundary correction, below) to run BEFORE this function
    instead of after -- SAWYER.WS's own 'D,B,A,C),' menu-tag list has
    FOUR separate ',' chunks that used to all share the SAME stale raw
    x=57.6pt (mechanism J's own class of bug: none of them ever got a
    real repositioning command), which this function's own same-key/
    near-x rule misread as double-strike duplicates of the first comma
    purely by coincidence. Running J first resolves each one to its own
    real, distinct, cascading position BEFORE this function ever looks
    at x at all, so they no longer collide -- while a REAL double-strike
    duplicate (this function's own confirmed territory: identical text
    reprinted at the identical real position, always the SAME font both
    times) is never something J's own font-CHANGE-triggered correction
    touches in the first place (J only fires when font or underline
    DIFFERS between two raw-same-x chunks; a genuine duplicate's two
    copies share a font, by construction) -- so this function's own
    detection is unaffected for every case it was ever meant to catch,
    including ones separated by other, unrelated chunks at a shared
    stale x (SCRIPT.WS's own '^P^K' bold double-strike, with an
    unrelated toggle-boundary comma sandwiched at the same raw x)."""
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
    `_strip_box_drawing_chunk_edges` (mechanism N).

    Runs BEFORE mechanisms D/C/K (moved here in mechanism Z's own
    residuals round, 2026-09-07): a chain of chunks that never got a real
    repositioning command (this function's own territory) can share one
    stale raw x across MORE than two chunks (SAWYER.WS's own
    'D,B,A,C),' menu-tag list, five chunks deep) -- resolving every one
    of them to its own real, distinct, cascading position FIRST means
    mechanism D's own same-position duplicate check (and mechanism C's/
    K's own gap checks) never mistake two DIFFERENT chunks that only
    coincidentally shared a stale x for a real duplicate or a real
    kerning/punctuation split. This function's own "toggled" condition
    (font OR underline differs from the IMMEDIATE predecessor at the
    same raw x) is NOT actually disjoint from mechanism D's own target,
    though, the way an earlier version of this docstring claimed: a
    genuine double-strike's SECOND strike can land with a DIFFERENT-font
    chunk as its own immediate predecessor at that shared x too, whenever
    the rest of that chunk's own sentence gets emitted BETWEEN the two
    strikes in the raw stream (confirmed real: -README.WS's own
    'LASERJET.PDF', double-struck bold, with ', and WS4.PDF).' emitted in
    between) -- the `is_repeat` guard above (the exact two-back SANDWICH
    shape a real double-strike always has, see its own comment) is what
    keeps this function from
    "correcting" that second strike into a meaningless position instead
    of leaving it alone for mechanism D to recognize and dedupe.

    Corrections CHAIN: each chunk's own corrected ("real") x, font, text
    and underline state feed forward as the base a LATER glued chunk
    advances from, while glue-DETECTION still compares against the
    preceding chunk's own RAW (uncorrected) x -- required for a run of
    MORE than one glued chunk in a row (the URL-then-")" pair above is
    exactly this shape: ")"'s raw x equals the URL's raw x, not the URL's
    corrected x, so detection must use the raw value even as advancement
    uses the corrected one). A single-pair chain -- mechanism J's own
    original BOXES case -- is the n=1 special case of the same loop."""
    # Pre-scan for the one shape a genuine mechanism-D double-strike
    # re-strike always has -- confirmed real on -README.WS's own
    # 'LASERJET.PDF' (bold), double-struck, with the rest of its own
    # sentence (', and WS4.PDF).') emitted BETWEEN the two strikes in
    # the raw stream: a run of EXACTLY THREE consecutive same-raw-x
    # chunks, shaped `A, B, A` (first and third share a key, the middle
    # one -- always the visually-following punctuation -- does not).
    # The second strike's own immediate predecessor is that middle
    # chunk, a DIFFERENT font, exactly this function's own toggle shape
    # -- but wrong: the second strike must stay at its own real,
    # unmodified position for mechanism D (which runs next) to
    # recognize and dedupe, not be "corrected" into some new,
    # meaningless position past the punctuation. Scoped to EXACTLY three
    # (never "any repeat anywhere in a same-x run"): SAWYER.WS's own
    # 'D,B,A,C),' menu-tag chain is eight chunks deep at ONE shared raw
    # x, and its own two matching commas sit four apart, not two, so a
    # length-3 run never forms there at all -- confirmed this fires
    # correctly even for a SHORT/generic repeated token (-README.WS's
    # own single-BOLD-LETTER double-strikes, 'D,,D' and 'B,,B', each
    # their OWN separate 3-run at a different x), which no text-length
    # heuristic could ever safely distinguish from SAWYER's own chain.
    repeat_ids = set()
    run_start = 0
    n = len(items)
    for i in range(1, n + 1):
        if i == n or items[i][0]['x_decipoints'] != items[run_start][0]['x_decipoints']:
            if i - run_start == 3:
                first_pc, _first_tc = items[run_start]
                third_pc, third_tc = items[run_start + 2]
                first_key = (first_pc['text'], first_pc.get('font'), first_pc['size_pt'],
                            items[run_start][1].get('_T'))
                third_key = (third_pc['text'], third_pc.get('font'), third_pc['size_pt'],
                            third_tc.get('_T'))
                if first_key == third_key:
                    repeat_ids.add(id(third_pc))
            run_start = i

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
        is_repeat = id(pc) in repeat_ids
        toggled = (prev_raw_x is not None and raw_x == prev_raw_x
                   and (pc.get('font') != prev_real_font
                        or bool(pc.get('underline')) != bool(prev_underline))
                   and not is_repeat)
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


TRAILING_OCCUPANT_WINDOW_DP = 300  # 30pt -- how far past a printed line's own
                                   # last chunk to look for a footnote/
                                   # end-note reference marker that has no
                                   # following same-baseline chunk to bound
                                   # a gap window against (DOCC.WS's own
                                   # footnote markers: 1-2 raised digits,
                                   # 9.25pt Courier, never wider than
                                   # ~11pt -- this is generous vs that,
                                   # while nowhere near a real word's own
                                   # width).
SUPSUB_MAX_DY_DP = 80  # 8pt -- generous vs. every measured real WS7
                       # super/subscript offset in this corpus (DOCC's
                       # own footnote-reference superscript AND -SCREEN's
                       # own subscript demo both measure exactly 4.5pt of
                       # vertical offset from their line's own baseline),
                       # while comfortably short of a genuinely different
                       # printed LINE (which sits at least one whole
                       # leading away, always >8pt in this corpus's own
                       # body sizes).


def _find_offbaseline_occupant(page_chunks, gap_x0_dp, gap_x1_dp, line_y_dp):
    """A super/subscript character sits on a DIFFERENT y than the line it
    visually belongs to -- WS7's own driver really does move the pen
    vertically for it (confirmed directly: DOCC's own footnote-
    reference '1' after 'Indians.' sits 4.5pt ABOVE its line's baseline;
    -SCREEN's own subscript '2' in 'H2O' sits 4.5pt BELOW), unlike this
    engine's own PDF, which keeps the SAME Td line-position and only
    applies a `Ts` rise (mechanism G). Left un-stitched, a real super/
    subscript character inside a word makes the two same-baseline WS7
    chunks either side of it look like they have a big horizontal GAP
    between them (the sub/superscript character's own width, sitting on
    the wrong y for `_merge_zero_gap_cross_font_chunks`'s own single-
    baseline character stream to see) -- exactly backwards from
    mechanism Z's usual problem (an unexplained SMALL gap that should
    merge); here an explained LARGE gap must still merge, with the
    occupant's own text spliced in.

    `page_chunks` is every (pc, tc) pair on the WHOLE page (any y, not
    just this line's). Returns the ONE chunk whose own natural x-span, in
    decipoints, falls (within one WORD_GAP_SLACK_PT's own decipoint
    equivalent either side) INSIDE [gap_x0_dp, gap_x1_dp], whose y is
    within SUPSUB_MAX_DY_DP of `line_y_dp` but NOT equal to it (a real
    super/subscript offset, never this same printed line), and whose own
    text `_is_unreliable_to_align` -- so this only ever absorbs a chunk
    that could never have become its own standalone checkable token
    anyway (a lone digit, a bare footnote marker), never a real,
    independently-matchable word; nothing is ever double-counted. Returns
    None (never stitched) when zero or more than one candidate matches --
    ambiguous is left alone, conservative by design."""
    slack_dp = round(fg.WORD_GAP_SLACK_PT * fg.DECIPT_PER_PT)
    candidates = []
    for pc, tc in page_chunks:
        y = pc['y_decipoints']
        if y == line_y_dp or abs(y - line_y_dp) > SUPSUB_MAX_DY_DP:
            continue
        if not _is_unreliable_to_align(pc['text']):
            continue
        x0 = pc['x_decipoints']
        x1 = x0 + round(fg.afm.string_width_pt(pc['text'], pc.get('font'), pc['size_pt'])
                        * fg.DECIPT_PER_PT)
        if x0 >= gap_x0_dp - slack_dp and x1 <= gap_x1_dp + slack_dp:
            candidates.append((pc, tc))
    return candidates[0] if len(candidates) == 1 else None


def _merge_zero_gap_cross_font_chunks(items, page_chunks=None):
    """Mechanism Z (triage 2026-09-07, Jon's ruling from the real-LaserJet
    paper scan of -SCREEN, the private corpus's own verdicts.json doc87 p6):
    the WS7-side half of same-side segmentation -- builds the SAME
    character-level word boundaries `fg.engine_page_tokens` now builds on
    the engine side (`fg.segment_words_from_chars`/`fg.char_space_
    width_pt`) from THIS WS7 print line's own already-cleaned chunk
    stream (after mechanisms N/D/C/K/J, above), so a word is the same set
    of characters on both sides regardless of which side happened to
    split it across more than one op/chunk. A gap that is fully
    accounted for by a super/subscript character sitting on a nearby,
    DIFFERENT y (see `_find_offbaseline_occupant`, immediately above) is
    stitched in too, so e.g. -SCREEN's own 'H' + subscript '2' + 'O'
    reconstructs as the one word 'H2O' this engine's own PDF already
    writes (mechanism G: the engine keeps one Td line and only applies a
    `Ts` rise, so it never had this problem on its own side).

    Unlike mechanism C (kerning-pair splits) and mechanism K (trailing
    punctuation), this does NOT require the two chunks to share a font --
    it is the general case those two are conservative, same-font-only
    special cases of: WS7's own driver sometimes starts a fresh print
    chunk (a style toggle, a font-substitution boundary) with NO real
    horizontal movement of the pen at all, and when that happens the two
    chunks are, visually, ONE continuous word/run -- exactly like
    -SCREEN's own cp437 Greek/math demo line, captured as ONE
    14-character WS7 chunk per styled repetition already (nothing to
    merge on THIS side for that document -- see the engine-side fix,
    `fg.engine_page_tokens`, mechanism Z, for why that line needed
    fixing at all).

    Confirmed correct on SAWYER.WS's own 'WSMSGS.OVR' (bold) + '.]'
    (plain): real WS7 prints them at IDENTICAL zero gap (once mechanism
    J's own toggle-boundary correction resolves '.]' 's real position --
    its raw captured x is stale, inherited from 'WSMSGS.OVR' 's own last
    real `H` command, exactly mechanism J's own documented shape), the
    SAME zero gap this engine's own PDF already places them at. The
    first attempt at this merge (2026-09-07, reverted the same day) only
    ever touched the engine side, so this exact WS7 chunk pair stayed
    unmerged under mechanism C/K's own same-font-only rule while the
    engine side merged anyway -- a real cross-side MATCHING mismatch, not
    an engine divergence, turning six previously-clean documents
    divergent. Merging both sides under the SAME rule fixes both: this
    line, and that one -- confirmed real, not a guess: WordStar printed
    them touching, so one word on both sides is the CORRECT result, not
    a workaround.

    `items` is one WS7 print line's (pc, tc) pairs, already sorted by x
    and already through `_strip_box_drawing_chunk_edges`/`_correct_
    toggle_boundary_chunks`/`_dedupe_double_strike_chunks`/`_merge_
    kerning_split_chunks`/`_merge_trailing_punctuation_chunks` (in that
    order -- see mechanism J's own docstring for why J now runs before
    D/C/K). `page_chunks`
    (every (pc, tc) pair on the WHOLE page, any y) enables the off-
    baseline super/subscript stitching described above; omit it (None,
    the default) to skip that half and merge same-baseline chunks only --
    every Tier-1 synthetic fixture that builds a single line by hand uses
    this default. A chunk that does NOT advance the line -- its own x
    lands at or before the running end of everything placed so far, e.g.
    a literal dash-overlay chunk WS7 emits at the SAME position as the
    word it strikes through (`-SCREEN`/`-README`'s own "Strike-out"
    demo: a '----------' chunk printed a second time directly on top of
    the word, not a real, exact double-strike duplicate mechanism D
    already dedupes, since its text differs) -- is a same-POSITION
    overlay, not a same-LINE continuation; the character model this
    function builds only ever describes side-by-side placement, so such
    a chunk never enters it at all and is returned UNTOUCHED, in its own
    original position in the output list (still subject to every
    downstream filter -- `_is_box_drawing_text`/`_is_unreliable_to_align`
    -- exactly as before this mechanism existed). Returns a new
    `(pc, tc)` list, sorted by x, in the same shape; a merged chunk keeps
    the FIRST character's own `tc` (so its `_T`/typeface-id-derived tier
    is unaffected) and the first chunk's own position/font/size, the same
    convention every other merge function in this file already uses."""
    slack_pt = fg.WORD_GAP_SLACK_PT
    chars = []
    overlays = []
    normal_items = []
    running_end_pt = None
    for pc, tc in items:
        x_pt = pc['x_decipoints'] / fg.DECIPT_PER_PT
        if running_end_pt is not None and x_pt < running_end_pt - slack_pt:
            overlays.append((pc, tc))  # same-position overlay, not a continuation
            continue
        basefont = pc.get('font')
        size_pt = pc['size_pt']
        space_w = fg.char_space_width_pt(basefont, size_pt)
        cursor = x_pt
        for ch in pc['text']:
            w = fg.afm.string_width_pt(ch, basefont, size_pt)
            x_start, x_end = cursor, cursor + w
            chars.append({
                'text': ch, 'x_start': x_start, 'x_end': x_end,
                'is_space': ch == ' ', 'space_width_pt': space_w,
                'size_pt': size_pt, 'font': basefont, 'tc': tc,
            })
            cursor = x_end
        running_end_pt = cursor
        normal_items.append((pc, tc))
    if page_chunks and normal_items:
        line_y_dp = items[0][0]['y_decipoints']

        def _splice(occ):
            opc, otc = occ
            obasefont, osize = opc.get('font'), opc['size_pt']
            ospace_w = fg.char_space_width_pt(obasefont, osize)
            ocursor = opc['x_decipoints'] / fg.DECIPT_PER_PT
            for ch in opc['text']:
                w = fg.afm.string_width_pt(ch, obasefont, osize)
                chars.append({
                    'text': ch, 'x_start': ocursor, 'x_end': ocursor + w,
                    'is_space': ch == ' ', 'space_width_pt': ospace_w,
                    'size_pt': osize, 'font': obasefont, 'tc': otc,
                })
                ocursor += w

        for i in range(len(normal_items) - 1):
            pc_a, pc_b = normal_items[i][0], normal_items[i + 1][0]
            end_dp = round((pc_a['x_decipoints'] / fg.DECIPT_PER_PT
                            + fg.afm.string_width_pt(pc_a['text'], pc_a.get('font'),
                                                      pc_a['size_pt'])) * fg.DECIPT_PER_PT)
            start_dp = pc_b['x_decipoints']
            if start_dp <= end_dp:
                continue  # already zero/negative gap, nothing to stitch
            occ = _find_offbaseline_occupant(page_chunks, end_dp, start_dp, line_y_dp)
            if occ is not None:
                _splice(occ)
        # The TRAILING search (past this line's own last chunk, below) is
        # gated on this baseline having at least one item that would
        # become its own checkable token on its own merits -- a baseline
        # made ENTIRELY of chunks that would never independently align
        # anyway (every one of them `_is_unreliable_to_align` -- e.g.
        # `by_y`'s OWN group for a lone superscript/subscript marker,
        # which exists as a group only because it sits on its own
        # distinct y) is never a real printed LINE with a trailing edge
        # of its own to search past -- it is only ever supposed to be
        # ABSORBED as an occupant by some OTHER, real line nearby
        # (confirmed real: -SCREEN's own trademark 'TM' marker, alone on
        # its own raised baseline, was wrongly absorbing the FOLLOWING
        # real line's own comma into a standalone 'TM,' token before this
        # guard existed). Scoped to the TRAILING search only -- the
        # MIDDLE-gap loop above needs no such guard: it is already
        # bounded by two same-baseline chunks a real line's own
        # `by_y` group actually holds (confirmed real: -SCREEN's own
        # 'H'+subscript-'2'+'O' shape has 'H' and 'O' each individually
        # SHORT enough to fail this same real-content test on their own,
        # yet the middle-gap merge between them is exactly this
        # mechanism's own correct, intended target).
        line_has_real_content = any(not _is_unreliable_to_align(pc['text'])
                                    for pc, _tc in normal_items)
        # A footnote/end-note reference at the very END of a printed line
        # (DOCC.WS's own footnote markers, e.g. 'agreement.' + a raised
        # '2' with nothing else on that baseline after it) has no NEXT
        # same-baseline chunk to bound a gap window against at all -- the
        # loop above, which only ever looks BETWEEN two same-baseline
        # chunks, can never see it. Re-run the same occupant search past
        # the LINE's own last chunk, bounded generously (a footnote
        # marker is never more than a couple of characters).
        last_pc = normal_items[-1][0]
        last_end_dp = round((last_pc['x_decipoints'] / fg.DECIPT_PER_PT
                             + fg.afm.string_width_pt(last_pc['text'], last_pc.get('font'),
                                                       last_pc['size_pt'])) * fg.DECIPT_PER_PT)
        trailing_occ = (_find_offbaseline_occupant(
            page_chunks, last_end_dp, last_end_dp + TRAILING_OCCUPANT_WINDOW_DP, line_y_dp)
            if line_has_real_content else None)
        if trailing_occ is not None:
            _splice(trailing_occ)
    chars.sort(key=lambda c: c['x_start'])
    merged = list(overlays)
    for w in fg.segment_words_from_chars(chars):
        pc = {
            'text': w['text'],
            'x_decipoints': round(w['x_start'] * fg.DECIPT_PER_PT),
            'y_decipoints': items[0][0]['y_decipoints'],
            'size_pt': w['size_pt'], 'font': w['font'],
        }
        merged.append((pc, w['tc']))
    merged.sort(key=lambda pt: pt[0]['x_decipoints'])
    return merged


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
        page_chunks = list(zip(pub, text_chunks))
        by_y = defaultdict(list)
        for pc, tc in page_chunks:
            by_y[pc['y_decipoints']].append((pc, tc))
        for _y, items in by_y.items():
            items.sort(key=lambda pt: pt[0]['x_decipoints'])
            items = _strip_box_drawing_chunk_edges(items)  # mechanism N
            items = _correct_toggle_boundary_chunks(items)  # mechanism J, before D (mechanism Z round)
            items = _dedupe_double_strike_chunks(items)   # mechanism D, before C
            items = _merge_kerning_split_chunks(items)    # mechanism C
            items = _merge_trailing_punctuation_chunks(items)  # mechanism K
            items = _merge_zero_gap_cross_font_chunks(items, page_chunks)  # mechanism Z
            if not items:
                # planning #180 phase 2 (v4 expansion, 2026-09-08): a line
                # whose chunks are ENTIRELY consumed by the merge passes
                # above (found on sawyer/TAGS/ONCF -- a one-line symbol-only
                # tag file where _strip_box_drawing_chunk_edges strips every
                # chunk on the line, none of them real text). Nothing left
                # to check on this line -- same "no checkable token" outcome
                # a pure box/rule/shading line already has, just discovered
                # via the merge passes instead of the box-drawing filter
                # directly. Contributes zero tokens, same as the box-drawing/
                # unreliable-to-align skip just below already does per-chunk.
                continue
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
    never a private corpus group's internal folder layout.

    Checks v1's own sources.json first (doc_name as a direct key -- the
    only shape v1 ever had), THEN v4's (planning #180 phase 2: v4 doc
    names/aliases live in a disjoint namespace from v1's, see
    fg.PRINTS_SUBDIR_V4's own docstring, so a v4 name never matches a v1
    entry and vice versa -- checking both costs nothing and keeps this one
    function the single place that decides the redaction, instead of
    fg.resolve_v4_capture's caller having to remember to ask twice)."""
    if ws_path is None:
        return None
    if fg._PRIVATE_CORPUS_ROOT:
        prints_dir = os.path.join(fg._PRIVATE_CORPUS_ROOT, 'ws7-prints', fg.PRINTS_SUBDIR)
        index = fg._load_sources_index(prints_dir)
        if index is not None:
            entry = index.get('captures', {}).get(doc_name)
            if entry is not None and entry.get('group') not in PUBLIC_SOURCE_GROUPS:
                return f'{doc_name}: source path withheld (non-public corpus group)'
        v4_group = fg.v4_doc_group(doc_name)
        if v4_group is not None and v4_group not in PUBLIC_SOURCE_GROUPS:
            return f'{doc_name}: source path withheld (non-public corpus group)'
    return _relative_source(ws_path)


def _divergence(doc, page, line_y, words, ws7_pos, pdf_pos, font_class, reason, detail):
    return {
        'doc': doc, 'page': page, 'line_y_top_pt': line_y, 'words': words,
        'ws7_pos': ws7_pos, 'pdf_pos': pdf_pos, 'font_class': font_class,
        'reason': reason, 'detail': detail,
    }


def doc_report(doc_name: str, engine_words: dict = None, engine_chars: dict = None) -> dict:
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
    reason vocabulary, and manifest comparison -- unmodified. `engine_chars`
    is the SAME idea, one level lower (a dict matching `fg.
    load_engine_chars()`'s own "engine-chars (JSON)" schema, raw
    characters instead of already-segmented words) -- for an external
    reader that must hand over characters and let this repo do mechanism
    Z's own word segmentation itself, never re-implemented a second time by
    the producer (see fg.load_engine_chars()'s own TOLERANCE note).
    `engine_chars` wins over `engine_words` if both are given (checked
    first, below). Default (both None) renders `ws_path` with this repo's
    own engine, same as ever.
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

    if engine_chars is not None:
        loaded = fg.load_engine_chars(engine_chars)
        n_engine_pages = loaded['n_engine_pages']
        eng_tokens = loaded['eng_tokens']
        eng_rasters_by_page = loaded['eng_rasters_by_page']
    elif engine_words is not None:
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
def _v4_private_placeholder(doc_name: str, group: str) -> dict:
    """The COMMITTED manifest entry for a private-group v4 document
    (jon-floppies/fixtures-ws5/ws7-private -- see fg.PRINTS_SUBDIR_V4's
    own docstring): verdict 'source-missing', no counts, no divergences,
    same shape test_pcl_fidelity.py already treats as a clean skip for a
    Sawyer-archive-only document. This is a DELIBERATELY STRICTER choice
    than v1's own precedent (DOCA/DOCB/DOCC/DOCD/DOCE/DOCF publish real
    verdicts/counts, source_ws redacted) -- not because that precedent was
    wrong, but because it was reviewed document-by-document (each entry's
    own hand-written provenance note) and happened to land on all-clean
    results with nothing in `divergences` to leak. That review does not
    scale to 64 documents, and doc_report()'s own `divergences` entries
    embed literal WORDS from the source (`words: [ws7_text, engine_text]`)
    -- committing a real report for one of Jon's private WS4 papers or
    fixtures-ws5 test documents risks putting document TEXT into this
    PUBLIC repo the moment that document has even one real divergence.
    So this function is called INSTEAD OF doc_report() for these 64 --
    doc_report() is never even invoked for them during --record, and no
    real content from the private corpus enters this process's memory on
    the path that writes the committed file. (A locally-armed live
    `pt.doc_report(doc_name)` call still computes the real thing -- see
    fg.resolve_v4_capture -- for the private workshop driver
    and for Jon's own vault-side analysis, neither of which commits its
    output here.)"""
    capture = fg.resolve_v4_capture(doc_name)
    return {'doc': doc_name, 'verdict': 'source-missing', 'source_ws': None,
            'counts_by_reason': {}, 'divergences': [],
            'capture_set': capture['capture_set'], 'install': capture['install'],
            'reason': (f'private corpus group ({group}) -- this repo never commits a real '
                       f'verdict/divergence report for a private-group document (see '
                       f'_v4_private_placeholder\'s own docstring); resolved and compared for '
                       f'real only in a locally-armed run against $CTRLKD_PRIVATE_CORPUS')}


def _excluded_placeholder(doc_name: str, reason: str) -> dict:
    """The COMMITTED manifest entry for a document in EXCLUDED_V4 (planning
    #224/#226, ruled 2026-09-08): verdict 'excluded', no counts, no
    divergences -- doc_report() is never called for these during --record,
    same reasoning _v4_private_placeholder gives for source-missing (no live
    recomputation needed to know a document is excluded; excluding it is the
    ruling, not a measurement). Distinct verdict from 'source-missing' so the
    two skip reasons never get confused reading the manifest: 'source-missing'
    means "not resolvable in this environment", 'excluded' means "resolvable,
    but Jon ruled this document out of the tier" (postscript/freeze/duplicate
    -- see EXCLUDED_V4's own docstring for which)."""
    return {'doc': doc_name, 'verdict': 'excluded', 'source_ws': None,
            'counts_by_reason': {}, 'divergences': [], 'reason': reason}


def regenerate_manifest(doc_names=None) -> dict:
    doc_names = doc_names or CAPTURED_DOCS
    documents = {}
    for name in doc_names:
        if name in EXCLUDED_V4:
            documents[name] = _excluded_placeholder(name, EXCLUDED_V4[name])
            continue
        v4_group = fg.v4_doc_group(name) if name in CAPTURED_DOCS_V4 else None
        if v4_group is not None and v4_group not in PUBLIC_SOURCE_GROUPS:
            print(f'pcl_tolerance: {name}: private-group v4 placeholder (not run)',
                  file=sys.stderr)
            documents[name] = _v4_private_placeholder(name, v4_group)
            continue
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
    ap.add_argument('--engine-chars', help='with --doc: judge a PRE-EXTRACTED engine-chars '
                    'JSON file (see fidelity_gate.py\'s "engine-chars (JSON)" schema comment) -- '
                    'raw CHARACTERS, one level lower than --engine-words, for an external reader '
                    'that must not re-implement mechanism Z\'s own word-boundary rule itself. '
                    'Mutually exclusive with --engine-words; not valid with --record.')
    a = ap.parse_args(argv)

    if a.engine_words and a.record:
        ap.error('--engine-words is not valid with --record')
    if a.engine_chars and a.record:
        ap.error('--engine-chars is not valid with --record')
    if a.engine_chars and a.engine_words:
        ap.error('--engine-chars and --engine-words are mutually exclusive')

    if a.doc:
        engine_chars = json.load(open(a.engine_chars)) if a.engine_chars else None
        engine_words = json.load(open(a.engine_words)) if a.engine_words else None
        print(json.dumps(doc_report(a.doc, engine_words=engine_words,
                                    engine_chars=engine_chars), indent=2))
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
