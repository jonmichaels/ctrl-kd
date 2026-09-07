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

    # or, using --doc-style resolution (both corpus env vars):
    CTRLKD_PRIVATE_CORPUS=/path/to/corpus python3 tools/fidelity_gate.py \
        --doc LYING --out-json /tmp/lying.json

    # --pdf: compare a DIFFERENT engine's own PDF (this tool reads any
    # PDF -- the comparison logic below never depends on how it was
    # produced) against the same WS7 ground truth, e.g. from the Swift/sr
    # side, without re-implementing this whole gate a second time:
    CTRLKD_PRIVATE_CORPUS=/path/to/corpus python3 tools/fidelity_gate.py \
        --doc LYING --pdf /path/to/sr-LYING-printed.pdf --out-json /tmp/lying-sr.json
    # or fully standalone, no corpus env vars at all:
    python3 tools/fidelity_gate.py --pdf OUT.pdf \
        --measurements NAME.measurements.json [--pcl NAME.pcl] --out-json /tmp/out.json

    # --engine-words: same as --pdf, but for an emitter this file's own PDF
    # parser (_TEXT_OP_RE) cannot read at all -- e.g. macOS Quartz's `Tm`/
    # `TJ` output over subset fonts. Takes a PRE-EXTRACTED words JSON (see
    # the "engine-words (JSON)" schema comment above dump_engine_words(),
    # below) instead of a PDF; everything downstream (matching, tolerance,
    # reason vocabulary, manifest comparison) runs exactly as it does for
    # --pdf, since load_engine_words() hands back the identical token shape:
    CTRLKD_PRIVATE_CORPUS=/path/to/corpus python3 tools/fidelity_gate.py \
        --doc LYING --engine-words /path/to/lying-words.json --out-json /tmp/lying-app.json

    # --dump-engine-words: produce that same words JSON from ctrl-kd's OWN
    # PDF (the rendered-from-ws_path PDF, or a --pdf) -- round-trips as
    # gate(pdf) == gate(--engine-words dump(pdf)); see
    # tests/test_pcl_tolerance.py's round-trip test.
    python3 tools/fidelity_gate.py --doc LYING --dump-engine-words /tmp/lying-words.json

For the automated, tolerance-aware version of this gate (per-font-class
drift bounds, a checked-in named-divergence manifest, drift detection) see
tools/pcl_tolerance.py and the `pcl` pytest tier (tests/test_pcl_fidelity.py)
-- this file stays the raw, tolerance-agnostic coordinate comparison both
of those are built on.

