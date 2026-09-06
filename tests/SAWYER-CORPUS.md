# Tier 2: the Sawyer WS7 archive

Robert J. Sawyer, the science fiction author, has published his own
WordStar 7 install tree as a historical/archival download:
<https://www.sfwriter.com/ws7.htm>. It is real, period WordStar content —
the only corpus this project has ever been able to validate `.WS` parsing
against beyond synthetic fixtures — and unlike Jon's own private documents
(tested separately, outside this repo), it is PUBLIC. Ruled 2026-08-26: filenames and paths from it may
appear directly in this repo's code, because the archive itself is a public
download, not personal material.

**Release pinned: 1.5** (zip sha256
`10213b23b3d030951e093eba36a1e41cb3ea6732e8e761e1b356ba4bc902e1af`, verified
independently against the download at the URL above before this tier's
data was first generated). Release 1.4 — the copy this project used before
— differs from 1.5 in 34 same-named files, including one document this
tier tests (`-README.WS` at the archive root); every hash this tier checks
is computed against 1.5, and `sawyer_fixture.sawyer_manifest_problem()`
checks a version marker (`DESCRIPT.ION`'s own hash) before trusting
anything else in an armed run, specifically so a stale local copy fails
loudly with a clear reason instead of quietly passing against the wrong
bytes or drifting one file at a time. Release identity (the version
marker, source URL, zip hash) lives as constants in `sawyer_fixture.py`.

## Arming

    CTRLKD_SAWYER_ARCHIVE=/path/to/WS   pytest -m sawyer

`/path/to/WS` is the archive's own top-level directory (the one holding
`CONVERT.WS`, `INSET/`, `ARTICLES/`, etc.) — nothing is copied into this
repo.

**Verify your path before arming** — a one-liner that checks for the same
marker files the archive's own top level holds, and says which:

    test -f "$CTRLKD_SAWYER_ARCHIVE/CONVERT.WS" \
      && test -d "$CTRLKD_SAWYER_ARCHIVE/INSET" \
      && test -d "$CTRLKD_SAWYER_ARCHIVE/ARTICLES" \
      && echo OK || echo "wrong dir -- point CTRLKD_SAWYER_ARCHIVE at the archive's own top level"

## What this tier deliberately does NOT do, at test time

**No live directory sweep.** Earlier versions of several of these tests
globbed `**/*.WS` across the whole archive (~180 files, most of them
installers, help text, and dictionaries — not documents this project has
any opinion about). Tier 2 tests an EXPLICIT, COMMITTED list only — never
the live archive's contents at test-collection or test-run time. Once
armed, a listed document that is missing or whose content no longer
matches its committed hash FAILS the run loudly; anything else the archive
also contains (e.g. everything a stranger's full, untrimmed public
download has that isn't on this committed list) is simply never looked at.

## The committed list: `tests/answer_key.json`, not a hand-picked manifest

Planning #205(a), 2026-09-06: this tier used to run a hand-picked
252-entry `tests/sawyer_manifest.json` — the original ten documents plus
241 more taken verbatim from a vault catalog of "genuine WordStar
documents." That manifest is **retired**. The committed list is now
`tests/answer_key.json`'s `groups.sawyer` (the same file
`tests/test_samples.py` shares for the 4 bundled samples) — every file a
maintainer's `tools/answer_key.py --record` run found under
`CTRLKD_SAWYER_ARCHIVE` at generation time, mechanically classified by
actually running it through this engine's own `core.detect()`/
`core.parse()` and recording what happened, not by consulting a catalog:

1. **`convertible`** — `core.parse()` succeeds. Gets the full format x
   mode grid (see "Answer key" below), pinned by hash.
2. **`known_nonconvertible`** — `core.parse()` raises `ParseError`. The
   recorded `reason` is `str()` of that real exception (e.g. `"not a
   convertible file (detected: binary -- 82% text but no structure)"`),
   not a hand-typed description.
3. **`non_document_assets`** — not attempted through `parse()` at all: one
   hand-identified rule (`sawyer_fixture.sawyer_is_non_document_asset`),
   a `.PIX` Inset image a handful of kept documents embed-reference, is
   image data, not a WordStar document.

Every entry in all three groups carries its own `path` (relative to the
archive root) and `source_sha256` — `sawyer_fixture.py` builds `SAWYER_DOCS`
(name -> `{path, sha256}`) directly from this key, so nothing about *which*
files this tier knows about, or their hashes, lives anywhere else.

