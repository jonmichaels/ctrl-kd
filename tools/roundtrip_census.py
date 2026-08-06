#!/usr/bin/env python3
"""Round-trip census: emit_ws(parse(x)) == x, measured over the real corpus.

Tasks #20/#21. For every file under the archive that detects as a WordStar
DOCUMENT (ws4 / ws5+), parse it, serialize it back with ctrlkd.writer, and
compare byte-for-byte. Reports identical/differs per file (first-divergence
offset with hex context), plus a category histogram of the failures --
"preservation is testable today"; this is the test.

READ-ONLY over the archive; nothing is copied anywhere. Real corpus content
never enters the repo -- the census prints offsets and a few hex bytes, not
text.

USAGE
-----
    .venv/bin/python tools/roundtrip_census.py [ROOT] [-v]

ROOT defaults to the Sawyer WS7 archive path below. -v lists every divergent
file with its hex context (default lists one example per category).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ctrlkd import core                                     # noqa: E402
from ctrlkd.writer import emit_ws, WriteError               # noqa: E402

DEFAULT_ROOT = '/mnt/md0/archives/preservation-tools/sawyer-ws7/'


def first_divergence(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n if len(a) != len(b) else -1


def hex_context(orig: bytes, out: bytes, off: int, width: int = 12) -> str:
    lo = max(0, off - 4)
    o = orig[lo:off + width].hex(' ')
    w = out[lo:off + width].hex(' ')
    return f'orig[{lo}:]= {o}\n        ours[{lo}:]= {w}'


def classify(orig: bytes, out: bytes, off: int, doc) -> str:
    """A NAME for why this file diverged -- judged at the first divergent
    byte, which is where the writer's story and the file's part company.
    Heuristic by nature; the point is an honest histogram, not a verdict."""
    era = (doc.roundtrip or {}).get('era', doc.meta.get('era'))
    ob = orig[off] if off < len(orig) else None
    wb = out[off] if off < len(out) else None
    if ob is None:
        return 'ours longer (extra bytes emitted)'
    if era in ('ws4', 'ws3'):
        if ob >= 0x80 or (wb is not None and wb >= 0x80):
            return 'ws4 high-bit flags'
        return 'ws4 other'
    if ob == 0x1D or wb == 0x1D:
        return 'block re-serialization'
    if ob == 0x1A:
        return 'trailing ^Z / tail'
    if ob == 0xA0:
        return 'soft space (A0)'
    if ob in (0x1E, 0x1F, 0x0F):
        return 'soft hyphen / binding space'
    if ob in (0x8D, 0x8A, 0x0D, 0x0A) or (wb in (0x8D, 0x8A, 0x0D, 0x0A)):
        return 'line-break bytes'
    if ob == 0x1B or wb == 0x1B:
        return 'extended-char escape'
    if ob < 0x20:
        return f'dropped control 0x{ob:02x}'
    if ob >= 0x80:
        return 'bare high byte'
    return 'other'


def census(root: str, verbose: bool = False):
    rows = []          # (relpath, size, status, off, category, context)
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            try:
                with open(path, 'rb') as fh:
                    data = fh.read()
            except OSError:
                continue
            if not data:
                continue
            det = core.detect(data)
            if det['variant'] not in ('ws4', 'ws5+'):
                continue
            rel = os.path.relpath(path, root)
            try:
                doc = core.parse_ws(data)
                out = emit_ws(doc)
            except WriteError as e:
                rows.append((rel, len(data), 'refused', -1, str(e), ''))
                continue
            except Exception as e:                          # honest census:
                rows.append((rel, len(data), 'error', -1,   # a crash is data
                             f'{type(e).__name__}: {e}', ''))
                continue
            if out == data:
                rows.append((rel, len(data), 'identical', -1, '', ''))
            else:
                off = first_divergence(data, out)
                cat = classify(data, out, off, doc)
                rows.append((rel, len(data), 'differs', off, cat,
                             hex_context(data, out, off)))
    return rows


def report(rows, verbose: bool):
    total = len(rows)
    ident = [r for r in rows if r[2] == 'identical']
    diff = [r for r in rows if r[2] == 'differs']
    other = [r for r in rows if r[2] in ('refused', 'error')]
    print(f'round-trip census: {len(ident)} of {total} detected WordStar '
          f'files byte-identical ({100 * len(ident) // max(1, total)}%)')
    # The honest split: the archive's AUTHORED documents all carry .WS/.ws;
    # the rest of the detections are dominated by detect()'s false positives
    # on binaries (fonts, EXEs, printer overlays), which no writer can be
    # expected to round-trip through a document parser.
    ws = [r for r in rows if r[0].upper().endswith('.WS')]
    ws_ok = [r for r in ws if r[2] == 'identical']
    rest = total - len(ws)
    rest_ok = len(ident) - len(ws_ok)
    print(f'  .WS documents:            {len(ws_ok)} of {len(ws)} identical')
    print(f'  other detected files:     {rest_ok} of {rest} identical '
          '(mostly detect() false positives on binaries)')
    print()
    hist = {}
    for r in diff + other:
        hist.setdefault(r[4], []).append(r)
    if hist:
        print(f'{"category":<38} {"files":>5}   example (first divergence)')
        print('-' * 100)
        for cat, rs in sorted(hist.items(), key=lambda kv: -len(kv[1])):
            ex = rs[0]
            where = f'@{ex[3]}' if ex[3] >= 0 else ''
            print(f'{cat:<38} {len(rs):>5}   {ex[0]} {where}')
        print()
    if verbose:
        for r in sorted(diff, key=lambda r: r[0]):
            print(f'{r[0]}  ({r[1]} bytes)  diverges @{r[3]}  [{r[4]}]')
            print(f'        {r[5]}')
        for r in sorted(other, key=lambda r: r[0]):
            print(f'{r[0]}  ({r[1]} bytes)  {r[2]}: {r[4]}')
    else:
        print('(-v lists every divergent file with hex context)')


def main(argv):
    verbose = '-v' in argv
    args = [a for a in argv if a != '-v']
    root = args[0] if args else DEFAULT_ROOT
    if not os.path.isdir(root):
        print(f'census: corpus not present at {root}', file=sys.stderr)
        return 2
    rows = census(root, verbose)
    report(rows, verbose)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
