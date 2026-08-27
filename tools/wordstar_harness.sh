#!/usr/bin/env bash
# Print a WordStar document using WordStar ITSELF, under DOSBox-X, headless.
#
# WHY
# ---
# The manuals do not settle every question (how `.ls` interacts with page
# capacity; whether margin lines double under double spacing; where `.cp`
# measures from). The program does. This runs the period-correct program and
# captures what it actually puts on paper, so the converter can be checked
# against the thing it is reproducing rather than against our reading of a
# manual.
#
# It is the companion to tools/parity_gauntlet.py. The gauntlet compares
# against printouts that happen to have survived; this produces a printout for
# ANY document on demand, including single-spaced ones where the gauntlet's
# filler-suppression trick has nothing to read.
#
# SETUP
# -----
# Full setup guide, including where to get WordStar, the directory layout each
# version needs, and every failure mode we have hit:
#
#     tools/WORDSTAR-HARNESS.md
#
# The short version:
#   * needs dosbox-x (NOT plain dosbox -- this uses AUTOTYPE and LPT capture),
#     plus xvfb and imagemagick for failure screenshots.
#   * you supply WordStar and you supply documents. Neither ships here.
#   * WS4 tree needs WS.EXE + WSOVLY1.OVR + WSMSGS.OVR + WSPRINT.OVR. It has no
#     command-line print, so the dialog is driven with AUTOTYPE, and output is
#     captured off LPT1.
#   * WS7 has `ws FILE /p /x`, but WS.EXE hardcodes C:\WS\PRINTERS -- the tree
#     MUST mount at C:\WS -- and an install may redirect print to a file whose
#     directory has to exist already.
#   * WordStar reports its errors ON SCREEN ONLY. On failure this script saves a
#     screenshot next to your output file; that is the only diagnostic there is.
#
# USAGE
#   tools/wordstar_harness.sh ws4 <ws4-dir> <document> <output>
#   tools/wordstar_harness.sh ws7 <ws7-dir> <document> <output>
set -euo pipefail

MODE=${1:-}; WSDIR=${2:-}; DOC=${3:-}; OUT=${4:-}
[ -z "$OUT" ] && { sed -n '/^# USAGE/,/^set -e/p' "$0" | head -4; exit 2; }
[ -d "$WSDIR" ] || { echo "no such WordStar directory: $WSDIR" >&2; exit 2; }
[ -f "$DOC" ]   || { echo "no such document: $DOC" >&2; exit 2; }
command -v dosbox-x >/dev/null || { echo "dosbox-x not installed" >&2; exit 2; }

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
# WordStar writes into its own directory, so it gets a copy. The source tree is
# left untouched -- an archived install should stay read-only.
mkdir -p "$WORK/WS" "$WORK/CAP"
cp -r "$WSDIR"/. "$WORK/WS/"
cp "$DOC" "$WORK/WS/DOC.WS"
if [ "$MODE" = ws7 ]; then
    # WS.EXE hardcodes C:\WS\PRINTERS for driver .PDFs, but an install may keep
    # them loose in the root (Sawyer's does) -- make both locations valid.
    cp "$WORK/WS/"*.PDF "$WORK/WS/PRINTERS/" 2>/dev/null || true
    # An install's default printer may Redirect To a file in a directory that
    # does not exist on the pristine tree (Sawyer's: C:\WS\TEMP\WORDSTAR.PCL).
    # WordStar opens the file only if the directory exists; without it the print
    # "succeeds" emitting nothing.
    mkdir -p "$WORK/WS/TEMP"
fi

# A display. WordStar reports errors on screen only, so a real (virtual) one is
# worth the two seconds even when nothing will look at it.
DISP=${WS_HARNESS_DISPLAY:-}
if [ -z "$DISP" ] && command -v Xvfb >/dev/null; then
    DISP=":$(( (RANDOM % 400) + 100 ))"
    Xvfb "$DISP" -screen 0 1024x768x24 >/dev/null 2>&1 &
    XPID=$!
    # kill ONLY our own Xvfb: `pkill -f Xvfb` would take down every other one
    # on the machine, and on a shared host that is somebody else's service.
    trap 'kill "$XPID" 2>/dev/null; rm -rf "$WORK"' EXIT
    sleep 2
