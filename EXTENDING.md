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
  .lines      list[Line]
Line
  .spans      list[Span]
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

* Within a `para` block, each `Line` is a **deliberate** line break (a poem line,
  a name/date heading, a chart row) — word wrap was already joined during
  parsing. Paragraph separation is the block boundary itself.
* Leading spaces in line text are the author's indentation. Keep them if your
  format can.
* Blank-line geometry inside `printed`-mode documents is page layout — preserve it.

## Worked example: a BBCode emitter

```python
# ctrlkd_bbcode.py
from ctrlkd import emitter

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
        for line in block.lines:
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
| `page` | page geometry from the file's own `.pl`/`.po`/`.mt`/`.mb`, with provenance: `size_name`, `size_source` (`'file'` \| `'default'`), `height_in`, `pl_lines`, `mt_lines`, `mb_lines`, `po_cols` and their `*_source`. **Unit-less dot-command arguments are LINES, not inches.** Lets a caller say "Legal (from file)" vs "Letter (default)" |
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
  emitters' display-label helper rather than printing it directly.
- Annotations carry a **tag string** (e.g. `AC1`), not a number.

### A naming footgun to know about

`ctrlkd/__init__.py` re-exports `convert()`, which rebinds the package attribute
`ctrlkd.convert` from the *submodule* to the *function*. `import ctrlkd.convert
as m` therefore binds `m` to the function. Use `from ctrlkd.convert import name`
for module members (e.g. `DEFAULT_NOTE_KINDS`). Nothing in the package is broken
by this, but third-party code can be surprised.
