#!/usr/bin/env python3
"""The WordStar run fixtures: this engine against what real WordStar did.

The WordStar teardowns keep scripted DOSBox-X runs of real WordStar 4.00 and
7.0 Rev. D: each run's input document, the files WordStar saved or the bytes
it sent to the printer, and an expected READING generated from those bytes
(schema `wordstar-reading/1`). A reading records only what WordStar's own
behaviour fixes (these bytes are a soft line end; the LaserJet put `line` at
x = 576, V = 480 on page 2), never what a converter's own formats should do
with it. Nothing is copied into this repo: `CTRLKD_TEARDOWNS` names the
teardowns checkout, and every fixture is read from there, in place, read-only.

Two sets, one manifest each (`<set>/fixtures/fixtures.json`, schema
`wordstar-run-fixtures/2`): `wordstar4-dos` and `wordstar-dos` (WS7). The
fixtures whose `use` is `reader`, `layout-printed` or `layout-lines` are for
the converters; every one of them carries a reading with one part per
document WordStar wrote or per print capture.

HOW EACH KIND OF FIXTURE IS COMPARED

`reader` -- the engine parses `part.file` (`core.parse`, auto-detect, the
CLI's defaults) and its physical lines are set against `part.lines`:

  - Dot lines (`dot: true`) are not body lines: the engine keeps them in
    `doc.meta['dot_commands']`, not in `doc.blocks`. They are checked by
    count only.
  - Text: the reading's `text` with U+00A0 (WordStar's justification and
    indent fill, `A0`) read as a plain blank, because the engine decodes
    `A0` to a blank. Where the reading names something WordStar prints, the
    engine's text may show it: a tab record as the blanks to its stop, a
    footnote/endnote record as its reference number, a binding space (`0F`)
    as a blank, an active soft hyphen as `-`. Characters below 20h are not
    text on either side. Trailing blanks are compared too: WordStar stores
    them.
  - A line ended by a form feed (`0C`), and a `.pa` dot line, are the
    engine's own `pagebreak` block; an empty form-feed line is nothing else.
  - An empty last line on one side only is the end of the file, not a line.
  - End: the reading's `end` against the engine line's own `soft` /
    `overprint` flags (`hard` = neither, `soft`, `overprint` = a lone 0D).
    `form feed` and `none` are compared as hard.
  - `variant`: the reading's `ws4`/`ws5+`/`nondocument` against what
    `core.detect` says (`nondocument` = `text` or `printstream`).

THE VARIANT. Many fixture inputs are plain ASCII the teardown sessions
wrote, which WordStar opened as a document; content-based detection calls
such a file `text` and lays it out as one. So every part is parsed as what
WordStar opened it as -- the release's document variant (`ws4`, `ws5+`) or
`text` for a nondocument -- exactly as `--variant` would, and a detection
that disagrees is reported on its own (kind `variant`).

`layout-printed` -- the engine renders `part.file` as Printed PDF (the
CLI's own defaults: `pictures='embed'`, as `fidelity_gate.render_engine_pdf`
does) and its words
are matched by text, in reading order, against the capture's decoded rows.
A row item is a run WordStar positioned; only the FIRST word of an item has
a known x (the blanks inside a run are not positioned). Coordinates: x is
the item's decipoints plus the PCL logical page's own 1/4" offset from the
paper's left edge (HP; WS7 teardown, `wordstar-dos/7-configuration.md` 7.7);
the engine's side is its page placed on the sheet the same way
(`pdf.logical_page_x`, read back from the page's leading `cm`). y is the
row's V, the baseline in decipoints from the page top. Page counts are
compared too. A word made only of box-drawing characters (the `.l#` bars, box
art) is drawn by the engine as vector cells, not text, so it is matched against
the layout JSON's `graphic_cells` on its page at its x (kind `missing-graphic`).

`layout-lines` -- WS4's DRAFT driver: rows of text, 1-based, a row = 1/6",
the paper's own left edge at column 0, blank rows left out, pages split at
form feeds. The same matching as `layout-printed`, with every word's x known
(column x 7.2pt, against the engine's x before it places the page on the
sheet: DRAFT has no logical page) and the baseline of row r at r x 12pt.

INSTALL. Each manifest's `install` names the settings its layout fixtures
assume: the FACTORY install of each release. This engine's own defaults are
WordStar's factory values; `install_problem()` checks that they agree, and
the parts are rendered with no page settings at all.

A MISMATCH is a fact to look at, not a verdict: it may be the engine, or a
rule the reading does not cover yet. `--report` prints every one.

    CTRLKD_TEARDOWNS=/path/to/teardowns python3 tools/teardown_fixtures.py --report [--json OUT]

After a deliberate change, `--update-known` rewrites the counts in
`tests/teardown_fixtures_known.json`, keeping every part's reason: it drops
the parts that now match, and refuses to write when a part mismatches for
the first time (that part needs its reason written first).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'src'))
sys.path.insert(0, _HERE)

from ctrlkd import core  # noqa: E402
from ctrlkd import pdf as pdfmod  # noqa: E402
from ctrlkd import pictures as ctrlkd_pictures  # noqa: E402
from ctrlkd import layout as layout_mod  # noqa: E402
import fidelity_gate as fg  # noqa: E402

ENV = 'CTRLKD_TEARDOWNS'
SETS = ('wordstar4-dos', 'wordstar-dos')
USES = ('reader', 'layout-printed', 'layout-lines')
MANIFEST_SCHEMA = 'wordstar-run-fixtures/2'
READING_SCHEMA = 'wordstar-reading/1'

# The PCL logical page starts 1/4" in from the paper's left edge.
PCL_LOGICAL_PAGE_X_PT = 18.0
# The engine prints a WS4 file as WS4's HPLJET does: line 1 sits its 1/3"
# vbias below the top margin, one line lower than DRAFT's row for it (WS4
# teardown 4 §15.2), and every later line keeps that offset at `.LH 8`.
DRAFT_TO_HPLJET_PT = 12.0
DRAFT_ROW_PT = 12.0
DRAFT_COL_PT = 7.2
# Position tolerance, in points: a decipoint is 0.1pt and the engine writes
# positions to 0.1pt, so two rounding steps.
POSITION_TOL_PT = 0.2

# Each release's factory install (the manifests' `install`) against this
# engine's own defaults.
_FACTORY_KEYS = {
    'wordstar4-dos': {'pl_lines': core.DEFAULT_PL_LINES, 'mt_lines': core.DEFAULT_MT_LINES,
                      'mb_lines': core.DEFAULT_MB_LINES, 'po_columns': core.DEFAULT_PO_COLS,
                      'hm_lines': core.DEFAULT_HM_LINES, 'fm_lines': core.DEFAULT_FM_LINES},
    'wordstar-dos': {'pl_in': core.DEFAULT_PL_LINES / 6, 'mt_in': core.DEFAULT_MT_LINES / 6,
                     'mb_in': core.DEFAULT_MB_LINES / 6, 'po_in': core.DEFAULT_PO_COLS / 10,
                     'hm_in': core.DEFAULT_HM_LINES / 6, 'fm_in': core.DEFAULT_FM_LINES / 6},
}

_HEX = re.compile(r'<([0-9A-F]{2})>')


def root():
    """The teardowns checkout, or None when the tier is not armed."""
    return os.environ.get(ENV) or None


def manifest_path(set_name, base=None):
    return os.path.join(base or root(), set_name, 'fixtures', 'fixtures.json')


def load_manifest(set_name, base=None):
    with open(manifest_path(set_name, base)) as f:
        return json.load(f)


def runs_dir(set_name, manifest, base=None):
    return os.path.normpath(os.path.join(os.path.dirname(manifest_path(set_name, base)),
                                         manifest['root']))


def manifest_problem(base=None):
    """One reason the armed tier cannot run, or None."""
    base = base or root()
    if not base:
        return f'{ENV} is not set'
    for s in SETS:
        p = manifest_path(s, base)
        if not os.path.isfile(p):
            return f'{ENV}={base}: no manifest at {s}/fixtures/fixtures.json'
        m = load_manifest(s, base)
        if m.get('schema') != MANIFEST_SCHEMA:
            return f'{s}: manifest schema {m.get("schema")!r}, this tier reads {MANIFEST_SCHEMA!r}'
    return None


def install_problem(set_name, manifest):
    """None when the manifest's install is this engine's factory default."""
    inst = manifest.get('install') or {}
    for key, ours in _FACTORY_KEYS[set_name].items():
        theirs = inst.get(key)
        if theirs is None or abs(float(theirs) - ours) > 0.002:
            return f'{set_name}: install {key}={theirs!r}, engine default {ours!r}'
    return None


def parts(base=None):
    """[(case_id, set_name, fixture, part_index, part)] for every converter
    fixture's reading part, both sets, manifest order."""
    out = []
    for s in SETS:
        m = load_manifest(s, base)
        for fx in m['fixtures']:
            if fx.get('use') not in USES:
                continue
            reading = fx.get('reading') or {}
            for i, part in enumerate(reading.get('parts', ())):
                tail = f'#{i}' if len(reading['parts']) > 1 else ''
                out.append((f'{s}/{fx["id"]}{tail}', s, fx, i, part))
    return out


