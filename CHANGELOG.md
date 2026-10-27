# Changelog

Releases before 4.7.0 are described in their own GitHub release notes:
https://github.com/jonmichaels/ctrl-kd/releases

## [Unreleased]

Printed mode now follows the teardowns of WordStar 4.00 and WordStar 7 Rev. D:
the programs' own code and real runs, checked by a new test tier
(`tests/test_teardown_fixtures.py`, armed by `CTRLKD_TEARDOWNS`).

### Added

- **`--printed-by own|ws7`** (and `parse(..., printed_by=)`): which WordStar
  prints a WordStar 4 file. Printing belongs to the program that prints:
  `own` (the default) prints a WS4 file as WS4 printed it; `ws7` prints it as
  WS7 prints the same file. A WS5+ file is always printed by WS7. See ERAS.md.
- **The layout JSON is version 14**: each printed page carries
  `logical_page_x`, where its x = 0 sits on the sheet.
- **`Span.soft`**: the offsets of a span's WS5+ soft spaces, which a
  justifying driver ignores.

### Changed

- **A Printed page sits on the LaserJet's logical page.** WordStar measures
  every x from the PCL logical page, 1/4" in from a Letter sheet's left edge
  (71 dots on A4, 60 and 59 in landscape: HP PCL 5 Technical Reference,
  tables 2-1 and 2-2), so text now lands where it did on paper, 18pt further
  right than before. A print stream stays at the edge.
- **A sub/superscript is set as WordStar 7 sets it**: reduced by each face's
  own factor, floored to the LaserJet's quarter point (9.25pt Courier, 8.25pt
  Helvetica at a 12pt body), on the driver's own narrower cell, and raised or
  lowered by the `.sr` roll exactly (4.5pt at the default, not 4).
- **WordStar 4 files paginate as WordStar 4 does**: a line starts while room
  is left (37 lines at `.lh 12`), a mid-file `.pl/.mt/.mb` acts on the page in
  progress, `.cp n` counts the lines it asks for, `^PK` in a header drops the
  blanks after it, the automatic page number sits at `.pc` 28, and a blank
  line at a page boundary is not forgiven.
- **WordStar 7's page flow**: a blank line after a full page or a trailing
  `.pa` makes a page with its number; a `.pa` on an empty page is ignored;
  empty soft-return lines at the top of a page ended for room are dropped; a
  page ended by a form feed in the text prints no number; under `.lh a` a
  line is led by the font it starts in and may overhang the bottom by its
  rise; the page number's baseline ignores `.cw`.
- **Justification is WordStar 7's**: slack shared in dots, `floor(w * S_rem
  / W_rem)`, by each blank's own width, over proportional and mixed-font
  lines too; a hard-returned line stays ragged.
- **`.l#`** numbers every row of the page, empty ones too, between WordStar's
  two bars. **`^PA`** prints in the LaserJet's alternate font (Gothic 10 pt).
- **A bare `.po` sets the page offset to 0**, and in a WS4 file a bad one
  (`.po x`) does too.
- **Detection**: WS4's `0D 8A` page marks count as evidence, a WS4 file's
  `1B xx 1C` density no longer wins over its word-end high bits, a WS5-style
  header kept as text in a WS4 file is no longer refused, and a short
  headerless WS7 file with soft returns is read as WS7, not text.
- **`--variant` chooses the era** (bit 7, record parsing, printing rules)
  instead of only the parser.

### Fixed

- **A stored soft return stays soft.** `Line.soft` is now exactly what the
  file stores (`8D 0A`, and `1F 8D 0A` after a soft hyphen). It used to read
  some of them as hard when the next word would have fit a guessed 65-column
  margin, or when the next line starts with a typed indent or `.lm` blank
  fill. A new `Line.keep_break` carries that Modern reflow decision (the
  break is kept, as for a poem), so Modern output does not change. Printed
  follows the stored return: `.oj on` justifies a line only when it ends in
  a soft return, in WordStar 4 documents too, and `.pf on` re-wraps across
  every stored soft return. `Line.wraps` is the join test reflow uses.

