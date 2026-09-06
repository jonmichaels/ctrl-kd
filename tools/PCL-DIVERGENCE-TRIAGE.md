# PCL divergence triage — 2026-09-06

Written against `tests/pcl_fidelity_manifest.json` as recorded by ctrl-kd
6741c10, then re-measured live after the fixes below landed. Scope: the
13 documents named in planning #202 (BOXES, LJ6DTP, LYING, OCAPTAIN,
PREVIEW, -README, SAWYER, -SCREEN, SCRIPT, TWAINLET, VERSIONS, WARPRAYR,
DOCC). Jon's ruling (#202, verbatim): fix the BROAD SUPPORT mechanisms
(page breaks, line spacing, margins, tabs, fixed-pitch positioning —
things every document relies on); LJ6DTP's own "printing hack" items stay
parked; font-substitution residuals are named, not fixed.

**Follow-up round, same day:** mechanisms C and D (both diagnosed-but-
unfixed harness bugs below) are now FIXED in `tools/pcl_tolerance.py`
(`_merge_kerning_split_chunks`, `_dedupe_double_strike_chunks`), and
mechanism E's recommendation ("recapture/re-point for every Sawyer-archive
document, not just -README") is now live: `tools/fidelity_gate.py`'s
`resolve_doc_paths` prefers a `ws7-prints/v2/<source path>` capture over
`v1/NAME` for ANY document that has one, keyed by `sources.json`'s own
`source` field, not a doc-name allowlist. Also fixed: the `pcl` tier's own
reason-filter defect (`tests/test_pcl_fidelity.py` used to filter out
divergences whose reason was the literal `'font-substitution'` — a string
`doc_report()` never emitted; see `tools/pcl_tolerance.py`'s new
`FONT_SUBSTITUTION_REASONS`/`is_font_substitution_reason`). One
consequence worth flagging loudly: `ws7-prints/v2` turned out to already
cover 14 of this triage's 18 captured documents (the v2 full-corpus batch,
paused at 188/467 for stall diagnosis as of today), not just -README —
every one of those 14 automatically switched ground truth as a direct
result of the general (not -README-specific) fix, and one of them
(mechanism F, below) turned out to flip an "OPEN, insufficient evidence"
diagnosis into "resolved -- it was a v1 CAPTURE artifact, not a real WS7
behavior." See each mechanism's own updated entry below for what changed
and why.

Every number below comes from `tools/pcl_tolerance.py --doc NAME` run
against the real WS7 captures at `$CTRLKD_PRIVATE_CORPUS/ws7-prints/v1/`
(never against our own prior output), cross-checked by hand against the
raw `.pcl`/`measurements.json` and, where noted, the `ws7-prints/v2`
captures. No corpus file was written to; this document and the code
changes it describes are the only outputs.

## Mechanism table