def unhex(text):
    """The manifest's byte form (printable ASCII as itself, `<XX>` for any
    other byte) back to bytes."""
    out = bytearray()
    pos = 0
    for m in _HEX.finditer(text):
        out += text[pos:m.start()].encode('latin-1')
        out.append(int(m.group(1), 16))
        pos = m.end()
    out += text[pos:].encode('latin-1')
    return bytes(out)


# ------------------------------------------------------------------ reader
_FF = object()  # a form-feed line: the engine's own `pagebreak` block


def _engine_lines(doc):
    out = []
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            out.append(_FF)
        for ln in b.lines:
            out.append(ln)
    return out


def _end_of(line):
    if getattr(line, 'overprint', False):
        return 'overprint'
    return 'soft' if line.soft else 'hard'


# What may stand in the engine's text where a reading names a record or a
# mark that WordStar prints as something: a tab record is the blanks to its
# stop; a note record is its reference number; a binding space and an active
# soft hyphen print themselves.
_RECORD_PATTERN = {'09': ' *', '03': r'[0-9A-Za-z*]{0,3}', '04': r'[0-9A-Za-z*]{0,3}'}
_MARK_TEXT = {'0F': ' '}


def _expected_pattern(rl):
    """A regex the engine's text must match in full."""
    text = rl['text']
    inserts = []
    for pos, typ, *_rest in rl.get('records', ()):
        if typ in _RECORD_PATTERN:
            inserts.append((pos, _RECORD_PATTERN[typ]))
    for pos, byte, name in rl.get('marks', ()):
        if 'prints -' in name:
            inserts.append((pos, '-'))
        elif byte in _MARK_TEXT:
            inserts.append((pos, re.escape(_MARK_TEXT[byte])))
    out, last = [], 0
    for pos, pat in sorted(inserts, key=lambda t: t[0]):
        out.append(re.escape(text[last:pos].replace('\u00a0', ' ')))
        out.append(pat)
        last = pos
    out.append(re.escape(text[last:].replace('\u00a0', ' ')))
    return ''.join(out)