fi

CONF="$WORK/harness.conf"
{
  echo '[dosbox]'; echo 'memsize=32'
  if [ "$MODE" = ws7 ]; then
      # WS7 paces its despooler against the emulated clock: without turbo a
      # 5-page LASERJET print trickles at ~100 bytes/min (measured 2026-08-12).
      # Turbo races the whole clock; a document prints in seconds. ws4 must NOT
      # get turbo -- its AUTOTYPE waits are emulated-time and would misfire.
      echo '[cpu]'; echo 'turbo=true'
  fi
  echo '[sdl]';    echo 'autolock=false'
  # LPT capture in BOTH modes. WS4 always prints to LPT1. A WS7 install prints
  # wherever its Redirect To field points -- often a file inside its own tree,
  # but an install aimed at LPT1 would otherwise print into an unconfigured
  # port, and DOSBox-X silently discards every byte sent there.
  echo '[parallel]'
  echo "parallel1=file append:$WORK/CAP/OUT.PRN timeout:5000"
  echo '[autoexec]'
  echo "mount c $WORK"
  echo 'c:'; echo 'cd \WS'
  if [ "$MODE" = ws4 ]; then
      # P, filename, then Esc -- the manual: "press the Esc key at any point"
      # to accept the defaults for every remaining prompt and print immediately.
      echo 'autotype -w 10 -p 0.4 p , d o c period w s enter , , esc'
      echo 'ws'
  else
      echo 'ws doc.ws /p /x'
  fi
  echo 'exit'
} > "$CONF"

# Baseline for the snapshot diff below -- taken BEFORE the emulator exists, so
# even instant output registers as new.
candidates() {
    find "$WORK/CAP" "$WORK/WS" -type f \
         \( -iname "*.PRN" -o -iname "*.PCL" -o -iname "*.ASC" -o -iname "*.TXT" -o -iname "*.PS" \) \
         -printf '%s\t%p\n' 2>/dev/null | sort
}
candidates > "$WORK/.pre"

echo "running WordStar ($MODE) ..." >&2
# `setsid` puts the emulator in its OWN process group, so cleanup below can
# signal the whole tree with one negative PID. Without it there is nothing to
# aim at: backgrounding a subshell gives you the SUBSHELL's pid, and killing
# that orphans everything inside it. See the cleanup comment for what that cost.
setsid env DISPLAY="${DISP:-}" dosbox-x -conf "$CONF" -nogui >/dev/null 2>&1 &
DBX=$!

# Wait for output to appear and stop growing, rather than guessing a duration.
#
# Output is detected by SNAPSHOT DIFF (path + size), never by mtime. DOSBox-X
# stamps DOS-written files from the emulated DOS clock at DOS granularity, and
# that timestamp can land fractionally BEFORE the conf written moments earlier
# on the host -- measured: output at 07:12:10.000, conf at 07:12:10.340. A
# `find -newer $CONF` therefore missed every WS7 print while the print itself
# succeeded. (Limit: a reprint that exactly matches a pre-existing file's path
# AND size is invisible; the per-run tree copy makes that effectively moot.)
FOUND=""
for _ in $(seq 1 100); do
    sleep 3
    # WS7's /x exits WordStar after printing and the autoexec `exit` closes the
    # emulator -- a clean exit means the print (and its final buffer flush) is
    # done, so take whatever appeared and stop waiting.
    if ! kill -0 "$DBX" 2>/dev/null; then
        FOUND=$(candidates | comm -13 "$WORK/.pre" - | head -1 | cut -f2)
        break
    fi
    CAND=$(candidates | comm -13 "$WORK/.pre" - | head -1 | cut -f2)
    if [ -n "$CAND" ] && [ -s "$CAND" ]; then
        A=$(stat -c%s "$CAND"); sleep 4; B=$(stat -c%s "$CAND")
        [ "$A" = "$B" ] && { FOUND="$CAND"; break; }
    fi
