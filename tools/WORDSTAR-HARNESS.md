# Running WordStar itself: setup guide

`tools/wordstar_harness.sh` drives a real WordStar under DOSBox-X, headless, and
captures what it prints. `tools/parity_gauntlet.py` compares our render against
such a printout.

This document is the setup you need before either is useful. Nothing here ships
with the repo — you supply WordStar and you supply documents.

---

## Why bother

The manuals do not settle every question. How `.ls` interacts with page
capacity, whether margin lines double under double spacing, where `.cp` measures
from — WordStar's own documentation is silent or ambiguous on all three, and
several defaults live in `WSCHANGE` rather than in any printed page.

The program is not ambiguous. Running it and reading what it puts on paper turns
those questions into measurements.

---

## 1. Requirements

Debian/Ubuntu:

```sh
sudo apt install dosbox-x xvfb imagemagick python3
```

| Package | Why |
|---|---|
| `dosbox-x` | the DOS emulator. **Not plain `dosbox`** — the harness relies on DOSBox-X's `AUTOTYPE` command and its `[parallel] parallel1=file` LPT capture, neither of which upstream DOSBox has |
| `xvfb` | a virtual display. Optional but strongly recommended — see §6 |
| `imagemagick` | provides `import`, used to screenshot the emulator when a run fails |
| `python3` | the output summary, and the gauntlet |

Verified on DOSBox-X 2024.03.01 on Linux. No display or desktop session needed.

---

## 2. Obtaining WordStar

WordStar was commercial software from MicroPro International, a company that no
longer exists. It is widely mirrored as abandonware; the rights situation is
unclear rather than permissive, so acquire your own copy and do not
redistribute. This repo ships none of it.

Known mirrors, in rough order of how established they are:

- **WinWorld** — `winworldpc.com`, has WordStar 4.0 for MS-DOS. Requires a free
  account to download.
- **vetusware** — carries WordStar 4.00 as both flat files and disk images.
- **archive.org** — reliable for WordStar 4 for **CP/M** and for manuals;
  MS-DOS 4.0 coverage is patchier, and an untitled floppy dump is not proof of
  version. Check what a file claims about itself before trusting it.

**Verify what you got** before running it. WordStar identifies itself in its own
binary:

```sh
strings -a WS.EXE | grep -i 'wordstar.*release'
# WordStar Release 4.00  Serial #........
# Copyright (C) 1979, 1987 MicroPro International Corporation.
```

Beware of copies that are a *different* version renamed. One well-known WS7
distribution ships `WS4.EXE`, `WS2.EXE` and `WS3RJS.EXE` which are all **WordStar
7 with different UI customisations** — the digit is a look-and-feel flavour, not a
version. `md5sum` them against `WS.EXE` and read the distribution's own notes.

**Manuals** are separately and freely available from `bitsavers.org` under
`/pdf/microPro/` — WordStar 3.0, 3.3, 4 (CP/M and MS-DOS), 5, and the WordStar 7
set. Worth having: they document the dot commands, the defaults, and the print
dialog this harness drives.

---

## 3. Directory layout

### WordStar 4

A flat directory. Mandatory:

```
WS.EXE          the program
WSOVLY1.OVR     editing overlay
WSMSGS.OVR      messages
WSPRINT.OVR     printing  -- without this, printing silently does nothing
```

Useful but optional: `WSCHANGE.EXE` + `WSCHANGE.OVR` (the customisation program,
and the only place several documented defaults actually live), `WSSPELL.OVR`,
`SPELSTAR.OVR`, `MAILMRGE.OVR`.

Point the harness at that directory. It copies it to a temp tree per run, so an
archived install stays read-only.

### WordStar 7

**The path matters.** `WS.EXE` has `C:\WS\PRINTERS` compiled into it (set via
`WSCHANGE`), so the tree must land at `C:\WS` inside DOSBox. The harness mounts
your directory as `C:\WS` for exactly this reason. If printer definitions are not
found there you get:

```
Can't print.  PDF or driver files not found.
```