def _expected_text(rl):
    """The readable form of `_expected_pattern`, for reports."""
    return rl['text'].replace('\u00a0', ' ')


def _engine_text(line):
    """The line's text as WordStar has it: a note's reference mark (`fnref`,
    which also marks a `..` comment line's own anchor) is the engine's, not
    the file's, and control characters are not text."""
    return ''.join(ch for sp in line.spans if 'fnref' not in sp.styles
                   for ch in sp.text if ch >= ' ')


def _expected_end(rl):
    return {'soft': 'soft', 'overprint': 'overprint'}.get(rl['end'], 'hard')


def _expected_lines(part):
    out = []
    for rl in part['lines']:
        if rl.get('dot'):
            if re.match(r'\.pa\b', rl['text'], re.I):
                out.append(_FF)
            continue
        if rl['end'] == 'form feed':
            if rl['text']:
                out.append(rl)
            out.append(_FF)
        else:
            out.append(rl)
    return out


_DETECTED = {'ws4': ('ws4',), 'ws5+': ('ws5+',), 'nondocument': ('text', 'printstream')}
_PARSE_AS = {'ws4': 'ws4', 'ws5+': 'ws5+', 'nondocument': 'text'}
_RELEASE_VARIANT = {'wordstar4-dos': 'ws4', 'wordstar-dos': 'ws5+'}


def _ws_evidence(data):
    """True when the bytes carry anything a WordStar detector could go on: a
    soft return (`8D 0A`), a page mark (`0D 8A`, `8D 8A`), a high-bit byte
    outside a `1B xx 1C` character, or a WS5+ header record."""
    if b'\x8d\x0a' in data or b'\x0d\x8a' in data or b'\x8d\x8a' in data:
        return True
    if data[:1] == b'\x1d':
        return True
    stripped = re.sub(rb'\x1b[\x00-\xff]\x1c', b'', data)
    return any(b >= 0x80 for b in stripped)


def _variant_check(data, want):
    """[mismatch] when detection disagrees with how WordStar opened it. A file
    with nothing for a detector to go on is `variant-plain` (the tier's own
    synthetic ASCII inputs), kept apart from a real `variant` miss. A file
    WordStar was told to open as a nondocument fails only when detection
    refuses it outright: the mode was the user's choice, not the file's."""
    try:
        got = core.detect(data).get('variant')
    except Exception as exc:  # detection itself failing is a finding
        got = f'{type(exc).__name__}'
    if want == 'nondocument':
        return [{'kind': 'variant', 'want': want, 'got': got}] if got == 'binary' else []
    if got not in _DETECTED.get(want, (want,)):
        kind = 'variant' if _ws_evidence(data) else 'variant-plain'
        return [{'kind': kind, 'want': want, 'got': got}]
    return []


def compare_reader(part, data):
    """[mismatch] for one reader part, `data` being the file's bytes."""
    want_variant = part.get('variant')
    found = _variant_check(data, want_variant)
    doc = core.parse(data, variant=_PARSE_AS.get(want_variant))
    want = _expected_lines(part)
    n_dot = sum(1 for rl in part['lines'] if rl.get('dot'))
    got_dot = len(doc.meta.get('dot_commands') or ())
    if n_dot != got_dot:
        found.append({'kind': 'dot-count', 'want': n_dot, 'got': got_dot})
    got = _engine_lines(doc)
    # an empty last line on either side is the end of the file, not a line
    while len(got) > len(want) and got[-1] is not _FF and not got[-1].text():
        got.pop()
    while len(want) > len(got) and want[-1] is not _FF and not want[-1]['text']:
        want.pop()
    for i in range(max(len(want), len(got))):
        rl = want[i] if i < len(want) else None
        ln = got[i] if i < len(got) else None
        if rl is None:
            found.append({'kind': 'extra-line', 'line': i + 1,
                          'got': 'form feed' if ln is _FF else ln.text()})
            continue
        if ln is None:
            found.append({'kind': 'missing-line', 'line': i + 1,
                          'want': 'form feed' if rl is _FF else _expected_text(rl)})
            continue
        if rl is _FF or ln is _FF:
            if rl is not ln:
                found.append({'kind': 'form-feed', 'line': i + 1,
                              'want': 'form feed' if rl is _FF else _expected_text(rl),
                              'got': 'form feed' if ln is _FF else ln.text()})
            continue
        gt = _engine_text(ln)
        if not re.fullmatch(_expected_pattern(rl), gt):
            found.append({'kind': 'text', 'line': i + 1, 'want': _expected_text(rl), 'got': gt,
                          'raw': rl['raw']})
        we, ge = _expected_end(rl), _end_of(ln)
        if want_variant == 'nondocument' and we == 'soft':
            we = 'hard'    # a nondocument has no soft returns, only bytes
        if we != ge:
            found.append({'kind': 'end', 'line': i + 1, 'want': rl['end'], 'got': ge,
                          'term': rl['term']})
    return found