- **Printed footnotes follow what WordStar 7 does with a note that does not
  fit.** Checked against real runs: when fewer than eight note lines of room
  are left (the program's "footnote run" setting) the reference line and the
  whole note move to the next page; otherwise the note runs, one line fewer
  than the room under the reference, the area ends on the bottom margin line,
  and the next page opens with the separator, `...Continued...` directly
  under it, a blank, then the rest. There is no three-line floor of body
  text: a very long note makes note-only pages. A note reference on a
  trailing empty last line is kept. A bare `.f# n` no longer adds `n` to
  note numbers WordStar already stored with it. A note that runs over several
  pages places its note-only pages and its last page as WordStar 7 does.
  `TAGS/-README.WS` now matches WordStar's own capture exactly. An untagged
  annotation prints no mark.

- **A bare `.rr` in a WS4 file** no longer swallows the next
  line; a soft line before an empty hard line under `.ls 2` stays soft; a
  WS7 nondocument keeps bit 7 (its CP437 characters show).

- **`.f# a` / `.f# A` (and `.e#`) letter the notes in Printed output**, as
  WordStar 7 prints them: a, b, c / A, B, C in the PDF, layout, text,
  Markdown and HTML, and as the footnote / endnote number format in RTF.
  Modern letters them too when no `--note-refs` is given; a `--note-refs`
  scheme, `word` or `prefixed`, wins over the document. `--note-refs` no
  longer defaults to `word`: without it, Modern follows `.f#`/`.e#` and is
  otherwise `word`.

## [4.10.1] — 2026-10-26

### Fixed

- **`-t markdown --pictures embed` now exports and links the pictures, as
  `-t md` always did.** The command line checked the format name as typed, so
  the long name skipped the picture export and the degradation note that the
  short one gave. It now checks the format itself, whichever name was typed.

- **A Printed document with footnotes, endnotes or annotations now lays out
  exactly like one without, apart from the note area itself.** The two had
  separate paginators, and the one for notes had drifted: it ignored `.psb`/
  `.psa`, the `.pm` first-line indent and the per-line `.sr` roll, dropped a
  print control's declared width when a heading restyled it, kept columns
  only until the first wrap, never resolved the even/odd page offset
  (`.poe`/`.poo`), stamped no per-page margin, length or orientation, and
  gave every page the document's last running head instead of the one in
  force on it. There is one paginator now; the note area (growth, the
  three-line floor, continuation, endnotes at the end) is a feature it runs
  when the document has notes. A note-bearing document's `layout` JSON now
  carries each page's own running head and foot, and its trailing blank lines
  are stripped like any other page's. A block that opens on a blank line
  enters its first text line at the style's own leading, notes or not
  (measured against real WordStar 7 on LYING.WS).

## [4.10.0] — 2026-09-17

### Added

- **A page can declare its own sheet.** `.pr or=` (landscape/portrait)
  measured against real WordStar 7: set at the top of a page it applies to
  that page immediately; set in the middle of a page it waits for the next
  page boundary, exactly as WS7 does. The Printed PDF now draws each page on
  its own sheet size instead of one page size for the whole document, and
  the running head/foot and automatic page number follow that page's own
  height (a landscape page's number no longer resolves off the top of a
  portrait document). `layout` JSON version 13 publishes a page's own size
  (width/height/orientation) only where it differs from the document's — the
  same "omit unless it differs" rule every other per-page field here already
  follows; a page that never changes size emits nothing new. Modern is
  unchanged by design — it composes on one reflowed sheet regardless of what
  the source document's pages asked for.

- **The `layout` JSON says when a running head, foot or page number is off the
  paper** (version 12). WordStar commands such a row anyway and lets the printer
  clip it — real WordStar 7 prints put the automatic number 14.4pt below the
  bottom edge of a Letter sheet when `.mb` is smaller than `.fm` — so the PDF is
  unchanged and still draws it there, with the page as its clip. A program
  drawing pages from this JSON has no paper to clip with, so such a row now
  carries `off_sheet: true` and must not be drawn. The key is absent, not false,
  on every row that is on the sheet.

### Fixed

- **Page furniture is set in the document's own face, not in Times.** Running
  heads, running feet, the automatic page number and footnote/endnote text were
  written in a hardcoded face and size in the RTF exports and in the Modern PDF
  — Times New Roman 11 on a Printed page whose body is Courier 12, on every page
  of a running-head document. They resolve through the same font chain body text
  does now: a `.h#`/`.f#` that opens a font block prints in THAT face and size
  (22 documents in the public test corpus, which the Printed PDF has always
  honoured and the other three surfaces threw away); a head that declares
  nothing takes the mode's body face — Courier in Printed, the reading face in
  Modern, Courier in a document that declares itself non-proportional. Sizes
  follow the same rule: Printed furniture is the body's size, Modern furniture
  is the body size less 2pt (12pt against Modern's 14pt body, where the RTF and
  the Modern PDF both used 11). Printed PDF is unchanged — it was already right.

- **Modern: a list bullet and its text no longer read as one crowded word.**
  The square bullet was drawn on the same fixed-pitch cell Printed uses, but
  the space after it was measured in the reading face — 3.5pt against the
  cell's 7.2 — so the item's first word sat about half as far from the bullet
  as it does in the Printed and Native views. It is now one cell, as it is
  there: the first word starts two cells past the bullet in all three views.
  Also fixed in the Modern RTF's hanging indent, which had computed a third
  number again. Only bullets whose marker is a cp437 block glyph are
  affected; a `*` or `-` marker is a real letter in the reading face and
  keeps the spacing it had.

- **Markdown: text that used to vanish now survives.** A document that
  literally says `<SP>`, `<Enter>` or `<B>` had that read as an HTML tag by
  every Markdown renderer, which showed NOTHING — the word disappeared.
  (`<B>` was worse: a real tag, switching bold on with nothing to switch it
  off.) `<` and `&` are escaped now. Affects Sawyer's macro and patch
  documentation heavily; none of the shipped samples.
- **Markdown: strikeout no longer breaks where a bold or italic word sits
  inside it.** The emitter closed the strikeout and reopened it with nothing
  in between (`~~alpha~~~~**beta**~~~~gamma~~`); four tildes are not
  strikethrough in any flavour, so the strike was lost AND the tildes showed
  up as text. The run is merged now.
- **Markdown: a verse or stanza containing a blank line no longer emits a
  line of invisible whitespace.** The two-trailing-spaces hard break turned
  such a blank into a line holding just two spaces, which CommonMark reads as
  a blank line — so the paragraph split anyway, into pieces whose raw text
  claimed otherwise. A blank line ends the unit now, which is what it always
  rendered as. The dangling trailing spaces at a unit's end go too.

  All three are Modern-mode Markdown only. A Printed-mode body, and any
  print-stream or ruler-driven document in either mode, is a fenced code
  block whose content is literal and is untouched.

- `ctrl-kd --version` no longer prints a Python `SyntaxWarning` ahead of its
  own output. A docstring cited RTF's `\margr` control word inside a plain
  (non-raw) string, so Python read `\m` as an escape sequence it did not
  recognise and warned about it. Nothing was broken, but the warning named a
  file inside the package and was the first thing a new Homebrew or PyPI user
  saw, which reads like a crash. It appeared only on a COLD bytecode cache —
  the first run after an install — which is why no development machine ever
  showed it. Every module is now compiled with warnings as errors by both the
  test suite and `tools/run-full-suite.sh`, so it cannot come back.

- **Printed RTF's text column is the document's own ruler width, not a
  fixed arithmetic off the page margins.** The column had been computed as
  paper width minus twice the left margin, which has nothing to do with what
  the author actually typed the page to hold; at the ordinary default it came
  out one character narrower than a common 69-character line, so thousands of
  facsimile lines across the public corpus arrived re-wrapped by the reader —
  the one thing Printed mode exists to prevent. The column now follows the
  widest ruler in the document (or the longest printed line itself, when box
  art or a print stream runs past its own ruler), and the page grows to fit
  it, up to Word's own maximum page size. A document whose lines are wider
  than even that still re-wraps in the reader — there is no page any reader
  accepts that would hold them, and that group shrank from 132 documents to
  32 in a full sweep.

- **A reverse-video banner ("white on black") is visible in RTF and HTML,
  not white text on a white page.** Both exporters kept WordStar's white
  colour but never painted the black ground behind it, so the words were
  simply not there — three documents in the public corpus lost a banner this
  way, one of which says outright in its own text that it should read white
  on black. The ground is drawn now; turning off inline styling removes it
  along with the colour, same as it always has for every other colour.

- **A Printed HTML page is no longer twice as tall as the document.** The
  facsimile block already breaks a line on its own newline; the emitter was
  also writing a `<br>` at the end of every line, so each line was followed
  by a blank one. A 57-page document rendered at double height with its line
  grid gone. The extra break is removed.

- **Newspaper-style columns (`.co`) render as one column block per section,
  in both Printed and Modern HTML**, not one box per paragraph. Modern had
  been opening a fresh pair of columns for every paragraph in a columnar
  region, which balances each paragraph on its own and leaves ragged,
  half-empty columns underneath; Printed dropped the columns entirely. Both
  now open a single container for the whole section, closing it only where
  the document itself ends the columns.

- **A Modern HTML page no longer scrolls sideways on a phone.** The Modern
  stylesheet had no line-length limit at all — a wide window gave a line
  roughly twice a comfortable reading length, and at phone width a long path,
  a run of control words, or a wide row of block graphics pushed the whole
  page off the edge of the screen. Modern HTML now keeps a reading-width
  column and lets only the one unbreakable row (an embedded picture) scroll
  inside itself, the way the Printed facsimile already does. Printed HTML is
  untouched — it was already narrow enough.

### Changed

- **Every quirk was renamed**, and the names that shipped in 4.9.0 still work.
  A quirk's name is text a reader reads and types — `--list-quirks` prints it,
  `--quirk`/`--no-quirk` take it, the `layout` format publishes it — so the six
  now say what they do in plain words instead of naming the printer driver or
  the code behind them:

  | 4.9.0 | now |
  |---|---|
  | `driver-euro-sign` | `euro-swap` |
  | `lj6dtp-typography` | `smart-punctuation` |
  | `lj6dtp-box-corners` | `box-corners` |
  | `lj6dtp-colour-as-gray` | `colors-as-gray` |
  | `lj6dtp-fill-patterns` | `fill-patterns` |
  | `stray-style-strikeout` | `sawyer-strikeout` |

  The old names are still ACCEPTED wherever one can be typed or stored, so
  nothing anyone has scripted or saved stops working. They are never PRINTED:
  `--list-quirks`, `quirks_applicable`/`quirks_applied` and every report say the
  new name only, so one output can never show both spellings for one quirk.
- Descriptions and the quirk window's own row titles use US spelling: "Screen
  colors as gray", "Colors 9–14 as hatch patterns".
- `--headers` and `--page-numbers` now say outright, in their own `--help`
  text, that they apply to PDF and RTF only. Text, Markdown and HTML are
  unpaged by design and never carried running heads, feet or page numbers;
  the flags are still accepted (and ignored, with no error) on those three
  formats — nothing about how they convert has changed.

3,325 answer-key cells were re-recorded across this release's commits (a cell
can move more than once as later commits build on earlier ones): 796 for the
per-page-sheet schema bump (792 `layout` cells at the version number alone,
one document's `pdf.printed`/`rtf.printed` pair for its actual landscape
page, and that same document's `layout` cells re-recorded a second time for
a follow-up fix to the running-head model), 540 for the Printed RTF column
width (385 documents' `rtf.printed`, 148 `rtf.modern`), 508 for the doubled
HTML line height (352 `html.printed`,
149 `html.modern`), 246 for the Modern HTML reading measure (all `html.modern`),
154 for the quirk renames (72 documents' `layout` cells, where the applied-quirk
list is spelled out), 897 for page-furniture fonts (354 `rtf.printed`, 353
`rtf.modern`, 178 `pdf.modern`, plus the picture-bearing twin of each), 115 for
the three Markdown fixes (`markdown.modern`), 28 for the newspaper-column fix
(14 documents, both HTML cells), 19 for the Modern bullet gap (`pdf.modern` +
`rtf.modern`), 14 for off-sheet furniture (7 documents' `layout` cells), and 8
for the reverse-video ground (2 documents, all four RTF/HTML cells). The
`--headers`/`--page-numbers` help wording and the compile-warnings fix moved
no cells at all.

## [4.9.0] — 2026-09-16

### Added

- **Quirks**: named, individually switchable departures from a literal reading
  of the bytes. ctrl-kd stays faithful by default and never quietly cleans
  anything up — instead each known departure now has a name, a one-line
  plain-language description, and a switch. `--list-quirks` prints them all;
  `--list-quirks FILE` also says which apply to that file and why;
  `--quirk NAME` / `--no-quirk NAME` turn one on or off (both repeatable);
  `--quirks off|auto|all` sets the baseline.
  - Six ship with this release. Five are on by default because the file's own
    printer header is the evidence for them — the peseta printing as a euro
    sign, and the four LaserJet LJ6DTP substitutions (typography, Univers box
    corners, colours as grey shades, colours as hatched fill patterns). These
    are exactly the substitutions ctrl-kd already made; naming them changes no
    output, and now they can be switched off to see the literal character.
  - One is off by default: `stray-style-strikeout` ignores a strikethrough
    that a paragraph style switches on while the writing itself never crosses
    anything out. That is how to read cleanly the documents whose style sheet
    turns strikethrough on and never turns it off (see 4.8.1).
  - Quirks are extensible the same way output formats are: `@ctrlkd.quirk`,
    or a pip-installable plugin through the `ctrlkd.quirks` entry-point group.
    See EXTENDING.md, "Adding a quirk".
- The `layout` format reports quirks: `quirks_applicable` (every quirk this
  document trips, whether or not it was turned on — so a reader can be offered
  one without having to already know it exists) and `quirks_applied` (the
  subset in force). Both omitted entirely when the document trips none.

### Changed

- `layout` format version 11 → 12 for the two fields above. Purely additive: a
  document that trips no quirk emits byte-identical JSON to version 11 apart
  from the version number itself. Every `layout` answer-key cell was
  re-recorded for the version number; no other cell in the key moved.

### Fixed

- A paragraph-style selection written at the end of a line was lost when the
  next line was a dot command; a manuscript's book list printed in the
  heading's face and spilled to an extra page, and the whole body came out
  right-aligned in text, Markdown and HTML. Both fixed; a numeric `.lh` now
  outranks the active style's line height, as WordStar does.
- Strikethrough is drawn as one rule across each struck run, spaces
  included, the way WordStar prints it (previously per word).
- NOVEL.WS (a reference manuscript) rejoins the print-fidelity tier; it had
  been mis-tagged as PostScript.

824 answer-key cells were re-recorded for the above: 792 `layout` cells
(389 documents' `layout.printed` + `layout.modern`, plus the 7
picture-bearing documents' `cells_pictures_off` pair) for the version bump,
16 cells across two documents (RTF-RJS/NOVEL.WS and OLDTIMES.WS) for the
end-of-line-selection/`.lh` fix, and 16 `pdf.printed` cells across 14
documents for the strikethrough fix.

## [4.8.1] — 2026-09-16

### Fixed

- A style whose typeface was an ordinary face — Courier, for one — but whose
  character-set bits said "math" printed its whole text in the Symbol font:
  Greek letters instead of words, in every export. A resolved typeface now
  wins; the character-set bits only decide when the typeface itself is
  unknown. (A manuscript's front matter, set in Courier and marked with
  those bits, was the visible case.)
- Strikethrough declared by a paragraph style stayed on only until the next
  styled paragraph, so a document whose style sheet turns strikethrough on
  and never turns it off stopped printing it struck through partway in.
  Real WordStar 7 keeps a style's strikethrough on until a later style turns
  it off, and ctrl-kd now matches — such documents print struck through to
  the end, as on paper. An opt-in "quirks" mode to read such documents
  cleanly is planned for a future release.

40 answer-key cells across 5 reference documents were re-recorded for these
two fixes.

## [4.8.0] — 2026-09-16

### Added

- The `layout` JSON that an app draws a Printed page from now says which
  style each running head and footer line is in, not only which face. A
  head that takes its weight from the document's own style select — as a
  booklet template's two heads do — came out bold in the PDF and light in
  anything drawing from the JSON.
- The check against real WordStar 7 output now compares the automatic page
  number by the column it is printed in as well as by its digits. A number
  printed in the wrong place used to score clean.

### Fixed

- `--headers off` did nothing at all to Modern PDF: a document's running
  heads and feet were still drawn on every Modern page, while the Printed
  PDF and both RTF exports dropped them as asked. Modern drops them too
  now. WordStar's own automatic page number is a separate matter and stays
  under `--page-numbers`, exactly as it already did everywhere else — and
  a document that declares a footer still has no automatic number, whether
  or not that footer is drawn.
- A landscape, two-column document came out of Modern view, Modern PDF and
  Modern RTF as a portrait, single-column page — a page the document never
  describes. All three now keep the sheet the document declares, its
  landscape flag, its column count and its gutter, and break to the next
  column where the document says to. Nothing is balanced, because WordStar
  does not balance: a short last group of columns stays short.
- A document whose page is shorter than US Letter — an envelope, a label,
  a Rolodex card — came out of Modern view and Modern PDF with every page
  blank: the text was drawn above the top of the short page it was drawn
  on. A taller page lost the extra room instead. Modern now lays out on
  the page the document declares.
- Modern view and Modern PDF now show WordStar's automatic page number
  wherever the Printed view does, centred at the foot of the page in
  Modern's own type. It vanished the moment you switched a numbered
  document from Printed to Modern. `--page-numbers auto/on/off` controls
  it on export exactly as it does for Printed.
- A document whose only footer command is a bare `.fo` — WordStar's way of
  turning the automatic number off without printing anything — still got a
  page number in the RTF exports. Real WordStar 7 prints none, and now
  neither do they.
- Modern view and Modern PDF drew every running head and foot at the left
  margin, whatever the document asked for: a booklet template's
  right-hand head sat on top of its left-hand one. A head or foot that its
  own style aligns right or centre is now aligned right or centre in
  Modern's own text measure. A head whose lines ask for DIFFERENT
  alignments is also written correctly to RTF now (one paragraph per
  line, since RTF cannot align twice inside one).
- A footer command typed part-way down a page put its text on the NEXT
  page in Modern view and Modern PDF. WordStar prints a footer at the
  bottom of the page, so it is never too late for one; Printed has read it
  that way for a while and Modern now does too.
- The automatic page number was placed from the document's own left print
  offset rather than from the offset in force on the page being numbered,
  so it sat in the wrong column on every page that moves the offset — the
  landscape templates that alternate a wide odd-page offset with a narrow
  even-page one, and the documents that change the offset part-way
  through. Footnote-bearing pages take the same rule now, instead of
  falling back to the document default.
- The automatic page number vanished from any document that set a line
  height above 12pt, and from any document that is all dot commands and
  running heads with no body at all — a font reference, a printer sample,
  a galley template. Its row, and the row a footer's own text prints on,
  are both counted in WordStar page lines (1/6 in) now, not in the
  document's own line height, and the fractions of a line a `.mb 1.8`
  asks for are kept instead of rounded. Documents that set no bottom
  margin at all correctly print no number, which a few of them used to.
- A booklet template's two running-head lines came out on two rows, with
  the right-hand one printed a third of the way across the page. Real
  WordStar 7 prints both on one row, one at each edge. A head or foot that
  its own style aligns right or centre now aligns against the page offset
  plus the right margin that style declares, and successive head lines
  step by the line height the document asked for — including a line height
  of zero, which is how this template asks for its two heads on one line.
- Modern view turned any paragraph that happened to open `Word:` followed
  by two spaces into a definition-list entry with a hanging indent — a
  plain callout paragraph ("Note:  Some printers may not…") got the same
  treatment as a real list of terms. A definition list now has to look
  like one: at least two entries whose labels start at the same column,
  and at least two different terms among them — a booklet template that
  repeats one "Space:  The final frontier…" paragraph 37 times shares a
  label column but defines nothing, and is prose.
- Modern PDF forced a flat 1-inch right margin while Modern RTF mirrored
  the document's own left print offset, so the same document's two Modern
  surfaces disagreed about where its text ended. Both now mirror whatever
  offset the document declares, falling back to 1 inch when it declares
  none.
- A document that turns page breaks off with `.pl 0` was written to RTF
  with a zero-height sheet, which some word processors refuse to open at
  all. Both RTF modes now fall back to a Letter page, the same way the
  PDF writers already did.

## [4.7.1] — 2026-09-15

### Fixed

- A document that used footnotes and also asked for no page numbers got a
  page number printed at the foot of every page anyway. Real WordStar 7
  prints none on such a document, and now neither does ctrl-kd — in the
  PDF, RTF and HTML exports and in the page-layout views alike.

## [4.7.0] — 2026-09-14

4.6.0 shipped page-level accuracy in PDF only and flagged RTF/HTML as not
caught up yet. This release catches them up, adds another round of
printed-page fixes measured against real WordStar 7, and adds a
MailMerge data-file reader.

### RTF and HTML catch up to PDF

Checked against a real reader (LibreOffice) and a real browser, not just
our own PDF. Page numbers (including the MailMerge page-number variable
and `.pn`'s start value); facing left/right headers and footers with
correct alignment and margins; no trailing blank page after a
document-ending page break; newspaper columns, column breaks, and a
running head that changes mid-document (Printed view only — Modern has
no column model, by design); keep-with-next around a heading; tabs
landing on WordStar's real stops; a first-line indent no longer doubling
up with typed leading spaces; Modern's verse/list/centred-line spacing
matching PDF; a real print stylesheet for Modern HTML; and three defects
a real browser caught (a folding control-code table, a bullet's runaway
continuation line, a picture row wrapping).

### Printed-page fidelity, measured against real WordStar 7

Auto-leading now follows WordStar's actual rule instead of guessing from
font size; `.pf on` print-time paragraph reflow is now honored; a
paragraph's margin now only affects the printed page under `.pf on`,
matching WordStar; header vs. footer redefinition timing is now correct
(they follow different rules); column width and page-budget math fixed;
`..` comment lines print nothing (previously leaked a number onto the
page); formatting at a form feed (fonts, color, footnotes, tabs) no
longer silently dropped; print-control editor labels no longer leak into
the Native view; the driver's character substitutions and the euro now
reach every export, not just PDF; text placed off the edge of the paper
now correctly counted as a match; a tab landing on an already-passed
stop now spends no space.

### MailMerge

`.DTA`/`.LST` data files are now detected (structurally, never by
keyword) and shown as their own kind in Document Info; export produces a
clean, code-stripped list of records. No merge is ever executed.

### Tooling

RTF/HTML exports are now structurally checked and parsed back to confirm
they agree with the source, on every test run. The real-WS7-printout
comparison begun in 4.6.0 was triaged this round: named divergences
10,576 → 3,682, 132 of 194 documents now byte-identical to a real
WordStar 7 LaserJet printout.
