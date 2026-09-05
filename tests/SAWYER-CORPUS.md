# Tier 2: the Sawyer WS7 archive

Robert J. Sawyer, the science fiction author, has published his own
WordStar 7 install tree as a historical/archival download:
<https://www.sfwriter.com/ws7.htm>. It is real, period WordStar content —
the only corpus this project has ever been able to validate `.WS` parsing
against beyond synthetic fixtures — and unlike Jon's own private documents
(tested separately, outside this repo), it is PUBLIC. Ruled 2026-08-26: filenames and paths from it may
appear directly in this repo's code, because the archive itself is a public
download, not personal material.

**Release pinned by this manifest: 1.5** (zip sha256
`10213b23b3d030951e093eba36a1e41cb3ea6732e8e761e1b356ba4bc902e1af`, verified
independently against the download at the URL above before this manifest was
generated). Release 1.4 — the copy this project used before — differs from
1.5 in 34 same-named files, including one document this tier tests
(`-README.WS` at the archive root); `sawyer_manifest.json`'s hashes are all
computed against 1.5, and `sawyer_fixture.sawyer_manifest_problem()` checks a
version marker (`DESCRIPT.ION`'s own hash) before trusting anything else in
an armed run, specifically so a stale local copy fails loudly with a clear
reason instead of quietly passing against the wrong bytes or drifting one
file at a time.

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

## What this tier deliberately does NOT do

**No directory sweep.** Earlier versions of several of these tests globbed
`**/*.WS` across the whole archive (~180 files, most of them installers,
help text, and dictionaries — not documents this project has any opinion
about). Ruled 2026-08-26: tier 2 tests an EXPLICIT, COMMITTED list only —
never the archive's full contents, and never re-derived by running a
classifier over the tree. Once armed, a listed document that is missing or
whose content no longer matches its committed hash FAILS the run loudly;
anything else in the archive is simply never looked at. Earlier tests'
full-archive-sweep behavior (screenplay zero-false-positive check) has been
narrowed to the same list, documented at its call site.

## The full manifest (252 entries, `sawyer_manifest.json`)

Expanded 2026-08-26 from the original ten to the FULL identified-document
set: Jon's vault catalog (`jon_vault/Projects/software/WordStar/
Corpus-Document-Catalog.md`, companion to `Corpus-And-Filetype-Index.md`)
enumerates **251 genuine WordStar documents** in the Sawyer archive by a
stated, non-rederived rule — "about 200" (an earlier, partial-scope
recollection) is explicitly retired there. That 251-path list is taken
**verbatim** as this manifest's population, per Jon's own instruction: it
is the source of truth, not something this repo's classify tooling
re-derives.

**Reconciled against this repo's pinned release (1.5) — the catalog was
built against a ~v1.4 copy:**

- **2 documents no longer exist** upstream in 1.5 at all (confirmed absent
  by full-tree search, not renamed/moved): `DICT/-CTRL.P`, `DICT/TEST-ALL.WS`.
  Dropped from the manifest; `tests/test_sawyer_corpus.py` asserts they stay
  dropped.
- **249 documents are present**, but **241 of the 249** have a different
  raw byte size in 1.5 than the catalog recorded — this is expected, not a
  data error: WordStar rewrites a document's own internal trailer (cursor
  position, block pointers) on every save, so resaving the whole tree
  between releases shifts nearly every file's total length slightly even
  where the visible prose is unchanged. Confirmed on the 7 documents this
  manifest already carried before this expansion (`RJS.WS`, `CONVERT.WS`,
  `LJ6DTP.WS`, `PREVIEW.WS`, `-SCREEN.WS`, `-README.WS` (root),
  `ARTICLES/SCRIPT.WS`): this pass's independently-computed release-1.5
  hashes and sizes match the pre-existing committed entries exactly. Every
  size in `sawyer_manifest.json` is release-1.5's real on-disk size, never
  the catalog's (now-stale) number.
- **10 of the 249 don't actually convert** through this engine's real
  `core.parse()` today, despite the catalog counting them as ws4/ws5+
  documents (an earlier, separate `classify_sawyer.py` pass corroborated
  them by a narrower structural signature than `core.detect()`'s full
  gate applies) — and the catalog's own notes already describe every one
  of them as non-prose/binary-shaped content: `CVWP/WP_WP_US.QRS`,
  `` CVWP/WP{WPC}.QKL ``, the four `DEFAULT/APP/03670464.CRT/*.CRT` files
  (font/cartridge width tables), `HIJAAK/ISI0.TMP`, `HIJAAK/ISI2.TMP`,
  `MANUALS/WordStar Manuals Index/index1.idx`, `WFW/UNC0819.DAT`. These
  are still in the manifest (source-hash checked like everything else) but
  `test_sawyer_corpus.py` asserts each one fails `core.parse()` with its
  exact reason, rather than silently excluding or force-converting them.

**Net document coverage: 249** (251 catalogued − 2 dropped), of which
**241 fully convert and are pinned by oracle hash**, and **10 are named,
asserted non-convertible**. The manifest also still carries the **3
non-catalog assets** the original ten-document manifest needed for their
own dedicated tests (`APP/-README.WS`, `APP/vDosPlus/-README.WS` — real
documents, but correctly excluded from the 251 as emulator-bundle
duplicates per the catalog's own named exclusions; `INSET/PIX/
WORDSTAR.PIX` — the Inset image asset the pix-reference documents point
at, never a WordStar document itself) = **252 manifest entries** total.

`tests/test_sawyer_corpus.py` runs every entry through, at minimum:
(a) source-hash match against the archive (`require_sawyer_doc`);
(b) for the 241 convertible documents, parse + emit `text` (modern) and
`layout` JSON, both must succeed; (c) each output's sha256 checked against
`tests/sawyer_oracle.json` (generated by `tools/gen_sawyer_oracle.py`,
same compact hash-only pattern as `tests/samples_oracle.json` — no
document content is committed, only digests).

## The original ten documents (still individually named below; their
richer dedicated tests elsewhere in the suite are unchanged by the
252-entry expansion above)

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
stub documents in the real archive — not a bug in this manifest, just a fact
about the archive.)

## Regenerating the manifest and oracle

If Sawyer ever ships a new release, the vault catalog's document list
changes, or a listed document's committed hash needs to move on purpose:

1. Download the new release from the URL above; verify its zip sha256
   independently (never trust a hash you were merely told).
2. Recompute `sha256sum` for every path in `sawyer_manifest.json` and for
   `DESCRIPT.ION` (the version marker). For the full 251-document catalog
   population, re-read `Corpus-Document-Catalog.md`'s per-corpus tables in
   the vault — take the path list verbatim, do not re-derive it by running
   a classifier over the archive tree.
3. Update `sawyer_manifest.json`'s `archive_release`, `zip_sha256`,
   `version_marker`, and every doc entry's `sha256`/`size`, and update this
   file's release number and the reconciliation notes above (which docs
   were dropped/changed, by name).
4. Regenerate the conversion oracle: `CTRLKD_SAWYER_ARCHIVE=/path/to/WS
   python3 tools/gen_sawyer_oracle.py` — rewrites `sawyer_oracle.json` for
   every manifest entry not in that script's `NON_DOCUMENT_ASSETS`/
   `KNOWN_NONCONVERTIBLE` sets. If a document that used to fail to convert
   now succeeds (an engine fix), move its name from
   `KNOWN_NONCONVERTIBLE`/`NONCONVERTIBLE_NAMES` in both
   `tools/gen_sawyer_oracle.py` and `tests/test_sawyer_corpus.py` before
   regenerating, so it gets oracle-checked instead of asserted-to-fail.
5. `python3 tools/gen_sawyer_oracle.py --check` (armed) confirms the
   committed oracle matches current engine output without rewriting it —
   useful in CI or before a commit.