# ------------------------------------------------------------------ layout
def _decode_item(text):
    """A row item's text with the manifest's `<XX>` bytes as CP437."""
    return unhex(text).decode('cp437')


SUPSUB_RISE_DP = 45       # WS7 factory `.sr`: 3/48" = 45 decipoints
COURIER_CELL_DP = 72      # 10 cpi
SUPSUB_CELL_DP = 55.2     # 13.04 cpi (23 dots)


def _glue_hpljet_scripts(rows):
    """WS4's HPLJET prints a sub/superscript by moving V by `.SR` x 15
    decipoints, printing the character and moving back, with no H move: so
    the reading shows the base run, a row with only the script character and
    the run's own x, then the rest of the run at that x again (WS4 teardown 4
    §15.2, run hj-sr). A one-item row at the run's x, off the run's V, with
    the next row back on it, is glued onto the item it continues, and so is
    that next row when it too sits at the run's x."""
    out = []
    last = None                   # (row, item) the next continuation joins
    for i, row in enumerate(rows):
        items = [list(it) for it in row['items']]
        cont = (last is not None and len(items) == 1 and row['page'] == last[0]['page']
                and items[0][0] is not None and items[0][0] == last[1][0])
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        script = (cont and row['v'] != last[0]['v'] and nxt is not None
                  and nxt['page'] == row['page'] and nxt['v'] == last[0]['v'])
        if script or (cont and row['v'] == last[0]['v']):
            last[1][1] += items[0][1]
            continue
        if out and out[-1]['page'] == row['page'] and out[-1]['v'] == row['v']:
            out[-1]['items'].extend(items)
        else:
            out.append({**row, 'items': items})
        last = (out[-1], out[-1]['items'][-1]) if out[-1]['items'] else None
    return out


def prepare_printed_rows(rows, hpljet=False):
    """The LaserJet rows in the form the engine's words are compared with.

    - `<XX>` bytes become their CP437 characters (the `.l#` bars).
    - A strikeout is printed as a second pass of `-` over the struck word;
      the engine draws a rule instead. An item of nothing but `-` that
      starts at the same x as another item on its row is that pass.
    - A sub/superscript is a separate pass 45 decipoints off its line; the
      engine's words keep it attached to the word it follows. (WS4's HPLJET
      prints it differently: `_glue_hpljet_scripts`.) An item on a
      row 45 decipoints from a base row on the same page, starting where a
      base item ends (Courier cells), is glued onto that item, and so is a
      base item that starts where it ends (13.04-cpi cells).
    """
    out = []
    for row in rows:
        items = [_positioned_item(item) for item in row['items']]
        xs = [x for x, t in items if not re.fullmatch(r'-+', t)]
        items = [[x, t] for x, t in items if not (re.fullmatch(r'-+', t) and x in xs)]
        out.append({**row, 'items': items})
    if hpljet:
        return [r for r in _glue_hpljet_scripts(out) if r['items']]
    by_key = {(r['page'], r['v']): r for r in out}
    for row in out:
        for rise in (SUPSUB_RISE_DP, -SUPSUB_RISE_DP):
            base = by_key.get((row['page'], row['v'] + rise))
            if base is None:
                continue
            for item in list(row['items']):
                ix, itext = item
                if ix is None:
                    continue
                for b in base['items']:
                    bx, btext = b
                    if bx is not None and abs(bx + len(btext) * COURIER_CELL_DP - ix) <= 2:
                        b[1] = btext + itext
                        tail_x = ix + len(itext) * SUPSUB_CELL_DP
                        for nxt in list(base['items']):
                            if nxt is not b and nxt[0] is not None and abs(nxt[0] - tail_x) <= 3:
                                b[1] += nxt[1]
                                base['items'].remove(nxt)
                                break
                        row['items'].remove(item)
                        break
    return [r for r in out if r['items']]


RECT_RE = re.compile(r'\[rect [\d.]+x[\d.]+ \w+\]')


def _positioned_item(item):
    """[x, text] for one reading item, its text decoded. An item whose x is
    not its first word's carries a third element (FIXTURES.md): leading
    blanks keep their text (the blanks make the first word unpositioned);
    a letter-spaced `.UJ` run is its `word`, with no x."""
    x, text = item[0], _decode_item(item[1])
    note = item[2] if len(item) > 2 else {}
    if note.get('unpositioned') == 'letter-spaced':
        return [None, note.get('word', text)]
    return [x, text]


