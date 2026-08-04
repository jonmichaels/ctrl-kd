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
| 3 | What a "column" measures in `.rm .lm .pm .po .pc` | ≤4: one character of the current font; 5+: fixed 0.1 in | **Modelled but UNVERIFIED.** WS7's "Upgrading" note and WS5's "What's New" name *different* command lists as affected. Only bites a document that changes `.cw` *and* uses a margin dot command. Settle by experiment (the harness) before relying on it |
| 4 | Default page-number column: `.pc` | 3.3: column 33; 4+: column 28 | **Modelled in the table; unreachable.** The `ws3` row exists but `detect()` never returns `ws3` — no WordStar 3 samples existed to build detection from. See "Adding WordStar 3" below |
| 5 | Bare `.pl` (no argument) | 6.0: page breaks OFF; 7.0: no effect | **KNOWN LIMITATION — 7.0 behaviour implemented.** See below |
| 6 | Style-library layout | validated on 5.5-format libraries | **Caveat on record.** Every in-file style library we have decodes as style version BCD 55; the layout is spec-version-neutral but unverified against a genuine 5.0/6.0-written library |

## Known limitation: bare `.pl` (divergence 5)

**The facts.** MicroPro engineering release note 649 (public: the WordStar 7
engineering notes circulate with the reference material at
[sfwriter.com](https://www.sfwriter.com/) and elsewhere), fixing bug 12284:

> DRIVERA.OVR now inserts ".pl0" (rather than ".pl") at start of PRVIEW.WS
> output file when printing a PRVIEW.PDF document. (".pl" by itself doesn't
> turn off page breaks in 7.0 document mode like it used to in 6.0.)

So in 6.0 document mode, bare `.pl` disabled page breaks; in 7.0 it does not
(and note 656 records the general 7.0 rule that a dot command with a missing
argument keeps the previous value).

**What ctrl-kd does.** The 7.0 reading: bare `.pl` is a no-op; explicit `.pl 0`
turns page breaks off (modelled as a page too tall to fill; the PDF page box
falls back to Letter). Both are tested.

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

## Adding WordStar 3 (divergence 4)

The `ws3` era row already records the known deltas (`.pc` default 33,
font-relative columns, no symmetric blocks/notes/`.sb`, WS4-style high-bit
word-wrap). What is missing is **detection**: `detect()` has never seen a
WordStar 3 file and returns `ws4` or `binary` for era-3 input today.

To add support: collect real WS3 (CP/M or DOS) samples; find a detectable
signature (release stamps in the file, byte statistics, dot-command vocabulary
— `.pc` handling itself may discriminate); teach `detect()` to return `'ws3'`;
add fixtures and tests. The rendering path needs no other change — the era row
does the work. Manuals for 3.0/3.3 are on
[bitsavers.org](http://bitsavers.org/pdf/microPro/).

## How divergences get settled here

Spec first (WSFORMAT.TXT and the engineering release notes), then known-answer
files, then **the program itself** under emulation — `tools/wordstar_harness.sh`
runs real WordStar 4 and 7 headless and captures what they print, and
`tools/pcl_text.py` turns the WS7 driver's PCL into measurable text positions.
Two implementations of this converter agreeing proves nothing (the second was
ported from the first); only those three sources settle anything.
