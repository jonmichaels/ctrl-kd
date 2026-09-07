# ctrl-kd — project conventions

Converts WordStar 4–7 documents and print-to-disk files to text/Markdown/HTML/RTF/PDF.
This file is PUBLIC — it describes the project only. Anything about the maintainer's
own machines, deployment, or data does not belong in this repo, ever.

## Architecture (don't fight it)

One IR, many emitters: `core.py` (detection + parsing → Document/Block/Line/Span) →
`emit.py` / `pdf.py` (registry of emitters). The IR contract is documented in
**EXTENDING.md** and is a compatibility promise: third-party plugins depend on it.
Changing Block/Line/Span, `convert()`, or CLI flags is a **major version bump**, period.

- **Zero runtime dependencies is a design constraint**, not an accident. PDF is
  hand-written on the base-14 fonts (Courier/Times/Helvetica/Symbol/ZapfDingbats —
  every viewer has them, so nothing is ever embedded) for exactly this reason.
  Don't add deps.
- New output formats go through the registry (`@emitter(...)` in emit.py, or the
  `ctrlkd.emitters` entry-point group) — never special-cased in cli.py.
- Detection is **content-based, never extension-based**. Names lie.

## Behaviors are empirical — don't "fix" them without evidence

The parsing rules were derived from a real 1987–92 WS4 corpus verified against
period printouts, plus the 86 WS7 documents in Robert J. Sawyer's public archive:

- The wrap test uses **strict** `<` (WS4 wrapped even on an exact-margin fit).
- Margin estimate = p90 of soft-wrapped line lengths, floor 65. Max is wrong.
- WS4's bit-7-on-last-letter applies to **control toggles too** — mask before dispatch.
- High-bit density alone is not WS4 evidence (binaries are full of high bytes).
- Print-stream code pairs (0x18/0x12 sup, 0x10/0x11 u, 0x13/0x15 + 0x05/0x06 i,
  0x1E/0x1F b) were decoded from one late-80s driver; they're a table, not gospel.

If a change touches any of these, it needs a failing synthetic fixture first.

## Tests

`pytest tests/ -q` is the REDUCED suite. The real one is `tools/run-full-suite.sh`,
which arms every corpus gate and runs the privacy audit. A bare `pytest` number is
not a result — say which suite produced it.

**Synthetic fixtures ONLY** — the development corpus is personal and must never
enter this repo, not even as a "temporary" test file. Every real-world behavior
gets encoded as constructed bytes (see the `ws4_text`/`ws7_block` helpers).

**A skipped check is not a passing check.** Corpus-dependent tests are gated on
environment variables; unset, they used to skip themselves and vanish from the
totals while the suite still reported success. The Sawyer-archive gate now
FAILS instead once armed (`tests/conftest.py`, `require_sawyer_doc`). Prefer
that shape for any new gate.

