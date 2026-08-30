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