| Mechanism | Documents | Divergence reasons affected | Class | Status |
|---|---|---|---|---|
| A. `.pm`/style first-line indent double-counted a typed leading indent | WARPRAYR, (would also have hit any other style-governed document that types its own hanging indent) | baseline-shift (indirectly, via alignment desync), line-start-shift, word-unmatched | **BROAD SUPPORT** | **FIXED** (`src/ctrlkd/pdf.py` `_printed_pm_fi_pt`, commit 8956ad4) |
| B. Harness `Tz`/`Ts` operator order (test tooling, not the engine) | WARPRAYR, LYING, PREVIEW, and every other document with a CG-Times/Univers-tier (Tz-scaled) line | word-unmatched, extra-word-in-engine, and everything a mismatched word desyncs downstream | **TOOLING** (harness bug, not an engine behaviour) | **FIXED** (`tools/fidelity_gate.py` `_TEXT_OP_RE`, commit 7285270) |
| C. WS7's own kerning-pair chunk-split ("W"+"ar", "Y"+"ou", "T"+"wain") | WARPRAYR (title "War"), TWAINLET/-README/others ("You", "Twain") — recurring across the corpus wherever a kerned pair starts a chunk | word-unmatched, extra-word-in-engine, and the alignment desync this causes for everything after it on the page | **TOOLING** (harness word-matching, not an engine behaviour — see below) | **FIXED** (`tools/pcl_tolerance.py` `_merge_kerning_split_chunks`, same-day follow-up) |
| D. Duplicate-position WS7 chunks (double-strike bold) | BOXES, SAWYER, VERSIONS (~all of their word-unmatched); partial in PREVIEW, SCRIPT, -SCREEN | word-unmatched, line-start-shift | **TOOLING** (harness word-matching) | **FIXED** (`tools/pcl_tolerance.py` `_dedupe_double_strike_chunks`, same-day follow-up) |
| E. `-README` v1 capture predates the current Sawyer archive file (v1.4 → v1.5) | -README, plus (once generalized) 13 more of this triage's 18 documents that already have a `ws7-prints/v2` capture | page-count-mismatch, and very likely most of its baseline-shift/word-unmatched/extra-word-in-engine | **CORPUS STALENESS** (not an engine bug) | **FIXED, generalized** (`tools/fidelity_gate.py` `resolve_doc_paths` now prefers any doc's own `v2` capture over `v1`, same-day follow-up) |
| F. 2 consecutive blank source lines print as 1 blank line's advance, but ONLY in plain-default-leading (no `.lh`/style) documents | OCAPTAIN, TWAINLET | baseline-shift (all of it, both docs) | Looked BROAD SUPPORT, but... | **RESOLVED — was a v1 CAPTURE artifact, not a real WS7 behavior** (see below) |
| G. Superscript/subscript advance width computed at the RAISED/reduced glyph size rather than the document's fixed-pitch cell, in a fixed-pitch document | DOCC (footnote references), -SCREEN (explicit sup/sub demo) | exact-drift | **BROAD SUPPORT** (a real, cumulative, per-occurrence drift) | **DIAGNOSED, fix attempted and reverted — root cause not yet pinned** |
| H. LJ6DTP's own printing-hack items (title fragmentation, table numbers, shading headings, Univers/CG-Times mapping residuals) | LJ6DTP only | baseline-shift, extra-word-in-engine, word-unmatched, line-start-shift, exact-drift, cgtimes-drift | **PARKED per Jon's ruling** | not attempted, by instruction |
| I. Font-substitution residuals (CG-Times/Univers drift beyond the modelled tolerance) | LYING, SCRIPT, WARPRAYR | cgtimes-drift-exceeds-tolerance | **FONT SUBSTITUTION** | named, not fixed (by design) |

---

## A. `.pm`/style first-line indent double-counted a typed indent — FIXED

**Evidence.** WARPRAYR.WS's Quote style carries `para_margin=5` (from its
style record, not a literal `.pm` dot command). Its stanzas are typed
with real leading spaces (10 on a stanza's own first line, 5 on
continuations) — a hanging-indent authoring convention, not a reflow
paragraph. Real WS7 (`ws7-prints/v1/WARPRAYR.pcl`/`.measurements.json`,
page 1 y=448.5 `'"God the all-terrible!...'`, page 2 y=326.1 `'"O Lord
our Father...'`) prints those lines at exactly left-edge + the TYPED
column count — `.pm`'s own 5 columns contribute nothing once the typed
indent already reaches or passes it. The engine added `fi` (`.pm`'s
first-line indent, `_printed_pm_fi_pt`) on top of the typed indent
unconditionally, landing those two lines 36pt (`.pm`'s 5 columns) too
far right — 158.4pt engine vs 122.4pt real WS7.

A prior fix ("Fix A", b26-print-fidelity-2) already existed for this
exact scenario, but only fires through `_split_indent`'s own indent
flag — which, by that function's own docstring, is "never flagged" for
a span with no WS5+ font block. WARPRAYR's real Quote paragraphs carry
no font block (their font comes from the style), so Fix A's guard never
actually engaged for the real document it is named after; its own test
used a synthetic `_helv_font_block()` fixture that reproduced the same
numbers without ever exercising the real corpus file.

**Fix.** `_printed_pm_fi_pt` (`src/ctrlkd/pdf.py`) now returns
`max(0, (para_margin - typed_leading_cols) * 7.2)` instead of the flat
`para_margin * 7.2` — reading the block's own first real line's typed
leading-space count and subtracting it, floored at zero. A typed indent
shorter than `.pm`'s column still gets topped up to it (unconfirmed
against a real capture, symmetric with the two measured cases either
side of it); one that already reaches or exceeds it adds nothing.
Identical to the old behaviour whenever the first line types no leading
whitespace of its own (the pre-existing, already-tested case) — verified
byte-identical against every existing Tier-1 test.

