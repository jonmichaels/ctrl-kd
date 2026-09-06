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

**Mechanism-G round (commit f328838):** implemented WS7's real sup/sub
pitch behaviour in fixed-pitch text (see mechanism G's own entry below,
rewritten from "diagnosed, fix attempted and reverted" to FIXED).
DOCC drops to 0 divergences (PASSES); -SCREEN's `exact-drift` drops
to 0, 8 unrelated divergences remain.

**Residuals round, same day:** part 2 of this task — traced and fixed
five more mechanisms (J, K, L, M, N; see each entry below) covering
BOXES, VERSIONS, PREVIEW, WARPRAYR, LYING, -README and SCRIPT.
BOXES/VERSIONS/PREVIEW now PASS outright; the rest have real,
substantial reductions with the remainder either traced to mechanism
I's font-substitution wrap cascade (accepted by design) or diagnosed
and documented as out-of-round (-README's own dynamic-right-tab header
question, -SCREEN's Symbol/cp437 mixed-encoding edge case, SCRIPT's
LQ-850-dot-matrix corpus mismatch). See the "Summary — all rounds"
section at the end for the full before/after table.

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
| G. Superscript/subscript advance width computed at the RAISED/reduced glyph size rather than the document's fixed-pitch cell, in a fixed-pitch document | DOCC (footnote references), -SCREEN (explicit sup/sub demo) | exact-drift | **BROAD SUPPORT** (a real, cumulative, per-occurrence drift) | **FIXED** (`src/ctrlkd/pdf.py` `_sized`/`_sup_sub_span_pitch`, commit f328838 — mechanism-G round) |
| H. LJ6DTP's own printing-hack items (title fragmentation, table numbers, shading headings, Univers/CG-Times mapping residuals) | LJ6DTP only | baseline-shift, extra-word-in-engine, word-unmatched, line-start-shift, exact-drift, cgtimes-drift | **PARKED per Jon's ruling** | not attempted, by instruction |
| I. Font-substitution residuals (CG-Times/Univers drift beyond the modelled tolerance), INCLUDING the word-wrap-point cascade it causes | LYING, WARPRAYR, SCRIPT (partial) | cgtimes-drift-exceeds-tolerance, and (once traced) most of LYING's/WARPRAYR's own remaining baseline-shift/extra-word-in-engine/word-unmatched/line-start-shift | **FONT SUBSTITUTION** | named, not fixed (by design) — see below for the wrap-cascade trace |
| J. A style toggle immediately after a character (no space) sometimes drops that character's own advance in WS7's own capture | BOXES ("(" + bold "^K'"), VERSIONS (its own 22 duplicate-position rows partly overlapped this) | exact-drift, word-unmatched | **TOOLING** (WS7 driver capture artifact) | **FIXED** (`tools/pcl_tolerance.py` `_correct_toggle_boundary_chunks`, residuals round) |
| K. WS7 emits a word's trailing punctuation as its own separate chunk, just outside mechanism C's own kerning-pair bound | WARPRAYR ("country"+","), LYING (comma/period splits), -README, LJ6DTP (partial) | word-unmatched, extra-word-in-engine | **TOOLING** (harness word-matching, wider sibling of mechanism C) | **FIXED** (`tools/pcl_tolerance.py` `_merge_trailing_punctuation_chunks`, own wider epsilon — widening C's OWN bound instead was tried and reverted, see below) |
| L. `[image: NAME]` picture placeholder has no WS7 text counterpart (real WS7 printed the raster) | PREVIEW (`[image: WORDSTAR.PIX]`) | extra-word-in-engine | **STRUCTURAL** (text vs. raster, not a position or content bug) | **FIXED** (`tools/fidelity_gate.py` `engine_page_tokens`/`_IMAGE_PLACEHOLDER_RE`, residuals round) |
| M. A fontless `.h#`/`.f#` header/footer line's own inline style-toggle byte (e.g. `^Y` italic) leaked into the Printed PDF as a literal control character instead of being interpreted | -README (`.h1`, wrapped in one `^Y`...`^Y` pair) | extra-word-in-engine, word-unmatched, exact-drift, line-start-shift (everything on the header line after the phantom glyph) | **BROAD SUPPORT** (any fontless header/footer with an inline toggle) | **FIXED** (`src/ctrlkd/pdf.py` `_hf_line_ops`, residuals round) |
| N. A WS7 chunk that glues a box-drawing/table-border character directly onto a word with no space | SCRIPT ("│Figure") | word-unmatched, extra-word-in-engine | **TOOLING** (WS7's LaserJet Courier charset draws box-drawing as a font glyph; our engine draws it as a vector) | **FIXED** (`tools/pcl_tolerance.py` `_strip_leading_box_drawing_chunks`, residuals round) |

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

## G. Superscript/subscript advance width in fixed-pitch text — FIXED

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

**Root cause, found** (2026-09-06 research pass,
`jon_vault/.../research/2026-09-06_ws7-blank-lines-and-superscript-advance.md`,
section G): the first attempted fix's own hypothesis was half right and
half wrong. Instrumented raw PCL from two independent WS7 captures
(DOCC.pcl, -SCREEN.pcl) shows the SAME byte-identical font-select pair
in both: body `ESC(sp12v10.00hsb4099T` (12pt, 10.00cpi = 7.2pt/char
cell) vs. sup/sub `ESC(sp9.25v13.04hsb4099T` (9.25pt, 13.04cpi =
5.5pt/char cell). Real WS7 does not merely draw a smaller glyph at the
document's ambient pitch (the first attempt's assumption) — it
RESELECTS an independently narrower PITCH, a separate field of the same
PCL command, restored to the body's own values on exit. Confirmed this
was also the reason the first attempt found "no change whatsoever": it
changed the WIDTH TARGET passed to `_span_pitch`, but `_span_pitch`
ignores that argument entirely once a real font block exists (`w /
HMI_PER_POINT`) — the exact suspicion the first attempt's own status
note raised, now confirmed directly (`_span_font`/`doc.fonts` dump
against both real corpus files: -SCREEN's demo characters carry a real
`font0` tag with `width_1800`; DOCC's own fnref markers carry NO font
tag at all, `entry` is `None`). The two documents therefore hit
DIFFERENT existing code branches of the SAME underlying bug: -SCREEN
(entry present) drew the FULL un-narrowed 7.2pt body cell for every
sup/sub character, landing everything after it +1.7pt (7.2-5.5) too far
right each occurrence; DOCC (entry `None`, `_span_pitch` falls back to
`pt * 0.6`) used the ALREADY-reduced `pt` (the old flat-2/3-ratio 8pt),
narrowing the cell TWICE to 4.8pt, 0.7pt narrower than WS7's real 5.5pt,
landing everything after it 0.7pt too far LEFT — opposite sign, same
root cause, matching both documents' own measured residuals exactly.

**Fix.** Two independent, additive changes in `src/ctrlkd/pdf.py`,
scoped to Printed mode's fixed-pitch line renderer only:
- `_sized()` now looks up a per-family sup/sub SIZE ratio
  (`_SUP_SUB_XHEIGHT_RATIO`), Courier keyed to the measured 9.25/12 =
  0.7708 (confirmed DIFFERENT from the manual's own Times-Roman worked
  example, 8.1/12 = 0.675 — a real font-specific x-height fraction, not
  a universal constant). Every other family keeps the prior flat 2/3
  default unconditionally (a new `family=None` default keeps every
  other call site, including all of Modern mode, byte-for-byte
  unaffected).
- A new `_sup_sub_span_pitch()` overrides the fixed-pitch CELL width for
  a sup/sub run: `body_cell * (5.5/7.2)`, keyed off the span's own
  UNREDUCED declared size (`size_here`, available at the same call
  site) rather than the already-reduced `pt` — this one change fixes
  BOTH real shapes (entry-present and entry-`None`) with the same call,
  since `_span_pitch(entry, size_here)` always answers "the span's own
  BODY cell" regardless of which branch it takes internally.

**Tests.** Two new Tier-1 unit tests
(`test_pdf_sup_in_fixed_pitch_ws7_font_block_uses_the_narrower_courier_cell`,
`test_pdf_sup_in_fontless_ws4_span_is_not_narrowed_twice`,
`tests/test_ctrlkd.py`) reproduce both shapes with synthetic content and
the measured decipoint arithmetic, mirroring -SCREEN's own mid-line
unjustified demo and DOCC's own no-gap-before-the-toggle shape
respectively. One existing test's regex widened to allow the optional
`Tz` operator this fix now sometimes needs for a Courier sup/sub run
(5.5pt no longer always equals Courier's own natural glyph width at the
reduced size).

**Result** (`tools/pcl_tolerance.py --doc`): DOCC 83 exact-drift → 0
(clean, PASSES `pytest -m pcl`). -SCREEN 25 exact-drift → 0; 8 unrelated
divergences remain (extra-word-in-engine 4, word-unmatched 4 — a
completely separate Symbol-font/cp437 encoding issue, not diagnosed
further this round, see the residuals-round summary below).

Commit f328838.

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

`cgtimes-drift-exceeds-tolerance`: LYING (4), WARPRAYR (0, see below),
LJ6DTP (4) — real CG-Times-substituted-to-Times word positions whose
drift exceeds the modelled bounded-per-line-distance tolerance (`tools/
pcl_tolerance.py`'s own `cgtimes_tolerance_pt`). Per the finalization
plan and Jon's ruling, this class is accepted by rule (a base-14-only
PDF cannot metrically match CG Times) — not touched, not tolerance-
widened. WARPRAYR's own count is confirmed 0 as of the residuals round
below (it was 25 before mechanism C landed — the alignment-desync
explanation this entry used to flag as unverified is now confirmed:
mechanism C's own merge fixed essentially all of it).

**The word-wrap-point cascade (residuals round, 2026-09-06).** Traced
LYING's and WARPRAYR's own remaining post-mechanism-J/K/L/M/N residuals
(LYING: 27 of 31; WARPRAYR: 6 of 11) to ONE shared root, not a new
mechanism: CG-Times' real metrics differ from Times' just enough that
our engine sometimes WRAPS a line at a different word boundary than
real WS7 did. Confirmed directly — LYING's own "lies--every" (engine,
end of one visual line) / "day;" (engine, start of the next) vs. WS7's
own single, unbroken "lies--everyday;" chunk (same visual line, no
wrap at all); the identical shape recurs at "failing--a"/"wholly" vs.
"failing--awholly", "case--as"/"personal" vs. "case--aspersonal", and
WARPRAYR's own "\"Bless"/"our" vs. "\"Blessour". Every one of these is
a real, DIFFERENT wrap decision, not a position or chunk-splitting bug
— a base-14 Times substitute inevitably accumulates a different
line-fill total than real CG-Times over a long enough run, and once a
line wraps differently, the following words' `extra-word-in-engine`/
`word-unmatched`/`baseline-shift`/`line-start-shift` divergences are
mechanical consequences of that ONE upstream difference, not four
separate bugs. This is the SAME accepted-by-design limitation this
section already names for `cgtimes-drift-exceeds-tolerance` — extended
here to its DOWNSTREAM effect on where lines wrap, still governed by
the same ruling (not touched, not tolerance-widened; fixing it would
mean either embedding CG-Times' own metrics, which the base-14-only
ruling rules out, or reverse-engineering WordStar's own exact
line-fill arithmetic well enough to match a font we do not have — out
of scope). **Named, not fixed**, same as every other font-substitution
residual in this section.

---

## J. A style toggle with no space drops the preceding character's own advance — FIXED (tooling)

**Evidence.** BOXES.WS: source `...to double lines (` + BOLD-toggle +
`^K'` + BOLD-toggle-off (no space between "(" and the toggle). Real
WS7's own measurements.json records BOTH the plain "(" chunk and the
bold "^K'" chunk starting at the IDENTICAL x (489.6pt) — one full
7.2pt Courier column short of where "(" 's own natural width would put
it. Our engine draws the two runs CONTIGUOUSLY (correct, unambiguous
fixed-pitch typesetting — nothing in WordStar's own spec says a toggle
eats a character's advance), so this is WS7's own driver artifact at a
style-change boundary, the same class of "capture artifact, not a real
position" mechanisms C and D already give this driver's other quirks.

**Fix.** `tools/pcl_tolerance.py`'s `_correct_toggle_boundary_chunks`:
when a chunk's x is EXACTLY equal to the immediately preceding chunk's
own x AND its font differs (a style toggle, not two chunks of the same
run mechanism C already owns), its x is corrected forward to the
preceding chunk's own natural AFM end before matching. Scoped tightly
to an EXACT x match (not a fuzzy epsilon) — the one confirmed shape.
Unit-tested (4 tests, `tests/test_pcl_tolerance.py`) including two
near-misses that must NOT fire (same font, or not an exact x match).

**Before/after:** BOXES `exact-drift` 1 → 0 (clean, PASSES). VERSIONS
`line-start-shift` 2 → 0 (clean, PASSES) — its own remaining
divergence after mechanism D turned out to be this same shape.

---

## K. WS7 splits a word's trailing punctuation into its own chunk — FIXED (tooling)

**Evidence.** WARPRAYR.WS: "country" at x=92.4pt (12pt Times-Roman,
natural AFM width 36.66pt → expected continuation at 129.06pt), but
WS7's own "," chunk starts at 131.0pt — a 1.94pt gap, just OUTSIDE
`KERNING_MERGE_EPS_PT` (1.5pt). The same shape recurs in LYING and
-README. This is mechanism C's own territory (a WS7 driver chunk
split) but with a WIDER, more variable gap than a kerning-pair split —
trailing punctuation apparently kerns slightly looser than a genuine
kerning PAIR does.

**Widening `KERNING_MERGE_EPS_PT` directly was tried and reverted.**
2.0pt and 2.5pt were each tested against the full 10-document set:
BOTH made every other document WORSE, not better (WARPRAYR itself
13→24 divergences at 2.0pt, 13→65 at 2.5pt; LYING 41→42/157; LJ6DTP
worse at every step) — real inter-word gaps in this corpus's smaller
CG-Times/Univers-substituted running sizes get that close too, so
widening mechanism C's own bound merges genuinely separate WORDS far
more often than it catches real kerning-pair splits. `KERNING_MERGE_EPS_PT`
stays 1.5, documented in its own comment as deliberately not widened.

**Fix.** A SEPARATE function, `tools/pcl_tolerance.py`'s
`_merge_trailing_punctuation_chunks`, with its OWN wider bound
(`TRAILING_PUNCT_MERGE_EPS_PT` = 3.0pt) — safe specifically because the
chunk being merged IN must be PURE punctuation
(`_is_pure_punctuation`: every character in `,.;:!?'")]-` and nothing
else), a shape a real standalone word's own WS7 chunk never takes (a
lone letter like "I"/"a" is explicitly excluded). This can never
mistake two adjacent short words for a word-plus-its-own-trailing-mark,
so widening it carries none of the direct-epsilon-widening risk.
Unit-tested (5 tests) including the "leaves two real words alone" and
"respects its own gap bound" cases.