def _first_word_tokens(rows, page_key, pos_of):
    """Expected tokens from reading rows: [{text, page, x or None, y_top}].
    `pos_of(row, item_index, word_index, char_col)` returns (x, y_top) or
    (None, y_top) for a word whose x is not known."""
    out = []
    for row in rows:
        items = row['items'] if 'items' in row else [[None, row['text']]]
        for ii, (ix, text) in enumerate(items):
            col = 0
            for wi, m in enumerate(re.finditer(r'\S+', text)):
                x, y = pos_of(row, ix, wi, m.start())
                if wi == 0 and m.start() and ix is not None:
                    x = None    # blanks lead the run: its first word's x is not known
                out.append({'text': m.group(0), 'page': row[page_key], 'x': x, 'y_top': y})
                col = m.end()
    return out


def _printed_pos(row, ix, wi, _col):
    x = ix / fg.DECIPT_PER_PT + PCL_LOGICAL_PAGE_X_PT if wi == 0 and ix is not None else None
    return x, row['v'] / fg.DECIPT_PER_PT


def _draft_pos(row, _ix, _wi, col):
    return col * DRAFT_COL_PT, row['row'] * DRAFT_ROW_PT


_PLACED_RE = re.compile(rb'\Aq 1 0 0 1 ([\d.]+) 0 cm\n')


def _engine_tokens(pdf, on_paper=True):
    """The engine's words, its page count and its sheet height. A word placed
    off its sheet is dropped: WordStar puts words there too (a page number
    under `.pl 0`, or past a short `.PL` on DRAFT's continuous paper), and
    off the sheet neither side can be compared by position. The expected
    words get the same cut (`compare_layout`).

    The engine draws a Printed page in the printer's own frame and places it
    on the sheet with one leading `cm` (`pdf.logical_page_x`); `on_paper`
    adds that placement to every x, for a LaserJet reading measured from the
    paper's edge. DRAFT has no logical page: its columns are compared in the
    frame the engine laid out."""
    pages = fg.extract_pages(pdf)
    toks = []
    for n, page in enumerate(pages, 1):
        h = page['mediabox'][1]
        placed = _PLACED_RE.match(page['content'])
        dx = float(placed.group(1)) if placed and on_paper else 0.0
        for t in fg.engine_page_tokens(page, n):
            if 0 <= t['y_top'] <= h:
                t['x'] += dx
                toks.append(t)
    sheet_h = pages[0]['mediabox'][1] if pages else 11 * 72
    return toks, len(pages), sheet_h


def _engine_pieces(pdf, on_paper=True):
    """{(page, text): [(x, baseline from the top)]} for every text op the
    engine draws: the pieces WS7's LASERJET moves to, one op each."""
    out = {}
    for n, page in enumerate(fg.extract_pages(pdf), 1):
        h = page['mediabox'][1]
        placed = _PLACED_RE.match(page['content'])
        dx = float(placed.group(1)) if placed and on_paper else 0.0
        for op in fg.parse_text_ops(page['content']):
            out.setdefault((n, op['text'].strip()), []).append((op['x'] + dx, h - op['y']))
    return out


def pieces_match(rows, pieces):
    """True when the capture and the engine agree move for move: every item
    WS7 positioned starts at an engine piece with the same x, on its row or,
    for a sub/superscript pass, on the row it was raised from, and is that
    piece's text, or the text of that piece and the ones after it on the
    row (spans the driver printed with no move between them); and the
    engine draws no other piece. Stronger than matching words, and what a
    kerned or scripted WS7 line needs: its moves split words the word
    reader joins differently on each side."""
    rise = SUPSUB_RISE_DP / fg.DECIPT_PER_PT
    ops = sorted((page, x, y, text) for (page, text), spots in pieces.items() if text
                 for x, y in spots)
    used = set()
    for row in rows:
        y = row['v'] / fg.DECIPT_PER_PT
        lines = [y, y + rise, y - rise]
        for ix, text in row['items']:
            t = text.strip()
            if ix is None or not t or ' ' in t or t != text:
                return False
            x = ix / fg.DECIPT_PER_PT + PCL_LOGICAL_PAGE_X_PT
            on_row = [k for k, (pg, ox, oy, _t) in enumerate(ops) if pg == row['page']
                      and k not in used and any(abs(oy - ly) <= POSITION_TOL_PT for ly in lines)]
            start = next((k for k in on_row if abs(ops[k][1] - x) <= POSITION_TOL_PT
                          and t.startswith(ops[k][3])), None)
            if start is None:
                return False
            got, chain = ops[start][3], [start]
            for k in on_row:
                if len(got) >= len(t):
                    break
                if ops[k][1] > ops[chain[-1]][1] and t.startswith(got + ops[k][3]):
                    got += ops[k][3]
                    chain.append(k)
            if got != t:
                return False
            used.update(chain)
    return len(used) == len(ops)