**Tests.** `tests/test_ctrlkd.py::test_pm_first_line_indent_not_doubled_with_no_font_block_either`,
`::test_pm_first_line_indent_tops_up_a_shorter_typed_indent`.

**Before/after (WARPRAYR, live `pcl_tolerance.py --doc`):**
`word-unmatched` 47 → 38, `extra-word-in-engine` 42 → 43 (net alignment
improvement; the residual `baseline-shift` count is explained separately
below — see mechanisms B/C).

---

## B. Harness `Tz`/`Ts` operator order — FIXED (tooling)

**Evidence.** Every one of pdf.py's 12 `ops.append(b'BT ...')` call
sites writes `Tf <rise> Ts` first and the optional `<tz> Tz` second,
immediately before `Td` — checked by hand across all 12. `tools/
fidelity_gate.py`'s `_TEXT_OP_RE` expected the reverse order (`Tz`
before `Ts`), so it **never matched a single Tz-scaled text-showing
op** — every CG-Times/Univers-substituted proportional word, which is
the entire reason a Tz scale exists in this emitter. `parse_text_ops`
silently dropped every such word; `engine_page_tokens` never saw it;
the gate then reported it as a WS7-side `word-unmatched`, or worse, let
a dropped word desync `difflib`'s whole-document alignment for
everything downstream of it on the page (this is most of the reason
WARPRAYR's `baseline-shift` count was so large — see mechanism C).

Confirmed directly: WARPRAYR's own `'"God the all-terrible!...'` Quote
line is Tz-scaled (`101.12 Tz` is a real value from its own PDF);
`("God) Tj` is present verbatim in the raw content stream but was
absent from `engine_page_tokens`'s output before this fix.

The existing regression test for this regex
(`test_parse_text_ops_reads_plain_and_tz_scaled_runs`,
`tests/test_fidelity_gate.py`) encoded the SAME wrong order in its own
fixture, so it could never have caught the bug — corrected alongside
the regex.

**Fix.** `tools/fidelity_gate.py`'s `_TEXT_OP_RE` reordered to
`Tf <rise> Ts (<tz> Tz)? Td`, matching pdf.py's real emission order.
This is a harness/tooling fix, not an engine change — it does not
loosen any tolerance, it corrects a data-extraction bug that was
producing false-positive divergences (and false-negative silence, where
a dropped word happened to make a real bug invisible) on every
CG-Times/Univers-tier line across the corpus.

**Before/after, several documents' live reports:**

| Doc | `word-unmatched` before → after |
|---|---|
| LYING | 79 → 41 |
| PREVIEW | 17 → 5 |
| LJ6DTP | 539 → 486 |

---

## C. WS7's own kerning-pair chunk split — diagnosed, not fixed

**Evidence.** Real WS7's own PCL driver splits certain words into TWO
separate print chunks with a kerning-adjusted gap and no actual space
between them — confirmed on WARPRAYR's title (`measurements.json`:
`'The'` at x=228.2, `'W'` at x=259.6, `'ar'` at x=273.6, `'Prayer'` at
x=293.5 — "W" and "ar" abut exactly at "W"'s own natural glyph width,
i.e. real WS7 printed `War` as two touching chunks). The SAME pattern
recurs elsewhere in the corpus: `"Y"`+`"ou"` (`'You'`), `"T"`+`"wain"`
(`'Twain'`). This is a printer-driver kerning artifact on WS7's side,
not anything our engine does.

