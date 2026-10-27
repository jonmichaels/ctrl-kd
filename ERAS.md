# Eras: how ctrl-kd models WordStar version differences

The user-facing summary is in `FAQ.md`. This is the technical account: what is
known to differ between WordStar releases, how each difference is handled, and
what it would take to close the gaps.

## The model

One table, `ERAS` in `src/ctrlkd/core.py`, keyed by *detected variant*
(`ws3` / `ws4` / `ws5+` / `printstream` / `text` / `binary`). Each entry is an
`Era` of **behaviour flags, not version switches** — code asks
`era.high_bit_wordwrap`, never `variant == 'ws4'` — so a new release slots in by
adding one row and teaching `detect()` to return it. Rules for a new row: every
axis conservative (a wrong `False` loses a feature; a wrong `True` can destroy
text — see the `binary` entry's history in the table's own comments), and no row
relies on the `era_for()` fallback.

Documents also *declare* their release: the WS5+ header block carries a BCD
version byte, surfaced as `doc.meta['ws_header']['release']`. Detection infers;
the header states. Both are available to key a future split on.

## Known divergences and their status

| # | Divergence | Releases | Status |
|---|---|---|---|
| 1 | High bit on text bytes: word-wrap/soft flags vs literal characters | ≤4 vs 5+ | **Modelled + oracle-verified.** WS4-era sets bit 7 on the last character of each word. WS5+ text is 7-bit with extended characters as `1B xx 1C` triples; a bare high-bit byte there is a *flagged control* (the `8D 8A` soft-return pair; flagged toggles), confirmed by tracing real WS7 print output byte-for-byte (2026-08-04) |
| 2 | Symmetric sequences, notes, `.sb` | 5+ only | **Modelled.** A WS4 file cannot contain them (exhaustive command-table extraction) |
| 3 | What a "column" measures in `.rm .lm .pm .po .pc` | ≤4: one character of the current font; 5+: fixed 0.1 in | **Modelled; WS7 half confirmed, WS4 half not yet run.** WS7 counts every ruler and margin column in `rlunit` = 180 HMI = 1/10 inch (WS7 teardown, `wordstar-dos/7-configuration.md` 7.1 and `13-screen-ui.md` 13.3; the `.pc` arithmetic in `11-print-engine.md` 11.5 divides by 180). WS4 stores its settings in columns and 1/120 in (`wordstar4-dos/5-configuration-addons.md`, the 7.3 note); what a WS4 margin column measures after a `.cw` change has not been run. Only bites a document that changes `.cw` *and* uses a margin dot command |
| 4 | Default page-number column: `.pc` | 3.3: column 33; 4: column 28 from the page offset; 7.0: centred on `(LM + RM) / 2`, which at the factory margins is 32 spaces, digit in column 33 | **Table row unread; WS3 unreachable by design.** `Era.pc_default` (28) is never read: Printed places every era's automatic number at WS7's 33.5 (`pdf._AUTO_PAGENO_DEFAULT_COL`), so a WS4 document's number lands 5 columns right of where WS4 prints it (WS4 teardown, `wordstar4-dos/4-formatting-printing.md`, the `.PC` row: default 28, manual p.215; WS7 teardown, `wordstar-dos/11-print-engine.md` 11.5). A plain WordStar 3.30 file cannot be told from a WS4 file by its bytes, so `detect()` never returns `ws3`. See "WordStar 3" below |
| 5 | Bare `.pl` (no argument) | 6.0: page breaks OFF; 7.0: keeps the previous value | **KNOWN LIMITATION — 7.0 behaviour implemented.** See below |
| 6 | Style-library layout | validated on 5.5-format libraries | **Caveat on record.** Every in-file style library we have decodes as style version BCD 55; the layout is spec-version-neutral but unverified against a genuine 5.0/6.0-written library |
| 7 | Footnote/endnote note TAGS and non-numeric FORMAT TYPES | WS5+ | **Formats: engine differs from WS7. Tags: unverified.** See below |

## Known limitation: bare `.pl` (divergence 5)