**Before/after:** WARPRAYR `extra-word-in-engine` 7→6, `word-unmatched`
2→1. LYING `extra-word-in-engine` 19→14, `word-unmatched` 11→6.
LJ6DTP (parked, reported for completeness only) `extra-word-in-engine`
332→327, `word-unmatched` 187→183 — no regression anywhere in the
10-document set.

---

## L. `[image: NAME]` picture placeholder has no WS7 text counterpart — FIXED (tooling)

**Evidence.** PREVIEW.WS's own `[image: WORDSTAR.PIX]` (core.py's
literal placeholder text for an unembedded picture — `--pictures off`
is the CLI default) reads as TWO `extra-word-in-engine` divergences
("[image:" and "WORDSTAR.PIX]"), plus a separate, unrelated
`word-unmatched` for real WS7 content ("Italic" — see mechanism D's
own epsilon widening below, which resolved that one). This is not a
position bug: real WS7 printed the actual embedded raster, never a
text label — a structural difference this text-position gate was
never going to be able to check either way.

**Fix.** `tools/fidelity_gate.py`'s `engine_page_tokens` now skips any
text-showing op whose FULL text matches `_IMAGE_PLACEHOLDER_RE`
(`^\[image: .*\]$`) before word-splitting — the same class of
exclusion `_is_box_drawing_text`/`_is_unreliable_to_align` already give
WS7-side chunks the gate cannot meaningfully align. Unit-tested
(`test_engine_page_tokens_excludes_a_picture_placeholder_span`,
`tests/test_fidelity_gate.py`) with real prose before/after the
placeholder in the same page, confirming only the placeholder's own
tokens are dropped.

