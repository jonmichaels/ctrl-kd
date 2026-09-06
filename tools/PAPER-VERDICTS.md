# Paper-scan verdicts — schema and workflow

Planning #200 (Engine-Test-Finalization-Plan Task 5). The 69 catalogued
M479fdw paper-scan pages (13 documents; see `ws7-prints/paper-scans/README.md`
in the private corpus) are the LOOK layer of the fidelity gate — a human
looks at the real printed page beside our engine's export and judges it.
Before this file, that judgment lived only in Jon's head and in prose
findings docs. This makes it a checked-in, machine-testable fact: a page
with no recorded verdict is **unreviewed**, never silently "passing".

The verdicts file itself is **private data** (it's keyed to the private
paper-scan corpus) and does not live in this repo. It lives at

    $CTRLKD_PRIVATE_CORPUS/ws7-prints/paper-scans/verdicts.json

`tools/paper_verdicts.py` reads and writes it; this repo only carries the
tool, the catalog (document names + scan-PDF page maps — not private, see
below), the schema, and the pytest tier that enforces it.

## Schema (JSON, `schema_version: 1`)

```json
{
  "schema_version": 1,
  "generator": {"tool": "tools/paper_verdicts.py", "date": "2026-09-06T00:00:00-04:00"},
  "catalog": {"documents": 13, "pages": 69,
              "source": "ws7-prints/paper-scans/README.md (M479fdw scan batches, 2026-08-20)"},
  "pages": [
    {
      "document": "WARPRAYR",
      "page": 2,
      "scan_file": "m479-scan-doc89.pdf",
      "scan_page_index": 2,
      "verdict": "font-substitution",
      "region_notes": [
        {"region": "body text, para 3",
         "what_differs": "CG Times on paper reads slightly narrower than our Times substitute; word wrap matches, letterfit does not",
         "reason": "font-substitution: CG Times has no base-14 stand-in with identical metrics (Engine-Test-Finalization-Plan tolerance model)"}
      ],
      "reviewer": "jon",
      "date": "2026-09-06",
      "engine_commit": "b9fa1c9...",
      "engine_commit_date": "2026-09-05T18:02:11-04:00",
      "answer_key_ref": "e335de199c101de5e0f7670ada88cda76f04cca9"
    }
  ]
}
```

Per-page fields:

| field | meaning |
|---|---|
| `document` | catalog document name (e.g. `WARPRAYR`, `-README`) |
| `page` | 1-based page number *within that document* |
| `scan_file` | which paper-scans PDF holds the scan (e.g. `m479-scan-doc89.pdf`) |
| `scan_page_index` | 1-based page number *within that scan PDF* |
| `verdict` | one of `pass`, `fail`, `font-substitution`, `unreviewed` |
| `region_notes` | list of `{region, what_differs, reason}` — what was looked at, what differs, why that's accepted/not |
| `reviewer` | who made the call |
| `date` | review date (`YYYY-MM-DD`) |
| `engine_commit` | ctrl-kd git SHA the review was made against |
| `engine_commit_date` | that commit's own commit date (ISO 8601) — used for staleness, not `date` above |
| `answer_key_ref` | `tests/answer_key.json`'s `generator.git_sha` at review time, for citation |

**Verdict meanings**: `pass` = paper and export agree, no notes needed.
`font-substitution` = the only difference is the expected consequence of
our base-14-only PDF constraint (Jon's 2026-09-05 ruling) — this verdict
**must** carry at least one `region_notes` entry with a non-empty `reason`
that says so; the test enforces this. `fail` = a real, unexplained
divergence; the test always fails a `fail`-verdict page by name until it's
fixed or reclassified with evidence. `unreviewed` = no human has looked
yet; the test fails it too — a skipped review is not a passing one.

## The catalog is not private

The document names, which scan PDF each is in, and the page counts are
already committed elsewhere in this repo (`tools/pcl_tolerance.py`'s
`CAPTURED_DOCS`, `tests/SAWYER-CORPUS.md`) and are reproduced verbatim from
the private corpus's own `ws7-prints/paper-scans/README.md` (a page map,
not a filesystem path). `tools/paper_verdicts.py`'s `CATALOG` constant is
the single source of truth for this 13-document/69-page list; only the
scan PDFs and rendered pages themselves stay outside this repo.

## CLI

```
# Write a fresh skeleton (every catalogued page = unreviewed) to a path.
# The orchestrator places this into the private corpus; --out defaults
# to stdout so this also works with no corpus at all.
python3 tools/paper_verdicts.py --init --out /path/to/verdicts.json

# Summarize an existing verdicts file: counts by verdict, unreviewed pages by name.
python3 tools/paper_verdicts.py --status --file /path/to/verdicts.json

# Record one page's verdict during a review session.
python3 tools/paper_verdicts.py --set WARPRAYR 2 font-substitution \
    --file /path/to/verdicts.json \
    --reason "CG Times has no base-14 stand-in" \
    --region "body text, para 3" --what-differs "narrower letterfit" \
    --reviewer jon

# Build Jon-style review collages (paper scan beside our rendered page),
# grouped by cause, at most 8 output files (visual-page-review convention).
python3 tools/paper_verdicts.py --collage --file /path/to/verdicts.json \
    --corpus "$CTRLKD_PRIVATE_CORPUS" --out-dir /path/to/scratch
```

`--file` defaults to `$CTRLKD_PRIVATE_CORPUS/ws7-prints/paper-scans/verdicts.json`
when `CTRLKD_PRIVATE_CORPUS` is set. `--collage`'s `--corpus` defaults to
`$CTRLKD_PRIVATE_CORPUS` the same way; it reads scans from
`<corpus>/ws7-prints/paper-scans/` and our own renders from
`<corpus>/ws7-prints/engine-printed/<DOCUMENT>.pdf` (both already exist in
that layout — see `tools/fidelity_gate.py`'s doc-resolution docstring).
`--collage` needs Pillow and `pdftoppm` (poppler-utils); neither is a
runtime dependency of ctrl-kd itself, same deferred-import discipline as
`tools/pcl_render.py`.

## The `paper` pytest tier

`tests/test_paper_verdicts.py`, marker `paper`, one parametrized test per
catalogued page (69 cases). Armed by `$CTRLKD_PRIVATE_CORPUS` — unarmed,
`pyproject.toml`'s `addopts` deselects the whole marker, same convention as
`sawyer`/`pcl`. Once armed:

- a page missing from the verdicts file, or verdict `unreviewed`, **fails**
  by name ("go review this page");
- verdict `fail` **fails** by name (a real, unfixed divergence);
- verdict `font-substitution` **fails** if it carries no `reason`;
- verdict `pass` or a properly-reasoned `font-substitution` **passes** —
  unless the review is **stale**: the page's `engine_commit_date` predates
  `tests/answer_key.json`'s current `generator.date` (the engine changed
  since this page was looked at) — that also fails by name, naming both
  dates.

The verdicts file path can be overridden independently of
`$CTRLKD_PRIVATE_CORPUS` with `$CTRLKD_PAPER_VERDICTS` (an absolute path to
a `verdicts.json`) — this exists so the tier can be exercised against a
scratch skeleton (e.g. straight out of `--init`) without needing a real,
populated private corpus tree; `$CTRLKD_PRIVATE_CORPUS` still has to be set
to *something* to arm the marker at all (same as every other corpus-gated
tier here), but its value is only actually dereferenced for the verdicts
path when `$CTRLKD_PAPER_VERDICTS` is unset.

`tools/run-full-suite.sh` reports this tier's armed/unarmed status
alongside `sawyer` and `pcl`.
