# Extending ctrl-kd with new output formats

An output format ("emitter") is one function. It never touches WordStar bytes —
parsing is done before it runs. It receives the intermediate representation (IR)
and returns a string — or bytes, for binary formats (the built-in PDF emitter
does this); the CLI writes bytes results in binary mode. Everything the four built-in formats do, yours can do.

## The contract

```python
def emit_myformat(doc, mode='modern', **options) -> str
```

* `doc` — a `ctrlkd.Document` (see IR reference below).
* `mode` — `'modern'` (reflowed paragraphs) or `'printed'` (line-for-line,
  fixed-width). Respect it if your format has a notion of layout; ignore it if
  not. Tip: `doc.meta.get('variant') == 'printstream'` or
  `doc.meta.get('columnar')` means the document only makes sense fixed-width,
  whatever the mode.
* `**options` — accept and ignore unknowns. The CLI passes `title=<basename>`.

## The IR reference

```
Document
  .blocks     list[Block]
  .footnotes  list[list[Span]]   # numbered 1..n, referenced in text (see fnref).
                                 # Footnotes, endnotes, AND annotations (WS5+/WS7):
                                 # all three print the same way (a numbered list at
                                 # the end), so this stays one flattened, ordered
                                 # view for emitters that don't care which is which.
  .endnotes     list[list[Span]] # WS5+/WS7 endnotes only, same shape as .footnotes
  .annotations  list[list[Span]] # WS5+/WS7 annotations only, same shape
  .comments     list[Note]       # WS5+/WS7 comments: WordStar never prints these,
                                 # so they're NOT in .footnotes -- only reachable
                                 # here or via .notes. Often the most interesting
                                 # content in a file (hidden author asides).
  .notes      list[Note]        # ALL note kinds, in document order -- the
                                 # authoritative structure; .footnotes/.endnotes/
                                 # .annotations/.comments above are convenience
                                 # views over this. Note: kind, text, number
                                 # (footnote/endnote only), tag (annotation's own
                                 # display-tag text, if any), line_count,
                                 # number_format, convert_to, dot_commands (any
                                 # dot-command lines found INSIDE the note's own
                                 # text, stripped from `text` but kept verbatim),
                                 # offset
  .unknown_blocks  list[UnknownBlock]  # unrecognised WS5+/WS7 symmetrical-sequence
                                       # types, preserved instead of dropped.
                                       # UnknownBlock: cmd, data (raw bytes), offset
  .meta       dict               # detection + parse info, e.g.:
                                 #   variant: 'ws4' | 'ws5+' | 'printstream' | 'text'
                                 #   columnar: bool   (ruler-line document: fixed-width!)
                                 #   margin_estimate, dot_commands, unknown_codes
Block
  .kind       'para'       ordinary content
              'pagebreak'  explicit page break (.pa dot command / form feed)
              'softpage'   WordStar's own pagination — render only in printed mode
  .heading    0 = body; 1..3 = title/heading/subheading level (WS5+)
  .lines      list[Line]     # PHYSICAL lines since 2.0.0 — see below
Line
  .spans      list[Span]
  .soft       bool           # True: ends in WordStar's own word wrap (a real line
                             # break on paper; just a join point for reflow)
  .lead_48    float | None   # the `.lh` line height in force ON THIS LINE, in
                             # 1/48in units. None = the document default,
                             # doc.meta['page']['lh_48'] — the common case.
                             # `.lh` is stateful, so a document that changes
                             # leading around its headings says so here.
  .text()     -> str        # convenience: all span text joined
Span
  .text       str
  .styles     frozenset     # subset of:
              'b' 'i' 'u' 'sup' 'sub' 'strike'   inline styles
              'fnref'                            this span IS a footnote reference:
                                                 .text is the number, doc.footnotes[n-1]
                                                 is the note. Render as your format's
                                                 footnote mechanism, not as plain text.
```

Semantics worth knowing:

* Within a `para` block, each `Line` is a **physical** line — exactly what sat on
  one printed line, including WordStar's own word wrap (`line.soft` marks those).
  Rendering line-for-line (printed mode)? Use `block.lines` directly. Reflowing
  (modern mode)? Call **`core.merged_lines(block)`** to get logical lines with
  soft-wrapped runs joined back (spaces inserted with WordStar's own rule, none
  after a hyphen); each logical line is then a deliberate break (a poem line, a
  name/date heading, a chart row). Before 2.0.0 the joining happened at parse
  time and printed mode couldn't undo it — thousand-column lines ran off the
  page.
