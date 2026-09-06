# PCL divergence triage — 2026-09-06

Written against `tests/pcl_fidelity_manifest.json` as recorded by ctrl-kd
6741c10, then re-measured live after the fixes below landed. Scope: the
13 documents named in planning #202 (BOXES, LJ6DTP, LYING, OCAPTAIN,
PREVIEW, -README, SAWYER, -SCREEN, SCRIPT, TWAINLET, VERSIONS, WARPRAYR,
DOCC). Jon's ruling (#202, verbatim): fix the BROAD SUPPORT mechanisms
(page breaks, line spacing, margins, tabs, fixed-pitch positioning —
things every document relies on); LJ6DTP's own "printing hack" items stay
parked; font-substitution residuals are named, not fixed.

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
| C. WS7's own kerning-pair chunk-split ("W"+"ar", "Y"+"ou", "T"+"wain") | WARPRAYR (title "War"), TWAINLET/-README/others ("You", "Twain") — recurring across the corpus wherever a kerned pair starts a chunk | word-unmatched, extra-word-in-engine, and the alignment desync this causes for everything after it on the page | **TOOLING** (harness word-matching, not an engine behaviour — see below) | **DIAGNOSED, NOT FIXED** |
| D. Duplicate-position WS7 chunks (double-strike bold) | BOXES, SAWYER, VERSIONS (~all of their word-unmatched); partial in PREVIEW, SCRIPT, -SCREEN | word-unmatched, line-start-shift | **TOOLING** (harness word-matching) | **DIAGNOSED, NOT FIXED** |
| E. `-README` v1 capture predates the current Sawyer archive file (v1.4 → v1.5) | -README | page-count-mismatch, and very likely most of its baseline-shift/word-unmatched/extra-word-in-engine | **CORPUS STALENESS** (not an engine bug) | **DIAGNOSED**, needs corpus recapture (planning #196/task 2), out of this repo's scope |
| F. 2 consecutive blank source lines print as 1 blank line's advance, but ONLY in plain-default-leading (no `.lh`/style) documents | OCAPTAIN, TWAINLET | baseline-shift (all of it, both docs) | Looked BROAD SUPPORT, but... | **OPEN — insufficient evidence for a safe rule** (see below) |
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

**Recommended fix (not attempted — out of my remaining budget this
round):** in `tools/pcl_tolerance.py`'s `load_ws7_tokens`, before
building tokens, merge two adjacent same-line WS7 chunks when the
second's `x_decipoints` start lands within a small epsilon of the
first's own AFM-measured natural end (`fg.afm.string_width_pt`) — i.e.
undo WS7's own kerning-pair chunk split before alignment, the same way
`_is_box_drawing_text`/`_is_unreliable_to_align` already pre-filter WS7
chunks before matching. This is squarely a harness fix, not an engine
change.

---

## D. Duplicate-position WS7 chunks (double-strike bold) — diagnosed, not fixed

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

**Recommended fix (not attempted):** `load_ws7_tokens` should de-duplicate
consecutive identical-text WS7 chunks at the identical (x, y) position
before handing them to `fg.match_doc` — a harness fix, not an engine
change; it would clear most of these three documents' counts without
touching the engine at all.

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

**Recommendation to whoever owns task 2:** recapture (or re-point
`pcl_tolerance.py`'s `PRINTS_SUBDIR`/doc resolution at) `v2` for every
Sawyer-archive document, not just -README — I did not find evidence any
of the other 6 Sawyer-group documents in this triage (BOXES, SAWYER,
SCRIPT, VERSIONS, PREVIEW, -SCREEN) have the SAME page-count-jump
problem (their own WS7/engine page counts already agree), but I also
didn't do a byte-for-byte content diff of every one against `v2` where
one exists — only BOXES and -SCREEN were spot-checked (their v2
captures matched v1, not stale).

---

## F. Two consecutive blank lines print as one, in plain-leading documents only — OPEN

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

**Divergence counts, unaffected by anything landed this round:**
OCAPTAIN `baseline-shift` 22 (all of it), TWAINLET `baseline-shift` 25
(all of it).

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

**Fixed, in the test harness (`tools/fidelity_gate.py`), not the engine:**
- Mechanism B: `_TEXT_OP_RE` operator order — commit 7285270.

**Diagnosed with concrete evidence, not fixed this round (documented
above for whoever picks each one up next):**
- C (WS7 kerning-pair chunk split — harness fix, `load_ws7_tokens` merge)
- D (WS7 duplicate-strike-bold chunks — harness fix, `load_ws7_tokens` dedupe)
- E (-README stale v1 capture — corpus recapture, outside this repo)
- F (2-blank-line collapse — needs a real WS7 probe before any fix)
- G (sup/sub fixed-pitch advance width — first hypothesis disproven, root cause not yet located)

**Parked per Jon's ruling:** H (LJ6DTP printing hacks).

**Accepted by design:** I (font-substitution residuals).

No document in this batch is fully clean after this round's fixes — the
manifest is regenerated (see the commit that updates
`tests/pcl_fidelity_manifest.json`) but NOT blessed/loosened for any of
the 13 named documents: every one of A-I above is either a real
remaining bug (F, G), a parked/accepted class (H, I), or a harness/
corpus problem outside this repo's engine (B is fixed in the harness
already; C, D, E are diagnosed but not yet fixed in the harness). The
`pcl` tier will keep failing by name on all 13 documents until the
harness fixes (C, D) and the real remaining engine bugs (F, G) are
addressed — which is the correct, honest state per this repo's own
"a divergence outside tolerance fails the test by name" doctrine.
