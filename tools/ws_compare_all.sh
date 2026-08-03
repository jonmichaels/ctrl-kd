#!/usr/bin/env bash
# Compare OUR printed render against live WordStar, for a whole folder.
#
# tools/wordstar_harness.sh prints ONE document. This runs it over a directory
# and diffs each result against our own output, so "does the converter still
# agree with WordStar?" is one command instead of a document-at-a-time chore.
#
# It is the companion to tools/parity_gauntlet.py, and answers a different
# question:
#   * the gauntlet  compares against print-to-disk output that SURVIVED from the
#                   period -- ground truth, but only for documents that happen
#                   to have a matching printout.
#   * this script   generates the comparison by running WordStar NOW, so it
#                   works for ANY document, including single-page ones and poems
#                   where no historical printout exists.
#
# Poems are the sharpest test here. A soft return where the next word WOULD have
# fit is a deliberate break, not word wrap, and telling those apart is the
# hardest judgement the line pass makes. A poem's every line is that judgement.
#
# Comparison is on STRIPPED text, line for line. A live WordStar install applies
# its own left offset and its own printer driver, so absolute indentation is a
# property of the install, not of the document -- see WORDSTAR-HARNESS.md.
#
# USAGE
#   tools/ws_compare_all.sh <ws-dir> <docs-dir> [ws4|ws7]
#
# Neither WordStar nor any document ships with this repo; both are arguments.
set -euo pipefail

WSDIR=${1:-}; DOCS=${2:-}; MODE=${3:-ws4}
HERE=$(cd "$(dirname "$0")" && pwd)
[ -d "${WSDIR:-}" ] && [ -d "${DOCS:-}" ] || {
    sed -n '/^# USAGE/,/^set -e/p' "$0" | head -4; exit 2; }

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
pass=0; fail=0; skip=0

printf '%-16s %6s %6s  %s\n' file ours ws verdict
for doc in "$DOCS"/*; do
    [ -f "$doc" ] || continue
    name=$(basename "$doc")
    # One retry: emulator startup is occasionally flaky under repeated runs,
    # and a transient empty result would otherwise read as a verdict.
    if ! "$HERE/wordstar_harness.sh" "$MODE" "$WSDIR" "$doc" \
            "$WORK/$name.prn" >/dev/null 2>&1; then
        sleep 2
        "$HERE/wordstar_harness.sh" "$MODE" "$WSDIR" "$doc" \
            "$WORK/$name.prn" >/dev/null 2>&1 || true
    fi
    if [ ! -s "$WORK/$name.prn" ]; then
        # NOT a pass. "We did not get an answer" is not "it agrees" -- counting
        # it as anything but a failure is how a real disagreement would hide.
        printf '%-16s %6s %6s  NO OUTPUT after retry (counts as FAIL)\n' "$name" - -
        skip=$((skip + 1)); continue
    fi
    python3 - "$doc" "$WORK/$name.prn" "$name" <<'PY' && pass=$((pass+1)) || fail=$((fail+1))
import sys, os, difflib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src')
                if '__file__' in dir() else 'src')
sys.path.insert(0, 'src')
from ctrlkd import core
from ctrlkd.pdf import _doc_to_pagelines

src, prn, name = sys.argv[1], sys.argv[2], sys.argv[3]


def trimmed(lines):
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return [l.strip() for l in lines]


ws = trimmed([l.rstrip(b'\r').decode('latin-1', 'replace')
              for l in open(prn, 'rb').read().split(b'\r\n')])
doc = core.parse_ws(open(src, 'rb').read())
ours = trimmed([''.join(t for t, _ in ln).rstrip()
                for pg in _doc_to_pagelines(doc, True) for ln in pg])

if ours == ws:
    print(f'{name:<16} {len(ours):6} {len(ws):6}  MATCH')
    sys.exit(0)

ratio = difflib.SequenceMatcher(None, ours, ws).ratio()
print(f'{name:<16} {len(ours):6} {len(ws):6}  {ratio * 100:5.1f}%')
shown = 0
for line in difflib.unified_diff(ws, ours, 'wordstar', 'ours', lineterm='', n=0):
    if line.startswith(('---', '+++', '@@')):
        continue
    print(f'{"":16} {line[:70]}')
    shown += 1
    if shown >= 6:
        print(f'{"":16} ...')
        break
sys.exit(1)
PY
done

echo
echo "$pass match, $fail differ, $skip produced no output."
# skips fail the run deliberately: an unanswered comparison is not a passing one
[ "$fail" -eq 0 ] && [ "$skip" -eq 0 ]