def join_kerned_items(rows, pieces, words):
    """A word a kerning pair splits is two moves in WS7's PCL, so two items
    on its row (WS7 teardown, `wordstar-dos/11-print-engine.md` 11.17): join
    them into the one word the engine shows, but only where the engine draws
    BOTH pieces at the capture's own x's on that row and reads them as one
    word starting there. `pieces` is `_engine_pieces`; `words` the engine's
    tokens."""
    def drawn(page, x, y, text):
        return any(abs(px - x) <= POSITION_TOL_PT and abs(py - y) <= POSITION_TOL_PT
                   for px, py in pieces.get((page, text), ()))

    # A proportional sub/superscript is a pass 45 decipoints off its line
    # that `prepare_printed_rows` cannot glue by Courier cells: an item the
    # engine draws at that x on the base row (its rise apart) moves there.
    by_key = {(r['page'], r['v']): r for r in rows}
    for row in rows:
        for rise in (SUPSUB_RISE_DP, -SUPSUB_RISE_DP):
            base = by_key.get((row['page'], row['v'] + rise))
            if base is None:
                continue
            base_y = base['v'] / fg.DECIPT_PER_PT
            for item in list(row['items']):
                ix, text = item
                if ix is not None and text.strip() and ' ' not in text.strip() and drawn(
                        row['page'], ix / fg.DECIPT_PER_PT + PCL_LOGICAL_PAGE_X_PT, base_y,
                        text.strip()):
                    row['items'].remove(item)
                    base['items'].append(item)
                    base['items'].sort(key=lambda it: (it[0] is None, it[0] or 0))
    rows = [r for r in rows if r['items']]

    for row in rows:
        y = row['v'] / fg.DECIPT_PER_PT
        items = row['items']
        i = 0
        head = None             # the first piece of the word items[i] has become
        while i + 1 < len(items):
            (ax, at), (bx, bt) = items[i], items[i + 1]
            if (ax is None or bx is None or ' ' in at.strip() or not at.strip() or not bt.strip()
                    or at != at.rstrip() or bt != bt.lstrip()):
                i, head = i + 1, None
                continue
            head = head or at
            pa = ax / fg.DECIPT_PER_PT + PCL_LOGICAL_PAGE_X_PT
            pb = bx / fg.DECIPT_PER_PT + PCL_LOGICAL_PAGE_X_PT
            first = (at + bt).split()[0]
            one_word = any(w['page'] == row['page'] and abs(w['x'] - pa) <= POSITION_TOL_PT
                           and abs(w['y_top'] - y) <= POSITION_TOL_PT
                           and w['text'].startswith(first) for w in words)
            if one_word and drawn(row['page'], pa, y, head) and \
                    drawn(row['page'], pb, y, bt.split()[0] if ' ' in bt else bt):
                items[i] = [ax, at + bt]
                del items[i + 1]
            else:
                i, head = i + 1, None
    return rows


def _doc_for(path, variant):
    with open(path, 'rb') as f:
        return core.parse(f.read(), variant=variant)


# Runs made with a WS.EXE patched to another footnote-run setting (WS7 report
# 14.15): the setting lives in the program, not the document, so the harness
# hands it to the engine (`doc.meta['fnrun']`) for these runs by file prefix.
PATCHED_FNRUN = {'fnr0': 0, 'fnr3': 3, 'fnr4': 4, 'fnr5': 5, 'fnr6': 6,
                 'fnr7': 7, 'fnr99': 99}


def _printed_doc(path, variant):
    """`path` read as `variant`, with the run's patched program settings."""
    with open(path, 'rb') as f:
        doc = core.parse(f.read(), variant=variant)
    run = os.path.basename(path).split('-')[0]
    if run in PATCHED_FNRUN:
        doc.meta['fnrun'] = PATCHED_FNRUN[run]
    return doc


def render_printed(path, variant):
    """The Printed PDF the CLI would write for `path` read as `variant`."""
    doc = _printed_doc(path, variant)
    pix = ctrlkd_pictures.resolve_document_pictures(doc, path)
    return pdfmod.emit_pdf(doc, mode='printed', pictures='embed', pix_results=pix)


def _engine_graphic_rows(path, variant, on_paper):
    """[(page, [(char, x)])], one per printed line: the cp437 box-drawing
    cells the engine draws as vectors rather than text (the layout JSON's
    `graphic_cells`, with the page's placement on the sheet when `on_paper`)."""
    doc = _printed_doc(path, variant)
    rows = []
    for n, page in enumerate(json.loads(layout_mod.emit_layout(doc, mode='printed'))
                             ['printed']['pages'], 1):
        dx = page.get('logical_page_x', 0.0) if on_paper else 0.0
        for line in page['lines']:
            cells = line.get('graphic_cells') or []
            if cells:
                rows.append((n, [[c['char'], c['x'] + dx, False] for c in cells]))
    return rows


def _box_only(text):
    return bool(text) and all(fg._is_box_drawing_char(ch) for ch in text)


def _match_graphic(word, rows):
    """Consume the engine cells that draw `word` (a box-drawing run whose
    first cell is at word['x']) on its page; True when found."""
    for page, cells in rows:
        if page != word['page']:
            continue
        for i in range(len(cells) - len(word['text']) + 1):
            run = cells[i:i + len(word['text'])]
            if (not any(c[2] for c in run)
                    and ''.join(c[0] for c in run) == word['text']
                    and abs(run[0][1] - word['x']) <= POSITION_TOL_PT):
                for c in run:
                    c[2] = True
                return True
    return False