* A manuscript that marks a new paragraph by indentation instead of a blank
  line stores every typed paragraph as its own hard-terminated `Line` inside
  ONE block — block boundaries alone are NOT paragraph separation for that
  shape of document. Call **`core.assemble_paragraphs(block, margin)`**
  (`margin = doc.meta.get('margin_estimate') or 65`) on top of
  `merged_lines()`'s output to get paragraph UNITS — lists of Lines that
  belong in one rendered paragraph — instead of one line per typed
  paragraph; the four built-in Modern emitters (RTF/HTML/text/Markdown) do
  this. `core.split_leading_indent(spans)` then separates a unit's own
  typed/machine indent (a real first-line-indent property in most formats)
  from its visible text. This is new, additive API (no IR field changed) —
  a plugin that still calls `merged_lines()` alone keeps working exactly as
  before, it just won't reflow typed-paragraph manuscripts the way the
  built-in formats now do. The `layout`/PDF path does not use it yet (own
  migration, tracked separately) — a plugin comparing its own output
  against `--format layout`/`--format pdf` for this shape of document will
  currently see them disagree on paragraph granularity.
* Leading spaces in line text are the author's indentation. Keep them if your
  format can.
* Blank-line geometry inside `printed`-mode documents is page layout — preserve it.
* A line's `lead_48` is the space **above** it, not below: `.lh` is a printer VMI,
  set before the feed that lands on the line it was typed for. `doc.meta['page']
  ['lh_48']` remains the document default (and what page capacity is computed at);
  `doc.meta['page']['lh_varies']` is True when any line differs from it.

## Worked example: a BBCode emitter

```python
# ctrlkd_bbcode.py
from ctrlkd import emitter, merged_lines

TAGS = {'b': 'b', 'i': 'i', 'u': 'u', 'sup': 'sup', 'sub': 'sub', 'strike': 's'}

@emitter('bbcode', ext='.bbcode')
def emit_bbcode(doc, mode='modern', **options):
    out = []
    for block in doc.blocks:
        if block.kind == 'softpage' and mode != 'printed':
            continue
        if block.kind in ('pagebreak', 'softpage'):
            out.append('[hr]')
            continue
        lines = []
        # physical lines when line-for-line, logical lines when reflowing
        for line in (block.lines if mode == 'printed' else merged_lines(block)):
            seg = ''
            for span in line.spans:
                text = span.text
                if 'fnref' in span.styles:
                    text = f'[sup]{text}[/sup]'
                else:
                    for st in span.styles:
                        if st in TAGS:
                            text = f'[{TAGS[st]}]{text}[/{TAGS[st]}]'
                seg += text
            lines.append(seg)
        para = '\n'.join(lines)
        if block.heading:
            para = f'[size=150][b]{para.strip()}[/b][/size]'
        if para.strip():
            out.append(para)
    body = '\n\n'.join(out)
    if doc.footnotes:
        notes = '\n'.join(f'{i+1}. ' + ''.join(s.text for s in n)
                          for i, n in enumerate(doc.footnotes))
        body += '\n\n[hr]\n' + notes
    return body + '\n'
```

Use it immediately in your own script:

```python
import ctrlkd_bbcode                      # registering is importing
from ctrlkd import convert
print(convert(open('ESSAY.WS','rb').read(), to='bbcode'))
```

## Shipping it as an installable plugin

Publish a package that declares the entry point; ctrl-kd discovers it at startup.
No changes to ctrl-kd, no registration import needed by the user:

```toml
# your plugin's pyproject.toml
[project]
name = "ctrl-kd-bbcode"
dependencies = ["ctrl-kd"]

[project.entry-points."ctrlkd.emitters"]
bbcode = "ctrlkd_bbcode:emit_bbcode"
```

After `pip install ctrl-kd-bbcode`:

```console
$ ctrl-kd ESSAY.WS -t bbcode
```

The output extension defaults to `.<name>`; set an `ext` attribute on the
function (`emit_bbcode.ext = '.bb'`) to override.

## Checklist for a good emitter

- [ ] Handles all three block kinds (`softpage` only renders in printed mode)
- [ ] Handles `heading` levels 1–3
- [ ] Renders `fnref` spans via the format's footnote mechanism (or superscript)
- [ ] Escapes the format's special characters in span text
- [ ] Survives a document with no footnotes, no headings, and empty blocks
- [ ] Accepts `**options` it doesn't know

## `doc.meta` keys

Free-form dict on `Document`, populated by the parser. Emitters may read any of
these; none are required.

