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
   parser survives a future emitter change) with a small CONTENT-STREAM
   STATE MACHINE (`_tokenize_content` + `parse_text_ops`), not a fixed-shape
   regex. pdf.py writes text ops in at least three shapes depending on
   which call site fired -- plain (`Tf <rise> Ts [<tz> Tz] x y Td`),
   Tz-scaled proportional (same, with `Tz` present), and Symbol-face
   bold/italic (`_symbol_style_op`: `Tf [<tz> Tz] [2 Tr <w> w | 0 Tr]
   <rise> Ts (x y Td | a b c d x y Tm)`) -- and a REGEX keyed to one
   operand order silently drops every op in a shape it wasn't written for
   (see "READER BUG" below `_tokenize_content`). The state machine instead
   tokenizes the stream into name/number/string/array/operator tokens and
   tracks Tf/Tz/Ts/Tr/w/Td/TD/Tm/T* as PDF text state actually works
   (Tz/Ts/Tr persist across BT/ET; Td/Tm/T* only move the CURRENT text
   line's position) -- so it reads every `Tj`/`TJ`/`'`/`"` regardless of
   what order the surrounding state ops were written in, and regardless of
   which of Td/Tm placed the text.
3. Splits each PAGE's own text into WORD-granular positions from
   CHARACTERS, not from op/chunk boundaries (mechanism Z, 2026-09-07,
   Jon's ruling from the real-LaserJet paper scan of -SCREEN, corpus
   verdicts.json doc87 p6): every character of every text op is walked
   at its own x (the project's OWN AFM metrics, `ctrlkd.afm.
   string_width_pt`, and the run's OWN Tz scale, carried across ops
   within a page exactly as pdf.py's `tz_state` does -- so a Courier run
   holding several words gets the same per-word x pdf.py itself
   computed, without re-deriving pdf.py's internal HMI/pitch state), then
   re-segmented into words purely by those characters
   (`segment_words_from_chars`): a space, or a horizontal gap at or past
   the smaller of the two adjoining characters' own face's space-glyph
   width (`char_space_width_pt`, capped -- a proportional/font-
   substituted face's own nominal space width is not a safe merge
   threshold in this corpus, see that function's own comment). A font,
   style, or `Ts` rise change with NO such gap is NEVER itself a word
   boundary -- this is what lets e.g. -SCREEN's own cp437 Greek/math
   demo line (drawn as several zero-gap, alternating Symbol/Courier text
   ops, Symbol-styled characters untransliterated back to their real
   Unicode identity via `ctrlkd.symbolmap`) read as ONE word, matching
   WS7's own single captured chunk in both text and position.
   `tools/pcl_tolerance.py`'s `_merge_zero_gap_cross_font_chunks` builds
   the identical segmentation from WS7's own measurements.json chunks, so
   a word is the same set of characters on both sides regardless of which
   side happened to draw it as more than one op/chunk.
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
    # parser still cannot read (this file's `parse_text_ops` is a small
    # state machine over `Tf`/`Tz`/`Ts`/`Tr`/`Td`/`TD`/`Tm`/`Tj`/`TJ`/`'`/`"`
    # in any operand order, but it is NOT a general PDF interpreter -- e.g.
    # macOS Quartz's hex-string (`<...>`) text over CID/Type0 subset fonts,
    # where the string bytes are glyph indices, not characters, isn't
    # recoverable this way at all). Takes a PRE-EXTRACTED words JSON (see
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

    # --engine-chars: ONE LEVEL LOWER than --engine-words -- a PRE-EXTRACTED
    # CHARACTERS JSON (see the "engine-chars (JSON)" schema comment above
    # load_engine_chars(), below) instead of already-segmented words. This
    # repo does mechanism Z's own word segmentation itself
    # (segment_words_from_chars) -- the producer (e.g. the macOS app's own
    # Quartz-based PDF reader) hands over characters only, never
    # re-implementing that boundary rule on its own side:
    CTRLKD_PRIVATE_CORPUS=/path/to/corpus python3 tools/fidelity_gate.py \
        --doc LYING --engine-chars /path/to/lying-chars.json --out-json /tmp/lying-app.json

    # --dump-engine-chars: produce that same chars JSON from ctrl-kd's OWN
    # PDF -- round-trips as gate(pdf) == gate(--engine-chars dump(pdf)) ==
    # gate(--engine-words dump(pdf)); see tests/test_fidelity_gate.py's
    # round-trip tests.
    python3 tools/fidelity_gate.py --doc LYING --dump-engine-chars /tmp/lying-chars.json

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
from ctrlkd import symbolmap  # noqa: E402

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

# READER BUG (PCL tier, mechanism Z, 2026-09-07): a single regex keyed to
# ONE fixed operand order can never cover this emitter, because pdf.py
# itself has (at least) three call-site shapes and they don't share an
# order:
#   plain:        BT /Fn SIZE Tf <rise> Ts [<tz> Tz] x y Td (TEXT) Tj ET
#   faux-bold:     BT /Fn SIZE Tf [<tz> Tz] 2 Tr <w> w <rise> Ts x y Td (T) Tj ET
#   faux-oblique:  BT /Fn SIZE Tf [<tz> Tz] 0 Tr <rise> Ts a b c d x y Tm (T) Tj ET
# (`_symbol_style_op`, the sole writer of the last two shapes, is used ONLY
# for a Symbol-substituted run carrying 'b'/'i' styling -- see its own
# docstring in pdf.py.) A prior fix (2026-09-06, "ORDER BUG") flipped
# `_TEXT_OP_RE`'s Ts/Tz order to match the PLAIN shape and claimed
# verification against "every ops.append(b'BT ...' call site" -- but
# `_symbol_style_op` builds its op with `b' '.join(parts)`, not a literal
# `ops.append(b'BT ...')` grep hit, so that claim was never actually
# checked against it. The regex still matched only the plain shape: every
# bold/italic/bold-italic run on a substituted face (WARPRAYR's Univers
# body is Tz-only and WAS fixed by the 2026-09-06 change; a Symbol-face
# styled run, e.g. -SCREEN's Greek quote, was not) extracted as zero
# words, not "unmatched" -- silently invisible to the gate, not reported
# as a divergence. `_tokenize_content`/`parse_text_ops` below replace the
# regex with a small state machine that accepts any operand order at all,
# fixing this for the current three shapes and for any future one.
_UNESC_RE = re.compile(rb'\\(.)')

# Content-stream tokenizer: a literal string `(...)` (escapes handled by
# _unescape_pdf_text at the point of use), a name `/Name` (leading slash
# stripped), a TJ-style array `[...]` (its own contents re-tokenized by
# the same function when TJ is handled), a number, or an operator keyword
# (letters/digits/`*`, or the single-character `'`/`"` show-text
# operators). Good enough for THIS repo's own content streams (plain PDF
# 1.4, no inline images, no nested arrays, no comments) -- not a general
# PDF content-stream parser.
_CS_TOKEN_RE = re.compile(
    rb'\((?P<str>(?:[^()\\]|\\.)*)\)'
    rb'|/(?P<name>[^\s()<>\[\]{}/%]+)'
    rb'|\[(?P<arr>(?:[^\[\]\\]|\\.)*)\]'
    rb'|(?P<num>[-+]?(?:\d+\.\d*|\.\d+|\d+))'
    rb'''|(?P<op>[A-Za-z][A-Za-z0-9*]*|'|")''')

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


def _tokenize_content(content: bytes):
    """Yield (kind, value) for every literal/name/array/number/operator
    token in a content stream, in byte order. `kind` is 'str' (raw,
    still-escaped bytes -- pass to `_unescape_pdf_text`), 'name' (bytes,
    leading `/` stripped), 'arr' (raw bytes INSIDE a `[...]` TJ array, not
    yet tokenized -- callers that care re-run this function over it),
    'num' (bytes, a decimal literal), or 'op' (bytes, the operator
    keyword, e.g. `Tf`/`Td`/`Tm`/`Tj`/`'`/`"`). See `_CS_TOKEN_RE`."""
    for m in _CS_TOKEN_RE.finditer(content):
        kind = m.lastgroup
        yield kind, m.group(kind)


def parse_text_ops(content: bytes) -> list:
    """[{font, basefont-name(unresolved), size, tz, rise, x, y, text}, ...]
    in emission order -- one entry per `Tj`/`TJ`/`'`/`"` text-showing
    operator found inside a `BT..ET` block, ACCEPTING ANY OPERAND ORDER
    the surrounding state operators (`Tf`/`Tz`/`Ts`/`Tr`/`w`) were written
    in, and either `Td`/`TD` (relative move) or `Tm` (absolute matrix --
    only its `e`/`f` translation matters here, since a shear's `a b c d`
    leaves the text ORIGIN unmoved, exactly the property pdf.py's own
    faux-oblique shear relies on) for position. Replaces a former regex
    keyed to one fixed operand order -- see the "READER BUG" comment above
    `_CS_TOKEN_RE`.

    State-tracking rules (this is a small, purpose-built state machine,
    not a general PDF interpreter -- see `_tokenize_content`'s own
    docstring):
      - `tz` (Tz) and `tr` (Tr) are PDF TEXT STATE: they persist across
        `ET`/`BT` (and are only WRITTEN when they change -- pdf.py's own
        per-page `tz_state` discipline), so this carries them forward
        exactly like the old regex carried `tz` forward.
      - `font`/`size`/`rise` are re-set by every `BT..ET` block this
        emitter writes (`Tf` and `Ts` both appear in every call site,
        confirmed against pdf.py), so no cross-block carrying is needed
        for them, but nothing here would break if a future call site
        omitted one -- they simply keep their last value, same as tz/tr.
      - the text position (`x`, `y`) resets to (0, 0) at each `BT` (a
        fresh text line matrix, per the PDF spec) and is then set by
        `Td`/`TD` (added to the current position) or `Tm` (replaces it
        outright with the matrix's own `e`, `f`).
      - `w` (line width, used only alongside faux-bold's `Tr 2`) and `T*`
        (next-line, unused by this emitter -- no `Tl` leading is ever
        set) are consumed so they don't corrupt the operand stack, but
        carry no information this gate needs.
    A `TJ` array is flattened to one op: its adjustment numbers (kerning,
    not word gaps) are ignored and its strings concatenated, matching how
    a single `Tj` string already gets word-split on space runs downstream
    (`split_engine_op`) -- not exercised by pdf.py today (it never writes
    `TJ`), kept for forward-compatibility with a different emitter's PDF
    (see `--pdf`/`--engine-words` in this file's own module docstring)."""
    ops = []
    tz = TZ_DEFAULT
    tr = 0
    font = size = rise = None
    in_bt = False
    x = y = 0.0
    pending = []          # [(kind, value_bytes), ...] since the last operator

    def nums():
        return [float(v) for k, v in pending if k == 'num']

    def names():
        return [v for k, v in pending if k == 'name']

    def strs():
        return [v for k, v in pending if k == 'str']

    def arrs():
        return [v for k, v in pending if k == 'arr']

    for kind, val in _tokenize_content(content):
        if kind != 'op':
            pending.append((kind, val))
            continue
        if val == b'BT':
            in_bt = True
            x = y = 0.0
        elif val == b'ET':
            in_bt = False
        elif val == b'Tf':
            nm, sz = names(), nums()
            if nm and sz:
                font, size = nm[-1].decode(), int(sz[-1])
        elif val == b'Tz':
            n = nums()
            if n:
                tz = n[-1]
        elif val == b'Ts':
            n = nums()
            if n:
                rise = int(n[-1])
        elif val == b'Tr':
            n = nums()
            if n:
                tr = int(n[-1])
        elif val in (b'Td', b'TD'):
            n = nums()
            if len(n) >= 2:
                x += n[-2]
                y += n[-1]
        elif val == b'Tm':
            n = nums()
            if len(n) >= 6:
                x, y = n[-2], n[-1]
        elif val in (b'Tj', b"'", b'"') and in_bt:
            s = strs()
            if s and font is not None:
                ops.append({'font': font, 'size': size, 'tz': tz, 'rise': rise,
                           'x': x, 'y': y, 'text': _unescape_pdf_text(s[-1])})
        elif val == b'TJ' and in_bt:
            a = arrs()
            if a and font is not None:
                text = ''.join(_unescape_pdf_text(v) for k, v in
                               _tokenize_content(a[-1]) if k == 'str')
                ops.append({'font': font, 'size': size, 'tz': tz, 'rise': rise,
                           'x': x, 'y': y, 'text': text})
        # every other operator (Do, cm, q, Q, w, T*, ...) needs no state of
        # its own here -- just falls through to the operand-stack clear.
        pending = []
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
# MECHANISM Z, same-side segmentation (2026-09-07, Jon's ruling from the
# real-LaserJet paper scan of -SCREEN, the private corpus's own verdicts.json
# doc87 p6): both sides of this gate now build a "word" the SAME way --
# from CHARACTERS placed at an x position, not from however many
# text-showing ops (engine) or PCL print chunks (WS7) happened to carry
# them. A word boundary is a space character, or a real horizontal GAP
# (>= the smaller of the two adjoining characters' own face's
# space-glyph width -- char_space_width_pt) between one character's own
# x_end and the next one's own x_start; a font, size, style or rise
# change with NO such gap is never itself a boundary. This is what lets
# -SCREEN's own cp437 Greek/math demo line (four alternating Symbol/
# Courier text ops per styled repetition, zero gap between every one of
# them) merge into ONE word matching WS7's own single 14-character
# captured chunk, while a real typed space between two differently-styled
# words still splits them correctly either way -- see
# segment_words_from_chars below (this file) for the engine side and
# tools/pcl_tolerance.py's `_merge_zero_gap_cross_font_chunks` (mechanism
# Z) for the WS7 side, and tools/PCL-DIVERGENCE-TRIAGE.md mechanism Z for
# the full trace, including why the FIRST attempt at this (2026-09-07,
# reverted the same day) broke six previously-clean documents: it only
# ever touched the engine side, so a WS7 chunk pair at the identical zero
# gap (confirmed on SAWYER.WS's own 'WSMSGS.OVR' + '.]', mechanism J's
# own toggle-boundary correction already resolves their real, contiguous
# position) never merged to match it. Applying the SAME rule to both
# sides fixes both cases at once.
WORD_GAP_SLACK_PT = 0.15  # decipoint-quantization (WS7's own measurements.json
                          # is 0.1pt-granular) plus ordinary float rounding --
                          # subtracted from the gap threshold so a real,
                          # deliberately-typed space whose measured gap lands
                          # a hair under its own nominal space-glyph width
                          # (rounding, never a font-substitution artifact)
                          # still counts as a boundary. Small relative to
                          # every threshold this repo's own faces produce
                          # (7.2pt Courier at 12pt/10cpi; a proportional
                          # face's own space glyph is never this narrow
                          # either), so it never risks turning a real
                          # zero-ish gap (mechanism Z's own target, always
                          # exactly 0.0pt in every confirmed case) into a
                          # false boundary.


WORD_GAP_MAX_PT = 1.5  # same magnitude as tools/pcl_tolerance.py's own
                       # KERNING_MERGE_EPS_PT, this corpus's own already-
                       # validated safe bound for "close enough to be one
                       # continuous run" in a CG-Times/Univers-substituted
                       # PROPORTIONAL running size. A face under font
                       # substitution (every proportional face this repo
                       # ever draws -- Jon's base-14-only ruling) has no
                       # exact space-glyph metric to trust at all: real
                       # WS7 word-to-word gaps in this corpus's own
                       # CG-Times-substituted 12-16pt running text measure
                       # as low as ~2.8pt (confirmed: LYING.WS's own 'is'
                       # 'eternal;', a real two-word gap, not a font-
                       # substitution artifact -- mechanism Z's own
                       # literal "the face's own space width" threshold,
                       # ~3.0pt for 12pt Times-Roman, sat ABOVE that real
                       # gap and wrongly merged it, the same "widening a
                       # merge epsilon regresses the rest of the corpus"
                       # lesson mechanism C's own docstring already
                       # names). Capping the threshold here costs nothing
                       # against every CONFIRMED mechanism-Z target (the
                       # Greek/math line, WSMSGS.OVR+'.]', a footnote
                       # marker, H2O) -- every one of them is fixed-pitch
                       # Courier and measures EXACTLY 0.0pt, nowhere near
                       # this cap either way -- and a genuine fixed-pitch
                       # word gap is always at least one full cell
                       # (>=3.6pt at any size this corpus uses), safely
                       # above it too.


SUBSTITUTED_PROPORTIONAL_GAP_MAX_PT = 0.3  # 'serif'/'sans' (classify_font) are
                       # ALWAYS a font-substitution target in this repo (CG
                       # Times -> Times, Univers -> Helvetica -- Jon's
                       # base-14-only ruling; there is no OTHER way a serif/
                       # sans-classified basefont ever appears), so real WS7
                       # word-to-word spacing there is under the SAME
                       # driver-justification noise WORD_GAP_MAX_PT's own
                       # comment names -- except worse: it is not just
                       # SMALLER than a nominal space-glyph width, it can be
                       # SMALLER than WORD_GAP_MAX_PT itself (confirmed:
                       # LYING.WS's own 'speak'/'no', a real two-word gap,
                       # measures 0.78pt -- inside WORD_GAP_MAX_PT's own
                       # 1.5pt bound, which merged it into 'speakno').
                       # There is no single threshold in this corpus that
                       # cleanly separates "real proportional word gap" from
                       # "font-substitution zero-gap artifact" -- real gaps
                       # range from well under 1pt to several pt. So a
                       # substituted-proportional character pair merges
                       # ONLY at a genuinely near-zero gap (float/decipoint-
                       # quantization noise, comfortably above
                       # WORD_GAP_SLACK_PT so a true zero-gap font-switch --
                       # none confirmed in this corpus's own proportional
                       # text, but the same principle as the fixed-pitch
                       # case -- would still merge), never at anything
                       # resembling a real, if unusually tight, space.


def char_space_width_pt(basefont, size_pt, tz=100.0):
    """The natural width of ONE space glyph in `basefont` at `size_pt`,
    scaled by `tz` (PDF horizontal-scale percent, 100 = unscaled) -- the
    same per-character AFM metric this file already uses for a word's own
    advance (afm.string_width_pt), applied to the one character (' ')
    that stands in for "how far a deliberately typed space actually moves
    the pen" in this font/size/scale, then CAPPED (see WORD_GAP_MAX_PT's
    and SUBSTITUTED_PROPORTIONAL_GAP_MAX_PT's own comments -- a
    proportional face's own nominal space-glyph width is not a safe merge
    threshold in this corpus, and a font-SUBSTITUTED proportional face
    ['serif'/'sans', classify_font] is worse still). For Courier (or any
    other monospace face) the UNCAPPED value equals ONE FIXED-PITCH CELL
    exactly, since every glyph -- including the space -- shares one
    width; for a proportional face it is that face's own real space-glyph
    width, before the cap. Used by segment_words_from_chars as the
    word-boundary gap threshold."""
    w = afm.string_width_pt(' ', basefont, size_pt) if basefont else size_pt * 0.6
    cap = (SUBSTITUTED_PROPORTIONAL_GAP_MAX_PT
          if classify_font(basefont) in ('serif', 'sans') else WORD_GAP_MAX_PT)
    return min(w, cap) * (tz / 100.0)


def _finish_word(chars):
    """[char, ...] (one word's worth, in left-to-right order, as built by
    segment_words_from_chars) -> one word dict: every field of the FIRST
    character (the same "merged token keeps the first chunk's own
    position/font/size" convention tools/pcl_tolerance.py's own
    mechanism-C/K chunk merges already use), plus 'text' (every
    character's own text, concatenated) and 'x' (the first character's
    own x_start)."""
    first = chars[0]
    word = dict(first)
    word['text'] = ''.join(c['text'] for c in chars)
    word['x'] = first['x_start']
    return word


def segment_words_from_chars(chars: list) -> list:
    """[{'text', 'x_start', 'x_end', 'is_space', 'space_width_pt', ...any
    other word-representative fields the caller wants carried through},
    ...], already sorted left-to-right on ONE baseline -> [{'text', 'x',
    ...the first character's own carried fields}, ...] -- mechanism Z's
    own shared segmentation rule (see the comment block above
    WORD_GAP_SLACK_PT): a space character always ends the current word
    (and is itself dropped, never part of any word); otherwise a boundary
    falls wherever the gap since the previous NON-SPACE character's own
    x_end is >= the SMALLER of the two characters' own `space_width_pt`,
    minus WORD_GAP_SLACK_PT. A font/size/style/rise change alone is never
    a boundary -- only real horizontal distance is. Both
    engine_page_tokens (below, engine side) and
    tools/pcl_tolerance.py's `_merge_zero_gap_cross_font_chunks` (WS7
    side) call this exact function so a word is the same set of
    characters on both sides no matter which side happened to draw it as
    more than one op/chunk."""
    words = []
    cur = []
    for ch in chars:
        if ch['is_space']:
            if cur:
                words.append(_finish_word(cur))
            cur = []
            continue
        if cur:
            prev = cur[-1]
            gap = ch['x_start'] - prev['x_end']
            threshold = min(prev['space_width_pt'], ch['space_width_pt'])
            if gap >= threshold - WORD_GAP_SLACK_PT:
                words.append(_finish_word(cur))
                cur = []
        cur.append(ch)
    if cur:
        words.append(_finish_word(cur))
    return words


def _op_chars(op: dict, basefont, font_class: str) -> list:
    """One engine text op (parse_text_ops' own shape) -> [char dict, ...]
    in emission order: every character's own x_start/x_end (the SAME
    Tz-scaled AFM advance split_engine_op always used, just walked one
    character at a time instead of stopping at a token boundary),
    is_space, its own space_width_pt (char_space_width_pt), and its own
    DISPLAY text -- a character drawn in the Symbol or ZapfDingbats face
    is UNTRANSLITERATED back to the real Unicode character it actually
    represents (ctrlkd.symbolmap.transliterate, the SAME reversible map
    pdf.py itself consulted, in the other direction, to choose which byte
    to write -- see symbolmap.py's own module docstring) -- so e.g.
    -SCREEN's own Symbol-styled 'a'/'GpSs'/'tFQWdfe' compare directly
    against WS7's own cp437-decoded real Greek/math text
    ('α'/'ΓπΣσ'/'τΦΘΩδφε'); an ordinary Courier/Times/Helvetica character
    passes through unchanged. WIDTH is always measured off the RAW
    (untransliterated) character -- the actual glyph pdf.py placed, and
    the same AFM table pdf.py's own layout used -- never the display
    text, which exists purely for word-text comparison. Consumed by
    segment_words_from_chars, directly (engine_page_tokens) or via
    split_engine_op (kept for its own single-op callers/tests)."""
    kind = None
    if basefont:
        low = basefont.lower()
        if low.startswith('symbol'):
            kind = 'math'
        elif 'dingbat' in low:
            kind = 'symbols'
    space_w = char_space_width_pt(basefont, op['size'], op['tz'])
    chars = []
    cursor = op['x']
    for raw_ch in op['text']:
        w_nat = (afm.string_width_pt(raw_ch, basefont, op['size']) if basefont
                 else op['size'] * 0.6)
        w_actual = w_nat * (op['tz'] / 100.0)
        x_start, x_end = cursor, cursor + w_actual
        display = symbolmap.transliterate(raw_ch, kind) if kind else raw_ch
        chars.append({
            'text': display, 'x_start': x_start, 'x_end': x_end,
            'is_space': raw_ch == ' ', 'space_width_pt': space_w,
            'size': op['size'], 'basefont': basefont, 'font_class': font_class,
        })
        cursor = x_end
    return chars

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
    each character's own AFM natural width (ctrlkd.afm -- the identical
    table pdf.py's `_natural_width_pt` reads) times the op's OWN Tz/100
    scale. A thin wrapper over `_op_chars`/`segment_words_from_chars` (the
    general, cross-op/cross-chunk mechanism-Z machinery, above) scoped to
    ONE op's own characters -- since there is never a real position gap
    BETWEEN two characters this function itself placed (each one's
    x_start is the previous one's own x_end, by construction), the only
    boundary segment_words_from_chars ever finds within a single op is at
    a literal space character, so this reproduces the pre-mechanism-Z
    behaviour (split on space runs) byte for byte for a single-op caller.
    For a fixed-pitch (Courier) run this reproduces pdf.py's uniform
    per-character pitch exactly (Courier's AFM widths are constant); for a
    proportional run pdf.py already writes one Tj per word (see
    `_line_ops_printed`), so this only ever needs to split multi-word
    Courier/indent runs. `engine_page_tokens` (below) does NOT call this
    -- it needs to merge words ACROSS ops too (mechanism Z), so it walks
    `_op_chars`/`segment_words_from_chars` directly over a whole baseline;
    this function stays for any caller that only has one op in hand."""
    basefont_resolved = basefont
    font_class = classify_font(basefont_resolved)
    chars = _op_chars(op, basefont_resolved, font_class)
    return [(w['text'], w['x']) for w in segment_words_from_chars(chars)]


def engine_page_tokens(page: dict, page_no: int) -> list:
    """[{text, x, y_top, size, basefont, font_class, page}, ...] for one PDF
    page dict (from extract_pages), word-granular. `y_top`/`x` are
    PAGE-LOCAL (relative to this page's own top-left) -- pagination
    differences between the engine and WS7 are a SEPARATE finding (see
    run_gate's page-alignment tracking), not folded into this per-token
    position.

    MECHANISM Z (2026-09-07, Jon's ruling from the -SCREEN paper scan):
    every text-showing op on a page is first exploded into its own
    CHARACTERS (`_op_chars`), grouped by baseline (op['y'], rounded --
    same convention `ws7_page_tokens`'s WS7-side `by_y` grouping already
    uses), sorted left-to-right, and re-segmented into words purely by
    the characters themselves (`segment_words_from_chars`): a space, or a
    real horizontal gap -- NEVER by which Tj/op happened to carry them.
    A font/style switch with no such gap is not a boundary, so -SCREEN's
    own cp437 Greek/math demo line (four alternating Symbol/Courier text
    ops per styled repetition, zero gap the whole way across) now merges
    into ONE word, matching WS7's own single 14-character captured chunk
    -- and (`_op_chars`'s own untransliteration) with comparable TEXT too,
    not just position. A first attempt at this same idea (2026-09-07,
    reverted the same day) merged on the engine side ALONE and broke six
    previously-clean documents (a WS7 chunk pair at the identical zero
    gap, e.g. SAWYER.WS's own 'WSMSGS.OVR' + '.]', stayed unmerged on
    that side) -- see tools/pcl_tolerance.py's
    `_merge_zero_gap_cross_font_chunks` for the matching WS7-side half of
    this fix, and tools/PCL-DIVERGENCE-TRIAGE.md mechanism Z for the full
    trace."""
    mb_h = page['mediabox'][1]
    by_baseline = defaultdict(list)
    for op in parse_text_ops(page['content']):
        if _IMAGE_PLACEHOLDER_RE.match(op['text']):
            continue
        basefont = page['fonts'].get(op['font'])
        font_class = classify_font(basefont)
        by_baseline[round(op['y'], 3)].extend(_op_chars(op, basefont, font_class))
    out = []
    for y in sorted(by_baseline, reverse=True):  # reading order: top of page first
        chars = sorted(by_baseline[y], key=lambda c: c['x_start'])
        for w in segment_words_from_chars(chars):
            out.append({
                'text': w['text'],
                'x': w['x'],
                'y_top': mb_h - y,
                'size': w['size'],
                'basefont': w['basefont'],
                'font_class': w['font_class'],
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
# emitter (not just this repo's own pdf.py -- e.g. macOS Quartz's hex-string
# text over CID/Type0 subset fonts, whose glyph-index string bytes
# `parse_text_ops`'s state machine cannot turn back into characters at all)
# can be judged by the exact same matching/tolerance machinery
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
#                             # segment_words_from_chars splits on a space
#                             # character or a real horizontal gap, never
#                             # on punctuation, so e.g. a trailing comma
#                             # stays attached to its word.
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


# ---------------------------------------------------- engine-chars (JSON)
ENGINE_CHARS_SCHEMA_VERSION = 2

# A pre-extracted substitute for a Printed PDF, ONE LEVEL LOWER than
# engine-words: individual CHARACTERS instead of already-segmented words.
# Exists because the app coder's own first attempt to re-implement
# mechanism Z's own word-boundary rule (segment_words_from_chars, above)
# directly against Quartz's real PDF text (subset CID/Type0 fonts, real
# /Widths-derived advances) regressed -- Jon's ruling, 2026-09-07: an
# external PDF reader hands this gate CHARACTERS, and this gate does the
# word segmentation ITSELF, in ONE place, for both sides, so mechanism Z's
# own boundary rule is never re-implemented a second time by any consumer.
# `load_engine_chars()` converts this schema into the identical
# per-baseline character sequence `_op_chars` builds from a parsed PDF's
# own text ops, then calls `segment_words_from_chars` -- the SAME function
# `engine_page_tokens` (the ops-based path) already calls -- so a word is
# the same set of characters regardless of which side (this repo's own PDF
# parser, or an external reader handing over characters) built it.
#
# SCHEMA (version 2) -- top level:
#     {
#       "schema_version": 2,
#       "n_pages": <int>,           # same meaning as the words schema's own
#                                    # n_pages (see "engine-words (JSON)",
#                                    # above)
#       "chars": [ <char>, ... ],   # every CHARACTER on every page, in ANY
#                                    # order (page + reading order
#                                    # recommended for readability; nothing
#                                    # downstream depends on global order --
#                                    # load_engine_chars groups by page then
#                                    # by baseline itself, same as
#                                    # engine_page_tokens does for ops)
#       "rasters": [ <raster>, ... ] # IDENTICAL shape to the words schema's
#                                    # own "rasters" (see above); [] if none
#     }
#
# <char>:
#     {
#       "text": <str>,       # exactly ONE character -- a single Unicode
#                             # scalar value. A literal space (" ") is a
#                             # real character here, not omitted --
#                             # load_engine_chars treats text == " " as
#                             # is_space, exactly `_op_chars`'s own rule.
#       "x_pt": <float>,     # this character's own glyph ADVANCE START, in
#                             # points, PAGE-LOCAL top-left origin (same
#                             # convention as the words schema's own "x_pt"
#                             # -- see this file's module docstring,
#                             # "COORDINATE CONVENTION"). x increases
#                             # rightward.
#       "x_end_pt": <float>, # this character's own glyph ADVANCE END, in
#                             # points, PAGE-LOCAL -- i.e. x_pt plus however
#                             # far this ONE character actually moved the
#                             # pen. MUST be the ADVANCE end (the font's own
#                             # /Widths or /W entry for the glyph actually
#                             # shown, times any text-matrix scale already
#                             # in effect), NEVER the glyph's ink/bounding-
#                             # box end -- segment_words_from_chars measures
#                             # the GAP since the previous character's own
#                             # x_end_pt, so a glyph-box width (which can
#                             # overshoot or undershoot the true advance,
#                             # e.g. an italic 'f' or a tight kerned pair)
#                             # reports a wrong gap and can flip a
#                             # word-boundary decision either way. See the
#                             # TOLERANCE note on load_engine_chars() below
#                             # for the exact caveat this buys/costs.
#       "y_top_pt": <float>, # this character's own BASELINE, in points,
#                             # PAGE-LOCAL, down from the page's own top
#                             # edge -- IDENTICAL convention and meaning to
#                             # the words schema's own "y_top_pt". Rise
#                             # (PDF `Ts`) is NOT applied here: a
#                             # superscript/subscript character reports its
#                             # own TRUE baseline, the same "the pen never
#                             # actually moved" model mechanism G's own
#                             # engine-side handling already uses (see
#                             # test_engine_page_tokens_merges_a_superscript_
#                             # inside_a_word).
#       "size_pt": <float>,  # nominal font size in points -- same meaning
#                             # as the words schema's own "size_pt".
#       "font": <str|null>,  # same meaning as the words schema's own
#                             # "font", nullable (a subset/system font this
#                             # repo cannot name at all is fine as null --
#                             # word-boundary math never actually needs
#                             # this field once "font_class" below is
#                             # given; it survives only for the divergence
#                             # report's own font_exact_match diagnostic).
#       "font_class": <str>, # REQUIRED, same vocabulary and same "producer
#                             # must supply it, never re-derived" rule as
#                             # the words schema's own "font_class" (see
#                             # above) -- it is what char_space_width_pt's
#                             # own cap picks between (WORD_GAP_MAX_PT vs
#                             # SUBSTITUTED_PROPORTIONAL_GAP_MAX_PT).
#       "page": <int>        # 1-indexed engine page number, same meaning
#                             # as the words schema's own "page"
#     }
#
# <raster>: IDENTICAL shape to the words schema's own <raster> (above) --
# this level of extraction has nothing to do with rasters at all.


def dump_engine_chars(pdf_bytes: bytes) -> dict:
    """A PDF (any of this repo's own PDFs) -> the engine-chars JSON schema
    documented immediately above -- ONE LEVEL LOWER than dump_engine_words:
    every character `_op_chars` itself builds from `parse_text_ops`, before
    segment_words_from_chars ever merges them into a word. Exists so that
    schema can be produced from ctrl-kd's own PDF and ROUND-TRIPPED:
    run_gate(..., pdf_bytes=X), run_gate(..., engine_chars=dump_engine_chars(X))
    and run_gate(..., engine_words=dump_engine_words(X)) must all report
    byte-identical results for the same X -- tests/test_fidelity_gate.py's
    round-trip tests check exactly this claim, for every bundled sample,
    the Tier 1 synthetic styled fixtures, and the generated picture
    fixture. `--dump-engine-chars PATH` (see main()) is this function wired
    to the CLI's own PDF path. Skips the same `[image: NAME]` placeholder
    ops engine_page_tokens itself skips (mechanism L) -- see
    `_IMAGE_PLACEHOLDER_RE`."""
    engine_pages = extract_pages(pdf_bytes)
    chars, rasters = [], []
    for i, page in enumerate(engine_pages):
        pn = i + 1
        mb_h = page['mediabox'][1]
        for op in parse_text_ops(page['content']):
            if _IMAGE_PLACEHOLDER_RE.match(op['text']):
                continue
            basefont = page['fonts'].get(op['font'])
            font_class = classify_font(basefont)
            y_top = mb_h - op['y']
            for c in _op_chars(op, basefont, font_class):
                chars.append({
                    'text': c['text'], 'x_pt': c['x_start'], 'x_end_pt': c['x_end'],
                    'y_top_pt': y_top, 'size_pt': c['size'], 'font': c['basefont'],
                    'font_class': c['font_class'], 'page': pn,
                })
        for r in engine_page_rasters(page, pn):
            rasters.append({
                'x_pt': r['x'], 'y_top_pt': r['y_top'],
                'w_pt': r['w_pt'], 'h_pt': r['h_pt'], 'page': pn,
            })
    return {'schema_version': ENGINE_CHARS_SCHEMA_VERSION,
            'n_pages': len(engine_pages), 'chars': chars, 'rasters': rasters}


def _external_chars_to_tokens(chars: list) -> list:
    """[<char>, ...] (the engine-chars JSON schema's own per-character
    dicts, any order) -> [{'text','x','y_top','size','basefont',
    'font_class','page'}, ...] -- the SAME word-token shape
    engine_page_tokens() itself produces from a parsed PDF's own ops.
    Groups by page, then by baseline (y_top_pt, rounded to 3 places -- same
    convention `engine_page_tokens`'s own by_baseline grouping uses on
    op['y']), sorts each baseline left-to-right, rebuilds the exact
    per-character dict shape `_op_chars` produces (text/x_start/x_end/
    is_space/space_width_pt/size/basefont/font_class), and re-segments
    through `segment_words_from_chars` -- mechanism Z's own shared
    segmenter, reused rather than reimplemented. See the TOLERANCE note on
    load_engine_chars(), below, for the one place this path measurably
    differs from the ops-based path: char_space_width_pt's own `tz`
    argument."""
    by_page_baseline = defaultdict(lambda: defaultdict(list))
    for c in chars:
        space_w = char_space_width_pt(c.get('font'), c['size_pt'])
        by_page_baseline[c['page']][round(c['y_top_pt'], 3)].append({
            'text': c['text'], 'x_start': c['x_pt'], 'x_end': c['x_end_pt'],
            'is_space': c['text'] == ' ', 'space_width_pt': space_w,
            'size': c['size_pt'], 'basefont': c.get('font'),
            'font_class': c['font_class'],
        })
    out = []
    for page in sorted(by_page_baseline):
        by_y = by_page_baseline[page]
        # reading order: top of page first -- y_top_pt is the TOP-DOWN
        # convention (y increases DOWNWARD, this file's module docstring's
        # own "COORDINATE CONVENTION"), the OPPOSITE of the raw PDF y
        # engine_page_tokens' own by_baseline sorts (reverse=True) --
        # so here the smallest y_top_pt is the topmost line: ascending.
        for y in sorted(by_y):
            row = sorted(by_y[y], key=lambda ch: ch['x_start'])
            for w in segment_words_from_chars(row):
                out.append({
                    'text': w['text'], 'x': w['x'], 'y_top': y,
                    'size': w['size'], 'basefont': w['basefont'],
                    'font_class': w['font_class'], 'page': page,
                })
    return out


def load_engine_chars(data: dict) -> dict:
    """The engine-chars JSON schema (documented above) -> {'n_engine_pages',
    'eng_tokens', 'eng_rasters_by_page'} -- the exact same three things
    load_engine_words() produces, so run_gate()/pcl_tolerance.doc_report()
    run completely unmodified downstream regardless of whether the engine
    side came from a parsed PDF, a pre-extracted words JSON, or (this
    function) a pre-extracted CHARACTERS JSON. Only checks that
    'schema_version' is present, same discipline as load_engine_words().

    TOLERANCE NOTE (read this before feeding this gate real Quartz-reader
    output): `_op_chars` (the ops-based path, i.e. this repo's own PDF)
    computes each character's own `space_width_pt` via
    `char_space_width_pt(basefont, size_pt, tz)`, where `tz` is the PDF
    `Tz` (horizontal-scale percent) operand actually in force for that
    character's own text-showing op -- pdf.py sets a real, non-100 Tz
    routinely (the face-constant-Tz HMI-grid machinery,
    `_line_ops_printed`), so the boundary threshold this repo's own PDF
    gets checked against is itself Tz-scaled. The engine-chars schema
    deliberately carries NO "tz" field: a reader working from real glyph
    positions (Quartz's own `/Widths`- or `/W`-derived advances -- this
    note's own reason `x_end_pt` must be the ADVANCE end, never the glyph
    box) has ALREADY applied whatever text-matrix scale was in effect to
    produce `x_pt`/`x_end_pt`, so the measured GAP between two characters
    is already in real page points with that scale baked in.
    `char_space_width_pt` is called here with its default `tz=100.0` --
    i.e. the boundary CAP itself (WORD_GAP_MAX_PT /
    SUBSTITUTED_PROPORTIONAL_GAP_MAX_PT) is applied AS WRITTEN, in page
    points, AFTER any text-matrix scale, never re-scaled a second time by a
    `tz` this schema does not carry. This is the one place `_external_
    chars_to_tokens`'s own threshold can differ, in principle, from
    `_op_chars`'s (which scales the SAME cap by the op's own real `tz`) --
    the round-trip tests (tests/test_fidelity_gate.py, including
    WARPRAYR's own Univers-substituted Tz-scaled quote line) and the
    private corpus's 18 captured documents (checked manually, not in this
    repo's own test suite -- see tools/PCL-DIVERGENCE-TRIAGE.md mechanism
    Z) confirm it never actually flips a word-boundary decision anywhere
    in this repo's own bundled samples, Tier 1 fixtures, or that corpus:
    every real Tz this corpus uses is a legibility-preserving HMI-grid
    nudge close to 100 (never a deliberate condense/expand), and every
    confirmed real word gap sits well clear of either cap either way (see
    WORD_GAP_MAX_PT's and SUBSTITUTED_PROPORTIONAL_GAP_MAX_PT's own
    comments for the measured margins). A future reader whose real
    Tz-equivalent scale sits far from 100 on a run that ALSO sits near a
    cap boundary is the one case this note flags as unverified -- report
    it if found; the fix is a real `tz` field on a future schema version,
    not a silent guess here."""
    if 'schema_version' not in data:
        raise ValueError("engine-chars JSON missing required 'schema_version' key")
    eng_tokens = _external_chars_to_tokens(data['chars'])
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
             engine_words: dict = None, engine_chars: dict = None) -> dict:
    """`ws_path` renders the CURRENT engine's own Printed PDF via
    render_engine_pdf(), same as ever. Pass `pdf_bytes` instead (any
    already-rendered PDF -- `ws_path` may then be None, kept only for the
    report's own 'ws_path' field) to compare a DIFFERENT engine's output
    against the same WS7 ground truth -- this is how the Swift/sr side
    reuses this tool without a second implementation of the whole gate
    (see main()'s `--pdf` flag). Pass `engine_words` instead of either
    (a dict already matching the schema load_engine_words() documents,
    e.g. json.load()ed from a file) to skip PDF PARSING entirely -- for
    an emitter this repo's own `parse_text_ops` state machine still cannot
    read (macOS Quartz's hex-string text over CID/Type0 subset fonts; see
    main()'s `--engine-words` flag and fidelity_gate.py's own module
    docstring for the engine-words schema). Pass `engine_chars` instead (a
    dict matching load_engine_chars()'s own "engine-chars (JSON)" schema)
    to hand this gate raw CHARACTERS instead -- this repo does the word
    segmentation itself (mechanism Z's own `segment_words_from_chars`),
    never re-implemented by the producer (see main()'s `--engine-chars`
    flag and load_engine_chars()'s own TOLERANCE note). At most one of
    `pdf_bytes`/`engine_words`/`engine_chars` should be passed;
    `engine_chars` wins over `engine_words`, which wins over `pdf_bytes`
    (checked in that order, below)."""
    ws7 = json.load(open(measurements_path))
    n_ws7_pages = len(ws7['pages'])

    if engine_chars is not None:
        loaded = load_engine_chars(engine_chars)
        n_engine_pages = loaded['n_engine_pages']
        eng_all = loaded['eng_tokens']
        eng_rasters_by_page = loaded['eng_rasters_by_page']
    elif engine_words is not None:
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
                    '(e.g. macOS Quartz hex-string text over CID/Type0 subset fonts, whose glyph '
                    'indices this file\'s own parse_text_ops cannot turn back into characters). '
                    'See this file\'s own module-level "engine-words '
                    '(JSON)" comment block, just above dump_engine_words(), for the schema -- '
                    'produced by --dump-engine-words, below, or by any other emitter\'s own '
                    'dumper. Same --doc/--measurements resolution as --pdf; mutually exclusive '
                    'with --pdf.')
    ap.add_argument('--dump-engine-words', help='ALSO write the engine-words JSON this run '
                    'actually extracted (from the PDF rendered from ws_path, or from --pdf) to '
                    'this path -- lets the schema be produced from ctrl-kd\'s own PDF and '
                    'round-tripped (gate(pdf) == gate(--engine-words dump)). Not valid together '
                    'with --engine-words/--engine-chars (there is no PDF to dump from in that '
                    'mode).')
    ap.add_argument('--engine-chars', help='compare a PRE-EXTRACTED engine-chars JSON file -- '
                    'raw CHARACTERS, one level lower than --engine-words -- instead of a PDF. '
                    'For an external PDF reader (e.g. the macOS app\'s own Quartz-based reader) '
                    'that can hand over real character positions but must NOT re-implement '
                    'mechanism Z\'s own word-boundary rule itself: this gate does that '
                    'segmentation, in one place, for both sides. See this file\'s own '
                    'module-level "engine-chars (JSON)" comment block, just above '
                    'dump_engine_chars(), for the schema, and load_engine_chars()\'s own '
                    'TOLERANCE note. Same --doc/--measurements resolution as --pdf; mutually '
                    'exclusive with --pdf/--engine-words.')
    ap.add_argument('--dump-engine-chars', help='ALSO write the engine-chars JSON this run '
                    'actually extracted (from the PDF rendered from ws_path, or from --pdf) to '
                    'this path -- lets the schema be produced from ctrl-kd\'s own PDF and '
                    'round-tripped (gate(pdf) == gate(--engine-chars dump)). Not valid together '
                    'with --engine-words/--engine-chars (there is no PDF to dump from in that '
                    'mode).')
    ap.add_argument('--out-json')
    ap.add_argument('--batch', nargs='+', help='Doc names to run in one pass '
                    '(each via --doc-style resolution); writes one JSON per '
                    'doc into --out-dir')
    ap.add_argument('--out-dir')
    a = ap.parse_args(argv)

    if a.engine_words and a.pdf:
        ap.error('--engine-words and --pdf are mutually exclusive')
    if a.engine_chars and a.pdf:
        ap.error('--engine-chars and --pdf are mutually exclusive')
    if a.engine_chars and a.engine_words:
        ap.error('--engine-chars and --engine-words are mutually exclusive')
    if a.dump_engine_words and (a.engine_words or a.engine_chars):
        ap.error('--dump-engine-words has no PDF to dump from when --engine-words/--engine-chars '
                 'is used')
    if a.dump_engine_chars and (a.engine_words or a.engine_chars):
        ap.error('--dump-engine-chars has no PDF to dump from when --engine-words/--engine-chars '
                 'is used')
    if (a.engine_words or a.dump_engine_words or a.engine_chars
            or a.dump_engine_chars) and a.batch:
        ap.error('--engine-words/--dump-engine-words/--engine-chars/--dump-engine-chars are '
                 'not supported together with --batch')

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
    elif a.pdf or a.engine_words or a.engine_chars:
        src = a.pdf or a.engine_words or a.engine_chars
        name = a.doc_opt or a.doc or os.path.splitext(os.path.basename(src))[0]
        if a.measurements:
            ws_path, mpath, pcl_path = a.ws, a.measurements, a.pcl
        else:
            if not (a.doc_opt or a.doc):
                ap.error('--pdf/--engine-words/--engine-chars needs either --doc NAME '
                         '(corpus resolution) or an explicit --measurements PATH')
            ws_path, mpath, pcl_path = resolve_doc_paths(name)
        if a.engine_chars:
            r = run_gate(name, ws_path, mpath, pcl_path,
                        engine_chars=json.load(open(a.engine_chars)))
        elif a.engine_words:
            r = run_gate(name, ws_path, mpath, pcl_path,
                        engine_words=json.load(open(a.engine_words)))
        else:
            pdf_bytes = open(a.pdf, 'rb').read()
            if a.dump_engine_words:
                json.dump(dump_engine_words(pdf_bytes), open(a.dump_engine_words, 'w'), indent=2)
            if a.dump_engine_chars:
                json.dump(dump_engine_chars(pdf_bytes), open(a.dump_engine_chars, 'w'), indent=2)
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
        if a.dump_engine_words or a.dump_engine_chars:
            pdf_bytes = render_engine_pdf(ws_path)
            if a.dump_engine_words:
                json.dump(dump_engine_words(pdf_bytes), open(a.dump_engine_words, 'w'), indent=2)
            if a.dump_engine_chars:
                json.dump(dump_engine_chars(pdf_bytes), open(a.dump_engine_chars, 'w'), indent=2)
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
