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
  hand-written on the base-14 Courier fonts for exactly this reason. Don't add deps.
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

`pytest tests/ -q`. **Synthetic fixtures ONLY** — the development corpus is personal
and must never enter this repo, not even as a "temporary" test file. Every real-world
behavior gets encoded as constructed bytes (see the `ws4_text`/`ws7_block` helpers).

## Prose is untested — sweep it on every change

The `--help` string once advertised the wrong format list for two releases. When
formats/flags change, update: cli.py `description=`, README intro + examples,
EXTENDING.md, pyproject.toml `description`, and the Homebrew formula `desc`.

## Releasing

Which number moves: **patch** = bug fix, no interface change; **minor** = new
format/flag/IR field, existing code keeps working; **major** = anything that breaks
the CLI, `convert()`, or the IR contract (see above).

1. Bump version in **both** `pyproject.toml` and `src/ctrlkd/__init__.py`.
2. Tests green; if behavior changed, eyeball real output, don't trust exit codes.
3. Commit, tag `vX.Y.Z`, push main **and** the tag — the tag triggers
   `.github/workflows/publish.yml` → PyPI via trusted publishing (no tokens).
4. PyPI's JSON API caches; confirm the upload in the workflow log, not the API.
5. `gh release create vX.Y.Z ...` — the tag alone is invisible on the Releases page.
6. Bump the Homebrew formula in `jonmichaels/homebrew-tap` (`Formula/ctrl-kd.rb`)
   to the new sdist, then sanity-check on a Mac
   (`brew update && brew upgrade ctrl-kd && brew test ctrl-kd`):

   ```console
   $ curl -s https://pypi.org/pypi/ctrl-kd/json | python3 -c "
   import json,sys
   d=json.load(sys.stdin); v=d['info']['version']
   f=[x for x in d['releases'][v] if x['packagetype']=='sdist'][0]
   print(f['url']); print(f['digests']['sha256'])"
   ```

   A new dependency would also need `resource` blocks in the formula — and ctrl-kd
   has none by design, so that's a decision, not a detail.