| Key | Meaning |
|---|---|
| `variant` | `ws4` / `ws5+` / `printstream` / `text` — how the file is *encoded* |
| `producer` | who *wrote* it, when detectable. `'wordtsar'` when the WordTsar-only dot commands `.PT`/`.PSA`/`.PSB` are present — those are not WordStar commands. Provenance, not format: a WordTsar file is still `ws5+` |
| `page` | page geometry from the file's own `.pl`/`.po`/`.mt`/`.mb`/`.hm`/`.fm`/`.lh`/`.ls`/`.cw`, with provenance: `size_name`, `size_source` (`'file'` \| `'default'`), `height_in`, `pl_lines`, `mt_lines`, `mb_lines`, `po_cols`, `hm_lines`, `fm_lines`, `lh_48` (line height, 1/48 in units), `ls`, `cw_120` (character width, 1/120 in units — 12 is 10 CPI) and their `*_source`. **Unit-less dot-command arguments are LINES, not inches** (`.lh`'s are 1/48 in; `.po`'s are columns; `.cw`'s are 1/120 in). Also carries the derived `text_lines` — printed text lines per page from WordStar's own model, `(pl − mt − mb)` at the `.lh` line height (55 for the defaults). `.po` defaults to **8** columns — the WS7 manual's ".8 inch" — and positions printed text at `po × cw` from the paper edge. `.hm`/`.fm` never reserve space (header/footer print *inside* `.mt`/`.mb`) and `.ls` never divides capacity (its blank lines are literal lines in the file); both are recorded for diagnosis only. Lets a caller say "Legal (from file)" vs "Letter (default)" |
| `footnote_number_start` / `endnote_number_start` | starting values from `.f#` / `.e#`, default 1. Footnotes and endnotes number **independently** — WordStar has separate commands for separate sequences |
| `comment_bug` | printstream only. WordStar's own print-time damage: documents containing `^ONC` comments, printed to disk with the ASCII/ASC256/PRVIEW/WS4 drivers (not XTRACT), lost the rest of the line after the comment. `{count, first_offset, stray_ctrl_t}`. **Report this as 1990s damage, not as a parse failure** — telling those apart is the point of a rescue tool |
| `margin_estimate` | statistically recovered wrap column |
| `dot_commands` | every dot-command line, verbatim and in order, recognised or not |
| `unknown_codes` | control bytes the parser did not interpret |
| `columnar` | the document only makes sense fixed-width |

`doc.unknown_blocks` holds unrecognised WS5+ symmetrical sequences as
`UnknownBlock(cmd, data, offset)` rather than discarding them. Preserving what we
cannot yet interpret is deliberate: it makes `--diagnose` honest about what a file
contains, and keeps lossless round-trip possible later.

## Notes

`doc.notes` is the authoritative list, in document order, of `Note(kind, text,
number, tag, line_count, number_format, convert_to, dot_commands, offset)` where
`kind` is `footnote` / `endnote` / `annotation` / `comment` (WordStar 7.0
symmetrical-sequence types 3-6). `doc.footnotes` / `.endnotes` / `.annotations` /
`.comments` are filtered views.

- **Comments were never printed by WordStar** and are excluded by default; pass
  `notes=` to opt them in. They are always preserved and reported by `--diagnose`.
- `Note.number` is the file's **raw 0-based index**, not a display number. Use the
  emitters' display-label helper (`emit._annotated_notes` / `_pageless_notes`)
  rather than printing it directly.
- Annotations carry a **tag string** (e.g. `AC1`), not a number.
- **Footnotes/endnotes can ALSO carry a tag** (WSFORMAT.TXT: the tag/number
  word's high bit, resolved one level deeper into the same shape again --
  "currently only one level of this recursion is used"). When `Note.tag` is
  set on a footnote/endnote, every emitter displays the tag and never
  renumbers it, exactly like an annotation. **UNTESTED AGAINST A REAL
  DOCUMENT** -- no document in the Sawyer archive carries a footnote/endnote
  tag; this is spec-faithful, synthetic-fixture-verified code (see
  `tests/test_ctrlkd.py`'s footnote/endnote-tag tests), not measured
  behaviour. Ruling 2026-08-24 item 4.
- **`Note.number_format`** (0 symbols, 1 upper-case, 2 lower-case, 3 numeric --
  the conversion-flag byte's high nybble) is honoured when a footnote/endnote's
  display label is built. Values 0/1/2 are likewise **UNTESTED AGAINST A REAL
  DOCUMENT** -- every archive document uses 3 (numeric); the symbol cycle
  (`*`, `†`, `‡`, `§`, `‖`, `¶`) is a documented fallback (the classical
  printer's/Word's own "symbol" footnote-numbering convention), not a
  confirmed WordStar sequence. Ruling 2026-08-24 item 5.
- **TXT/MD/HTML renumber footnotes/endnotes continuously** (independently per
  kind) when — and only when — WordStar's own per-page-reset numbers actually
  collide within that kind (`emit._pageless_notes`); a document whose notes
  already number consecutively (WordStar's `.F#`/`.E#` dot command, unparsed
  by this project on purpose) is left untouched. Printed, Modern PDF, and RTF
  never renumber — they keep WordStar's own numbers (RTF via `\chftn`/
  `\ftnalt` auto-numbering instead). A tagged note never participates in
  collision detection or renumbering, in any format. Ruling 2026-08-24 item 1.

### A naming footgun to know about

`ctrlkd/__init__.py` re-exports `convert()`, which rebinds the package attribute
`ctrlkd.convert` from the *submodule* to the *function*. `import ctrlkd.convert
as m` therefore binds `m` to the function. Use `from ctrlkd.convert import name`
for module members (e.g. `DEFAULT_NOTE_KINDS`). Nothing in the package is broken
by this, but third-party code can be surprised.
