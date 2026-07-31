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