`--doc NAME` resolves NAME.WS through the corpus's own capture index,
$CTRLKD_PRIVATE_CORPUS/ws7-prints/v1/sources.json (`{"format":1,
"captures":{NAME:{"source":<corpus-relative path>, ...}}}`) -- one entry
per capture, written by whoever adds a capture to the corpus, so this
tool never has to know which of the corpus's private groups a given NAME
lives under -- only sawyer/ and pd-samples/authored/ are ever named in
this repo's own code, since those two are public; any other group the
index carries is the private corpus's own business, not this repo's (see
tools/pcl_tolerance.py's PUBLIC_SOURCE_GROUPS). The resolved path is
always `$CTRLKD_PRIVATE_CORPUS/<source>`. If the index
file itself is absent (an older corpus clone), this falls back to the
older group search: pd-samples/authored/NAME.WS, or for SAWYER/
VERSIONS/etc -- the PRIVATE_DOCS table below -- $CTRLKD_SAWYER_ARCHIVE/
NAME.WS, same shape as every other Sawyer-archive consumer in this repo;
the doc is SKIPPED, not errored, when the relevant env var is unset in
that fallback path. NAME.measurements.json/.pcl come from
$CTRLKD_PRIVATE_CORPUS/ws7-prints/v1/ -- the ground-truth PCL capture
data lives inside the private corpus itself, same layout as the vault
copy it was captured into. There is no separate flag for it: an unset
CTRLKD_PRIVATE_CORPUS, or a missing measurements.json, FAILS the gate
loudly (never a silent skip, never a silent pass) naming the exact path
it looked for.

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
from ctrlkd import pictures as ctrlkd_pictures  # noqa: E402

DECIPT_PER_PT = 10.0

# Corpus roots come from the environment ONLY. They used to carry hardcoded
# absolute paths naming a particular machine -- as published as any file.
# One var per corpus, one shape each (D3, 2026-09-03): CTRLKD_PRIVATE_CORPUS
# is the corpus clone's own root; the authored pd-samples live under its
# pd-samples/authored/ subdirectory. CTRLKD_SAWYER_ARCHIVE is the Sawyer
# archive's own top-level directory, same shape every other consumer in
# this repo expects (tests/sawyer_fixture.py).
PRIVATE_CORPUS_ENV = 'CTRLKD_PRIVATE_CORPUS'
_PRIVATE_CORPUS_ROOT = os.environ.get(PRIVATE_CORPUS_ENV)
DEFAULT_AUTHORED_ROOT = (
    os.path.join(_PRIVATE_CORPUS_ROOT, 'pd-samples', 'authored')
    if _PRIVATE_CORPUS_ROOT else None)
# The ground-truth PCL capture directory (NAME.measurements.json/.pcl) now
# lives INSIDE the private corpus too, at ws7-prints/v1/ -- same relative
# layout as the vault copy it was captured into (verified: v1/ holds the
# .measurements.json/.pcl pairs; ws7-captures/ holds only raw .pcl). No
# flag, no separate env var -- the old required flag for this directory
# was removed 2026-09-05 once the data moved into the corpus (Jon: "I
# don't love that we have it").
PRINTS_SUBDIR = 'v1'
# A second, newer capture round lives alongside v1 at ws7-prints/v2/ --
# NOT one flat NAME.measurements.json/.pcl pair per doc like v1, but the
# doc's own sources.json-relative SOURCE PATH plus the same two
# extensions (e.g. v1 has 'sawyer/-README.WS' captured at
# v1/-README.measurements.json; v2 has the SAME capture at
# v2/sawyer/-README.WS.measurements.json). See resolve_doc_paths and
# tools/PCL-DIVERGENCE-TRIAGE.md mechanism E: -README's own v1 capture
# predates the current Sawyer-archive file (v1.4 vs v1.5) and undercounts
# its real page count by 2; a v2 recapture already exists and matches the
# CURRENT engine's output verbatim. resolve_doc_paths therefore prefers
# the v2 capture for ANY doc that has one (checked via sources.json's own
# 'source' path, not a doc-name allowlist -- so a future v2 recapture of
# any other Sawyer-archive document is picked up with no code change
# here), falling back to v1 when no v2 capture exists for that source yet.
PRINTS_SUBDIR_V2 = 'v2'
# A third capture round, ws7-prints/v3/ -- Jon's ruling 2026-09-06: every
# future real-WS7 capture is made with the FACTORY binary (PRISTINE.EXE,
# no WSCHANGE customization), because mechanism S (PCL-DIVERGENCE-TRIAGE.md)
# found that v1/v2 were both captured on Robert J. Sawyer's own
# WSCHANGE-customized install, whose `.po` factory default (column 7) is
# NOT WordStar 7's own stock default (column 8, confirmed via a direct
# PRISTINE.EXE probe). v3 uses v1's OWN flat NAME.measurements.json/
# NAME.pcl naming (not v2's source-relative-path naming) plus its own
# sources.json carrying a top-level 'install' field -- see
# _install_for_subdir/DEFAULT_INSTALL_BY_SUBDIR below for what happens
# when that field isn't there yet (the corpus is being captured
# incrementally; a doc with no v3 file at all just isn't preferred).
# Preferred over v2, which is preferred over v1 -- see resolve_doc_capture.
PRINTS_SUBDIR_V3 = 'v3'
# The capture index (see module docstring): one entry per NAME, giving a
# corpus-relative source path -- resolved BEFORE the group-search fallback
# below, so a new capture only needs an index entry, never a code change
# here. SOURCES_INDEX_FILENAME lives alongside the .measurements.json/.pcl
# pairs it names, at $CTRLKD_PRIVATE_CORPUS/ws7-prints/v1/ (and, when it
# exists, ws7-prints/v3/ -- v2 has no sources.json of its own, see
# _install_for_subdir).
SOURCES_INDEX_FILENAME = 'sources.json'
# Provenance label for a capture set, when that set's OWN sources.json
# doesn't declare an explicit top-level 'install' field itself (see
# _install_for_subdir) -- v1/v2 predate that field entirely (both are
# uniformly Robert J. Sawyer's WSCHANGE-customized install, mechanism S);
# v3 is expected to declare 'install': 'pristine' in its own sources.json
# once the capture job finishes, this is only the fallback.
DEFAULT_INSTALL_BY_SUBDIR = {
    PRINTS_SUBDIR: 'sawyer-wschange',
    PRINTS_SUBDIR_V2: 'sawyer-wschange',
    PRINTS_SUBDIR_V3: 'pristine',
}
ARCHIVE_ENV = 'CTRLKD_SAWYER_ARCHIVE'
# Values in PRIVATE_DOCS below are paths RELATIVE to the archive root.
# Legacy fallback ONLY -- used when the corpus has no sources.json (see
# resolve_doc_paths).
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
#
# ORDER BUG (PCL tier, WARPRAYR.WS): every `ops.append(b'BT ...')` call
# site in pdf.py (all 12 of them, checked 2026-09-06) writes `Tf <rise> Ts`
# FIRST and the optional `<tz> Tz` SECOND, immediately before `Td` -- this
# regex previously expected the reverse order (`Tz` before `Ts`), so it
# NEVER matched a single Tz-scaled op (every CG-Times/Univers-substituted
# proportional word -- the whole reason a Tz scale exists at all, see
# pdf.py's Tz docstring). `parse_text_ops` silently dropped every such
# word, `engine_page_tokens` never saw it, and this gate reported it as a
# WS7-side `word-unmatched` (or shifted its neighbour's own alignment) on
# EVERY document with a CG-Times/Univers-tier line -- confirmed by hand:
# WARPRAYR's own '"God the all-terrible...' Quote line (a Tz-scaled run,
# `104.15 Tz`/`101.12 Tz` are real values from its own PDF) had `"God`
# literally present in the raw content stream (`("God) Tj`) but absent
# from `engine_page_tokens`'s output before this fix.
_TEXT_OP_RE = re.compile(
    rb'BT /(?P<font>\S+) (?P<size>-?\d+) Tf '
    rb'(?P<rise>-?\d+) Ts '
    rb'(?:(?P<tz>-?[\d.]+) Tz )?'
    rb'(?P<x>-?[\d.]+) (?P<y>-?[\d.]+) Td '
    rb'\((?P<text>(?:[^()\\]|\\.)*)\) Tj ET')
_UNESC_RE = re.compile(rb'\\(.)')

TZ_DEFAULT = 100.0   # pdf.py's own PDF-default text-scaling state

# One shape covers every embedded-picture draw op pdf.py writes (round 19,
# PIX images RULED IN -- both `ops.append(b'q %.2f 0 0 %.2f %.2f %.2f cm '
# b'/Im%d Do Q' ...)` call sites, checked by hand): a unit-square `cm`
# scaled to the drawn width/height and translated to the box's own
# LOWER-LEFT corner (PDF's own bottom-up y), then `/Im<N> Do`. Planning
# #211 (mechanism L revisited): this is the engine-side half of the new
# raster-position comparison -- see engine_page_rasters/ws7_page_rasters
# below.
_IMAGE_OP_RE = re.compile(
    rb'q (?P<w>[\d.]+) 0 0 (?P<h>[\d.]+) (?P<x>[\d.]+) (?P<y>[\d.]+) cm '
    rb'/Im(?P<idx>\d+) Do Q')


def parse_image_ops(content: bytes) -> list:
    """[{idx, w, h, x, y}, ...] in emission order -- `x`/`y` are the drawn
    box's own LOWER-LEFT corner in PDF page space (bottom-up), `w`/`h` its
    drawn width/height in points, straight off the `cm` matrix. Mirrors
    `parse_text_ops`'s shape/discipline for the image-drawing op instead
    of the text-showing one."""
    ops = []
    for m in _IMAGE_OP_RE.finditer(content):
        ops.append({
            'idx': int(m.group('idx')),
            'w': float(m.group('w')), 'h': float(m.group('h')),
            'x': float(m.group('x')), 'y': float(m.group('y')),
        })
    return ops


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

# Mechanism L (triage 2026-09-06 residuals round). A `[image: NAME]` picture
# placeholder (core.py's own byte-for-byte
# `b'[image: ' + name + b']'`, written as ONE coalesced span -- pictures.py's
# own docstring: "off" is the CLI default, so this text stands in for a
# raster WordStar embedded via its own .PIX inset format) has, BY
# CONSTRUCTION, no WS7 text counterpart at all -- real WS7 printed the
# actual raster, not a text label. Confirmed on PREVIEW.WS (its own
# `[image: WORDSTAR.PIX]` reads as two `extra-word-in-engine` divergences
# for exactly this reason). This is not a position or content bug to fix --
# it is a structural difference (text vs. raster) this text-position gate
# was never going to be able to check either way, the same class of
# exclusion `_is_box_drawing_text`/`_is_unreliable_to_align` already give
# WS7-side chunks the gate cannot meaningfully align.
_IMAGE_PLACEHOLDER_RE = re.compile(r'^\[image: .*\]$')


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
        if _IMAGE_PLACEHOLDER_RE.match(op['text']):
            continue
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


def engine_page_rasters(page: dict, page_no: int) -> list:
    """[{x, y_top, w_pt, h_pt, page}, ...] for one PDF page dict's own
    embedded-picture `Do` ops (planning #211, mechanism L revisited).
    Same PAGE-LOCAL, top-down convention as engine_page_tokens: `x` is the
    drawn box's own left edge (PDF's `cm` x is already the page's left
    edge, same as a text op's), `y_top` is the box's own TOP edge
    (`mediabox_h - (op_y + op_h)` -- PDF's `cm` y is the box's BOTTOM-LEFT
    corner in PDF's bottom-up space, so the box's top is `op_y + op_h`
    above the page bottom, flipped the same way `engine_page_tokens`
    flips a text baseline)."""
    mb_h = page['mediabox'][1]
    out = []
    for op in parse_image_ops(page['content']):
        out.append({
            'x': op['x'],
            'y_top': mb_h - (op['y'] + op['h']),
            'w_pt': op['w'], 'h_pt': op['h'],
            'page': page_no,
        })
    return out


# --------------------------------------------------- engine-words (JSON)
ENGINE_WORDS_SCHEMA_VERSION = 1

# A pre-extracted substitute for a Printed PDF -- so a PDF written by ANY
# emitter (not just this repo's own pdf.py -- e.g. macOS Quartz's `Tm`/`TJ`
# operators over subset fonts, which _TEXT_OP_RE cannot parse at all: it
# matches only pdf.py's own literal `BT /Fn SIZE Tf ... Td (TEXT) Tj ET`
# op shape) can be judged by the exact same matching/tolerance machinery
# this whole file (and pcl_tolerance.py, one layer up) already runs on
# ctrl-kd's own PDF output. Produced by dump_engine_words() from this
# repo's own PDF (see that function's own docstring for the round-trip
# guarantee this buys), or by any other emitter directly; consumed by
# load_engine_words() and, through it, run_gate(..., engine_words=...) /
# pcl_tolerance.doc_report(..., engine_words=...).
#
# SCHEMA (version 1) -- top level:
#     {
#       "schema_version": 1,
#       "n_pages": <int>,             # total engine page count, INCLUDING
#                                      # pages with zero words (a blank or
#                                      # image-only page still counts --
#                                      # n_pages drives page_count_mismatch)
#       "words": [ <word>, ... ],     # every word on every page, in ANY
#                                      # order (page + reading order is
#                                      # recommended for readability, but
#                                      # nothing downstream depends on
#                                      # global order -- match_doc/
#                                      # difflib re-derives correspondence
#                                      # from each token's own 'page' plus
#                                      # whole-document text alignment)
#       "rasters": [ <raster>, ... ]  # embedded-picture boxes; [] if none
#     }
#
# <word>:
#     {
#       "text": <str>,       # the word's own literal text, no surrounding
#                             # whitespace, exactly as it should compare
#                             # against a WS7 chunk's own text (see
#                             # match_doc/difflib) -- this repo's own
#                             # _TOKEN_RE splits on runs of spaces only,
#                             # never on punctuation, so e.g. a trailing
#                             # comma stays attached to its word.
#       "x_pt": <float>,     # LEFT edge of the word's own first glyph, in
#                             # points, PAGE-LOCAL (relative to THIS
#                             # page's own top-left corner, NOT the PDF's
#                             # native bottom-left origin -- see this
#                             # file's own module docstring, "COORDINATE
#                             # CONVENTION"). x increases rightward.
#       "y_top_pt": <float>, # the word's own BASELINE, in points,
#                             # PAGE-LOCAL, measured DOWN from the page's
#                             # own top edge (y increases downward, the
#                             # OPPOSITE of raw PDF space). A word whose
#                             # baseline sits at raw PDF bottom-up position
#                             # y_pdf on a page of height page_height_pt
#                             # converts as y_top_pt = page_height_pt - y_pdf
#                             # (exactly engine_page_tokens' own `mb_h -
#                             # op['y']`, below).
#       "size_pt": <float>,  # nominal font size in points (PDF Tf size,
#                             # or the emitting engine's own equivalent)
#       "font": <str|null>,  # the word's own font/BaseFont name,
#                             # UNRESOLVED (a PDF subset name like
#                             # "ABCDEF+Helvetica" is fine as-is -- see
#                             # "font_class", which is what classification
#                             # actually runs on downstream). null if
#                             # genuinely unknown.
#       "font_class": <str>, # REQUIRED: one of "serif" / "sans" /
#                             # "fixed" / "symbol" / "unknown"
#                             # (classify_font()'s own vocabulary). NOT
#                             # derived by the loader -- a subset or
#                             # system font name cannot be reliably
#                             # reclassified by this repo's own base-14
#                             # prefix heuristic, so the PRODUCER must
#                             # supply the correct class directly:
#                             # Courier/any monospace face -> "fixed",
#                             # Times/a serif body face -> "serif",
#                             # Helvetica/Arial/a sans face -> "sans",
#                             # Symbol/ZapfDingbats/Wingdings -> "symbol".
#       "page": <int>        # 1-indexed engine page number this word is on
#     }
#
# <raster>:
#     {
#       "x_pt": <float>,     # drawn box's own LEFT edge, page-local points
#       "y_top_pt": <float>, # drawn box's own TOP edge, page-local points,
#                             # down from the page's own top edge
#       "w_pt": <float>,     # drawn width, points
#       "h_pt": <float>,     # drawn height, points
#       "page": <int>        # 1-indexed engine page number
#     }
#
# Everything downstream of extraction -- match_doc, pair_deltas,
# frame_offset, residuals, and pcl_tolerance.py's whole tolerance/reason-
# vocabulary/manifest machinery -- consumes only the common token shape
# engine_page_tokens()/engine_page_rasters() already produce from a PDF
# this repo parsed itself (keys x/y_top/size/basefont instead of this
# schema's x_pt/y_top_pt/size_pt/font); load_engine_words() below is the
# one place that translates between the two.


def dump_engine_words(pdf_bytes: bytes) -> dict:
    """A PDF (any of this repo's own PDFs -- extract_pages/
    engine_page_tokens/engine_page_rasters already know how to parse
    them) -> the engine-words JSON schema documented immediately above.
    Exists so that schema can be produced from ctrl-kd's own PDF output
    and ROUND-TRIPPED: run_gate(..., pdf_bytes=X) and run_gate(...,
    engine_words=dump_engine_words(X)) must report byte-identical results
    for the same X -- tests/test_pcl_tolerance.py's round-trip test
    checks exactly this claim, for every bundled sample plus a generated
    synthetic fixture. `--dump-engine-words PATH` (see main()) is this
    function wired to the CLI's own PDF path."""
    engine_pages = extract_pages(pdf_bytes)
    words, rasters = [], []
    for i, page in enumerate(engine_pages):
        pn = i + 1
        for t in engine_page_tokens(page, pn):
            words.append({
                'text': t['text'], 'x_pt': t['x'], 'y_top_pt': t['y_top'],
                'size_pt': t['size'], 'font': t['basefont'],
                'font_class': t['font_class'], 'page': pn,
            })
        for r in engine_page_rasters(page, pn):
            rasters.append({
                'x_pt': r['x'], 'y_top_pt': r['y_top'],
                'w_pt': r['w_pt'], 'h_pt': r['h_pt'], 'page': pn,
            })
    return {'schema_version': ENGINE_WORDS_SCHEMA_VERSION,
            'n_pages': len(engine_pages), 'words': words, 'rasters': rasters}


def load_engine_words(data: dict) -> dict:
    """The engine-words JSON schema (documented above) -> {'n_engine_pages',
    'eng_tokens', 'eng_rasters_by_page'} -- the exact three things
    run_gate()/pcl_tolerance.doc_report() need in place of
    extract_pages(pdf_bytes) + engine_page_tokens(...) +
    engine_page_rasters(...). `eng_tokens` comes back in the SAME
    per-word dict shape engine_page_tokens() itself produces (text/x/
    y_top/size/basefont/font_class/page), so every match_doc/
    pair_deltas/frame_offset/pcl_tolerance call downstream runs
    unmodified regardless of which side built the tokens. Accepts a dict
    from THIS repo's own dump_engine_words(), or from any other
    producer (e.g. the macOS app's own PDFKit-based dumper) that follows
    the same schema. Only checks that 'schema_version' is present (there
    is only one version today, ENGINE_WORDS_SCHEMA_VERSION) -- a future
    incompatible bump should add a real compatibility check here."""
    if 'schema_version' not in data:
        raise ValueError("engine-words JSON missing required 'schema_version' key")
    eng_tokens = [{
        'text': w['text'], 'x': w['x_pt'], 'y_top': w['y_top_pt'],
        'size': w['size_pt'], 'basefont': w.get('font'),
        'font_class': w['font_class'], 'page': w['page'],
    } for w in data['words']]
    eng_rasters_by_page = defaultdict(list)
    for r in data.get('rasters', []):
        eng_rasters_by_page[r['page']].append({
            'x': r['x_pt'], 'y_top': r['y_top_pt'],
            'w_pt': r['w_pt'], 'h_pt': r['h_pt'], 'page': r['page'],
        })
    return {'n_engine_pages': data['n_pages'], 'eng_tokens': eng_tokens,
            'eng_rasters_by_page': dict(eng_rasters_by_page)}


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


def ws7_page_rasters(page: dict, page_no: int) -> list:
    """measurements.json page['rasters'] (pcl_render.py's own
    `ESC*r#A`/raster-origin capture, planning #211) -> the same
    {x, y_top, w_pt, h_pt, page} shape `engine_page_rasters` produces.
    `x_decipoints`/`y_decipoints` are ALREADY the raster's own top-left
    corner in PCL's native top-down convention (the cursor position at
    ESC*r#A, the same convention ws7_page_tokens' baseline y already
    uses) -- confirmed directly against PREVIEW/-SCREEN's own v3 capture:
    x_decipoints=576 (57.6pt) lands exactly on the engine's own resolved
    `.po` left margin. `width_px`/`height_px` at the raster's own
    `resolution_dpi` give the physical size in points (`px / dpi * 72`),
    same arithmetic pcl_render.py itself uses to size the PNG it writes."""
    out = []
    for r in page.get('rasters', []):
        w_pt = r['width_px'] / r['resolution_dpi'] * 72.0
        h_pt = r['height_px'] / r['resolution_dpi'] * 72.0
        out.append({
            'x': r['x_decipoints'] / DECIPT_PER_PT,
            'y_top': r['y_decipoints'] / DECIPT_PER_PT,
            'w_pt': w_pt, 'h_pt': h_pt,
            'page': page_no,
        })
    return out


# ------------------------------------------------------------------ engine
def render_engine_pdf(ws_path: str) -> bytes:
    """The document rendered exactly as the CLI would for --mode printed:
    `core.parse` (auto-detect, cp437, the CLI's own defaults) then
    `pdf.emit_pdf(doc, mode='printed')` -- letter, the document's own
    geometry, nothing overridden.

    Mechanism L revisited (planning #211, 2026-09-06): this used to call
    `emit_pdf(doc, mode='printed')` with ZERO options, which means
    `pictures` defaults to the LIBRARY default, 'off' -- the opposite of
    the CLI's own default ('embed'). A picture-bearing document (PREVIEW,
    -SCREEN, -README) was therefore NEVER actually exercised through this
    gate with its picture embedded -- the engine side always showed the
    bare "[image: NAME]" placeholder text, which mechanism L's own
    `_IMAGE_PLACEHOLDER_RE` filter then excluded from the text-position
    comparison entirely, leaving the embedded raster completely untested.
    Now resolves this document's own real doc.graphics references against
    its own on-disk path (same call answer_key.py's `_doc_entry` makes)
    and renders with `pictures='embed'` -- the product default, actually
    exercised. For a document with no picture reference this changes
    nothing (`resolve_document_pictures` returns `[]`, and 'embed' with no
    results to embed behaves identically to 'off')."""
    data = open(ws_path, 'rb').read()
    doc = core.parse(data)
    pix_results = ctrlkd_pictures.resolve_document_pictures(doc, ws_path)
    return pdfmod.emit_pdf(doc, mode='printed', pictures='embed', pix_results=pix_results)


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
             pcl_path: str = None, pdf_bytes: bytes = None,
             engine_words: dict = None) -> dict:
    """`ws_path` renders the CURRENT engine's own Printed PDF via
    render_engine_pdf(), same as ever. Pass `pdf_bytes` instead (any
    already-rendered PDF -- `ws_path` may then be None, kept only for the
    report's own 'ws_path' field) to compare a DIFFERENT engine's output
    against the same WS7 ground truth -- this is how the Swift/sr side
    reuses this tool without a second implementation of the whole gate
    (see main()'s `--pdf` flag). Pass `engine_words` instead of either
    (a dict already matching the schema load_engine_words() documents,
    e.g. json.load()ed from a file) to skip PDF PARSING entirely -- for
    an emitter this repo's own `_TEXT_OP_RE` cannot read at all (macOS
    Quartz's `Tm`/`TJ` operators over subset fonts; see main()'s
    `--engine-words` flag and fidelity_gate.py's own module docstring for
    the engine-words schema). At most one of `pdf_bytes`/`engine_words`
    should be passed; `engine_words` wins if both are (checked first,
    below)."""
    ws7 = json.load(open(measurements_path))
    n_ws7_pages = len(ws7['pages'])

    if engine_words is not None:
        loaded = load_engine_words(engine_words)
        n_engine_pages = loaded['n_engine_pages']
        eng_all = loaded['eng_tokens']
        eng_rasters_by_page = loaded['eng_rasters_by_page']
    else:
        if pdf_bytes is None:
            pdf_bytes = render_engine_pdf(ws_path)
        engine_pages = extract_pages(pdf_bytes)
        n_engine_pages = len(engine_pages)
        eng_all = []
        for i, p in enumerate(engine_pages):
            eng_all.extend(engine_page_tokens(p, i + 1))
        eng_rasters_by_page = {i + 1: engine_page_rasters(p, i + 1)
                               for i, p in enumerate(engine_pages)}

    # Build the WS7 whole-document token stream (each token carries its
    # own real page number) and match ONCE, globally, against eng_all
    # (built above, from whichever source) -- see match_doc's docstring
    # for why per-page-index matching breaks under pagination drift.
    ws7_all = []
    for i, p in enumerate(ws7['pages']):
        ws7_all.extend(ws7_page_tokens(p, p.get('page', i + 1)))

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
    # Grouping eng_all (built above, from whichever source) back by its
    # own 'page' field reproduces exactly the same per-page token lists
    # engine_page_tokens(p, i + 1) would have, in the same order
    # (concatenation-then-regroup is lossless) -- so this works
    # identically whether eng_all came from a freshly-parsed PDF or from
    # load_engine_words(), with no second pass over `engine_pages`.
    eng_tokens_by_page = defaultdict(list)
    for t in eng_all:
        eng_tokens_by_page[t['page']].append(t)
    eng_gaps_by_page = {}
    for pn in range(1, n_engine_pages + 1):
        _, gaps = engine_baseline_gaps(eng_tokens_by_page.get(pn, []))
        eng_gaps_by_page[pn] = gaps

    # Planning #211 (mechanism L revisited): raster (embedded-picture)
    # position, matched by page + emission order within a page -- the
    # corpus never carries more than one raster per page today, so
    # positional pairing (not text alignment, which doesn't apply to a
    # raster) is unambiguous; a future document with two pictures on one
    # page would pair them in the same left-to-right/top-to-bottom order
    # both sides draw them in. `ws7`/`engine` is None on whichever side
    # has fewer at that page/index -- never force-paired, same "unmatched
    # is reported, not guessed" discipline as match_doc. eng_rasters_by_page
    # was built above, from whichever engine-word source was given.
    ws7_rasters_by_page = {p.get('page', i + 1): ws7_page_rasters(p, p.get('page', i + 1))
                           for i, p in enumerate(ws7['pages'])}
    raster_report = []
    for pn in sorted(set(ws7_rasters_by_page) | set(eng_rasters_by_page)):
        ws7_r = ws7_rasters_by_page.get(pn, [])
        eng_r = eng_rasters_by_page.get(pn, [])
        for i in range(max(len(ws7_r), len(eng_r))):
            w = ws7_r[i] if i < len(ws7_r) else None
            e = eng_r[i] if i < len(eng_r) else None
            entry = {'page': pn, 'ws7': w, 'engine': e}
            if w is not None and e is not None:
                entry['dx'] = round(e['x'] - w['x'], 3)
                entry['dy'] = round(e['y_top'] - w['y_top'], 3)
                entry['dw'] = round(e['w_pt'] - w['w_pt'], 3)
                entry['dh'] = round(e['h_pt'] - w['h_pt'], 3)
            raster_report.append(entry)

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
        'rasters': raster_report,
        'pages': page_reports,
    }