**Current counts** (see `tests/answer_key.json`'s own `counts` block for
the live numbers): the corpus's documents-only trim (which
`CTRLKD_SAWYER_ARCHIVE` is expected to point at when regenerating — see
below) held 396 files at last generation: 385 convertible, 10
known-nonconvertible, 1 non-document asset. The 2026-08-26 expansion's 252
entries (241/10/1) are an exact subset — the #205(a) expansion only added
previously-untested real documents (README/reference prose, `.LST`/`.DOC`
content, extensionless `TAGS/` tag documents, and the `.PAT`/`.MRG`
engine-input files this engine's `core.parse()` happens to also accept) to
the `convertible` bucket; nothing moved out of `known_nonconvertible` or
`non_document_assets`, and nothing that used to convert stopped.

**Naming.** A document's key in `groups.sawyer` is its path relative to
the archive root, with five pre-existing short aliases kept for backward
compatibility (three duplicate `-README.WS` basenames disambiguated by
directory, and two short aliases handed out when the original ten-document
manifest was first hand-built) — see `sawyer_fixture._NAME_OVERRIDES`.
Every other duplicate basename the corpus contains (`HP-ENV.LST` appears
3x, `MAILING.DOC` 2x, dozens more) is keyed by its own full path,
unambiguous by construction; new entries are never aliased.

| Manifest key | Path | Why it's here |
|---|---|---|
| `RJS.WS` | `RJS.WS` | whole-document strikethrough via a style-library `attrs_on` bit — the polarity gate's real-corpus check |
| `CONVERT.WS` | `CONVERT.WS` | cp437 vector bullet glyph aspect ratio |
| `LJ6DTP.WS` | `LJ6DTP.WS` | cp437 vector symbol-table glyph aspect ratio (card suits, etc.) |
| `PREVIEW.WS` | `PREVIEW.WS` | one of the 5 real documents that reference `WORDSTAR.PIX` |
| `-SCREEN.WS` | `-SCREEN.WS` | ditto; also the one with its own footnotes routing through paginated-notes PIX embedding |
| `-README.WS (root)` | `-README.WS` | ditto |
| `-README.WS (APP)` | `APP/-README.WS` | ditto (a distinct document, despite the same name) |
| `-README.WS (APP/vDosPlus)` | `APP/vDosPlus/-README.WS` | ditto |
| `SCRIPT.WS` | `ARTICLES/SCRIPT.WS` | the ONE document in the archive that should trip screenplay detection |
| `WORDSTAR.PIX` | `INSET/PIX/WORDSTAR.PIX` | the actual Inset image the 5 documents above reference; pixel-count/print-options size ground truth |

(`PREVIEW.WS` and `APP/-README.WS` happen to be byte-identical, 768-byte
stub documents in the real archive — not a bug, just a fact about the
archive.)

`tests/test_sawyer_corpus.py` runs every entry through, at minimum:
(a) source-hash match against the archive (`require_sawyer_doc`);
(b)/(c) for every convertible document, parse + emit EVERY registered
format x mode, each cell's sha256/byte-length checked against the answer
key (see below); for known-nonconvertible entries, `core.parse()` is
asserted to fail with its exact recorded reason; for non-document assets,
only the source hash is checked.

## Answer key (`tests/answer_key.json`, `tools/answer_key.py`)

Since Task 3 (planning #198/#195), this tier's conversion output isn't
checked against a narrow per-file oracle — it's one shared key covering
the 4 bundled samples AND every convertible Sawyer document, across EVERY
registered format (`text`, `markdown`, `html`, `rtf`, `pdf`, `layout`) x
EVERY mode (`printed`, `modern`) this engine supports. One named test per
(doc, format, mode) cell, so a failure names exactly which cell of which
document changed. See `tools/answer_key.py`'s own module docstring for the
full schema, provenance, and honesty-class discussion (it is a
self-recorded drift detector, not a correctness check against real
WordStar 7 — that comparison is the separate `pcl` tier, over a private
corpus).

## Regenerating

If Sawyer ever ships a new release, the corpus's own documents-only trim
changes, or the engine's classification of a file changes on purpose:

1. Download the new release from the URL above; verify its zip sha256
   independently (never trust a hash you were merely told).
2. Recompute the version marker (`DESCRIPT.ION`'s sha256) and update
   `ARCHIVE_RELEASE`/`ARCHIVE_SOURCE_URL`/`ARCHIVE_ZIP_SHA256`/
   `VERSION_MARKER` at the top of `tests/sawyer_fixture.py`.
3. `CTRLKD_SAWYER_ARCHIVE=/path/to/trimmed/sawyer python3
   tools/answer_key.py --record` — point it at a tree that is ALREADY the
   intended population (this project's own documents-only trim), not an
   arbitrary raw archive dump: `build_sawyer()` walks and mechanically
   classifies every file it finds there, with no filtering of its own.
4. Review the diff to `tests/answer_key.json` like any other reviewed
   change before committing — which names moved bucket, and why, should
   be explainable from the diff alone.
5. `python3 tools/answer_key.py --check` (armed) confirms the committed
   key matches current engine output without rewriting it — useful in CI
   or before a commit.