done
# SCREENSHOT BEFORE KILLING. WordStar reports its errors on screen and nowhere
# else, so the screenshot IS the diagnostic -- and a dead X server photographs
# black. This used to sit after the kill and worked only by accident: DOSBox-X
# ignores SIGTERM, so the emulator was still up when the camera clicked. Making
# the kill actually work (below) turned every failure screenshot black, which is
# how the ordering bug surfaced at all.
if [ -z "$FOUND" ] && [ -n "${DISP:-}" ] && command -v import >/dev/null; then
    DISPLAY="$DISP" import -window root "${OUT%.*}-screen.png" 2>/dev/null \
      && echo "screen saved to ${OUT%.*}-screen.png -- WordStar puts its errors there" >&2
fi

# Kill ONLY the emulator this run started -- and make sure it actually DIES.
#
# `pkill -x dosbox-x` would kill every dosbox on the machine, including a
# concurrent run of this same script: that happened, and the first run's cleanup
# killed the second mid-keystroke, leaving it stalled at the print prompt with a
# half-typed filename. So this signals one process GROUP, never a name.
#
# WHY THE ESCALATION IS NOT OPTIONAL (2026-08-03): this used to be a
# bare `kill "$DBX"`, and DOSBox-X IGNORES SIGTERM. Every run therefore leaked
# its emulator. Nineteen accumulated over one day, each still writing to its
# redirect, and they filled a 936 G root filesystem to zero bytes free -- which
# takes down every service on the box, not just this script. `kill` returning 0
# means the signal was delivered, never that the process died. Verify, then
# escalate to the signal nothing can catch.
kill -TERM -"$DBX" 2>/dev/null || kill -TERM "$DBX" 2>/dev/null || true
for _ in 1 2 3 4 5; do
    kill -0 "$DBX" 2>/dev/null || break
    sleep 1
done
if kill -0 "$DBX" 2>/dev/null; then
    kill -KILL -"$DBX" 2>/dev/null || kill -KILL "$DBX" 2>/dev/null || true
    sleep 1
fi
wait "$DBX" 2>/dev/null || true
if kill -0 "$DBX" 2>/dev/null; then
    echo "WARNING: emulator pid $DBX survived SIGKILL -- check for orphans" >&2
fi

if [ -z "$FOUND" ]; then
    echo "no print output produced." >&2
    echo "(the screen was captured above, BEFORE the emulator was killed)" >&2
    exit 1
fi

cp "$FOUND" "$OUT"
echo "wrote $OUT ($(stat -c%s "$OUT") bytes, from $(basename "$FOUND"))"
python3 - "$OUT" <<'PY'
import sys
d = open(sys.argv[1], 'rb').read()
ff = d.count(b'\x0c')
lines = d.split(b'\r\n')
pat = ''.join('T' if l.strip(b'\r\x14 ') else '.' for l in lines)
print(f'  {len(lines)} lines, {ff} form feeds')
if ff == 0:
    # WS4's "Use form feeds?" defaults to NO, so page breaks usually arrive as
    # a run of blank lines (bottom margin + top margin) rather than a 0x0C.
    import itertools
    runs, pos = [], 0
    for k, g in itertools.groupby(pat):
        n = len(list(g)); runs.append((k, n, pos)); pos += n
    # A gap only counts as a PAGE BREAK if text falls on both sides of it. The
    # run before the first text is the opening top margin, and the run after
    # the last text is trailing paper -- neither divides two pages.
    first = next((i for i, c in enumerate(pat) if c == 'T'), len(pat))
    last = len(pat) - 1 - next((i for i, c in enumerate(reversed(pat)) if c == 'T'), 0)
    big = [n for k, n, at in runs if k == '.' and n >= 8 and at > first and at < last]
    if big:
        print(f'  page gaps: {len(big)} interior runs of {sorted(set(big))} blank '
              f'lines => {len(big) + 1} pages (no form feeds; margins print as blanks)')
PY