# ------------------------------------------------------------- doc lookup
def _load_sources_index(prints_dir: str):
    """The parsed sources.json from `prints_dir`, or None if it doesn't
    exist there (an older corpus clone, or --pdf/--ws standalone use that
    never calls this at all) -- absence is not an error, it just means
    resolve_doc_paths falls back to the older group search."""
    index_path = os.path.join(prints_dir, SOURCES_INDEX_FILENAME)
    if not os.path.exists(index_path):
        return None
    with open(index_path) as f:
        return json.load(f)


def _install_for_subdir(prints_dir: str, subdir_name: str) -> str:
    """The 'install' provenance label for one capture set: that set's own
    sources.json top-level 'install' field when it declares one, else the
    documented default for that subdir (DEFAULT_INSTALL_BY_SUBDIR) -- v1's
    and v2's sources.json (v2 has none of its own at all) predate this
    field, v3's is expected to carry it directly once the capture job
    finishes."""
    index = _load_sources_index(prints_dir)
    if index is not None and index.get('install'):
        return index['install']
    return DEFAULT_INSTALL_BY_SUBDIR.get(subdir_name, 'unknown')


def resolve_doc_capture(doc_name: str) -> dict:
    """{'ws_path', 'measurements_path', 'pcl_path', 'capture_set',
    'install'} for a known corpus doc name -- the same resolution
    resolve_doc_paths (below) exposes as a 3-tuple, PLUS which capture
    round actually supplied measurements_path/pcl_path ('v3'/'v2'/'v1',
    see PRINTS_SUBDIR*) and that round's own install provenance
    ('pristine'/'sawyer-wschange'/...). 'ws_path' may be None (see
    resolve_doc_paths' own docstring for when/why) -- 'capture_set'/
    'install' are always populated regardless, since provenance is a
    property of the measurements data, not of whether a local .WS source
    also resolved.

    The ground-truth PCL capture data (NAME.measurements.json/.pcl) is
    NOT optional: it lives at $CTRLKD_PRIVATE_CORPUS/ws7-prints/v1/, and
    there is no flag or default to fall back to. An unset
    CTRLKD_PRIVATE_CORPUS, or a measurements.json that isn't there, FAILS
    LOUD naming the exact path -- never a silent skip, never a silent
    pass -- because a fidelity number computed against nothing would be
    worse than no number.

    The .WS source itself is resolved through ws7-prints/v1/sources.json
    when that index exists (see module docstring): every capture the
    index names resolves to $CTRLKD_PRIVATE_CORPUS/<its 'source' path>,
    regardless of which private group it lives under. Only when the
    index file itself is absent does this fall back to the older
    PRIVATE_DOCS/DEFAULT_AUTHORED_ROOT group search.

    Capture-set preference is v3 > v2 > v1 (Jon's ruling 2026-09-06: a
    pristine PRISTINE.EXE capture outranks either Sawyer-install round).
    v1 stays the default and the only capture directory ever required to
    exist at all (the RuntimeError below still checks v1 first, so an
    entirely uncaptured doc still fails loud naming its v1 path). v2 is
    checked via the index's own 'source' path (its own directory layout,
    see PRINTS_SUBDIR_V2); v3 uses v1's flat NAME.measurements.json
    naming instead (see PRINTS_SUBDIR_V3), so it's checked directly by
    doc_name, independent of whether the index resolves anything at all.
    Either one only ever REPLACES which measurements_path/pcl_path/
    capture_set this function returns, never which doc names are known."""
    if not _PRIVATE_CORPUS_ROOT:
        raise RuntimeError(
            f'{PRIVATE_CORPUS_ENV} is not set. Ground-truth PCL captures '
            f'for {doc_name} are expected at $'
            f'{PRIVATE_CORPUS_ENV}/ws7-prints/{PRINTS_SUBDIR}/'
            f'{doc_name}.measurements.json -- set {PRIVATE_CORPUS_ENV} to '
            'the private corpus root.')
    prints_dir = os.path.join(_PRIVATE_CORPUS_ROOT, 'ws7-prints', PRINTS_SUBDIR)
    measurements_path = os.path.join(prints_dir, f'{doc_name}.measurements.json')
    pcl_path = os.path.join(prints_dir, f'{doc_name}.pcl')
    if not os.path.exists(measurements_path):
        raise RuntimeError(
            f'ground-truth measurements not found: {measurements_path}')
    capture_set = PRINTS_SUBDIR

    v3_dir = os.path.join(_PRIVATE_CORPUS_ROOT, 'ws7-prints', PRINTS_SUBDIR_V3)
    v3_measurements = os.path.join(v3_dir, f'{doc_name}.measurements.json')
    v3_pcl = os.path.join(v3_dir, f'{doc_name}.pcl')
    has_v3 = os.path.exists(v3_measurements)

    ws_path = None
    index = _load_sources_index(prints_dir)
    if index is not None:
        entry = index.get('captures', {}).get(doc_name)
        if entry is not None:
            ws_path = os.path.join(_PRIVATE_CORPUS_ROOT, entry['source'])
            v2_dir = os.path.join(_PRIVATE_CORPUS_ROOT, 'ws7-prints', PRINTS_SUBDIR_V2)
            v2_measurements = os.path.join(v2_dir, f"{entry['source']}.measurements.json")
            v2_pcl = os.path.join(v2_dir, f"{entry['source']}.pcl")
            if os.path.exists(v2_measurements):
                measurements_path, pcl_path, capture_set = v2_measurements, v2_pcl, PRINTS_SUBDIR_V2
            if has_v3:
                measurements_path, pcl_path, capture_set = v3_measurements, v3_pcl, PRINTS_SUBDIR_V3
            install = _install_for_subdir(
                v3_dir if capture_set == PRINTS_SUBDIR_V3 else prints_dir, capture_set)
            return {'ws_path': ws_path, 'measurements_path': measurements_path,
                    'pcl_path': pcl_path, 'capture_set': capture_set, 'install': install}

    if has_v3:
        measurements_path, pcl_path, capture_set = v3_measurements, v3_pcl, PRINTS_SUBDIR_V3

    if doc_name in PRIVATE_DOCS:
        root = os.environ.get(ARCHIVE_ENV)
        if root:
            ws_path = os.path.join(root, PRIVATE_DOCS[doc_name])
    else:
        ws_path = os.path.join(DEFAULT_AUTHORED_ROOT, f'{doc_name}.WS')

    install = _install_for_subdir(
        v3_dir if capture_set == PRINTS_SUBDIR_V3 else prints_dir, capture_set)
    return {'ws_path': ws_path, 'measurements_path': measurements_path,
            'pcl_path': pcl_path, 'capture_set': capture_set, 'install': install}


