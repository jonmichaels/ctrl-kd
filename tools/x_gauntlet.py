#!/usr/bin/env python3
"""x_gauntlet.py -- X-POSITION regression gate for Printed-mode PDF output.

WHY THIS EXISTS
---------------
parity_gauntlet.py compares the LINE STREAM and PAGINATION only -- by its own
docstring it deliberately never compares x, because for THAT gate's job
(printstream vs. document) a difference in x is not necessarily an error.
This gate exists for a different question: a change to how WordStar tabs are
positioned is about to move x coordinates across much of the corpus, and there
is currently no instrument that would notice. This is that instrument. It has
one baseline -- its own prior run -- and one job: tell someone, precisely,
which of a fixed set of documents moved, on which page, on which line, by how
many points, when they change the tab code.

WHAT IT DOES
------------
1. Renders each fixture .WS to a Printed-mode PDF exactly as the CLI would
   (core.parse + pdf.emit_pdf(doc, mode='printed'), no options -- same call
   tools/fidelity_gate.py's render_engine_pdf makes).
2. Parses the PDF's own content streams BY HAND (plain PDF 1.4, no
   dependency -- confirmed by reading pdf.py's _emit_pdf_inner, same
   approach tools/fidelity_gate.py already uses). Generalised one step
   further than that tool's regex: every text-showing op in pdf.py reduces,
   inside its own BT..ET block, to a Tf, an optional Tz, a position (Td for
   every ordinary span; Tm only for a Symbol-face italic run --
   _symbol_style_op), and exactly one Tj. Extracting structurally (last
   Td/Tm before the Tj, not one fixed operator sequence) means an inserted
   Tr (the same function's bold-stroke op) never breaks capture -- verified
   against -SCREEN.WS's styled Symbol run, the one fixture that exercises
   both the Td and the Tm branch of _symbol_style_op in the same block.
3. Groups ops into visual LINES by y-coordinate: pdf.py emits one output
   line's spans consecutively at the SAME y and never revisits a y within a
   page (_line_ops_printed is called once per PageLine), so "a new y value
   in emission order" IS a new printed line, and counting those transitions
   reproduces the number a human would read off the page.
4. Snapshots {doc: {pages: [{lines: [{y, spans: [{x, h, n}, ...]}]}]}} to
   stable JSON -- sorted keys, fixed float rounding, no timestamps, no
   absolute paths.

   THE SNAPSHOT NEVER STORES A SPAN'S ACTUAL TEXT, ONLY A HASH (`h`, sha1
   truncated to 12 hex) AND ITS LENGTH (`n`). parity_gauntlet.py's own rule
   is "REAL DOCUMENTS NEVER ENTER THIS REPO" -- the corpus stays outside
   the checkout for exactly the reason that these fixtures are real 1992
   documents (several of them Robert Sawyer's own copyrighted short
   fiction, bundled with the WS7 archive for demo purposes, not licensed
   for redistribution as a github-hosted derivative). A per-span x/text
   snapshot with the text left in clear would, committed, amount to
   checking in near-total transcriptions of "Lying", "Darkness", "Your Way
   or Mine", -README's essay, etc. Hashing preserves every bit of the
   gate's REAL job -- did this span's identity survive, and if so did its
   x move -- with zero prose entering git history. `check` mode still
   prints real excerpts to the terminal (it re-renders the CURRENT fixture
   tree live, off-disk, every run) -- only the committed JSON is redacted.
5. `check` mode re-renders the fixtures fresh, hashes the same way, and
   diffs against the stored (already-hashed) snapshot -- reporting every
   span whose x moved or whose hash changed: `page 5 line 12: x 157.3 ->
   180.1  "Shading 85%"` (the quoted text is always the FRESH render's own
   string, never anything read back out of the snapshot file), plus a
   per-document and grand summary.

A fixture that fails to render (missing resource, parse error) is recorded
as SKIPPED with the exception text and the run continues -- it never aborts
the whole gauntlet. (In practice: `emit_pdf(doc, mode='printed')` with no
options defaults `pictures` to 'off', so a fixture referencing a missing
.PIX file -- -SCREEN/PREVIEW -> WORDSTAR.PIX -- never even attempts to open
it; nothing here goes looking for the image at all, so a missing one has
nothing to break. The try/except stays anyway for whatever else could
raise.)

FIXTURES
--------
A fixed manifest (`FIXTURES` below), same convention as fidelity_gate.py's
own `PRIVATE_DOCS` dict -- named documents resolved against a root, not
"whatever happens to be in a directory". Two groups:

  TAB_FIXTURES (14) -- every WS7 sample document named as containing a
  type-9 tab block: OLDTIMES, VERSIONS, LJ6DTP, -README, WORDSTAR, STRENGTH,
  WARPRAYR, CONVERT, FORMFEED, LYING, PREVIEW, SCRIPT, YOURWAY.
  These are exactly the documents the coming tab-position change can move.

  CONTROL_FIXTURES (3) -- chosen from the OTHER .WS files in the same
  directory, verified (by walking the 0x1D symmetric-block framing core.py
  uses, core.py:2728-2751) to carry ZERO type-9 blocks:
    * BOXES.WS   -- heavy box-drawing/graphics content (_graphic_ops path),
                    a structurally different render path from prose; if a
                    tab change ever leaks into graphics positioning, this
                    is what would show it first.
    * -SCREEN.WS -- plain prose PLUS a styled-Symbol demo line (the one
                    fixture exercising _symbol_style_op's Tm branch) and a
                    dangling WORDSTAR.PIX reference -- exercises the parser
                    edge cases in this tool itself, not just the corpus.
    * OCAPTAIN.WS -- short, plain, tag-free prose; the simplest possible
                    "nothing here should ever move" control.
  If any of these three move when only the tab code changed, that change
  reached further than tabs and the run should stop, not be explained away.

USAGE
-----
    python3 tools/x_gauntlet.py capture [root] -o <snapshot.json>
    python3 tools/x_gauntlet.py check   [root] <snapshot.json> [-v]

With no explicit `root`, each FIXTURES name is resolved against the two
corpus env vars (D3, 2026-09-03; read-only, never modified by this tool):
CTRLKD_SAWYER_ARCHIVE (tried directly and under its ARTICLES/ subdirectory
-- most TAB_FIXTURES/CONTROL_FIXTURES names are real Sawyer-archive
documents) and CTRLKD_PRIVATE_CORPUS's own pd-samples/authored/
subdirectory (the handful of authored names: WARPRAYR, LYING, OCAPTAIN). A
name missing from every candidate is recorded SKIPPED, not fatal. Pass an
explicit `root` to run the same fixed manifest against one flat directory
instead (e.g. a staging directory holding all of FIXTURES together).

REAL DOCUMENTS NEVER ENTER THIS REPO -- same rule as parity_gauntlet.py; the
corpus lives outside the checkout, and the one artifact this tool DOES
commit (the snapshot) carries hashes, not text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ctrlkd import core, pdf as pdfmod  # noqa: E402

# ------------------------------------------------------------- fixture list
# See module docstring's FIXTURES section for why each name is here.
# The WS7 samples are not in this public repo and neither is the path to
# them. One var per corpus, one shape each (D3, 2026-09-03) -- see
# resolve_fixture_path below for how a bare name is found under either.
SAWYER_ENV = 'CTRLKD_SAWYER_ARCHIVE'
PRIVATE_CORPUS_ENV = 'CTRLKD_PRIVATE_CORPUS'

TAB_FIXTURES = [
    'OLDTIMES.WS', 'VERSIONS.WS', 'LJ6DTP.WS', '-README.WS', 'WORDSTAR.WS',
    'STRENGTH.WS', 'WARPRAYR.WS', 'CONVERT.WS', 'FORMFEED.WS', 'LYING.WS',
    'PREVIEW.WS', 'SCRIPT.WS', 'YOURWAY.WS',
]
CONTROL_FIXTURES = ['BOXES.WS', '-SCREEN.WS', 'OCAPTAIN.WS']
FIXTURES = TAB_FIXTURES + CONTROL_FIXTURES

# --------------------------------------------------------------- PDF parsing
# Same technique as tools/fidelity_gate.py (hand-rolled, no dependency;
# content streams are plain, not Flate-compressed, but FlateDecode is
# honoured if a future emitter change declares it).
_OBJ_RE = re.compile(rb'(\d+)\s+0\s+obj\s*(.*?)\s*endobj', re.DOTALL)
_STREAM_RE = re.compile(rb'stream\r?\n(.*?)\r?\nendstream', re.DOTALL)

# One BT..ET block, taken whole -- see module docstring point 2 for why the
# position/Tj is pulled out of the block structurally rather than matched by
# one fixed operator sequence (an inserted Tr must never break capture).
_BT_BLOCK_RE = re.compile(rb'BT (.*?) ET', re.DOTALL)
_TD_RE = re.compile(rb'(-?[\d.]+)\s+(-?[\d.]+)\s+Td')
_TM_RE = re.compile(
    rb'(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+'
    rb'(-?[\d.]+)\s+(-?[\d.]+)\s+Tm')
_TJ_RE = re.compile(rb'\((?P<text>(?:[^()\\]|\\.)*)\)\s*Tj')
_UNESC_RE = re.compile(rb'\\(.)')


def _unescape_pdf_text(raw: bytes) -> str:
    def rep(m):
        c = m.group(1)
        return c if c in b'()\\' else b'\\' + c
    return _UNESC_RE.sub(rep, raw).decode('cp1252', 'replace')


def parse_pdf_objects(data: bytes) -> dict:
    return {int(m.group(1)): m.group(2) for m in _OBJ_RE.finditer(data)}


def _dict_ref(body: bytes, key: str):
    m = re.search(re.escape(key.encode()) + rb'\s+(\d+)\s+0\s+R', body)
    return int(m.group(1)) if m else None


def _stream_bytes(objs: dict, num: int) -> bytes:
    body = objs[num]
    m = _STREAM_RE.search(body)
    raw = m.group(1)
    if b'/FlateDecode' in body:
        import zlib
        raw = zlib.decompress(raw)
    return raw


def extract_page_contents(pdf_bytes: bytes) -> list:
    """[content_bytes, ...] in document page order, from the /Pages
    object's own /Kids array (not object-number order -- an emitter
    implementation detail this tool must not depend on)."""
    objs = parse_pdf_objects(pdf_bytes)
    pages_num = next(n for n, b in objs.items()
                     if re.search(rb'/Type\s*/Pages\b', b))
    kids_m = re.search(rb'/Kids\s*\[(.*?)\]', objs[pages_num], re.DOTALL)
    kid_nums = [int(x) for x in re.findall(rb'(\d+)\s+0\s+R', kids_m.group(1))]
    out = []
    for pnum in kid_nums:
        body = objs[pnum]
        cnum = _dict_ref(body, '/Contents')
        out.append(_stream_bytes(objs, cnum) if cnum is not None else b'')
    return out


def parse_text_ops(content: bytes) -> list:
    """[(x, y, text), ...] in emission order -- one entry per text-showing
    operation (one per BT..ET block; pdf.py never emits more than one Tj
    inside a block). A block with no position op or no Tj (shouldn't occur
    for a real text-showing block) is skipped rather than guessed at."""
    ops = []
    for block in _BT_BLOCK_RE.finditer(content):
        body = block.group(1)
        tj = None
        for m in _TJ_RE.finditer(body):
            tj = m  # a block carries exactly one Tj in this emitter
        if tj is None:
            continue
        td = tm = None
        for m in _TD_RE.finditer(body):
            td = m
        for m in _TM_RE.finditer(body):
            tm = m
        # Whichever position op is present; Td and Tm never both occur in
        # the same block (_symbol_style_op picks one or the other).
        if td is not None:
            x, y = float(td.group(1)), float(td.group(2))
        elif tm is not None:
            x, y = float(tm.group(5)), float(tm.group(6))
        else:
            continue
        ops.append((x, y, _unescape_pdf_text(tj.group('text'))))
    return ops


# ------------------------------------------------------------------ engine
def render_pdf(ws_path: str) -> bytes:
    """The document rendered exactly as the CLI's --mode printed does:
    core.parse (auto-detect, cp437 default) then
    pdf.emit_pdf(doc, mode='printed') with no options -- same call
    tools/fidelity_gate.py's render_engine_pdf makes. No `pictures` option
    is passed, so `pictures` defaults to 'off' inside emit_pdf and no PIX
    resource is ever opened for this gate (confirmed by reading emit_pdf/
    _doc_to_pagelines/_body_stream_printed: pix_results is only consulted
    when pictures in ('embed','export'), and the CLI is the only caller
    that ever sets that). Any OTHER render failure (parse error,
    unhandled construct) is left to propagate -- the caller records it as
    a skip."""
    data = open(ws_path, 'rb').read()
    doc = core.parse(data)
    return pdfmod.emit_pdf(doc, mode='printed')


def snapshot_doc(ws_path: str) -> dict:
    """{'ok': True, 'pages': [...]} or {'ok': False, 'error': str}.

    pages: [{'lines': [{'y': float, 'spans': [{'x': float, 'text': str}, ..]}
    ]}, ...]. Lines are grouped by a CHANGE in y in emission order (see
    module docstring point 3) -- not by rounding/sorting, so the snapshot
    reflects exactly what the renderer emitted, in the order it emitted it.

    This is the FULL, in-memory form -- text included. It is never written
    to disk as-is; see `redact_doc` for the form that gets committed."""
    try:
        pdf_bytes = render_pdf(ws_path)
    except Exception as e:                        # noqa: BLE001 -- recorded
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    pages = []
    for content in extract_page_contents(pdf_bytes):
        ops = parse_text_ops(content)
        lines, cur_y, cur_spans = [], None, []
        for x, y, text in ops:
            if cur_y is None or y != cur_y:
                if cur_spans:
                    lines.append({'y': round(cur_y, 2), 'spans': cur_spans})
                cur_y, cur_spans = y, []
            cur_spans.append({'x': round(x, 2), 'text': text})
        if cur_spans:
            lines.append({'y': round(cur_y, 2), 'spans': cur_spans})
        pages.append({'lines': lines})
    return {'ok': True, 'pages': pages}


def _span_hash(text: str) -> str:
    return hashlib.sha1(text.encode('utf-8', 'surrogateescape')).hexdigest()[:12]


def redact_doc(doc_snap: dict) -> dict:
    """`snapshot_doc`'s result with every span's `text` replaced by `h`
    (its hash) and `n` (its length) -- see module docstring point 4. This
    is the ONLY form this tool ever writes to disk."""
    if not doc_snap.get('ok'):
        return doc_snap
    pages = []
    for page in doc_snap['pages']:
        lines = []
        for line in page['lines']:
            spans = [{'x': s['x'], 'h': _span_hash(s['text']), 'n': len(s['text'])}
                     for s in line['spans']]
            lines.append({'y': line['y'], 'spans': spans})
        pages.append({'lines': lines})
    return {'ok': True, 'pages': pages}


# --------------------------------------------------------------- resolution
def resolve_fixture_path(name: str, root: str = None) -> str:
    """Absolute path to a FIXTURES name, or None if not found anywhere.

    `root`, if given, is checked first as ONE FLAT DIRECTORY holding every
    fixture together (back-compat with a staged/merged checkout) -- same
    behavior this tool always had. With no `root` (the normal case), each
    name is resolved against the two corpus env vars directly, per the
    corpus's own known shape: CTRLKD_SAWYER_ARCHIVE (tried at its top level
    and under ARTICLES/, since most of these names are real Sawyer-archive
    documents) then CTRLKD_PRIVATE_CORPUS's own pd-samples/authored/
    subdirectory (the authored names)."""
    if root:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    sawyer_root = os.environ.get(SAWYER_ENV)
    if sawyer_root:
        for candidate in (os.path.join(sawyer_root, name),
                          os.path.join(sawyer_root, 'ARTICLES', name)):
            if os.path.isfile(candidate):
                return candidate
    private_corpus = os.environ.get(PRIVATE_CORPUS_ENV)
    if private_corpus:
        candidate = os.path.join(private_corpus, 'pd-samples', 'authored', name)
        if os.path.isfile(candidate):
            return candidate
    return None


# --------------------------------------------------------------- snapshot
def capture_full(root: str = None) -> dict:
    """{name: snapshot_doc(...)} (FULL, in-memory form -- text included) for
    every name in FIXTURES, resolved via `resolve_fixture_path`. A name
    that resolves nowhere is recorded {'ok': False, 'error': 'not found
    under any corpus root'} -- SKIPPED, same as any other render failure,
    never fatal to the run."""
    out = {}
    for name in FIXTURES:
        path = resolve_fixture_path(name, root)
        if path is None:
            out[name] = {'ok': False, 'error': 'not found under any corpus root'}
            continue
        out[name] = snapshot_doc(path)
    return out


def _fmt_diff(name, page_no, line_no, x0, x1, text):
    return (f'{name:12} page {page_no:2} line {line_no:3}: '
            f'x {x0:8.2f} -> {x1:8.2f}  {text!r}')


def compare_doc(name, before: dict, after_full: dict) -> tuple:
    """(moved_count, report_lines) for one document. `before` is the
    REDACTED (hash-only) stored form; `after_full` is the FULL, freshly
    rendered form -- hashed on the fly here for comparison, but its real
    text is what gets printed in a diff line (see module docstring point
    5: the snapshot is never the source of displayed text)."""
    lines_out = []
    if not before.get('ok') or not after_full.get('ok'):
        if before.get('ok') != after_full.get('ok'):
            lines_out.append(
                f'{name:12} STATUS CHANGED: '
                f'{"ok" if before.get("ok") else before.get("error")}'
                f' -> {"ok" if after_full.get("ok") else after_full.get("error")}')
            return (1, lines_out)
        return (0, lines_out)

    moved = 0
    bp, ap = before['pages'], after_full['pages']
    for pi in range(max(len(bp), len(ap))):
        if pi >= len(bp):
            lines_out.append(f'{name:12} page {pi + 1:2}: PAGE ADDED')
            moved += 1
            continue
        if pi >= len(ap):
            lines_out.append(f'{name:12} page {pi + 1:2}: PAGE REMOVED')
            moved += 1
            continue
        bl, al = bp[pi]['lines'], ap[pi]['lines']
        for li in range(max(len(bl), len(al))):
            if li >= len(bl):
                texts = [s['text'] for s in al[li]['spans']]
                lines_out.append(f'{name:12} page {pi + 1:2} line {li + 1:3}: '
                                 f'LINE ADDED {texts!r}')
                moved += 1
                continue
            if li >= len(al):
                lines_out.append(f'{name:12} page {pi + 1:2} line {li + 1:3}: '
                                 f'LINE REMOVED ({len(bl[li]["spans"])} spans)')
                moved += 1
                continue
            bs, as_ = bl[li]['spans'], al[li]['spans']
            for si in range(max(len(bs), len(as_))):
                if si >= len(bs):
                    lines_out.append(f'{name:12} page {pi + 1:2} line {li + 1:3}: '
                                     f'SPAN ADDED {as_[si]["text"]!r}')
                    moved += 1
                    continue
                if si >= len(as_):
                    lines_out.append(f'{name:12} page {pi + 1:2} line {li + 1:3}: '
                                     f'SPAN REMOVED (hash {bs[si]["h"]})')
                    moved += 1
                    continue
                b, a = bs[si], as_[si]
                a_hash = _span_hash(a['text'])
                if a_hash != b['h']:
                    lines_out.append(
                        f'{name:12} page {pi + 1:2} line {li + 1:3}: '
                        f'TEXT CHANGED (was {b["n"]} chars, hash {b["h"]}) '
                        f'-> {a["text"]!r} (x {b["x"]:.2f} -> {a["x"]:.2f})')
                    moved += 1
                elif abs(b['x'] - a['x']) > 0.05:
                    lines_out.append(_fmt_diff(
                        name, pi + 1, li + 1, b['x'], a['x'], a['text']))
                    moved += 1
    return (moved, lines_out)


def check(root: str, snapshot_path: str, verbose=False) -> int:
    before = json.load(open(snapshot_path))
    after_full = capture_full(root)
    any_diff = False
    docs_moved = []
    for name in sorted(set(before) | set(after_full)):
        if name not in after_full:
            print(f'{name:12} MISSING from current run (was in snapshot)')
            any_diff = True
            continue
        if name not in before:
            print(f'{name:12} NEW (not in snapshot)')
            any_diff = True
            continue
        moved, lines_out = compare_doc(name, before[name], after_full[name])
        if moved:
            any_diff = True
            docs_moved.append((name, moved))
            for ln in lines_out:
                print(ln)
        status = 'ok' if after_full[name].get('ok') else 'SKIPPED'
        n_moved_str = f'{moved} diffs' if moved else 'unchanged'
        print(f'{name:12} [{status}] {n_moved_str}')
    print()
    if docs_moved:
        print(f'{len(docs_moved)}/{len(after_full)} documents moved:')
        for name, moved in docs_moved:
            print(f'  {name}: {moved} diffs')
    else:
        print(f'0/{len(after_full)} documents moved -- x-position gate CLEAN.')
    return 1 if any_diff else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)

    cap = sub.add_parser('capture')
    cap.add_argument('root', nargs='?', default=None,
                     help='One flat directory holding every FIXTURES name '
                     '(optional; default resolves each name against '
                     'CTRLKD_SAWYER_ARCHIVE / CTRLKD_PRIVATE_CORPUS instead)')
    cap.add_argument('-o', '--out', required=True)

    chk = sub.add_parser('check')
    chk.add_argument('root', nargs='?', default=None,
                     help='Same as capture\'s `root`')
    chk.add_argument('snapshot')
    chk.add_argument('-v', '--verbose', action='store_true')

    a = ap.parse_args(argv[1:])
    if a.cmd == 'capture':
        full = capture_full(a.root)
        n_ok = sum(1 for v in full.values() if v.get('ok'))
        n_pages = sum(len(v['pages']) for v in full.values() if v.get('ok'))
        n_spans = sum(len(l['spans']) for v in full.values() if v.get('ok')
                     for p in v['pages'] for l in p['lines'])
        redacted = {n: redact_doc(v) for n, v in full.items()}
        json.dump(redacted, open(a.out, 'w'), indent=1, sort_keys=True)
        print(f'captured {len(full)} fixtures ({n_ok} ok, '
              f'{len(full) - n_ok} skipped), {n_pages} pages, '
              f'{n_spans} text-showing ops -> {a.out} (hashed, no source '
              f'text written)')
        for name, v in sorted(full.items()):
            if not v.get('ok'):
                print(f'  SKIPPED {name}: {v["error"]}')
        return 0
    return check(a.root, a.snapshot, a.verbose)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
