# FAQ

## Which WordStar versions does ctrl-kd read?

- **WordStar 4** documents (and the high-bit word-wrap convention of that era).
- **WordStar 5, 6, and 7** documents. For these, ctrl-kd follows **the WordStar 7
  standard**: MicroPro's own *File Format for WordStar Release 7.0* (17 March 1992),
  the last and most complete official format specification. A public copy lives at
  [sfwriter.com/wsformat.txt](https://www.sfwriter.com/wsformat.txt); manuals for
  every release are at [bitsavers.org](http://bitsavers.org/pdf/microPro/).
- **Print-to-disk files** — the printer byte stream captured to a file, a distinct
  format most converters mangle.

Not sure what a file is? `ctrl-kd --diagnose FILE` reports what it detected and why.

## Why "the WordStar 7 standard" for 5/6/7 — aren't they different?

Mostly they are not: the on-disk format was stable across 5.0–7.0, and the 7.0
specification documents it in full. Where releases genuinely diverged, ctrl-kd
models the difference explicitly (see `ERAS.md` for the mechanism). Two cases are
worth knowing about:

### Known limitation: bare `.pl` under WordStar 6.0

A `.pl` command **with no argument** meant "turn page breaks off" in WordStar 6.0,
but stopped meaning that in 7.0 — MicroPro's own engineering notes record the
change (their PRVIEW driver had to start writing `.pl0` instead; internal bug
12284). ctrl-kd follows the 7.0 reading: a bare `.pl` changes nothing, while an
explicit `.pl 0` turns page breaks off in both.

**Impact:** a document written for WordStar 6.0 that relies on bare `.pl` would
paginate here (7.0 behaviour) instead of flowing unbroken (6.0 behaviour). We have
never seen such a document — none exists in our reference corpus — and we have no
WordStar 6.0 installation to verify against, so the 6.0 behaviour is deliberately
not guessed at. If you have a real document affected by this, please open an
issue and attach it (or a trimmed sample): that is exactly the evidence needed to
implement the split properly. Technical details: `ERAS.md`.

### WordStar 3 (CP/M and early DOS)

Not currently supported: ctrl-kd will not identify a file as WordStar 3. The
groundwork exists — the era table already carries a `ws3` entry recording what is
known to differ (the default page-number column moved from 33 to 28 between 3.3
and 4, and pre-WS5 margin commands measure columns in the *current font's* width
rather than a fixed 0.1 inch) — but detection was never taught to recognise the
release, because we had no WordStar 3 documents to detect. If you have real
WordStar 3 files, open an issue: with samples in hand the support is a
well-marked, modest job. Technical details: `ERAS.md`.

## How do I know the output is right?

Three sources of truth, in order: MicroPro's own format specification and
engineering release notes; known-answer files (MicroPro's demo/test documents,
whose correct rendering is knowable in advance); and **WordStar itself**, run
under emulation and measured (`tools/WORDSTAR-HARNESS.md`). Behaviour in this
converter is traceable to one of those three — and where none of them settles a
question, the code says so rather than guessing quietly.

## Something renders differently than real WordStar printed it?

That is a bug we want. Open an issue with the file (or a trimmed sample) and, if
you have it, the original printout or a description of what WordStar itself did.

## Why does `--encoding` only accept cp437? What about international WordStar?

The high-bit bytes in a WordStar file are glyphs from the PC's OEM code page,
and every file this project has ever been tested against uses **code page 437**
(the US IBM PC set — which Anglophone machines everywhere ran, Canada included).
WordStar 5+ itself acknowledged other code pages — its font blocks carry
symbol-map bits that distinguish cp437 from cp850, the DOS "multilingual"
Western European set — so files written on French, German, or Spanish machines
plausibly exist with accented text in cp850 (or cp860/863/865) byte positions.

We have **zero such files**. Implementing another code page is easy — it is a
byte table — but *validating* one is not: without a real document written on
such a machine, a synthetic test only proves our table matches our table,
and this project ships evidence-driven behavior, not assumptions. So the CLI
refuses what it cannot verify. The Python library API (`ctrlkd.core.parse`)
still accepts any codec name, so an experimenter holding real international
WordStar material can try it today — and if you have such files, please open
an issue: a genuine known-answer document is exactly what would turn this
limitation into a feature.