`tools/pcl_tolerance.py`'s existing `_is_unreliable_to_align` filter
(short/no-alnum tokens excluded from alignment) removes the lone
first-letter chunk (`"W"`, len 1) but leaves the SUFFIX chunk (`"ar"`,
len 2, real alnum content) as its own standalone token with no engine
counterpart — the engine correctly emits the whole word `War` as one
token. The mismatch (`ar` unmatched on the WS7 side, `War` unmatched on
the engine side) is real, but it is an artifact of WS7's own chunk
splitting, not an engine positioning bug — and worse, feeding two
mismatched tokens into `difflib.SequenceMatcher`'s whole-document
alignment can desync everything that follows on the page, which is very
likely the dominant contributor to WARPRAYR's still-large
`baseline-shift` count (title/byline residuals of exactly -12.00pt that
don't correspond to any real 12pt positional error once you look at the
raw x/y values directly — see the fork investigation this triage is
built on).

**Fix (same-day follow-up).** `tools/pcl_tolerance.py`'s
`_merge_kerning_split_chunks` merges two-or-more adjacent same-line WS7
chunks, before `_is_box_drawing_text`/`_is_unreliable_to_align` ever run
on them, whenever they share the same size and font (both the
post-substitution name and the pre-substitution PCL typeface id) and the
next chunk's own x lands within `KERNING_MERGE_EPS_PT` (1.5pt) of where
the running merged text's own AFM natural width says it should end —
exactly undoing WS7's own kerning-pair chunk split before alignment, the
same way `_is_box_drawing_text`/`_is_unreliable_to_align` already
pre-filter WS7 chunks. Wired into `load_ws7_tokens` right after the new
mechanism-D dedupe (below) and before the exclusion filters. Unit-tested
against synthetic two- and three-way splits, a real gap (not merged), and
a font change at the split point (not merged) — `tests/test_pcl_tolerance.py`.

Confirms the triage's own suspicion above: WARPRAYR's `cgtimes-drift-
exceeds-tolerance` count (mechanism I) dropped from 25 to 0 once this
landed — essentially ALL of it was this mechanism's own alignment desync
cascading through the page, not real font-metric drift. WARPRAYR's
`baseline-shift` count (title/byline residuals) also dropped from 431 to
0 for the same reason.

---

## D. Duplicate-position WS7 chunks (double-strike bold) — FIXED

**Evidence** (from the parallel six-document investigation this triage
also drew on): WS7's own raw PCL emits each BOLDED word/token TWICE at
the identical (x, y) position — a double-strike fake-bold technique
HP-resident fonts use when no true bold weight exists. Confirmed by
direct inspection of `measurements.json`: BOXES's `"SAWYER.EXE"` and
`"^K'"`, SAWYER's `"PATCH.LST"`, and 22 duplicate-position chunks across
VERSIONS's 4 pages (bold filenames/command names in a reference table)
are all literal duplicate chunks in the WS7 capture. Our engine renders
bold as one PDF bold-font glyph run, not a doubled strike (the correct,
intended choice — Jon's base-14-only ruling gives us real bold weights,
no double-strike fakery needed), so the aligner's 1:1 sequence match
always leaves one WS7 copy stranded as `word-unmatched`.

This accounts for essentially ALL of BOXES's, SAWYER's, and VERSIONS's
non-font divergences, and a meaningful share of PREVIEW/SCRIPT/-SCREEN's.