("PDF" here means **Printer Definition File**, WordStar's own format — it predates
Adobe's use of the initials by years.)

So a WS7 tree needs:

```
WS.EXE, *.OVR         the program and its overlays
PRINTERS/*.PDF        printer definitions -- ASCII, DRAFT, PRVIEW,
                      TYPEWR, LASERJET, PS ...
```

Some distributions keep the `.PDF` files loose in the root; copy them into a
`PRINTERS/` subdirectory as well.

---

## 4. Running it

```sh
tools/wordstar_harness.sh ws4 /path/to/ws4-dir  DOCUMENT  output.prn
tools/wordstar_harness.sh ws7 /path/to/ws7-dir  DOCUMENT  output.prn
```

`DOCUMENT` is any WordStar file. It is copied in as `DOC.WS`; your original is
not touched.

Typical output:

```
running WordStar (ws4) ...
wrote output.prn (18040 bytes, from OUT.PRN)
  595 lines, 0 form feeds
  page gaps: 8 interior runs of [11, 12] blank lines => 9 pages
```

### How the two versions differ

|  | WordStar 4 | WordStar 7 |
|---|---|---|
| command-line print | **none** | `ws FILE /p /x` |
| how the harness drives it | `AUTOTYPE` types `P`, the filename, then `Esc` | just runs the command |
| where output goes | LPT1, captured by DOSBox-X to a file | wherever the install's **Redirect To** points |
| speed | seconds | seconds (PCL); minutes with some text drivers |

`Esc` at any print prompt means *"use the defaults for everything remaining and
print now"* — the manual says so, and the print screen says so too. That is what
makes WS4 drivable with four keystrokes instead of eight.

---

## 5. Reading the output

**Form feeds are usually absent.** WS4's `Use form feeds?` prompt defaults to
**no**, so page breaks arrive as a run of blank lines — bottom margin plus top
margin — rather than a `0x0C`. The harness detects this and reports page count
from the gaps. A gap only counts as a page break if text falls on **both** sides:
the run before the first text is the opening top margin and the run after the
last is trailing paper, and counting those inflates the page count by two.

**Blank lines may not look blank.** In some print streams a "blank" line carries
a control byte such as `0x14`. A naive `strip()` will read it as text. The
harness strips `\r`, `0x14` and spaces before deciding.

**With a plain-text driver you get text; with a laser driver you get PCL.** PCL
is not a worse answer — it encodes exact cursor positions (`ESC&a###H` /
`ESC&a###V`), which is *more* precise for geometry than plain text. Choose based
on the question you are asking.

---

## 6. Troubleshooting

**Use a display even though it is headless.** `SDL_VIDEODRIVER=dummy` works, but
**WordStar reports its errors on screen and nowhere else** — not to stdout, not
to an exit code, not to a log. Running under `Xvfb` and screenshotting is the
only way to find out why a run did nothing. The harness starts its own `Xvfb`
and, on failure, saves a screenshot next to your output file. Every setup
problem below was diagnosed from one of those screenshots and from nothing else.

| Symptom | Cause |
|---|---|
| `Can't print. PDF or driver files not found.` | WS7 tree is not at `C:\WS`, or `PRINTERS/` is missing |
| `Not a valid filename.` | the install's **Redirect To** path names a directory that does not exist. Create it |
| runs, exits, no output | check whether the install redirects print to a file instead of LPT1 — look at the Print dialog's `Redirect To` field |
| prints forever, no output | a printer definition that does not match the driver it replaced. Do not swap `.PDF` files around; select the driver properly instead |
| nothing happens at all | `WSPRINT.OVR` missing from a WS4 tree |

**Never `pkill -f Xvfb`.** On a shared machine that kills every other Xvfb,
which may be somebody's service. The harness kills only the one it started, by
PID. For the same reason avoid `pkill -f` with any pattern that could match your
own shell's command line — `pkill -f "dosbox-x -conf foo.conf"` matches the very
shell running it and kills that instead, which surfaces as a mystifying exit code
rather than an error.

---

## 7. Limits worth knowing

- **A WordStar install carries settings.** Margins, line spacing, default
  printer and page length can all have been customised via `WSCHANGE` by whoever
  built the copy you downloaded. Two installs of the same version can paginate
  the same document differently. If a result surprises you, check the install
  before concluding anything about WordStar.
- **A period printout is ground truth only if the document was not edited after
  it was printed.** Diff the text before trusting a pair; `KNOWN-DIFFS.txt` in
  the gauntlet exists for the cases where it was.
- **Version matters.** Defaults drifted across releases — `.pc` changed between
  3.3 and 4, and the meaning of a "column" in margin dot commands changed at 5
  (font-relative before, a fixed 0.1in after). Run the version that matches the
  documents you care about.

## 7. Printing with the Sawyer WS7 install — the working procedure (2026-08-12, verified)

An earlier version of this section theorized the fix was driving WS7's
print-options dialog to select a driver. WRONG — no keystrokes are needed
(and stray AUTOTYPE keys during WS7 startup actually POISON the print:
runs with injected keys stalled at "P1" forever). The harness now does all
of the below itself; this is the reference for what and why.

Three conditions make `ws FILE /p /x` produce output headlessly:

1. **Tree mounted at C:\WS** (§3; WS.EXE hardcodes C:\WS\PRINTERS).
2. **Driver .PDFs present in PRINTERS\** — Sawyer keeps them loose in the
   root; copy `WS/*.PDF` into `WS/PRINTERS/` per run.
3. **The default printer's Redirect-To directory must exist.** Sawyer's
   default = LASERJET redirecting to `C:\WS\TEMP\WORDSTAR.PCL`, and
   `TEMP\` is not in the pristine tree. `mkdir WS/TEMP` per run. Without
   it the print "succeeds" while emitting nothing.

Plus the speed discovery: **`[cpu] turbo=true`** in the DOSBox-X conf.
WS7 paces its despooler against the emulated clock — without turbo a
5-page LASERJET print trickles at ~100 bytes/min and looks like a hang;
with turbo it completes in ~10 seconds and the emulator exits (`/x` +
autoexec `exit`), which is itself the completion signal. Do NOT give ws4
turbo (its AUTOTYPE timing would misfire).

Per-driver redirect targets on this install (where output lands):
- LASERJET → `C:\WS\TEMP\WORDSTAR.PCL` (PCL5; decode with
  `tools/pcl_text.py` — exact per-run cursor positions in decipoints).
- ASCII → `C:\WS\ASCII.TXT` (plain text; page breaks arrive as blank-line
  runs, no form feeds). To force plain-text output without touching the
  document, copy `ASCII.PDF` over `PRINTERS/LASERJET.PDF` ("driver swap")
  — but note the ASCII driver imposes its own page geometry, so use it for
  CONTENT questions, never for POSITION questions.
- `<doc>.$GP` (≈1.5 KB, style-table strings) is WordStar's internal print
  work file, not output — seeing only this means the print never reached
  the driver stage (usually condition 3 missing).

KNOWN LIMIT: documents carrying WS7 paragraph styles (e.g. Sawyer's own
OLDTIMES.WS, authored with "MS Chapter Title" etc.) stall the LASERJET
driver indefinitely even under turbo (dosbox spins at 100% CPU, zero
output after the `.$GP` prelude). Plain-ASCII documents with dot commands
print perfectly. For position questions about such documents, reproduce
the relevant geometry in a minimal ASCII doc (explicit `.pl/.mt/.mb/.hm` +
the same header) and print THAT — verified equivalent for the header
question below.

### Settled by real WS7 bytes (2026-08-12)
Stock geometry (`.pl66 .mt3 .mb8 .hm2`, `.h1 Sawyer / Old Times / #`),
genuine LASERJET.PDF, decoded PCL:
- header baseline V=120 decipoints (0.167") = **physical line 1**, on
  page 1 AND page 2;
- first body line baseline V=480 (0.667") = **line 4**;
- gap = 360 decipoints = exactly 3 lines at 6 LPI.
This matches the engine's placement to the decipoint: WordStar really does
print the header on line 1 under stock defaults. Separately, printing with
the INSTALL's own defaults (no explicit dot commands) put the header at
V=357 ≈ line 3 with body at line 6 — Sawyer's install carries WSCHANGE'd
margins (≈.mt5/.hm3), presumably because line 1 sits at a LaserJet's
printable edge. Both facts matter: the engine models stock WordStar
correctly, and period Sawyer printouts would still show the header lower.

## Install divergence: default .po (dx experiment 2026-08-20)

Sawyer's install carries a WSCHANGE'd default page offset of **7 columns
(50.4pt)**, not the manual's 8 (57.6pt) — same family as its `.mt5/.hm3`
margins above. A doc with no explicit `.po` therefore prints 7.2pt left of
an engine using the manual default; this is the entire corpus-wide frame
dx=+7.2pt (engine−WS7, IQR 0.0) once measured. Also measured: `.po` is a
FIXED 7.2pt/column at both 10cpi and 12cpi — the manual's ".CW determines
the actual amount of indentation" clause does not match real output.
