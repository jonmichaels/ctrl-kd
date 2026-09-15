# Changelog

Releases before 4.7.0 are described in their own GitHub release notes:
https://github.com/jonmichaels/ctrl-kd/releases

## [Unreleased]

### Fixed

- A landscape, two-column document's Modern RTF came out as a square page
  with no columns — a page the document never describes, and one its own
  Modern PDF (which keeps the sheet and the columns) does not print. The
  Modern RTF now carries the real sheet, the landscape flag, the column
  count and the gutter, and breaks to the next column where the document
  says to.
- A document whose page is shorter than US Letter — an envelope, a label,
  a Rolodex card — came out of Modern view and Modern PDF with every page
  blank: the text was drawn above the top of the short page it was drawn
  on. A taller page lost the extra room instead. Modern now lays out on
  the page the document declares, and a document that turns page breaks
  off with `.pl 0` gets a Letter-sized page instead of a zero-height one.
- Modern view and Modern PDF now show WordStar's automatic page number
  wherever the Printed view does, centred at the foot of the page in
  Modern's own type. It vanished the moment you switched a numbered
  document from Printed to Modern. `--page-numbers auto/on/off` controls
  it on export exactly as it does for Printed.
- A document whose only footer command is a bare `.fo` — WordStar's way of
  turning the automatic number off without printing anything — still got a
  page number in the RTF exports. Real WordStar 7 prints none, and now
  neither do they.
- A booklet template's two running-head lines came out on two rows, with
  the right-hand one printed a third of the way across the page. Real
  WordStar 7 prints both on one row, one at each edge. A head or foot that
  its own style aligns right or centre now aligns against the margin that
  style declares, and successive head lines step by the line height the
  document asked for — including a line height of zero, which is how this
  template asks for its two heads on one line.

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