**Fix (same-day follow-up).** `tools/pcl_tolerance.py`'s
`_dedupe_double_strike_chunks` drops the second (and any further) copy of
an identical (text, x, size, post-substitution font, pre-substitution
typeface id) chunk on the same WS7 line, keeping the first, before
`load_ws7_tokens` hands anything to `fg.match_doc` — a harness fix, not
an engine change. Unit-tested for the exact-duplicate case and three
near-miss cases that must NOT dedupe (same x different text, same text
different x, same text/x but a different font). Confirmed: SAWYER and
VERSIONS both went fully `word-unmatched`-clean (SAWYER's `PATCH.LST`,
VERSIONS's 22 duplicate-position chunks); BOXES's `word-unmatched`
cleared too (its `"SAWYER.EXE"`/`"^K'"` duplicates), leaving only an
unrelated single `exact-drift`; PREVIEW and SCRIPT's `word-unmatched`
counts both dropped as documented ("partial" — the rest is mechanism C,
also fixed above).

---

## E. `-README` v1 capture is stale relative to the current file — corpus, not engine

**Evidence.** `sources.json` resolves `-README`'s WS source to
`sawyer/-README.WS` (the CURRENT file in the corpus, version 1.5, dated
Monday Aug 12 2024 per its own title-page text). The `ws7-prints/v1/
-README.measurements.json` capture is dated 2026-08-20 and its own
title-page text reads version 1.4, dated Wednesday Jul 31 2024 — an
OLDER version of Robert Sawyer's own archive file, captured before his
own update added 2 pages of content. A newer capture already exists at
`ws7-prints/v2/sawyer/-README.WS.measurements.json` (16 pages) and
matches our CURRENT engine's -README output **verbatim**: page 1 opens
identically (`'COMPLETE WORDSTAR FOR DOS 7.0 ARCHIVE...'`), page 8 and
page 16 both open with byte-identical running-head text
(`'WordStar 7.0 Archive / 8 SWAP.COM...'`, `'... / 16 Design: melanie...'`).

This means -README's `page-count-mismatch` (14 WS7 vs 16 engine) is NOT
an engine bug — it is exactly the pagination a real, current copy of the
file produces on real WS7. It also means the bulk of -README's other
recorded divergences (`baseline-shift` 35, `extra-word-in-engine` 793,
`word-unmatched` 196) are very likely mostly-bogus content-mismatch
noise from comparing our current output against an outdated 14-page
capture, not real per-line bugs — I did not attempt to separate any
real signal out of that noise, since the ground truth itself needs
replacing first.

**Action taken: none in this repo.** The corpus lives outside ctrl-kd
and is read-only reference data for this task; recapturing/migrating
`ws7-prints/v1` → `v2` (or wiring `pcl_tolerance.py` to prefer `v2`
where it exists) is planning #196/finalization-plan task 2's job, not
this repo's. **Part 3 below deliberately does NOT bless -README's
manifest entry** — regenerating it now would launder a data problem as
an accepted result.

**Fix (same-day follow-up), generalized beyond the recommendation
above.** `tools/fidelity_gate.py`'s `resolve_doc_paths` now prefers a
`ws7-prints/v2/<sources.json source path>` capture over the flat
`v1/NAME` one whenever the v2 file exists on disk — keyed by the source
path the index already carries, not a doc-name allowlist, so this
resolves -README (and any future v2 recapture) with no further code
change. Turned out to matter far beyond -README: as of this same-day
follow-up, `ws7-prints/v2` (a full-corpus recapture batch, 188/467
documents done, paused for stall diagnosis) already covers 14 of this
triage's 18 documents. All 14 switched ground truth automatically. Spot
checks across several of them (not exhaustive) found no case where the
switch made a real bug disappear rather than a stale-capture artifact —
see mechanism F below for the one case (OCAPTAIN/TWAINLET) where it
resolved what had been an open question, and mechanism I's WARPRAYR note
for how switching plus mechanism C together collapsed a large apparent
divergence that turned out to be almost entirely a harness alignment
artifact, not font drift. The 4 still on v1 (SAWYER, SCRIPT, PREVIEW,
VERSIONS) simply have no v2 capture yet as of this batch's current
progress (SCRIPT specifically is one of the batch's known
`driver-missing` stalls — its embedded printer driver, LQ-850, was never
installed in the v2 harness tree).

---

## F. Two consecutive blank lines print as one, in plain-leading documents only — RESOLVED (v1 capture artifact)

**Evidence.** OCAPTAIN.WS and TWAINLET.WS (both single-page, NO `.lh`
and NO paragraph styles at all — the plain document-default 12pt
leading grid throughout) each have exactly 2 literal blank physical
source lines immediately before a closing `----------` rule + attribution
paragraph. Real WS7 prints that gap as 24.0pt (ONE blank line's worth,
12+12), not 36.0pt (two blank lines' worth, 12×3) — i.e. one of the two
typed blank lines contributes nothing to the printed page. Our engine
(correctly, by every other measurement in this corpus) renders the
literal count: 36.0pt, i.e. 12pt too much, landing everything from the
attribution paragraph onward exactly one line too low.

**Why this is NOT fixed:** the SAME 2-consecutive-blank-lines-before-a-
rule shape recurs in LYING.WS and WARPRAYR.WS — documents that DO carry
real paragraph styles/`.lh` state — and in BOTH of those, real WS7
prints the FULL, uncollapsed count (LYING: 43.2pt = 3×14.4pt exactly;
WARPRAYR: 36.0pt = 3×12pt exactly, its own body-block leading). So the
collapse is not "2+ blank lines before a rule collapse to 1" in general
— it only reproduces in the two documents with NO active `.lh`/style
leading at all, and I could not find a second within-document example
in either document (a blank run of exactly 1 is common and always
prints correctly at its own full count; a blank run of exactly 2 occurs
ONLY at this one spot in each of the two affected documents) to
distinguish "any run of 2+ collapses to 1 under plain leading" from
some other, narrower rule I haven't found evidence for. Guessing a
general rule here risks silently breaking LYING/WARPRAYR's own
currently-correct blank-line handling for no real gain (2 short,
single-page documents, ~22 divergences combined) — this is exactly the
"research before guessing" situation: the right next step is a real WS7
probe (dosbox-x, a constructed document with 2/3/4 consecutive blank
lines at plain default leading, both with and without a following rule
line) before writing any fix, not a code change today.

**Resolution (same-day follow-up).** Once mechanism E's v2 preference
picked up OCAPTAIN's and TWAINLET's own v2 captures (both `pd-samples/
authored`, part of the same full-corpus batch), both documents'
`baseline-shift` divergences vanished entirely (verdict: clean). Direct
comparison of the two captures' own `baseline_gaps_pt` confirms why: at
the EXACT gap this section describes, OCAPTAIN's v1 capture records
`24.0` (the "collapsed" one-blank-line advance) while its v2 capture of
the identical source file records `36.0` (the full, uncollapsed
three-line advance our engine already produces); TWAINLET shows the
identical pattern at its own equivalent gap (v1 `24.0`, v2 `36.0`, same
position in each list). Both v1 and v2 are genuine real-WS7-LaserJet
captures of the SAME unchanged source file, produced by DIFFERENT
tooling (v1: `pcl_render.py`'s own analysis; v2: `gpcl6`, Ghostscript's
PCL interpreter, adopted after Jon ruled the `pcl_render.py` PNG path
broken 2026-08-24) — so this was never a real WS7 print behavior at all,
on either side of the LYING/WARPRAYR counter-evidence below: it was a
bug in the v1 capture pipeline specific to how it counted blank-line
advances near the end of these two short, single-page documents, which
the batch's own tooling change happened to fix as a side effect. This
also confirms the original diagnosis was right to stay OPEN rather than
guess a general "2+ blank lines collapse" rule from it — there never was
such a rule to find; LYING and WARPRAYR's own gap lists are byte-
identical between v1 and v2 (spot-checked directly), so their
"uncollapsed" counter-evidence stands unchanged.

**No code or tolerance change was needed for this document pair** —
their divergence disappeared purely from the corpus now offering a
correct capture (mechanism E), the same class of fix as -README's, just
discovered as a side effect of generalizing E rather than sought
directly.

---

## G. Superscript/subscript advance width in fixed-pitch text — diagnosed, fix attempted and reverted

**Evidence.** DOCC.WS4 (a WS4 paper with inline footnote references)
shows 83 `exact-drift` divergences, every one showing a residual of
exactly -0.70pt or -1.40pt (never anything else) — a residual that does
NOT grow with distance into the line (ruling out an accumulating
per-character metric error), but DOES compound by exactly -0.70pt per
distinct footnote reference encountered earlier in the document (one
reference on a line: -0.70pt; two: -1.40pt). Every divergent run starts
immediately after an inline footnote-reference digit. DOCA/DOCB/DOCD/DOCE/
DOCF — the other 5 WS4 papers in this corpus, all reproducing EXACTLY
against real WS7 — contain no inline footnote references, consistent
with the drift being specific to whatever happens at a footnote marker.

-SCREEN.WS (an explicit superscript/subscript demo line, WS7) shows the
SAME shape independently: +1.70pt after one sup/sub toggle, +3.40pt
(exactly 2×1.70) after two — opposite sign from DOCC, but the same
"constant-per-occurrence, compounding" signature. This was NOT visible
before mechanism B's fix (the Tz/Ts regex bug had been dropping these
words as `word-unmatched` entirely); fixing B made these real, exact
positional residuals newly visible.

**Hypothesis:** a superscript/subscript span's advance width is
computed using the RAISED/reduced glyph size (`pdf.py`'s `_sized`
reduces a sup/sub span to 2/3 size for drawing) rather than the
document's real fixed-pitch cell width — real fixed-pitch printing
keeps the character CELL constant regardless of a superscript's smaller
drawn glyph (the physical print head doesn't narrow its step for a
raised character), so every character after a sup/sub run should land
on the SAME grid a same-size run would, not a size-scaled one.

**Attempted fix:** changed the fixed-pitch pitch computation
(`_span_pitch(entry, pt)` → `_span_pitch(entry, size_here)`, using the
span's pre-reduction declared size for the WIDTH target while keeping
the reduced size for the drawn `Tf`) in `_line_ops_printed`'s
non-proportional branch. **Result: no change whatsoever to either
DOCC's or -SCREEN's live divergence counts**, and it broke an
existing, correct test
(`test_pdf_printed_footnote_and_endnote_markers_share_the_same_rise`) by
introducing a Tz operator that test's regex didn't expect. **Reverted**
(not committed) — this means the code path I fixed is not the one
DOCC/-SCREEN's footnote/sup-sub spans actually take at render time
(most likely: WS4 parsing populates `doc.fonts` with a synthetic
Courier entry carrying `width_1800`, which makes `_span_pitch` take its
OTHER branch — `w / HMI_PER_POINT`, ignoring `pt`/`size_here` entirely
either way — so the real bug, if it's in pitch computation at all, is
somewhere I haven't yet located; it's equally possible the real cause is
in `_tz_scale`'s own scale computation, or somewhere in `_sized`/`rise`
interacting with the glyph's OWN natural AFM width at the reduced size
in a way I haven't traced).

**Status:** open, with two independent real-document confirmations and
a disproven first hypothesis. The next step is tracing the ACTUAL code
path a fixed-pitch document's sup/sub span takes (instrument
`_line_ops_printed` directly against DOCC's own rendering, don't
reason from the docstrings alone) before attempting a second fix.

---

## H. LJ6DTP — parked per Jon's ruling

1260 divergences (`extra-word-in-engine` 657, `word-unmatched` 539,
`baseline-shift` 44, `exact-drift` 8, `line-start-shift` 10,
`cgtimes-drift-exceeds-tolerance` 2 as last recorded; the Tz/Ts fix
above moved these numbers around — `extra-word-in-engine` 679,
`word-unmatched` 486 live — without changing LJ6DTP's fundamental
character). Spot-checked samples: page 1's masthead runs a fragmented
title ("obert" split from "Robert" — the same kerning-chunk-split
mechanism as C, but LJ6DTP-specific compounding on top of it), page 5's
"Shading" heading is 18pt off baseline, page 7's data-table numbers are
scattered by 10pt baseline shifts and multi-point exact-drifts, and
page 2-5's running head ("LJ6DTP") is offset by 8-10pt at every line
start. This matches Jon's own framing exactly ("LJ6DTP does a lot of
'printing hack' things... I don't want to waste a bunch of time trying
to fix every single thing there") — not attempted, by instruction.

---

## I. Font-substitution residuals — named, not fixed (by design)

`cgtimes-drift-exceeds-tolerance`: LYING (3), WARPRAYR (25), LJ6DTP (2)
— real CG-Times-substituted-to-Times word positions whose drift exceeds
the modelled bounded-per-line-distance tolerance (`tools/
pcl_tolerance.py`'s own `cgtimes_tolerance_pt`). Per the finalization
plan and Jon's ruling, this class is accepted by rule (a base-14-only
PDF cannot metrically match CG Times) — not touched, not tolerance-
widened. WARPRAYR's 25 are the largest count; worth a closer look in a
future round to confirm they're genuinely all font-metric drift and not
ANOTHER instance of mechanism C's alignment-desync (some plausibly are,
given how entangled WARPRAYR's numbers turned out to be) — not verified
individually this round.

---

## Summary for Part 2/3

**Fixed, in the engine (`src/ctrlkd`), each with a Tier-1 test:**
- Mechanism A: `_printed_pm_fi_pt` (pdf.py) — commit 8956ad4.

**Fixed, in the test harness (`tools/fidelity_gate.py`/`tools/pcl_tolerance.py`), not the engine:**
- Mechanism B: `_TEXT_OP_RE` operator order — commit 7285270.
- Mechanism C: `_merge_kerning_split_chunks` — same-day follow-up.
- Mechanism D: `_dedupe_double_strike_chunks` — same-day follow-up.
- Mechanism E: `resolve_doc_paths` prefers a doc's own `v2` capture over
  `v1` when one exists — same-day follow-up, generalized beyond -README.
- The `pcl` tier's own reason-filter defect (`tests/test_pcl_fidelity.py`
  used to filter on a reason string `doc_report()` never emitted) — same-
  day follow-up, `FONT_SUBSTITUTION_REASONS`/`is_font_substitution_reason`.