def compare_layout(part, path, variant, hpljet=False):
    """[mismatch] for one layout part; `path` is the printed document.
    `hpljet`: the engine prints this part as WS4's HPLJET, so DRAFT's rows
    sit `DRAFT_TO_HPLJET_PT` higher than the engine's lines."""
    with open(path, 'rb') as f:
        found = _variant_check(f.read(), {'ws4': 'ws4', 'ws5+': 'ws5+'}.get(variant, 'nondocument'))
    pdf = render_printed(path, variant)
    printed = 'v' in (part['rows'][0] if part['rows'] else {'v': 0})
    eng, n_pages, sheet_h = _engine_tokens(pdf, on_paper=printed)
    if printed:
        # A `[rect WxH fill]` item is a PCL rectangle the driver drew, not
        # text: this tool does not compare rectangles yet, so each is
        # counted, never silently dropped.
        source_rows = []
        for r in part['rows']:
            items = [it for it in r.get('items', []) if not RECT_RE.fullmatch(str(it[1]))]
            for it in r.get('items', []):
                if RECT_RE.fullmatch(str(it[1])):
                    found.append({'kind': 'rect-not-compared', 'text': it[1], 'page': r['page']})
            if items:
                source_rows.append({**r, 'items': items})
        rows = [r for r in prepare_printed_rows(source_rows, hpljet)
                if 0 <= r['v'] / fg.DECIPT_PER_PT <= sheet_h]
        if not hpljet:
            pieces = _engine_pieces(pdf)
            if pieces_match(rows, pieces) and part.get('pages') in (None, n_pages):
                return found
            rows = join_kerned_items(rows, pieces, eng)
        want = _first_word_tokens(rows, 'page', _printed_pos)
        check_y = True
    else:
        rows = [r for r in part['rows'] if r['row'] * DRAFT_ROW_PT <= sheet_h]
        want = _first_word_tokens(rows, 'page', _draft_pos)
        if hpljet:
            for w in want:
                w['y_top'] += DRAFT_TO_HPLJET_PT
        # DRAFT prints whole rows: a row is a line only at `.LH 8` (6 lpi)
        page = _doc_for(path, variant).meta.get('page') or {}
        check_y = page.get('lh_48', 8) == 8 and not page.get('lh_varies')
    if part.get('pages') is not None and part['pages'] != n_pages:
        found.append({'kind': 'pages', 'want': part['pages'], 'got': n_pages})
    # A run of box-drawing characters is drawn as vector cells, not text: it
    # is matched against the engine's graphic cells, on its page at its x.
    graphics = [w for w in want if w['x'] is not None and _box_only(w['text'])]
    if graphics:
        want = [w for w in want if not (w['x'] is not None and _box_only(w['text']))]
        rows_g = _engine_graphic_rows(path, variant, printed)
        for w in graphics:
            if not _match_graphic(w, rows_g):
                found.append({'kind': 'missing-graphic', 'text': w['text'], 'page': w['page'],
                              'x': round(w['x'], 2)})
    m = fg.match_doc(want, eng)
    for w, e in m['pairs']:
        if w['page'] != e['page']:
            found.append({'kind': 'page-of-word', 'text': w['text'], 'want': w['page'],
                          'got': e['page']})
            continue
        dy = round(e['y_top'] - w['y_top'], 2)
        if check_y and abs(dy) > POSITION_TOL_PT:
            found.append({'kind': 'y', 'text': w['text'], 'page': w['page'],
                          'want': round(w['y_top'], 2), 'got': round(e['y_top'], 2), 'd': dy})
        if w['x'] is not None:
            dx = round(e['x'] - w['x'], 2)
            if abs(dx) > POSITION_TOL_PT:
                found.append({'kind': 'x', 'text': w['text'], 'page': w['page'],
                              'want': round(w['x'], 2), 'got': round(e['x'], 2), 'd': dx})
    for w in m['unmatched_ws7']:
        found.append({'kind': 'missing-word', 'text': w['text'], 'page': w['page']})
    for e in m['unmatched_engine']:
        found.append({'kind': 'extra-word', 'text': e['text'], 'page': e['page']})
    return found


# ------------------------------------------------------------------ driver
def check_part(set_name, fixture, part, base=None):
    """[mismatch] for one part. Raises FileNotFoundError when the part's
    file is not in the checkout."""
    m = load_manifest(set_name, base)
    path = printed_document(runs_dir(set_name, m, base), part, fixture['use'])
    if fixture['use'] == 'reader':
        with open(path, 'rb') as f:
            return compare_reader(part, f.read())
    variant = _RELEASE_VARIANT[set_name] if fixture.get('mode') != 'nondocument' else 'text'
    hpljet = set_name == 'wordstar4-dos'
    return compare_layout(part, path, variant, hpljet)


class SourceUnavailable(Exception):
    """A part printed from a file the teardowns do not carry (a private
    corpus document, kept there only by its hash), and the corpus that has it
    is not armed here."""


