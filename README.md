```
        __       __      __       __
  _____/ /______/ /     / /______/ /
 / ___/ __/ ___/ /_____/ //_/ __  /
/ /__/ /_/ /  / /_____/ ,< / /_/ /
\___/\__/_/  /_/     /_/|_|\__,_/
```
# ctrl-kd

Convert WordStar for DOS v4-v7 files to modern formats. **^KD: save and done.**

`ctrl-kd` reads WordStar for DOS documents, WordStar print stream files, and 
MailMerge data files, and writes plain text, Markdown, HTML, RTF, or PDF (set on a viewer's 
built-in base-14 fonts — no dependencies, nothing embedded, the page as it 
would have printed: printed mode follows the document's own font blocks and 
its own layout arithmetic, while modern mode is the same document reflowed 
for today: its fonts, headers, and footnotes all carried.

```console
$ ctrl-kd ESSAY.WS                      # -> ESSAY.rtf: modern reflow, the
                                        #    document's own fonts carried
$ ctrl-kd --mode printed LETTER.WS      # -> LETTER.pdf: the 1990 facsimile
$ ctrl-kd ESSAY.WS -t md                # modern markdown instead
$ ctrl-kd ESSAY.WS -t html -t rtf       # multiple formats
$ ctrl-kd --page-settings sawyer X.WS   # a known machine's page defaults
$ ctrl-kd --diagnose MYSTERY.FIL        # what IS this file?
$ ctrl-kd --comments MEMO.WS            # include the author's hidden comments
$ ctrl-kd --no-notes PAPER.WS           # body text only, no notes
$ ctrl-kd --samples DIR                 # write 4 bundled public-domain sample .WS files into DIR
$ ctrl-kd --list-quirks ESSAY.WS        # which known quirks this file has, and why
$ ctrl-kd --quirk sawyer-strikeout NOVEL.WS   # turn one on
```

## Modes

* `--mode modern` (default; bare runs produce RTF): the document brought to a
  modern audience — reflowed, its own fonts and styles carried, footnotes at
  the page bottom, gaps the file never specified filled with today's
  conventions (a comfortable serif at reading size, one-inch margins).
* `--mode printed` (bare runs produce PDF): every line as laid out, on the
  era's own page — how it came off the printer. Gaps are filled with 1990's
  conventions instead; `--page-settings` supplies a particular machine's.

More information: **[FAQ.md](FAQ.md)**, and **[ERAS.md](ERAS.md)**.

## Install

```console
$ brew install jonmichaels/tap/ctrl-kd     # macOS / Linuxbrew
$ pipx install ctrl-kd                     # or: pip install ctrl-kd
```
Download Windows x86_64: [Latest Version](https://github.com/jonmichaels/ctrl-kd/releases/latest/download/ctrl-kd-windows-x86_64.zip)

Python ≥ 3.9, no dependencies. Library API: `ctrlkd.convert(data, to='html')`.

## Quirks

Some WordStar files ask for something the bytes do not quite mean. A file's own
header names the printer it was last printed through, and some of those
printers were modified so that a character prints as something else — a peseta
printing as a euro sign, an underscore printing as an em dash. Other files
carry a setting somebody left switched on by accident, like a paragraph style
that crosses out every line it touches.

ctrl-kd is faithful by default and never quietly cleans anything up. Instead
each such departure is a named **quirk** you can see and switch:

```console
$ ctrl-kd --list-quirks           # every quirk, with a plain-language description
$ ctrl-kd --list-quirks NOVEL.WS  # which of them apply to this file, and why
$ ctrl-kd --quirk NAME FILE       # turn one on           (repeatable)
$ ctrl-kd --no-quirk NAME FILE    # turn one off          (repeatable)
$ ctrl-kd --quirks off FILE       # none at all: the most literal reading
```

Quirks whose evidence is in the file itself (its own printer header) are on by
default; ones that are somebody's judgement rather than the file's own evidence
are off until you ask. Writing your own — including as a pip-installable
plugin — is in **[EXTENDING.md](EXTENDING.md)**.

## Adding an output format

An output format is one function over the parsed document — register it with the
`@ctrlkd.emitter` decorator, or ship it as a pip-installable plugin via the
`ctrlkd.emitters` entry-point group and it appears in the CLI automatically.
**[EXTENDING.md](EXTENDING.md)** has the IR contract, a complete worked example
(BBCode in ~40 lines), and a checklist.

## Siblings

**[Soft Return](https://github.com/jonmichaels/soft-return)** — macOS viewer and converter plus QuickLook extension.
Includes a Swift command line utility.

## Lineage

I wanted to be able to see the 70-some WordStar 4 files I had from junior high 
and high school. In about an hour and half my agent had my files looking 
pretty good. And then I fell down the research rabbit hole...

`ctrl-kd` wouldn't have been possible without the tools and documentation that 
kept WordStar readable: Yohanes Nugroho's WS-CON, Michael Petrie's English port, 
the `wsconvert`project, Robert J. Sawyer's WordStar archive, and the WordStar 
format documentation community. 

My own test files are personal and are not distributed — this repo's tests use 
synthetic fixtures and some public domain docs I retyped in WordStar 4 and 
WordStar 7 in DOSBox-X, plus Robert J. Sawyer's public WS7 archive (opt-in, 
`pytest -m sawyer`; see `tests/SAWYER-CORPUS.md`) you can run your own tests
against that if you have a copy: download the archive, point
`CTRLKD_SAWYER_ARCHIVE` at its top-level directory (the one holding
`CONVERT.WS`, `INSET/`, `ARTICLES/`), and verify the path before arming —
`tests/SAWYER-CORPUS.md` has a one-line smoke check. A `CTRLKD_PRIVATE_CORPUS`
variable also exists, for my own private regression fixtures — it has no
effect unless you're me.

## Credits

Written by Jon Michaels — whose 1987–1992 WordStar files, and the need to read
them again, are the reason this exists — with Athena (Claude, Anthropic) as
co-author.