**Resolved as a corpus/tooling artifact, not an engine or harness change:**
- Mechanism F: OCAPTAIN/TWAINLET's `baseline-shift` was a bug in the v1
  capture pipeline's own blank-line accounting, not a real WS7 print
  behavior — the v2 recapture (different tooling) shows the full,
  uncollapsed advance our engine already produces. Resolved as a side
  effect of generalizing E, not sought directly.

**Diagnosed with concrete evidence, not fixed this round:**
- G (sup/sub fixed-pitch advance width — first hypothesis disproven, root cause not yet located)

**Parked per Jon's ruling:** H (LJ6DTP printing hacks).

**Accepted by design:** I (font-substitution residuals) — note WARPRAYR's
own count dropped from 25 to 0 once C landed; see mechanism C's entry.

**Result after this round** (`pytest -m pcl`, corpus armed): of the 13
documents named in planning #202, OCAPTAIN, TWAINLET and SAWYER now PASS
(mechanisms D and E resolved every one of their real divergences); BOXES,
DOCC, LJ6DTP, LYING, PREVIEW, -README, -SCREEN, SCRIPT, VERSIONS and
WARPRAYR still FAIL BY NAME — every remaining failure is either mechanism
G (DOCC, -SCREEN), mechanism H (LJ6DTP, parked by instruction), or a
real remaining divergence this round did not address (the others). No
document's pass/fail status flips purely from the reason-filter fix in
this snapshot: every document carrying a font-substitution-tier residual
either also carries an unrelated real divergence (LJ6DTP, LYING), or had
its font-substitution count fall to zero once mechanism C landed
(WARPRAYR) — the fix is still correct and unit-tested infrastructure, it
simply had no live document to flip from fail to pass today. See
tools/pcl_tolerance.py's own commit history and `tests/
pcl_fidelity_manifest.json` for the exact before/after counts by reason.