**Pictures are a real axis, not an afterthought.** `--pictures` (off/embed/
export, CLI default `embed`) is a shipped, user-facing flag — `tests/
answer_key.json`'s `axes.pictures` and `tools/answer_key.py`'s own
`PICTURES_AXIS` docstring note are the record of it. Every document's
`cells` grid is recorded with `pictures='embed'` and that document's own
resolved `PixResult` list (the product default, actually exercised, not an
emitter's library-internal fallback); a document with `picture_bearing:
true` (`doc.graphics` non-empty) additionally carries a `cells_pictures_off`
grid for the CLI's other value. The `pcl` tier's own `fg.render_engine_pdf`
follows the same rule (planning #211, mechanism L revisited,
`tools/PCL-DIVERGENCE-TRIAGE.md`) — a picture-bearing captured document's
raster position/size is compared against real WS7 too now, when the
capture has one (`raster-position-shift`/`raster-size-mismatch`/
`raster-count-mismatch`, `tools/pcl_tolerance.py`). Get this wrong (render
with the library's own `pictures='off'` default instead of the CLI's) and
a picture-bearing document's real embedded-image byte stream is silently
never exercised by anything — exactly what happened before this note
existed.

**The `pcl` gate can judge a PDF it cannot parse.** `tools/fidelity_gate.py`'s
own `parse_text_ops` is a small content-stream state machine (`Tf`/`Tz`/
`Ts`/`Tr`/`w`/`Td`/`TD`/`Tm`/`T*`/`Tj`/`TJ`/`'`/`"`, any operand order —
replaced a regex keyed to one fixed order, mechanism Z,
`tools/PCL-DIVERGENCE-TRIAGE.md`) — but it is still not a general PDF
interpreter: a PDF a different emitter wrote (macOS Quartz's hex-string
text over CID/Type0 subset fonts, e.g., whose string bytes are glyph
indices, not characters) extracts as zero words, not "everything
unmatched." `--engine-words FILE` (both `fidelity_gate.py`
and `pcl_tolerance.py`'s own `--doc`) takes a PRE-EXTRACTED words JSON
instead of a PDF — see the "engine-words (JSON)" schema comment above
`dump_engine_words()` in `tools/fidelity_gate.py` for the exact shape (a
producer must supply `font_class` directly; it is never re-derived from a
subset font name). `--dump-engine-words FILE` produces that same JSON from
ctrl-kd's own PDF, so the round-trip claim (`gate(pdf) ==
gate(--engine-words dump(pdf))`) is checked in
`tests/test_fidelity_gate.py` against the bundled public samples plus a
generated picture-bearing fixture — Tier 1, no private data. Everything
downstream of extraction (matching, tolerance, reason vocabulary, manifest
comparison) is unmodified either way.

**External readers hand this gate CHARACTERS, not words — one segmenter,
for both sides.** The macOS app's own PDFKit/Quartz-based reader tried to
re-implement mechanism Z's own word-boundary rule
(`segment_words_from_chars`/`char_space_width_pt`) a second time, against
real glyph advances, and regressed — Jon's ruling, 2026-09-07: an external
reader hands this gate raw characters and this gate does the segmentation
itself, in ONE place. `--engine-chars FILE` (both `fidelity_gate.py` and
`pcl_tolerance.py`'s own `--doc`), schema_version 2, is one level lower
than `--engine-words`: per-character `text`/`x_pt`/`x_end_pt` (the ADVANCE
end, never the glyph box)/`y_top_pt`/`size_pt`/`font`(nullable)/
`font_class`(required)/`page` — see the "engine-chars (JSON)" schema
comment above `dump_engine_chars()` for the exact shape, and
`load_engine_chars()`'s own TOLERANCE note for the one place this path
could, in principle, disagree with the ops-based path (the boundary caps
are applied in page points, never re-scaled by a `Tz`-equivalent this
schema doesn't carry — confirmed to cost nothing against every bundled
sample, Tier 1 fixture, and the private corpus's 18 captured documents).
`--dump-engine-chars FILE` produces that JSON from ctrl-kd's own PDF, so
the three-way round-trip claim (`gate(pdf) == gate(--engine-words
dump(pdf)) == gate(--engine-chars dump(pdf))`) is checked in
`tests/test_fidelity_gate.py` against the bundled public samples, all four
Tier 1 synthetic styled fixtures (symbol-styled bold/italic, the -SCREEN
Greek/math zero-gap line, zero-gap punctuation, a superscript inside a
word), and the generated picture-bearing fixture — no private data.

## This repo is PUBLIC — the guard is mechanical, not advisory

Private material reached this repo repeatedly, and every fix added one more
literal to a list of known-bad words. That could only ever catch the leak that
had already happened: hooks installed 2026-08-20 passed a private repo path
straight through on 2026-08-23, because the path was a new SHAPE, not a listed
word. Three more leaks were sitting in tracked files, unnoticed, for weeks.

So the rule is about shape:

> **No filesystem path to anybody's machine, ever** — no `~/`, `/home/`,
> `/Users/`, `/mnt/`, `/root/`. Corpus roots come from the environment.
> No machine names. Not in code, not in comments, not in docstrings, not in
> commit messages, not in author/committer fields.

- `tools/private_patterns.sh` — the ONE pattern definition. Everything sources it.
- `tools/audit_private.sh` — scans the tracked set. Runs inside the full suite.
- `tools/githooks/` — pre-commit, commit-msg, pre-push. Tracked and reviewable.

**On a fresh clone, run `tools/install-hooks.sh` once.** The hooks used to live
untracked in `.git/hooks`, which meant they existed on exactly one machine and
nobody could review them.

Do not weaken the pattern to let something through — take the path out of the
code instead. Do not bypass with `--no-verify` without Jon's explicit word.

## Prose is untested — sweep it on every change

The `--help` string once advertised the wrong format list for two releases. When
formats/flags change, update: cli.py `description=`, README intro + examples,
EXTENDING.md, pyproject.toml `description`, and the Homebrew formula `desc`.

## Releasing

Which number moves: **patch** = bug fix, no interface change; **minor** = new
format/flag/IR field, existing code keeps working; **major** = anything that breaks
the CLI, `convert()`, or the IR contract (see above).

1. Bump `__version__` in `src/ctrlkd/__init__.py` — the ONLY version
   (pyproject reads it dynamically; a guard fails the release if the tag
   disagrees).
2. Tests green; if behavior changed, eyeball real output, don't trust exit codes.
3. Commit and push main.
4. `gh release create vX.Y.Z --title ... --notes ...` — writing the release
   IS the trigger: the pipeline (publish.yml, on release-published) guards
   the version, publishes to PyPI via trusted publishing, and bumps the
   Homebrew formula itself over the tap deploy key. Verify all three jobs
   green in the run; workflow_dispatch is the fallback if GitHub's event
   delivery is degraded (it was, 2026-08-06 — check githubstatus.com when
   runs go silent).
5. Windows exe: windows-exe.yml also fires on release-published — verify its
   run is green and BOTH zips landed on the release (ctrl-kd-X.Y.Z-windows-
   x86_64.zip + stable ctrl-kd-windows-x86_64.zip), then byte-check
   releases/latest/download/ctrl-kd-windows-x86_64.zip against the versioned
   asset. Content gate is EXECUTION (the workflow runs the exe and converts a
   sample) — strings-scanning is blind on Nuitka onefile's compressed payload.
   Full process doc: jon_vault WordStar/ctrl-kd-windows-exe.md.
6. Sweep README versions (download links, SPM examples, roadmap) — it went
   stale across two releases once.

**This list is MANDATORY at every release, read top to bottom.** 4.0.0
skipped its longer ancestor and shipped with a stale PyPI and a
two-majors-old formula; the automation (built 2026-08-06, proven live on
4.0.1) now does the mechanical steps, but the guard only protects the
releases you actually cut through it. soft-return has its own list; run
both when releasing in lockstep.

   A new dependency would also need `resource` blocks in the formula — and ctrl-kd
   has none by design, so that's a decision, not a detail.
