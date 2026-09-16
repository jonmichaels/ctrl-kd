# Changelog

Releases before 4.7.0 are described in their own GitHub release notes:
https://github.com/jonmichaels/ctrl-kd/releases

## [Unreleased]

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
