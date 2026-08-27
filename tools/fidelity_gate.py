#!/usr/bin/env python3
"""fidelity_gate.py -- Round 26, "numbers for the machine" fidelity gate.

WHY THIS EXISTS
---------------
The ruled fidelity gate has two sides: what a human eye judges from a
rendered page, and what a ruler measures. This is the ruler. It compares
ctrl-kd's own Printed PDF output against real WordStar 7 print captures
(PCL5 -> measurements.json, tools/pcl_render.py's own ground-truth
extraction) PURELY on coordinates -- WS7's decipoint positions from its
own printer commands versus the engine's own PDF Td positions. No pixels,
no glyph rendering, no human judgment anywhere in this file.

WHAT IT DOES
------------
1. Renders a WordStar `.WS` source with the engine's own library API
   (`pdf.emit_pdf(doc, mode='printed')`, letter, default options -- the
   same call `tests/test_printed_fidelity.py` exercises).
2. Parses the resulting PDF's content streams BY HAND (no dependency: the
   objects are plain PDF 1.4, content streams are NOT Flate-compressed in
   this emitter -- confirmed by reading pdf.py's own `_emit_pdf_inner` --
   but FlateDecode is still honoured if a stream declares it, so the
   parser survives a future emitter change). Every text-drawing operation
   pdf.py writes has one shape: `BT /Fn SIZE Tf [SCALE Tz ]RISE Ts X Y Td
   (TEXT) Tj ET` -- one regex covers the whole emitter (headers/footers,
   footnotes, line numbers, and the main body all share it; verified
   against every `ops.append(b'BT ...` call site in pdf.py).
3. Splits each engine text run into WORD-granular positions using the
   project's OWN AFM metrics (`ctrlkd.afm.string_width_pt`) and the run's
   OWN Tz scale (carried across ops within a page's content stream,
   exactly as pdf.py's `tz_state` does) -- so a Courier run holding
   several words gets the same per-word x pdf.py itself computed, without
   re-deriving pdf.py's internal HMI/pitch state.
4. Matches engine words to WS7 chunks per page, in reading/emission
   order, via difflib's sequence alignment on the TEXT ONLY -- this is
   honest about disagreement: a word that doesn't literally match on
   both sides is reported unmatched rather than paired by position.
5. Computes per-matched-pair deltas (dx, dy, size, font-class agreement),
   derives the FRAME OFFSET (median dx/dy -- the coordinate-frame
   constant between PCL origin and PDF origin, which contains the real
   top/left margin discrepancy) per page and per doc, and reports the
   residual after removing it.

COORDINATE CONVENTION (read this before reading any number below)
-------------------------------------------------------------------
Both sides are converted to the SAME frame: origin at the page's own
top-left, x rightward, y DOWNWARD (PCL's native convention, and the more
legible one for "margin" reasoning). WS7: x_pt = x_decipoints/10,
y_top_pt = y_decipoints/10 (PCL's ESC&a#V positions the text BASELINE,
per the HP PCL5 reference). Engine: x_pt = Td x (PDF's origin is already
the page's left edge); y_top_pt = mediabox_height - Td y (PDF's origin is
bottom-left, so flipped to match).

    dx = engine_x_pt  - ws7_x_pt
    dy = engine_y_top_pt - ws7_y_top_pt

Positive dx: the engine places the word FARTHER RIGHT than WS7 did.
Positive dy: the engine places the baseline FARTHER FROM THE TOP (i.e. a
LOOSER top margin) than WS7 did. Negative dy: a TIGHTER top margin than
WS7's -- the direction the field report names.

No PCL logical-page offset is assumed anywhere in this file. The frame
offset is measured, never hardcoded; ESC&l...E top-margin commands found
in the raw .pcl are surfaced separately, as corroborating evidence only.

USAGE
-----
    python3 tools/fidelity_gate.py DOC --ws PATH.WS --measurements PATH.json \
        [--pcl PATH.pcl] [--out-json PATH]

    # or, using the checked-in corpus layout + env vars for the private one:
    python3 tools/fidelity_gate.py --doc LYING --out-json /tmp/lying.json

`--doc NAME` resolves NAME.WS from the checked-in pd-samples/authored tree
(or, for SAWYER/VERSIONS, from $CTRLKD_SAWYER_ROOT/NAME.WS -- a private
corpus path that never enters this repo; the doc is SKIPPED, not errored,
when that env var is unset) and NAME.measurements.json/.pcl from
$CTRLKD_WS7_PRINTS (required -- there is no built-in default path).

CAVEAT (dx experiment 2026-08-20): core.parse() auto-detect classifies
minimal plain-ASCII dot-command replica docs as 'printstream', which
bypasses _printed_left/_printed_size (fixed 72pt MARGIN / 12pt SIZE) and
yields a spurious constant frame dx. For replica experiments, call
core.parse_ws() directly or force-tag the doc.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import statistics
import sys
from collections import defaultdict

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
from ctrlkd import core, pdf as pdfmod, afm  # noqa: E402

DECIPT_PER_PT = 10.0

# Corpus roots come from the environment ONLY. They used to carry hardcoded
# absolute paths naming a particular machine -- as published as any file.
AUTHORED_ROOT_ENV = 'CTRLKD_AUTHORED_ROOT'
DEFAULT_AUTHORED_ROOT = os.environ.get(AUTHORED_ROOT_ENV)
DEFAULT_WS7_PRINTS_ROOT = None
# The private corpus (Sawyer WS7 install tree): env var only, skip-when-
# absent. Values are paths RELATIVE to the root the env var names.
SAWYER_ROOT_ENV = 'CTRLKD_SAWYER_ROOT'
WS7_PRINTS_ENV = 'CTRLKD_WS7_PRINTS'
PRIVATE_DOCS = {
    'SAWYER': 'SAWYER.WS',
    'VERSIONS': 'VERSIONS.WS',
    '-README': '-README.WS',
    '-SCREEN': '-SCREEN.WS',
    'BOXES': 'BOXES.WS',
    'PREVIEW': 'PREVIEW.WS',
    'SCRIPT': 'ARTICLES/SCRIPT.WS',
    'LJ6DTP': 'LJ6DTP.WS',
}


# --------------------------------------------------------------- PDF parsing
_OBJ_RE = re.compile(rb'(\d+)\s+0\s+obj\s*(.*?)\s*endobj', re.DOTALL)
_STREAM_RE = re.compile(rb'stream\r?\n(.*?)\r?\nendstream', re.DOTALL)
_MEDIABOX_RE = re.compile(
    rb'/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]')
_FONT_DICT_RE = re.compile(rb'/Font\s*<<(.*?)>>', re.DOTALL)
_FONT_ENTRY_RE = re.compile(rb'/(\S+)\s+(\d+)\s+0\s+R')
_BASEFONT_RE = re.compile(rb'/BaseFont\s*/([^\s/>]+)')

# One shape covers every `ops.append(b'BT ...')` call site in pdf.py.
_TEXT_OP_RE = re.compile(
    rb'BT /(?P<font>\S+) (?P<size>-?\d+) Tf '
    rb'(?:(?P<tz>-?[\d.]+) Tz )?'
    rb'(?P<rise>-?\d+) Ts '
    rb'(?P<x>-?[\d.]+) (?P<y>-?[\d.]+) Td '
    rb'\((?P<text>(?:[^()\\]|\\.)*)\) Tj ET')
_UNESC_RE = re.compile(rb'\\(.)')

TZ_DEFAULT = 100.0   # pdf.py's own PDF-default text-scaling state


def parse_pdf_objects(data: bytes) -> dict:
    """{obj_num: object body bytes} -- a flat, filter-agnostic index."""
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


def extract_pages(pdf_bytes: bytes) -> list:
    """[{mediabox: (w, h), fonts: {'F1': basefont, ...}, content: bytes}, ...]
    in document page order, taken from the /Pages object's own /Kids array
    (not from object-number order, which is an emitter implementation
    detail this tool must not depend on)."""
    objs = parse_pdf_objects(pdf_bytes)
    pages_num = next(n for n, b in objs.items() if b.startswith(b'<< /Type /Pages')
                     or re.search(rb'/Type\s*/Pages\b', b))
    kids_m = re.search(rb'/Kids\s*\[(.*?)\]', objs[pages_num], re.DOTALL)
    kid_nums = [int(x) for x in re.findall(rb'(\d+)\s+0\s+R', kids_m.group(1))]
    pages = []
    for pnum in kid_nums:
        body = objs[pnum]
        mb = _MEDIABOX_RE.search(body)
        w, h = float(mb.group(3)), float(mb.group(4))
        fonts = {}
        fdict_m = _FONT_DICT_RE.search(body)
        if fdict_m:
            for fname, fnum in _FONT_ENTRY_RE.findall(fdict_m.group(1)):
                fobj = objs.get(int(fnum), b'')
                bfm = _BASEFONT_RE.search(fobj)
                fonts[fname.decode()] = bfm.group(1).decode() if bfm else None
        cnum = _dict_ref(body, '/Contents')
        content = _stream_bytes(objs, cnum) if cnum is not None else b''
        pages.append({'mediabox': (w, h), 'fonts': fonts, 'content': content})
    return pages


def _unescape_pdf_text(raw: bytes) -> str:
    def rep(m):
        c = m.group(1)
        return c if c in b'()\\' else b'\\' + c
    return _UNESC_RE.sub(rep, raw).decode('cp1252', 'replace')


def parse_text_ops(content: bytes) -> list:
    """[{font, basefont-name(unresolved), size, tz, rise, x, y, text}, ...]
    in emission order. `tz` is the SCALE IN EFFECT for this op -- carried
    forward across ops exactly as pdf.py's own per-page `tz_state` does
    (Tz is text state and survives ET; pdf.py only ever WRITES the
    operator when the value changes)."""
    ops = []
    tz = TZ_DEFAULT
    for m in _TEXT_OP_RE.finditer(content):
        if m.group('tz'):
            tz = float(m.group('tz'))
        ops.append({
            'font': m.group('font').decode(),
            'size': int(m.group('size')),
            'tz': tz,
            'rise': int(m.group('rise')),
            'x': float(m.group('x')),
            'y': float(m.group('y')),
            'text': _unescape_pdf_text(m.group('text')),
        })
    return ops


# ------------------------------------------------------ font classification
def classify_font(basefont) -> str:
    """serif / sans / fixed / symbol / unknown -- from a base-14 name. Both
    sides of this gate use the SAME naming (pcl_render.py's TYPEFACE_FAMILY
    maps to pdf.py's own BASE14 strings: 'Times-Bold', 'Courier', 'Symbol',
    ...), so this one function classifies both."""
    if not basefont:
        return 'unknown'
    n = basefont.lower()
    if n.startswith('symbol') or n.startswith('zapfdingbats'):
        return 'symbol'
    if n.startswith('courier'):
        return 'fixed'
    if n.startswith('times'):
        return 'serif'
    if n.startswith('helvetica'):
        return 'sans'
    return 'unknown'


# --------------------------------------------------- engine word splitting
_TOKEN_RE = re.compile(r' +|[^ ]+')


def split_engine_op(op: dict, basefont) -> list:
    """One text op -> [(word_text, x_pt), ...] for its non-space tokens,
    walking the SAME per-character advance pdf.py itself would have used:
    the token's own AFM natural width (ctrlkd.afm -- the identical table
    pdf.py's `_natural_width_pt` reads) times the op's OWN Tz/100 scale.
    For a fixed-pitch (Courier) run this reproduces pdf.py's uniform
    per-character pitch exactly (Courier's AFM widths are constant); for a
    proportional run pdf.py already writes one Tj per word (see
    `_line_ops_printed`), so this only ever needs to split multi-word
    Courier/indent runs."""
    words = []
    cursor = 0.0
    for tok in _TOKEN_RE.findall(op['text']):
        if basefont:
            w_nat = afm.string_width_pt(tok, basefont, op['size'])
        else:
            w_nat = len(tok) * op['size'] * 0.6
        w_actual = w_nat * (op['tz'] / 100.0)
        if not tok.isspace():
            words.append((tok, op['x'] + cursor))
        cursor += w_actual
    return words


def engine_page_tokens(page: dict, page_no: int) -> list:
    """[{text, x, y_top, size, basefont, font_class, page}, ...] for one PDF
    page dict (from extract_pages), word-granular, in emission order.
    `y_top`/`x` are PAGE-LOCAL (relative to this page's own top-left) --
    pagination differences between the engine and WS7 are a SEPARATE
    finding (see run_gate's page-alignment tracking), not folded into this
    per-token position."""
    mb_h = page['mediabox'][1]
    out = []
    for op in parse_text_ops(page['content']):
        basefont = page['fonts'].get(op['font'])
        for text, x in split_engine_op(op, basefont):
            out.append({
                'text': text,
                'x': x,
                'y_top': mb_h - op['y'],
                'size': op['size'],
                'basefont': basefont,
                'font_class': classify_font(basefont),
                'page': page_no,
            })
    return out


def engine_baseline_gaps(tokens: list) -> list:
    """Median-rounded distinct baseline y_top values, sorted top-to-bottom,
    and their consecutive gaps -- the engine-side twin of measurements.json's
    own `baselines_pt`/`baseline_gaps_pt` (pcl_render.py's `analyze_page`)."""
    ys = sorted({round(t['y_top'], 1) for t in tokens})
    gaps = [round(ys[k + 1] - ys[k], 3) for k in range(len(ys) - 1)]
    return ys, gaps


# ------------------------------------------------------------- WS7 loading
def ws7_page_tokens(page: dict, page_no: int) -> list:
    """measurements.json page['chunks'] -> the same token shape
    `engine_page_tokens` produces, so both sides compare like for like.
    `x`/`y_top` stay PAGE-LOCAL, same reasoning as the engine side."""
    out = []
    for c in page['chunks']:
        out.append({
            'text': c['text'],
            'x': c['x_decipoints'] / DECIPT_PER_PT,
            'y_top': c['y_decipoints'] / DECIPT_PER_PT,
            'size': c['size_pt'],
            'basefont': c.get('font'),
            'font_class': classify_font(c.get('font')),
            'page': page_no,
        })
    return out


# ------------------------------------------------------------------ engine
def render_engine_pdf(ws_path: str) -> bytes:
    """The document rendered exactly as the CLI would for --mode printed:
    `core.parse` (auto-detect, cp437, the CLI's own defaults) then
    `pdf.emit_pdf(doc, mode='printed')` with no options -- letter, the
    document's own geometry, nothing overridden."""
    data = open(ws_path, 'rb').read()
    doc = core.parse(data)
    return pdfmod.emit_pdf(doc, mode='printed')


# ------------------------------------------------------------------ match
def match_doc(ws7_tokens: list, engine_tokens: list) -> dict:
    """Align two WHOLE-DOCUMENT token lists (each already concatenated in
    page/reading order, every token carrying its own 'page' number) by
    TEXT, via difflib's sequence matcher -- 'equal' blocks become matched
    pairs; everything else is reported unmatched ON THE SIDE(S) IT APPEARS,
    never silently dropped and never force-paired by position.

    Matching is done ACROSS THE WHOLE DOC, not page-by-page: when the
    engine's pagination puts more or less text on a page than WS7 did
    (a real, separately-reported finding -- see run_gate's page-alignment
    tracking), the SAME WORD can land on a different nominal page number
    on each side. A per-page-index match would treat that as two
    unrelated pages and lose the alignment near every divergence; matching
    globally on text finds the true correspondence regardless of which
    page either side put it on, and a pair's `page` fields then tell you
    whether that correspondence crossed a page boundary."""
    ws7_words = [t['text'] for t in ws7_tokens]
    eng_words = [t['text'] for t in engine_tokens]
    sm = difflib.SequenceMatcher(None, ws7_words, eng_words, autojunk=False)
    pairs = []
    unmatched_ws7, unmatched_engine = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for i, j in zip(range(i1, i2), range(j1, j2)):
                pairs.append((ws7_tokens[i], engine_tokens[j]))
        else:
            unmatched_ws7.extend(ws7_tokens[i1:i2])
            unmatched_engine.extend(engine_tokens[j1:j2])
    return {'pairs': pairs, 'unmatched_ws7': unmatched_ws7,
            'unmatched_engine': unmatched_engine}


def _iqr(vals: list):
    if len(vals) < 2:
        return 0.0
    q1, _, q3 = statistics.quantiles(vals, n=4, method='inclusive')
    return round(q3 - q1, 3)


def pair_deltas(pairs: list) -> list:
    """dx is PAGE-LOCAL and always comparable (x never accumulates across a
    pagination difference). dy is ALSO computed page-locally on each side,
    which is only a clean measurement of the top-margin/frame offset when
    `same_page` is True -- a pair whose two halves landed on different
    nominal page numbers (pagination drift; see match_doc) has a dy that
    mixes the real frame offset with wherever-drift-put-it-on-the-page, so
    callers must gate dy statistics on `same_page` (frame_offset does)."""
    out = []
    for w, e in pairs:
        out.append({
            'ws7_text': w['text'], 'engine_text': e['text'],
            'dx': round(e['x'] - w['x'], 3),
            'dy': round(e['y_top'] - w['y_top'], 3),
            'size_delta': round(e['size'] - w['size'], 3),
            'ws7_font': w.get('basefont'), 'engine_font': e.get('basefont'),
            'font_exact_match': w.get('basefont') == e.get('basefont'),
            'font_class_match': w['font_class'] == e['font_class'],
            'ws7_font_class': w['font_class'], 'engine_font_class': e['font_class'],
            'ws7_y_top': round(w['y_top'], 1), 'engine_y_top': round(e['y_top'], 1),
            'ws7_page': w['page'], 'engine_page': e['page'],
            'same_page': w['page'] == e['page'],
        })
    return out


def frame_offset(deltas: list) -> dict:
    """dx from every pair (page-independent). dy from SAME-PAGE pairs only
    -- see pair_deltas' docstring. `n_dx`/`n_dy` are reported separately
    since a doc with real pagination drift can have far fewer same-page
    pairs than total matched pairs; that gap is itself reported by the
    caller as `cross_page` counts, never silently absorbed here."""
    if not deltas:
        return {'n_dx': 0, 'n_dy': 0, 'median_dx': None, 'median_dy': None,
                'iqr_dx': None, 'iqr_dy': None}
    dxs = [d['dx'] for d in deltas]
    same = [d for d in deltas if d['same_page']]
    dys = [d['dy'] for d in same]
    return {'n_dx': len(dxs), 'n_dy': len(dys),
            'median_dx': round(statistics.median(dxs), 3),
            'median_dy': round(statistics.median(dys), 3) if dys else None,
            'iqr_dx': _iqr(dxs), 'iqr_dy': _iqr(dys) if dys else None}


def residuals(deltas: list, offset: dict) -> list:
    """Residuals are computed, and meaningful, ONLY for same-page pairs --
    see pair_deltas/frame_offset. Cross-page pairs are excluded entirely
    (not zero-filled, not guessed): their dy is explained by pagination
    drift, not by per-chunk layout error, and mixing the two would hide
    both."""
    if offset['n_dx'] == 0 or offset['median_dy'] is None:
        return []
    mx, my = offset['median_dx'], offset['median_dy']
    out = []
    for d in deltas:
        if not d['same_page']:
            continue
        rx, ry = d['dx'] - mx, d['dy'] - my
        out.append(dict(d, resid_dx=round(rx, 3), resid_dy=round(ry, 3),
                        resid_pt=round((rx * rx + ry * ry) ** 0.5, 3)))
    return out


# ---------------------------------------------------- PCL corroboration
_PCL_GROUP_RE = re.compile(rb'\x1b&l([^\x1b]*)')
_PCL_FIELD_RE = re.compile(rb'([+-]?\d*\.?\d*)([a-zA-Z])')


def extract_pcl_top_margin_fields(pcl_bytes: bytes) -> list:
    """Every ESC&l...E (top margin, HP PCL5 ref) field VALUE found in the
    raw capture -- corroborating evidence only, never consumed to correct
    or seed the empirical frame-offset measurement above."""
    out = []
    for gm in _PCL_GROUP_RE.finditer(pcl_bytes):
        for val, letter in _PCL_FIELD_RE.findall(gm.group(1)):
            if letter.upper() == b'E' and val not in (b'', b'+', b'-'):
                out.append(val.decode('ascii'))
    return out


def _agreement(deltas, key):
    if not deltas:
        return None
    return round(sum(1 for d in deltas if d[key]) / len(deltas), 4)


# --------------------------------------------------------------- doc-level
def run_gate(doc_name: str, ws_path: str, measurements_path: str,
             pcl_path: str = None) -> dict:
    ws7 = json.load(open(measurements_path))
    pdf_bytes = render_engine_pdf(ws_path)
    engine_pages = extract_pages(pdf_bytes)

    n_ws7_pages = len(ws7['pages'])
    n_engine_pages = len(engine_pages)

    # Build whole-document token streams (each token carries its own real
    # page number) and match ONCE, globally -- see match_doc's docstring
    # for why per-page-index matching breaks under pagination drift.
    ws7_all, eng_all = [], []
    for i, p in enumerate(ws7['pages']):
        ws7_all.extend(ws7_page_tokens(p, p.get('page', i + 1)))
    for i, p in enumerate(engine_pages):
        eng_all.extend(engine_page_tokens(p, i + 1))

    m = match_doc(ws7_all, eng_all)
    all_deltas = pair_deltas(m['pairs'])
    doc_offset = frame_offset(all_deltas)
    doc_resid = residuals(all_deltas, doc_offset)
    doc_worst = sorted(doc_resid, key=lambda r: -r['resid_pt'])[:15]
    cross_page_pairs = [d for d in all_deltas if not d['same_page']]

    # ------------------------------------------------- per-(WS7)-page report
    by_ws7_page = defaultdict(list)
    for d in all_deltas:
        by_ws7_page[d['ws7_page']].append(d)
    unmatched_ws7_by_page = defaultdict(list)
    for t in m['unmatched_ws7']:
        unmatched_ws7_by_page[t['page']].append(t['text'])
    unmatched_engine_by_page = defaultdict(list)
    for t in m['unmatched_engine']:
        unmatched_engine_by_page[t['page']].append(t['text'])
    ws7_gaps_by_page = {p.get('page', i + 1): p.get('baseline_gaps_pt', [])
                        for i, p in enumerate(ws7['pages'])}
    eng_gaps_by_page = {}
    for i, p in enumerate(engine_pages):
        eng_tok_i = engine_page_tokens(p, i + 1)
        _, gaps = engine_baseline_gaps(eng_tok_i)
        eng_gaps_by_page[i + 1] = gaps

    page_reports = []
    for pn in range(1, n_ws7_pages + 1):
        deltas = by_ws7_page.get(pn, [])
        offset = frame_offset(deltas)
        resid = residuals(deltas, offset)
        worst = sorted(resid, key=lambda r: -r['resid_pt'])[:10]
        cross = [d for d in deltas if not d['same_page']]
        ws7_gaps = ws7_gaps_by_page.get(pn, [])
        eng_gaps = eng_gaps_by_page.get(pn, [])
        page_reports.append({
            'ws7_page': pn,
            'matched': len(deltas),
            'cross_page_matched': len(cross),
            'cross_page_engine_pages': sorted({d['engine_page'] for d in cross}),
            'unmatched_ws7': len(unmatched_ws7_by_page.get(pn, [])),
            'unmatched_ws7_text': unmatched_ws7_by_page.get(pn, []),
            'frame_offset': offset,
            'font_class_agreement': _agreement(deltas, 'font_class_match'),
            'font_exact_agreement': _agreement(deltas, 'font_exact_match'),
            'residual_max_pt': max((r['resid_pt'] for r in resid), default=None),
            'residual_median_pt': (round(statistics.median(
                [r['resid_pt'] for r in resid]), 3) if resid else None),
            'worst_residuals': worst,
            'ws7_baseline_gaps_pt': ws7_gaps,
            'engine_baseline_gaps_pt': eng_gaps,
            'baseline_gap_median_ws7': (round(statistics.median(ws7_gaps), 3)
                                        if ws7_gaps else None),
            'baseline_gap_median_engine': (round(statistics.median(eng_gaps), 3)
                                           if eng_gaps else None),
        })
    # engine pages/words that matched NOTHING on any WS7 page, grouped by
    # their own (engine) page number -- reported once at doc level rather
    # than duplicated per WS7 page.
    unmatched_engine_all = {pn: txts for pn, txts in
                            sorted(unmatched_engine_by_page.items())}

    pcl_top_margin_fields = None
    if pcl_path and os.path.exists(pcl_path):
        pcl_top_margin_fields = extract_pcl_top_margin_fields(open(pcl_path, 'rb').read())

    # PAGE 1 ALWAYS starts fresh on both sides -- no prior page's line count
    # can have drifted it -- so its frame offset is the one number in this
    # report that pagination-capacity differences cannot contaminate. Every
    # later page's `same_page` dy is a mix of the true frame offset AND
    # wherever a pagination-capacity mismatch has pushed that content to
    # WITHIN the page (see run_gate's page-report loop; growing |dy| across
    # pages in the per-page table is the signature of that, not a growing
    # margin bug). Doc-wide dx has no such problem (x resets every line,
    # independent of pagination) and stays trustworthy across the whole doc.
    first_page_offset = page_reports[0]['frame_offset'] if page_reports else None

    return {
        'doc': doc_name, 'ws_path': ws_path, 'measurements_path': measurements_path,
        'pcl_path': pcl_path,
        'n_ws7_pages': n_ws7_pages, 'n_engine_pages': n_engine_pages,
        'page_count_mismatch': n_ws7_pages != n_engine_pages,
        'first_page_frame_offset': first_page_offset,
        'ws7_chunks_total': len(ws7_all), 'engine_words_total': len(eng_all),
        'doc_matched': len(all_deltas),
        'doc_unmatched_ws7': len(m['unmatched_ws7']),
        'doc_unmatched_engine': len(m['unmatched_engine']),
        'doc_cross_page_matched': len(cross_page_pairs),
        'doc_cross_page_fraction': (round(len(cross_page_pairs) / len(all_deltas), 4)
                                    if all_deltas else None),
        'doc_frame_offset': doc_offset,
        'doc_font_class_agreement': _agreement(all_deltas, 'font_class_match'),
        'doc_font_exact_agreement': _agreement(all_deltas, 'font_exact_match'),
        'doc_residual_median_pt': (round(statistics.median(
            [r['resid_pt'] for r in doc_resid]), 3) if doc_resid else None),
        'doc_residual_max_pt': max((r['resid_pt'] for r in doc_resid), default=None),
        'doc_worst_residuals': doc_worst,
        'unmatched_engine_by_page': unmatched_engine_all,
        'pcl_top_margin_e_field_values': pcl_top_margin_fields,
        'pages': page_reports,
    }


# ------------------------------------------------------------- doc lookup
def resolve_doc_paths(doc_name: str):
    """(ws_path, measurements_path, pcl_path) for a known corpus doc name,
    or (None, ...) if a required private root is unset -- SKIP, not error."""
    prints_root = os.environ.get(WS7_PRINTS_ENV) or DEFAULT_WS7_PRINTS_ROOT
    if not prints_root:
        raise RuntimeError(
            f'{WS7_PRINTS_ENV} is not set and there is no default path. '
            'This gate FAILS rather than quietly measuring nothing.')
    measurements_path = os.path.join(prints_root, f'{doc_name}.measurements.json')
    pcl_path = os.path.join(prints_root, f'{doc_name}.pcl')
    if doc_name in PRIVATE_DOCS:
        root = os.environ.get(SAWYER_ROOT_ENV)
        if not root:
            return None, measurements_path, pcl_path
        ws_path = os.path.join(root, PRIVATE_DOCS[doc_name])
    else:
        if not DEFAULT_AUTHORED_ROOT:
            raise RuntimeError(
                f'{AUTHORED_ROOT_ENV} is not set and there is no default path. '
                'This gate FAILS rather than quietly measuring nothing.')
        ws_path = os.path.join(DEFAULT_AUTHORED_ROOT, f'{doc_name}.WS')
    return ws_path, measurements_path, pcl_path


# ------------------------------------------------------------------- table
def print_table(reports: list):
    hdr = ('DOC', 'WS7pg/ENGpg', 'MATCHED/TOTAL', 'UNMATCHED(ws7/eng)',
           'XPAGE%', 'DOC_MED_DX', 'PG1_MED_DY(n)', 'PG1_IQR_DY',
           'RESID_MED(pg1)', 'FONT_CLASS%')
    rows = []
    for r in reports:
        off = r['doc_frame_offset']
        p1 = r['first_page_frame_offset'] or {}
        total = off['n_dx'] + r['doc_unmatched_ws7']
        pg1_resid = (r['pages'][0]['residual_median_pt'] if r['pages'] else None)
        rows.append((
            r['doc'],
            f"{r['n_ws7_pages']}/{r['n_engine_pages']}",
            f"{off['n_dx']}/{total}",
            f"{r['doc_unmatched_ws7']}/{r['doc_unmatched_engine']}",
            f"{r['doc_cross_page_fraction']}",
            f"{off['median_dx']}",
            f"{p1.get('median_dy')}({p1.get('n_dy')})",
            f"{p1.get('iqr_dy')}",
            f"{pg1_resid}",
            f"{r['doc_font_class_agreement']}",
        ))
    widths = [max(len(hdr[i]), *(len(row[i]) for row in rows)) if rows
              else len(hdr[i]) for i in range(len(hdr))]
    def fmt(cells):
        return '  '.join(c.ljust(w) for c, w in zip(cells, widths))
    print(fmt(hdr))
    print(fmt(['-' * w for w in widths]))
    for row in rows:
        print(fmt(row))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('doc', nargs='?', help='Doc name for --doc-style resolution '
                    '(same as --doc)')
    ap.add_argument('--doc', dest='doc_opt')
    ap.add_argument('--ws')
    ap.add_argument('--measurements')
    ap.add_argument('--pcl')
    ap.add_argument('--out-json')
    ap.add_argument('--batch', nargs='+', help='Doc names to run in one pass '
                    '(each via --doc-style resolution); writes one JSON per '
                    'doc into --out-dir')
    ap.add_argument('--out-dir')
    a = ap.parse_args(argv)

    reports = []
    if a.batch:
        for name in a.batch:
            ws_path, mpath, pcl_path = resolve_doc_paths(name)
            if ws_path is None:
                print(f'fidelity_gate: {name}: skipped -- ${SAWYER_ROOT_ENV} unset',
                      file=sys.stderr)
                continue
            if not os.path.exists(ws_path) or not os.path.exists(mpath):
                print(f'fidelity_gate: {name}: skipped -- source or '
                      f'measurements not found', file=sys.stderr)
                continue
            r = run_gate(name, ws_path, mpath, pcl_path)
            reports.append(r)
            if a.out_dir:
                os.makedirs(a.out_dir, exist_ok=True)
                json.dump(r, open(os.path.join(a.out_dir, f'{name}.json'), 'w'),
                          indent=2)
    else:
        name = a.doc_opt or a.doc
        if not name:
            ap.error('need a doc name (positional, --doc) or --batch')
        if a.ws and a.measurements:
            ws_path, mpath, pcl_path = a.ws, a.measurements, a.pcl
        else:
            ws_path, mpath, pcl_path = resolve_doc_paths(name)
            if ws_path is None:
                print(f'fidelity_gate: {name}: skipped -- ${SAWYER_ROOT_ENV} unset',
                      file=sys.stderr)
                return 0
        r = run_gate(name, ws_path, mpath, pcl_path)
        reports.append(r)
        if a.out_json:
            json.dump(r, open(a.out_json, 'w'), indent=2)

    print_table(reports)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