Also independently fixed this round: `_dedupe_double_strike_chunks`
(mechanism D) widened from an EXACT x match to a `DOUBLE_STRIKE_EPS_PT`
(2.0pt) tolerance — PREVIEW's own "Italic" label is WS7's own
double-strike fake-ITALIC (not just bold), and its second strike is
offset ~1.4pt (a slant simulation) rather than landing at the exact
same x a plain bold double-strike does. Verified this widening does
not swallow a real word-to-word gap anywhere in the 10-document set
(unit test: `test_dedupe_double_strike_chunks_epsilon_does_not_swallow_a_real_word_gap`).

**Before/after:** PREVIEW `extra-word-in-engine` 2→0,
`word-unmatched` 1→0 (clean, PASSES).

---

## M. A fontless header/footer line's own inline style toggle leaked as a literal control byte — FIXED (broad support, engine)

**Evidence.** -README.WS's own `.h1` (no font block, wrapped in one
`^Y`...`^Y` italic pair — WS_TOGGLES[0x19] == 'i'):
`src/ctrlkd/pdf.py`'s `_hf_line_ops` had TWO code paths — a
font-present branch that correctly runs the line through `hf_runs`
(interpreting toggle bytes into styles) and drawing per styled run, and
a "byte-identical to before this existed" fast path for the
overwhelmingly common fontless case that wrote the WHOLE raw string,
UNPROCESSED, into ONE `Tj` call. That fast path never checked whether
the raw string actually contained a toggle byte — so a fontless header
WITH an inline toggle (real, common: many documents style part of
their own running head) had its literal `\x19` control byte written
straight into the PDF. A PDF viewer (and this repo's own fidelity gate,
reproducing what one would compute) then advances the pen by whatever
width Courier's own AFM table gives an undefined glyph code —
`src/ctrlkd/afm.py`'s `_COURIER` table is `(COURIER_WIDTH,) * 256`,
i.e. EVERY byte value including the control range gets a full 7.2pt
advance — landing a phantom extra character glued onto the following
word. Confirmed on -README's own header: the engine's Printed PDF
carried `\x19WordStar` on every page (2-16), and `"N\x19"` (the page
number plus the CLOSING toggle, no space) wherever the substituted
page number was 2+ digits long enough to survive
`_is_unreliable_to_align`'s own length-2 filter (single-digit pages'
own `"N\x19"` are 2 characters, filtered out the same way a lone
comma is — this is why the bug was invisible on pages 2-9 and only
showed up as divergences on 10-16). "7.0"/"Archive" (the words AFTER
the phantom glyph) landed 7.2-14.4pt right of WS7's own real
(correctly-italic-then-restored, no phantom glyph) position.