def _private_source(part):
    """The private document a part with no `file` was printed from:
    `source` `sawyer/<path>` under $CTRLKD_SAWYER_ARCHIVE, or `private
    corpus: <name>` found by name under it or $CTRLKD_PRIVATE_CORPUS, and
    in either case only the file with the part's own sha256."""
    import hashlib
    source = part.get('source') or ''
    roots = [os.environ.get('CTRLKD_SAWYER_ARCHIVE'), os.environ.get('CTRLKD_PRIVATE_CORPUS')]
    roots = [r for r in roots if r]
    if not roots:
        raise SourceUnavailable(f'{source}: CTRLKD_SAWYER_ARCHIVE / CTRLKD_PRIVATE_CORPUS not set')
    want = part.get('sha256')

    def same(path):
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest() == want

    if source.startswith('sawyer/') and os.environ.get('CTRLKD_SAWYER_ARCHIVE'):
        path = os.path.join(os.environ['CTRLKD_SAWYER_ARCHIVE'], source[len('sawyer/'):])
        if os.path.isfile(path):
            if not same(path):
                raise ValueError(f'{source}: the archive copy is not the file WordStar printed '
                                 f'(sha256 differs)')
            return path
    name = source.split(':', 1)[-1].strip()
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn == name and same(os.path.join(dirpath, fn)):
                    return os.path.join(dirpath, fn)
    raise SourceUnavailable(f'{source}: not found, with its sha256, in the armed corpus')


def printed_document(runs, part, use):
    """The file a part is about. For a layout part that is the document
    WordStar printed: when the run edited the input before printing (typed
    a note, set a font) and saved it, that is the run's `-out-` file, which
    the reading does not always name; it is used whenever it exists and
    differs from the named `-in-` file. A part with no `file` was printed
    from a private corpus document (`_private_source`)."""
    if part.get('file') is None:
        return _private_source(part)
    path = os.path.join(runs, part['file'])
    if use == 'reader' or '-in-' not in part['file']:
        return path
    out = os.path.join(runs, part['file'].replace('-in-', '-out-'))
    if os.path.isfile(out):
        with open(path, 'rb') as a, open(out, 'rb') as b:
            if a.read() != b.read():
                return out
    return path


def _summary(found):
    kinds = {}
    for f in found:
        kinds[f['kind']] = kinds.get(f['kind'], 0) + 1
    return ', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))


def report(base=None):
    rows = []
    for case, s, fx, _i, part in parts(base):
        try:
            found = check_part(s, fx, part, base)
            error = None
        except Exception as exc:  # a crash is a result too
            found, error = [], f'{type(exc).__name__}: {exc}'
        rows.append({'case': case, 'use': fx['use'], 'claim': fx['claim'],
                     'cite': fx.get('cite', []), 'error': error, 'mismatches': found})
    return rows


KNOWN_PATH = os.path.join(_HERE, '..', 'tests', 'teardown_fixtures_known.json')


def update_known(rows, path=KNOWN_PATH):
    """Rewrite the known list's `kinds` from `rows`, keeping each reason."""
    with open(path) as f:
        known = json.load(f)
    old = known['parts']
    new, unreasoned = {}, []
    for r in rows:
        if r['error']:
            print(f'{r["case"]}: {r["error"]}', file=sys.stderr)
            return 1
        kinds = {}
        for m in r['mismatches']:
            kinds[m['kind']] = kinds.get(m['kind'], 0) + 1
        if not kinds:
            continue
        reason = old.get(r['case'], {}).get('reason')
        if not reason:
            unreasoned.append(f'{r["case"]} {kinds}')
            continue
        new[r['case']] = {'kinds': kinds, 'reason': reason}
    if unreasoned:
        print('new mismatches need a reason first (nothing written):', file=sys.stderr)
        for u in unreasoned:
            print('  ' + u, file=sys.stderr)
        return 1
    for case in sorted(set(old) - set(new)):
        print(f'now matches: {case}')
    for case in sorted(set(old) & set(new)):
        if old[case]['kinds'] != new[case]['kinds']:
            print(f'counts changed: {case} {old[case]["kinds"]} -> {new[case]["kinds"]}')
    known['parts'] = new
    with open(path, 'w') as f:
        json.dump(known, f, indent=1, ensure_ascii=False)
        f.write('\n')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--report', action='store_true', help='print every mismatch')
    ap.add_argument('--json', help='also write the full report as JSON here')
    ap.add_argument('--limit', type=int, default=8, help='mismatches shown per part')
    ap.add_argument('--update-known', action='store_true',
                    help='rewrite the known list\'s counts, keeping each reason')
    a = ap.parse_args(argv)
    problem = manifest_problem()
    if problem:
        print(problem, file=sys.stderr)
        return 2
    for s in SETS:
        ip = install_problem(s, load_manifest(s))
        if ip:
            print('install:', ip)
    rows = report()
    if a.update_known:
        return update_known(rows)
    clean = [r for r in rows if not r['mismatches'] and not r['error']]
    print(f'{len(rows)} parts: {len(clean)} match, {len(rows) - len(clean)} do not')
    for r in rows:
        if not r['mismatches'] and not r['error']:
            continue
        print(f'\n{r["case"]} [{r["use"]}] {r["claim"]}')
        print(f'  cite: {", ".join(r["cite"])}')
        if r['error']:
            print(f'  ERROR {r["error"]}')
            continue
        print(f'  {_summary(r["mismatches"])}')
        for f in r['mismatches'][:a.limit]:
            print('   ', json.dumps(f, ensure_ascii=False))
        if len(r['mismatches']) > a.limit:
            print(f'    ... {len(r["mismatches"]) - a.limit} more')
    if a.json:
        with open(a.json, 'w') as f:
            json.dump(rows, f, indent=1, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