**The facts.** MicroPro engineering release note 649 (public: the WordStar 7
engineering notes circulate with the reference material at
[sfwriter.com](https://www.sfwriter.com/) and elsewhere), fixing bug 12284:

> DRIVERA.OVR now inserts ".pl0" (rather than ".pl") at start of PRVIEW.WS
> output file when printing a PRVIEW.PDF document. (".pl" by itself doesn't
> turn off page breaks in 7.0 document mode like it used to in 6.0.)

So in 6.0 document mode, bare `.pl` disabled page breaks; in 7.0 it does not.
Note 662 (bug 12453) gives the 7.0 rule: when the argument is missing or starts
with a bad character, `.pl .mt .lh .mb .hm .fm` keep the previous value. (Note
656, which this file used to credit, says the opposite, that a missing argument
reads as zero; WS7 Rev. D does not do that.) Runs of WS7 Rev. D confirm note
662 for `.pl`, `.mt`, `.mb` and `.lh`: a bare or bad argument keeps the previous
value. A bare **`.po`** is the exception: it sets the page offset to 0 (WS7
teardown, `wordstar-dos/7-configuration.md` 7.9, runs arg-*).

**What ctrl-kd does.** The 7.0 reading: bare `.pl` is a no-op; explicit `.pl 0`
turns page breaks off (modelled as a page too tall to fill; the PDF page box
falls back to Letter). Both are tested. A bare `.po` is also a no-op today,
which differs from WS7 (it should set 0); the run fixtures test it.

**Why the 6.0 behaviour is not implemented.** Two missing pieces of evidence:
no document in our reference corpus uses bare `.pl` at all (so there is no real
input to validate against), and we have no WordStar 6.0 installation to measure
(the harness runs 4 and 7). Implementing an era split against zero inputs and no
oracle would be exactly the kind of guess this project keeps finding bugs in.

**What a future fix looks like**, for whoever picks it up:

1. Evidence first: a real 6.0-era document that uses bare `.pl`, and ideally a
   WordStar 6.0 install runnable under the harness (`tools/WORDSTAR-HARNESS.md`)
   to measure the actual pagination.
2. Add an era axis (e.g. `bare_pl_disables_breaks`) rather than a version test,
   per the table's design rule.
3. Choosing the era: the header's declared release
   (`doc.meta['ws_header']['release']`, BCD byte — real 6.0 documents declare
   `6.0`) is the right key; detection statistics cannot distinguish 6 from 7.
4. Wire bare `.pl` (currently: argument missing → no change) to the flag, and
   add the ratifying test *from the measurement, not from this document*.

## WordStar 3 (divergence 4)

The `ws3` era row records the known deltas (`.pc` default 33, font-relative
columns, no symmetric blocks/notes/`.sb`, WS4-style high-bit word-wrap), but
`detect()` never returns it, and it cannot learn to for an ordinary document.
The WordStar 3.30 teardown (`wordstar33-dos/3-document-format-files.md` 3.1,
3.12; `6-ws33-vs-ws4.md`) settles why:

- A 3.30 file has no header, signature or version byte, and every byte 3.30
  writes means the same thing in WS4. A plain 3.30 document is a valid WS4
  document byte for byte, and the WS4 reading of it is correct.
- What proves a file is NOT 3.30: a `1B xx 1C` extended character; a WS4-only
  dot command (`.RR`, `.PM`, `.H1`-`.H5`, `.F1`-`.F5`, `.AW`, `.PS`, `.LQ`,
  `.UL` and the rest); bit 7 on a `-`, `1Eh` or `1Fh` (3.30 sets it only before
  `20h`/`09h`); `00h` anywhere other than right before a word or in the zero
  padding at the end.
- What only points to 3.30: `00h` right before a word (SpellStar's flag; in WS4
  it is a typed `^P@`).

If a file is known to be 3.30 (from its disk or date, not its bytes), three
things change: its `00h` bytes are dropped (WS4 keeps them as `^P@` text);
`.LM`/`.RM`/`.LS` act only in merge printing; the page-number column default is
33, not 28. Full WS3 support is out of scope; identification is the most a
content-based detector can offer.

## Footnote/endnote note tags and number formats (divergence 7)

**The facts.** WSFORMAT.TXT documents two fields on a footnote/endnote's own
symmetrical-sequence block: the tag/number word ("if the high order bit of
this word is set... the low 15 bits are the offset of the internal
sequence" containing "the footnote number tag" -- resolved one level
deeper, the same 5-byte shape recurring, since "currently only one level of
this recursion is used") and the conversion-flag byte's high nybble ("0
means to use symbols, 1 is for upper case, 2 is for lower case, and 3 is
for numbers").

**What WS7 actually prints** (WS7 teardown, `wordstar-dos/15-open-items-closed.md`
15.10 and `11-print-engine.md` 11.11; runs w16-fnup, w16-fnlow, w16-fnsym,
w16-fnlow2, w16-fnup2): the number is printed in the **`.f#` (`.e#`) format in
force at print time**, not in the nibble stored in the note. A document whose
notes all store nibble 1, 2 or 4 prints `1.`, `2.`; the same document with
`.f# a` or `.f# A` as its first line prints `a.`, `b.` or `A.`, `B.`, in the
text and at the foot, restarting each page. The `.f#` parser takes a digit
(decimal), an upper-case letter (upper) or a lower-case letter (lower); the
print formatter knows 1 upper, 2 lower, 3 decimal and **4 symbols** (WSFORMAT's
"0 means symbols" is not what the program does). The stored nibble is only
the editor's copy: a save rewrites it on the notes the editor re-paginated and
leaves it stale on the rest.

**What ctrl-kd does, and where it differs.** `core._parse_note` resolves the
recursive high-bit case into `Note.tag` for footnote/endnote exactly as it
already did for annotations, and `Note.number` stays `None` for a tagged note
so it is never renumbered. `emit._annotated_notes` displays a tag when present
(every format) and formats a plain number per the STORED `Note.number_format`
(0 symbols via the classical `*`/`†`/`‡`/`§`/`‖`/`¶` cycle; 1/2 upper/lower
alpha; 3, and anything undocumented, arabic). Behaviour set by project
decision, 2026-08-24. Two things differ from WS7: the format should come from
the `.f#`/`.e#` setting in force (which this project does not parse yet), and
the symbols code is 4, not 0. Changing it reverses that decision, so it waits
for one.

**Still unverified:** a user-assigned footnote tag (custom mark). No run has
printed one, and no Sawyer-archive document carries one; it is implemented to
spec and pinned only by synthetic fixtures (`tests/test_ctrlkd.py`).

## How divergences get settled here

Spec first (WSFORMAT.TXT and the engineering release notes), then known-answer
files, then **the program itself**: read in disassembly and run under
emulation. The WordStar teardowns (WS 3.30, 4.00 and 7.0 Rev. D, each a set of
numbered reports, cited here by report file and section) do the reading and
keep scripted DOSBox-X runs of real WordStar with every input and output; their
run fixtures are a test tier here (`tests/test_teardown_fixtures.py`). Locally,
`tools/wordstar_harness.sh` runs real WordStar 4 and 7 headless and captures what they print, and
`tools/pcl_text.py` turns the WS7 driver's PCL into measurable text positions.
Two implementations of this converter agreeing proves nothing (the second was
ported from the first); only those three sources settle anything.