def resolve_doc_paths(doc_name: str):
    """(ws_path, measurements_path, pcl_path) for a known corpus doc name,
    or (None, ...) if $CTRLKD_SAWYER_ARCHIVE is unset for an archive-only
    doc under the legacy fallback -- SKIP, not error (the archive is a
    legitimately optional public corpus; see the module docstring). Thin
    wrapper over resolve_doc_capture (above), which is what actually knows
    the resolution order and also reports capture-set/install provenance;
    kept as its own function since most callers (and most existing tests)
    only ever needed the three paths."""
    info = resolve_doc_capture(doc_name)
    return info['ws_path'], info['measurements_path'], info['pcl_path']


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
    ap.add_argument('--pdf', help='compare THIS already-rendered PDF instead of rendering '
                    'ws_path with this repo\'s own engine -- e.g. the Swift/sr engine\'s own '
                    'Printed PDF for the same named document. Pair with --doc NAME to resolve '
                    'the WS7 measurements/.pcl from the corpus as usual, or with an explicit '
                    '--measurements PATH [--pcl PATH] for a fully standalone comparison that '
                    'needs neither CTRLKD_PRIVATE_CORPUS nor CTRLKD_SAWYER_ARCHIVE.')
    ap.add_argument('--engine-words', help='compare a PRE-EXTRACTED engine-words JSON file '
                    'instead of a PDF -- for an emitter this repo cannot parse as a PDF at all '
                    '(e.g. macOS Quartz Tm/TJ output over subset fonts, which this file\'s own '
                    '_TEXT_OP_RE cannot match). See this file\'s own module-level "engine-words '
                    '(JSON)" comment block, just above dump_engine_words(), for the schema -- '
                    'produced by --dump-engine-words, below, or by any other emitter\'s own '
                    'dumper. Same --doc/--measurements resolution as --pdf; mutually exclusive '
                    'with --pdf.')
    ap.add_argument('--dump-engine-words', help='ALSO write the engine-words JSON this run '
                    'actually extracted (from the PDF rendered from ws_path, or from --pdf) to '
                    'this path -- lets the schema be produced from ctrl-kd\'s own PDF and '
                    'round-tripped (gate(pdf) == gate(--engine-words dump)). Not valid together '
                    'with --engine-words (there is no PDF to dump from in that mode).')
    ap.add_argument('--out-json')
    ap.add_argument('--batch', nargs='+', help='Doc names to run in one pass '
                    '(each via --doc-style resolution); writes one JSON per '
                    'doc into --out-dir')
    ap.add_argument('--out-dir')
    a = ap.parse_args(argv)

    if a.engine_words and a.pdf:
        ap.error('--engine-words and --pdf are mutually exclusive')
    if a.dump_engine_words and a.engine_words:
        ap.error('--dump-engine-words has no PDF to dump from when --engine-words is used')
    if (a.engine_words or a.dump_engine_words) and a.batch:
        ap.error('--engine-words/--dump-engine-words are not supported together with --batch')

    reports = []
    if a.batch:
        for name in a.batch:
            ws_path, mpath, pcl_path = resolve_doc_paths(name)
            if ws_path is None:
                print(f'fidelity_gate: {name}: skipped -- ${ARCHIVE_ENV} unset',
                      file=sys.stderr)
                continue
            if not os.path.exists(ws_path):
                print(f'fidelity_gate: {name}: skipped -- source not found',
                      file=sys.stderr)
                continue
            r = run_gate(name, ws_path, mpath, pcl_path)
            reports.append(r)
            if a.out_dir:
                os.makedirs(a.out_dir, exist_ok=True)
                json.dump(r, open(os.path.join(a.out_dir, f'{name}.json'), 'w'),
                          indent=2)
    elif a.pdf or a.engine_words:
        src = a.pdf or a.engine_words
        name = a.doc_opt or a.doc or os.path.splitext(os.path.basename(src))[0]
        if a.measurements:
            ws_path, mpath, pcl_path = a.ws, a.measurements, a.pcl
        else:
            if not (a.doc_opt or a.doc):
                ap.error('--pdf/--engine-words needs either --doc NAME (corpus resolution) or '
                         'an explicit --measurements PATH')
            ws_path, mpath, pcl_path = resolve_doc_paths(name)
        if a.engine_words:
            r = run_gate(name, ws_path, mpath, pcl_path,
                        engine_words=json.load(open(a.engine_words)))
        else:
            pdf_bytes = open(a.pdf, 'rb').read()
            if a.dump_engine_words:
                json.dump(dump_engine_words(pdf_bytes), open(a.dump_engine_words, 'w'), indent=2)
            r = run_gate(name, ws_path, mpath, pcl_path, pdf_bytes=pdf_bytes)
        reports.append(r)
        if a.out_json:
            json.dump(r, open(a.out_json, 'w'), indent=2)
    else:
        name = a.doc_opt or a.doc
        if not name:
            ap.error('need a doc name (positional, --doc) or --batch')
        if a.ws and a.measurements:
            ws_path, mpath, pcl_path = a.ws, a.measurements, a.pcl
        else:
            ws_path, mpath, pcl_path = resolve_doc_paths(name)
            if ws_path is None:
                print(f'fidelity_gate: {name}: skipped -- ${ARCHIVE_ENV} unset',
                      file=sys.stderr)
                return 0
        if a.dump_engine_words:
            pdf_bytes = render_engine_pdf(ws_path)
            json.dump(dump_engine_words(pdf_bytes), open(a.dump_engine_words, 'w'), indent=2)
            r = run_gate(name, ws_path, mpath, pcl_path, pdf_bytes=pdf_bytes)
        else:
            r = run_gate(name, ws_path, mpath, pcl_path)
        reports.append(r)
        if a.out_json:
            json.dump(r, open(a.out_json, 'w'), indent=2)

    print_table(reports)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