**Fix.** `_hf_line_ops`'s fontless fast path is now taken ONLY when the
line has no byte below 0x20 at all (`res is None or not any(ord(c) <
0x20 for c in txt)`, `entry is None` unchanged) — otherwise it falls
through to the SAME run-by-run `hf_runs` loop the font-present branch
already used, with `family='Courier'`/`pt=size` substituted for the
missing font entry. A `res is None` caller (there is no way to
register a font without one) always keeps the old single-Tj behaviour,
matching the docstring's own prior guarantee. Two new Tier-1 tests
(`tests/test_printed_fidelity.py`): one confirms no `\x19` byte reaches
the PDF and that "WordStar 7.0 Archive / 1" renders as real italic
Courier-Oblique text at the document's own left margin; the other
confirms a PLAIN header (no toggle bytes at all — the overwhelmingly
common case) stays on the exact prior single-Tj path, byte for byte.

**Before/after (-README):** `extra-word-in-engine` 22→0,
`word-unmatched` 15→0. `exact-drift` 31→15 (the running-head
cascade this phantom character caused on every page). One NEW class of
divergence appeared as a side effect of the fix correctly EXPOSING
content that previously never reached text comparison at all —
`line-start-shift` 1→8, all "WordStar" itself, all on 2-digit pages
(10-16) only, all a consistent 7.2pt raw offset. Traced as far as: the
header's own SOURCE carries a `\t` (TAB) inside a paragraph-style
property block immediately before the toggle-wrapped text, which core.py
converts to a fixed 41-space run at PARSE time (same for every page);
real WS7 evidently recomputes this padding PER PAGE based on the
ACTUAL substituted page-number width (a true right-tab), narrowing by
one column when the page number grows from 1 to 2 digits, while our
engine's baked-once padding does not. **Diagnosed, not fixed this
round** — reproducing WordStar's own dynamic right-tab arithmetic for
a header/footer `#` token is a real, separate architecture question,
out of this round's scope; -README's own `sources.json` v1.4→v1.5
staleness is NOT a factor here (mechanism E already generalized past
it).

