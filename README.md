# ctrl-kd

Convert WordStar-era files to modern formats. **^KD: save and done.**

`ctrl-kd` reads WordStar 4 documents, WordStar 5–7 documents, and WordStar
**print-to-disk files** (the printer byte stream, captured to a file — a distinct
format most converters mangle), and writes plain text, Markdown, HTML, RTF, or PDF (set on a
viewer's built-in base-14 fonts — no dependencies, nothing embedded, the page as it would have
printed: printed mode follows the document's own font blocks, modern mode stays Courier).

```console
$ ctrl-kd ESSAY.WS                      # -> ESSAY.md
$ ctrl-kd ESSAY.WS -t html -t rtf       # multiple formats
$ ctrl-kd ESSAY.WS -t pdf --mode printed # a facsimile of the 1990 printout
$ ctrl-kd --mode printed LETTER.WS      # line-for-line, as it printed in 1990
$ ctrl-kd --diagnose MYSTERY.FIL        # what IS this file?
$ ctrl-kd --comments MEMO.WS            # include the author's hidden comments
$ ctrl-kd --no-notes PAPER.WS           # body text only, no notes
```

## Why another converter?

Existing tools each lose something. Fed a WordStar 4 file, converters written for
WS7 delete the last letter of every word (WS4 set bit 7 on it). Most delete soft
returns outright — `Jon Michaels` + `March 6, 1992` becomes
`Jon MichaelsMarch 6, 1992` — which also destroys every poem, because poem lines
end in soft returns too. And print-to-disk files aren't WordStar documents at all,
so feeding them to a WordStar converter produces stray superscripts and garbage.

`ctrl-kd` was built by converting a real 1987–1992 corpus (high-school and college
papers, poems, stories — WordStar 4 on DOS, dot-matrix printer) and verifying
against surviving period printouts of the same documents. Its rules are empirical:

* **Detection by content, never by extension.** WS4 vs WS5+ vs print stream vs
  plain text vs binary, with the evidence shown in `--diagnose`.
* **The wrap test.** WordStar wrapped only when the next word didn't fit. So a
  soft return where the next word *would* have fit (strictly — WordStar wrapped
  even on an exact-margin fit) is a deliberate break: a poem line, a heading.
  Everything else is word wrap and joins with a space. The margin is estimated
  from the 90th percentile of soft-wrapped line lengths (floor 65, the default).
* **Break runs.** Soft/hard return runs containing a hard return and a blank line
  are paragraph breaks; a lone hard return is the author's deliberate line break.
  Double-spaced documents (blank soft lines between every line) collapse
  automatically.
* **Ruler lines mean columns.** A `.rr----!----` dot line defines tab stops; the
  document's alignment is space-built and only survives fixed-width. Such
  documents render `printed` in every mode.
* **Print streams render verbatim** — they ARE the printed page — with printer
  style codes decoded (superscript/underline/italic/bold pairs; table in
  `core.PRINT_CODES`, derived from a late-80s dot-matrix driver and overridable).
* **WS5+ symmetric blocks** (`0x1D`: real footnotes/endnotes, headings, page
  breaks — machinery added in WS5) are parsed with their nested structure,
  verified against the 86 WordStar 7 documents in Robert J. Sawyer's public
  WordStar archive. All **four** note kinds WordStar distinguished are read and
  kept apart — footnote, endnote, annotation, and comment — with in-text
  references (`[^n]` in Markdown, DPUB-ARIA anchors in HTML, real `\footnote`
  destinations in RTF). **Comments never appear unless you ask for them**, since
  WordStar never printed them; `--diagnose` still reports that they exist.
  Paragraph styles become headings, and 82/86 convert with zero mojibake.
  More WS5–7 corpora still welcome.
* **Page geometry** from the file's own `.pl`/`.po`/`.mt`/`.mb`/`.hm`/`.fm`/
  `.lh`/`.ls`/`.cw`, so `--mode printed` reproduces WordStar's own page: the
  vertical model (`.pl − .mt − .mb` at the `.lh` line height — 55 text lines
  for WordStar's defaults, not a guessed 1-inch margin), the horizontal one
  (`.po` page offset at the `.cw` character pitch), and WordStar's own line
  breaks — a soft return is where the line broke on paper, so printed output
  keeps it (and reflowed Modern output still joins it). `--diagnose` says
  whether each figure came from the file or from the default.
  In `printed` mode footnotes are laid out the way WordStar laid them out: at
  the foot of the page that references them, behind a twenty-dash separator,
  split across pages with `...Continued...` when they do not fit.

## Modes

* `--mode modern` (default): reflowed paragraphs, semantic markup, deliberate
  line breaks kept.
* `--mode printed`: every line as laid out, fixed-width, `.pa`/form-feed page
  breaks honored — how it came off the printer.

Version coverage, known limitations (WordStar 6's bare `.pl`, WordStar 3
status), and how behaviour gets verified: **[FAQ.md](FAQ.md)**, with the
technical account in **[ERAS.md](ERAS.md)**.

## Install

```console
$ brew install jonmichaels/tap/ctrl-kd     # macOS / Linuxbrew
$ pipx install ctrl-kd                     # or: pip install ctrl-kd
```

Python ≥ 3.9, no dependencies. Library API: `ctrlkd.convert(data, to='html')`.

## Adding an output format

An output format is one function over the parsed document — register it with the
`@ctrlkd.emitter` decorator, or ship it as a pip-installable plugin via the
`ctrlkd.emitters` entry-point group and it appears in the CLI automatically.
**[EXTENDING.md](EXTENDING.md)** has the IR contract, a complete worked example
(BBCode in ~40 lines), and a checklist.

## Siblings

**[soft-return](https://github.com/jonmichaels/soft-return)** — CtrlKD, a Swift
port of this engine, verified byte-for-byte against this implementation via
machine-generated test vectors (the two projects found six real bugs in each
other during the port). It grows the `sr` CLI and the Soft Return macOS app.

## Lineage

Standing on the shoulders of the tools and documentation that kept WordStar
readable: Yohanes Nugroho's WS-CON, Michael Petrie's English port, the `wsconvert`
project, Robert J. Sawyer's WordStar archive, and the WordStar format
documentation community. Behaviors were studied and reimplemented; no code was
copied. The development corpus is personal and is not distributed — tests use
synthetic fixtures that encode the same behaviors.

## Credits

Written by Jon Michaels — whose 1987–1992 WordStar files, and the need to read
them again, are the reason this exists — with Athena (Claude, Anthropic) as
co-author: the byte archaeology, the wrap test, and the implementation grew out
of a joint effort to recover those disks. Every commit carries the co-author
trailer.

## License

MIT © Jon Michaels