---

## N. A WS7 chunk glues a box-drawing character onto an adjoining word — FIXED (tooling)

**Evidence.** SCRIPT.WS: a table-bordered figure caption, "│Figure" —
ONE literal WS7 print chunk combining the border character and the
word with no space. The LaserJet's resident Courier charset draws a
box-drawing character (cp437's own extended range, U+2500-25FF) as an
ORDINARY GLYPH, same font, same advance as any other character — WS7's
own driver never distinguishes it from real text. Our own engine draws
a box-drawing character as a VECTOR (`_graphic_ops`, Jon's ruling: real
drawn lines, not a font glyph standing in for one) and keeps it
entirely separate from the adjoining text span (`_split_graphics`) — so
our own "Figure" token never carries a box character, and never will,
no matter how correct its position.

**Fix.** `tools/pcl_tolerance.py`'s `_strip_leading_box_drawing_chunks`
strips a WS7 chunk's own LEADING box-drawing/block/geometric run
(reusing `_BOX_DRAWING_RANGES`, the same ranges `_is_box_drawing_text`
already uses for a chunk that is NOTHING BUT box-drawing characters)
before matching, correcting the chunk's x forward by the stripped
run's own natural AFM width — the same "this is what our engine's own
text stream would show" normalization mechanisms C/J/K already give
this driver's other representation differences. Unit-tested (3 tests)
including a pure-box-drawing chunk (left alone — `_is_box_drawing_text`'s
own territory) and plain text (left alone).

**Before/after (SCRIPT):** `extra-word-in-engine` 2→0 (the "Figure"
half), `word-unmatched` 2→0 (the "│Figure" half).

---

## Summary — all rounds (mechanism-G round + residuals round, 2026-09-06)

**Fixed, in the engine (`src/ctrlkd`), each with a Tier-1 test:**
- Mechanism A: `_printed_pm_fi_pt` (pdf.py) — commit 8956ad4.
- Mechanism G: `_sized`/`_sup_sub_span_pitch` (pdf.py) — commit f328838.
- Mechanism M: `_hf_line_ops` (pdf.py) — residuals round.

**Fixed, in the test harness (`tools/fidelity_gate.py`/`tools/pcl_tolerance.py`), not the engine:**
- Mechanism B: `_TEXT_OP_RE` operator order — commit 7285270.
- Mechanism C: `_merge_kerning_split_chunks` — same-day follow-up.
- Mechanism D: `_dedupe_double_strike_chunks` — same-day follow-up;
  widened to a 2.0pt slant-offset tolerance in the residuals round
  (`DOUBLE_STRIKE_EPS_PT`, mechanism L's own follow-on).
- Mechanism E: `resolve_doc_paths` prefers a doc's own `v2` capture over
  `v1` when one exists — same-day follow-up, generalized beyond -README.
- Mechanism J: `_correct_toggle_boundary_chunks` — residuals round.
- Mechanism K: `_merge_trailing_punctuation_chunks` — residuals round
  (its own wider epsilon; widening C's directly was tried and reverted,
  see mechanism K's own entry).
- Mechanism L: `_IMAGE_PLACEHOLDER_RE` exclusion in
  `fidelity_gate.engine_page_tokens` — residuals round.
- Mechanism N: `_strip_leading_box_drawing_chunks` — residuals round.
- The `pcl` tier's own reason-filter defect (`tests/test_pcl_fidelity.py`
  used to filter on a reason string `doc_report()` never emitted) — same-
  day follow-up, `FONT_SUBSTITUTION_REASONS`/`is_font_substitution_reason`.

**Resolved as a corpus/tooling artifact, not an engine or harness change:**
- Mechanism F: OCAPTAIN/TWAINLET's `baseline-shift` was a bug in the v1
  capture pipeline's own blank-line accounting, not a real WS7 print
  behavior — the v2 recapture (different tooling) shows the full,
  uncollapsed advance our engine already produces. Resolved as a side
  effect of generalizing E, not sought directly.

**Parked per Jon's ruling:** H (LJ6DTP printing hacks).

**Accepted by design:** I (font-substitution residuals, INCLUDING the
word-wrap-point cascade it causes — see mechanism I's own entry, updated
this round). WARPRAYR's own `cgtimes-drift-exceeds-tolerance` count
confirmed 0 (was 25 before mechanism C landed).

**Diagnosed with concrete evidence, not fixed this round:**
- Mechanism M's own side effect on -README: real WS7 evidently recomputes
  a header/footer's own tab-derived leading indent PER PAGE based on the
  substituted page number's actual width (a true right-tab); our engine
  bakes the indent once at parse time. Affects only documents crossing a
  page-number digit-count boundary with a tab-padded `#` header/footer —
  -README is the only one in this corpus's named set.
- -SCREEN's remaining 6 divergences (`extra-word-in-engine` 2,
  `word-unmatched` 4, exposed only after mechanism G's fix stopped them
  hiding behind the sup/sub exact-drift noise): a Symbol-font Greek
  alphabet demo where SOME characters are typed via cp437's own native
  Greek-lookalike bytes (e.g. 0xE1/0xE6, cp437's own "ß"/"µ" glyphs used
  as a Beta/mu stand-in) mixed with OTHERS typed as ASCII + an explicit
  Symbol-font toggle in the SAME visual run — our engine renders the
  cp437-native bytes as literal Courier "ß"/"µ" text (their genuine
  cp437 decode) rather than routing them through the Symbol font the
  surrounding toggle established, while the ASCII+toggle characters
  round-trip correctly. One contrived reference/demo line, not
  reproduced elsewhere in the corpus; not investigated further this
  round (a real fix needs tracing exactly which code path a Symbol-font
  span's own cp437-native-byte characters take through
  `core.py`'s parser, separate from this triage's own scope).
- SCRIPT's remaining 14 divergences (`exact-drift` 12,
  `line-start-shift` 2, all one running-head/footer line, "PROFILES
  MONTH '88 SCRIPT.001..."): a consistent 21.6pt (3-character) left
  offset between our engine's rendered position and WS7's own capture.
  SCRIPT.WS is one of the triage's own noted `driver-missing` stalls
  (mechanism E's entry) — its embedded printer driver is LQ-850, an
  EPSON DOT-MATRIX driver, never installed in the `ws7-prints/v2` batch
  harness, so SCRIPT's own capture is still on `v1` while every other
  document in this round switched to `v2`'s LaserJet-driver captures.
  This document's own real-WS7 ground truth was produced by a
  DIFFERENT printer driver family than the LaserJet conventions this
  engine (and the rest of this corpus) targets — plausibly a genuine
  driver-specific margin convention, not an engine bug to chase. Not
  investigated further this round; would need either a LaserJet
  recapture of SCRIPT (planning #196's own job) or explicit
  LQ-850-aware modelling, out of this round's scope.

**Result after both rounds** (`pytest -m pcl`, corpus armed): of the 13
documents named in planning #202, BOXES, DOCC, OCAPTAIN, PREVIEW,
SAWYER, TWAINLET and VERSIONS now PASS (7 of 13, up from 3 after the
first follow-up round). LJ6DTP (parked, by instruction), LYING,
-README, -SCREEN, SCRIPT and WARPRAYR still FAIL BY NAME. Per-document
divergence counts, before this round's fixes → after (LJ6DTP included
for completeness only; excluded from the "fixed" claim by Jon's
ruling):

| Doc | Before (mechanism-G round's own starting point) | After |
|---|---|---|
| WARPRAYR | 13 | 11 |
| VERSIONS | 2 | 0 (PASSES) |
| PREVIEW | 3 | 0 (PASSES) |
| BOXES | 1 | 0 (PASSES) |
| LYING | 41 | 31 |
| SCRIPT | 31 | 14 |
| -README | 88 | 23 |
| -SCREEN (after mechanism G) | 8 | 6 |
| DOCC (mechanism G) | 83 | 0 (PASSES) |
| LJ6DTP (parked) | 1260-ish, unchanged in kind | still large, not a target |

See `tools/pcl_tolerance.py`'s own commit history and `tests/
pcl_fidelity_manifest.json` for the exact current counts by reason, per
document.
