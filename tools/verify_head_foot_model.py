#!/usr/bin/env python3
"""planning #251 part d: proves the printed head/foot/auto-page-number MODEL
(`Page.header_lines`/`footer_lines`/`auto_pageno`, `emit_layout`'s own
`header_lines`/`footer_lines`/`auto_page_number`) agrees with what `emit_pdf`'s
own bytes actually draw, for every page of every document -- corpus-wide, not
just the two documents (sawyer/-SCREEN.WS, the app's own BOTHNOTE.WS) that
found the gap in the first place.

WHY this exists: `_attach_head_foot_lines_printed` and `_running_ops` both
call `_resolve_head_foot_lines` -- "the SAME function" -- and that was true
95% of the time, but `_attach_head_foot_lines_printed` used to `continue`
(skip entirely) on any page `_paginate_printed_notes` built as a bare Python
list rather than a `Page` instance (its footnote-area body pages), because a
bare list cannot carry the `header_lines`/`footer_lines`/`auto_pageno`
attributes the model writes. `_running_ops`'s own render loop has no such
skip -- it reads `getattr(pl, 'headers', None)` and draws regardless. Two
sources that could (and did) disagree: the model said `None` while the PDF
drew "1" at x=291.6/y=732.0 on -SCREEN.WS page 1. "PDF bytes unchanged"
proofs never caught this, because the writer's OWN path never moved -- only
the model's copy of it was stale. This script is the check that would have
caught it: it renders NOTHING from the model (the model is never a rendering
path) -- it reads the model's own resolved entries and confirms each one is
PRESENT, at the stated (text, x, y), in the real PDF bytes `emit_pdf` wrote.

Scope: the DEFAULT-options render only (`EmitOptions()`/no CLI flags) -- a
document rendered with `--headers off` or an explicit `--page-numbers on/off`
override is DELIBERATELY out of scope, per `_attach_head_foot_lines_printed`'s
own docstring: the model always resolves the document's own NATURAL 'auto'
state, a flag only ever tells the WRITER whether to draw it. That is a
different, already-documented divergence, not this defect.

Usage:
    tools/verify_head_foot_model.py [--archive DIR] [--all] [PATH ...]

    --archive DIR   Sawyer archive root (default: $CTRLKD_SAWYER_ARCHIVE).
                     Every 'convertible' document in tests/answer_key.json's
                     own 'sawyer' group is checked, plus the 4 bundled
                     samples. Omit --archive (and unset the env var) to run
                     the samples only.
    PATH ...        Additional individual files to check (e.g. a private
                     overlay's own fixtures) -- checked in addition to
                     whatever --archive/env selects, never a replacement for
                     it.
    --all           Report every mismatch found instead of stopping at the
                     first document that has one.

Exit status: 0 iff every page of every document checked has a model that
agrees with the PDF bytes. Non-zero (with every mismatch printed) otherwise.
"""
import argparse, json, os, re, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'src'))

from ctrlkd import core                                    # noqa: E402
from ctrlkd.emit import hf_runs                              # noqa: E402
from ctrlkd.layout import emit_layout                       # noqa: E402
from ctrlkd.pdf import emit_pdf, _ESC_FALLBACK, _PDF_PT_PER_COL  # noqa: E402

CONTROL_RE = re.compile(rb'[\x00-\x1f]')


def _degrade(text):
    """The exact raw bytes `_esc()` puts inside a Tj literal for `text`
    (before `_esc()`'s own backslash-escaping, which this script's
    `_unescape` already reverses on the PDF side) -- text.WS7's own cp1252/
    WinAnsiEncoding cannot carry every glyph a WordStar document can type
    (box-drawing characters, some typographic marks): `_esc()` degrades
    those through a lookalike table FIRST (imported here as `_ESC_FALLBACK`,
    not reimplemented -- e.g. a box-drawing vertical bar becomes an ASCII
    `|`), then falls back to a bare `?` for anything cp1252 still can't
    represent. This is a general property of EVERY printed-PDF text
    string, not specific to header/footer/auto-page-number -- the JSON
    model (both the head/foot fields this script checks and the ordinary
    body-line `segments` text) always keeps the full original glyph;
    only the PDF bytes degrade it, at render time. Applying the identical
    degradation here (imported, not re-derived) is what lets this script
    tell a REAL model/PDF disagreement apart from this already-documented,
    unrelated cp1252 ceiling (found corpus-wide on sawyer/LSRBOX.WS's own
    box-drawing running head while first proving this script out)."""
    return text.translate(_ESC_FALLBACK).encode('cp1252', 'replace')

# The writer's own text-showing operator shape (`_running_ops`/`_hf_line_ops`/
# `_page_stream`, all of pdf.py): `BT /Fn SIZE Tf RISE Ts [TZ Tz ][X Y Td ](LIT) Tj ET`
# -- the `Tz`/`Td` groups are each optional (a continuation run on a proportional
# line reuses the pen position and omits `Td`; `Tz` is only written when it
# changes). Matches this project's own emitted bytes only -- not a general PDF
# content-stream parser.
_TJ_RE = re.compile(
    rb'BT /F(\d+) (-?\d+) Tf (-?\d+) Ts '
    rb'(?:(-?[\d.]+) Tz )?(?:(-?[\d.]+) (-?[\d.]+) Td )?'
    rb'\((.*?)\) Tj ET')


def _unescape(literal):
    """Undo `_esc()`: backslash escapes exactly one following byte (`\\`, `(`, `)`)."""
    out = bytearray()
    i = 0
    while i < len(literal):
        if literal[i:i + 1] == b'\\' and i + 1 < len(literal):
            out.append(literal[i + 1])
            i += 2
        else:
            out.append(literal[i])
            i += 1
    return bytes(out)


def content_spans(stream_bytes):
    """[(x_or_None, y_or_None, text), ...] in stream order for ONE page's own
    content stream."""
    spans = []
    for m in _TJ_RE.finditer(stream_bytes):
        _font, _size, _rise, _tz, x, y, lit = m.groups()
        spans.append((float(x) if x is not None else None,
                     float(y) if y is not None else None,
                     _unescape(lit)))
    return spans


def split_page_streams(pdf_bytes):
    """One entry per page content stream, in REAL page order -- walked from
    the PDF's own object graph (`/Type /Catalog` -> `/Pages` -> `/Kids` ->
    each `/Type /Page`'s own `/Contents`), not guessed from which
    `stream`/`endstream` blocks happen to contain text ops. A page with NO
    text at all (an empty page, or one whose only content is vector ops)
    still gets its own entry here -- `b''` if its `/Contents` stream truly
    has none -- so a document with such a page is counted correctly instead
    of silently losing a slot and shifting every later page's own stream out
    of alignment with `pages_model`.

    This project's own writer never compresses a content stream (checked,
    not assumed -- a `/Filter` anywhere means this script's assumptions no
    longer hold)."""
    assert b'/Filter' not in pdf_bytes, (
        "compressed content stream -- this script assumes ctrl-kd's own "
        "always-uncompressed writer")
    objs = {}
    for m in re.finditer(rb'(\d+) 0 obj\s*(.*?)endobj', pdf_bytes, re.DOTALL):
        num = int(m.group(1))
        body = m.group(2)
        sm = re.search(rb'stream\r?\n(.*?)endstream', body, re.DOTALL)
        objs[num] = (body, sm.group(1) if sm else None)

    cat_num = next((n for n, (body, _s) in objs.items()
                    if b'/Type /Catalog' in body), None)
    assert cat_num is not None, "no /Type /Catalog object found"
    m = re.search(rb'/Pages (\d+) 0 R', objs[cat_num][0])
    assert m, "/Type /Catalog has no /Pages reference"

    def _leaf_pages(pages_num):
        body = objs[pages_num][0]
        km = re.search(rb'/Kids \[(.*?)\]', body, re.DOTALL)
        assert km, f"object {pages_num} (/Type /Pages) has no /Kids array"
        out = []
        for kid in (int(x) for x in re.findall(rb'(\d+) 0 R', km.group(1))):
            kid_body = objs[kid][0]
            if b'/Type /Pages' in kid_body:
                out += _leaf_pages(kid)
            else:
                out.append(kid)
        return out

    out = []
    for page_num in _leaf_pages(int(m.group(1))):
        page_body = objs[page_num][0]
        cm = re.search(rb'/Contents (\d+) 0 R', page_body)
        out.append(objs[int(cm.group(1))][1] or b'' if cm else b'')
    return out


def check_document(path):
    """Returns (mismatches: [str], error: str|None). `error` means the
    document could not be checked at all (parse/emit failure) -- distinct
    from an empty `mismatches` list (checked clean)."""
    try:
        data = open(path, 'rb').read()
    except OSError as e:
        return [], f"could not read: {e}"
    try:
        doc = core.parse(data)
    except Exception as e:
        return [], f"parse error: {e!r}"
    try:
        layout = json.loads(emit_layout(doc, mode='printed'))
    except Exception as e:
        return [], f"emit_layout error: {e!r}"
    try:
        pdf_bytes = emit_pdf(doc, mode='printed')
    except Exception as e:
        return [], f"emit_pdf error: {e!r}"

    pages_model = layout.get('printed', {}).get('pages', [])
    try:
        page_streams = split_page_streams(pdf_bytes)
    except AssertionError as e:
        return [], str(e)

    if len(page_streams) < len(pages_model):
        return [], (f"PDF has {len(page_streams)} page content stream(s), "
                    f"model has {len(pages_model)} page(s)")

    mismatches = []
    for pi, pg in enumerate(pages_model):
        spans = content_spans(page_streams[pi])

        auto = pg.get('auto_page_number')
        if auto is not None:
            want_x, want_y = round(auto['x'], 1), round(auto['y'], 1)
            found = any(
                x is not None and y is not None
                and text == _degrade(auto['text'])
                and round(x, 1) == want_x and round(y, 1) == want_y
                for x, y, text in spans)
            if not found:
                mismatches.append(
                    f"page {pi + 1}: auto_page_number {auto['text']!r} at "
                    f"({want_x}, {want_y}) not drawn anywhere in the PDF's "
                    f"own page {pi + 1} content stream")

        for kind, key in (('header', 'header_lines'), ('footer', 'footer_lines')):
            for li, entry in enumerate(pg.get(key) or []):
                # `header_lines[i]['text']` is documented as PRE-styling: "a
                # consumer runs it through the SAME hf_runs-shaped styling
                # pass the raw headers/footers dict already requires" (see
                # `emit_layout`'s own docstring, version 6). `hf_runs`
                # (imported, not reimplemented) is also where the one
                # documented cp437-lookalike text substitution lives (the
                # '∙'->'•' collapse, register C9) -- comparing the MODEL's
                # raw text directly against drawn PDF bytes without this
                # pass is a false mismatch, not a real one (found on
                # sawyer/LJ6DTP.WS's own running head while first proving
                # this script out).
                runs = hf_runs(entry['text'])
                want_y = round(entry['y'], 1)
                if not runs:
                    # A slot carrying ONLY WordStar style-toggle bytes (no
                    # visible glyph at all, e.g. an unpaired `^O`/shift-in
                    # pair with nothing typed between them) resolves to no
                    # runs at all (`hf_runs`' own "returns [] for a head
                    # that is nothing but control bytes" -- LJ6DTP.WS's own
                    # `.f1` is its named example) -- nothing to require in
                    # the PDF here (measured: sawyer/ARTICLES/FORMFEED.WS's
                    # own `.h1` is the same shape).
                    continue
                # `x`: documented as simply the page's own resolved LEFT
                # (`_resolve_head_foot_lines`'s own docstring: "x is simply
                # the caller's already-resolved left ... no header/footer
                # line's own starting x has ever depended on page_no"),
                # NOT a promise that the first glyph drawn sits exactly
                # there. One real writer mechanism moves it AND drops text:
                # a fontless leading run on a PROPORTIONAL header/footer
                # face is re-stamped as 10-CPI machine-width ADVANCE
                # instead of being drawn as glyphs at all (`_hf_line_ops`'s
                # own "WordStar re-stamps a tab-derived leading indent as
                # 10-CPI machine spaces" -- confirmed corpus-wide on
                # sawyer/LJ6DTP.WS and sawyer/REF/WSFORMAT.WS, both real
                # `.h#`/`.f#` font blocks with a right-tab-baked leading
                # indent) -- replicated here (imported `_PDF_PT_PER_COL`,
                # the SAME constant, not a re-derived one) exactly for that
                # one documented case: the leading run is dropped from
                # BOTH the expected text and the expected x baseline;
                # every other line's expected x/text are the model's own,
                # unmodified.
                want_x = round(entry['x'], 1)
                font_idx = entry.get('font')
                proportional = (font_idx is not None and 0 <= font_idx < len(doc.fonts)
                                and doc.fonts[font_idx].get('proportional'))
                drawn_runs = runs
                if proportional and not runs[0][0].strip():
                    want_x = round(entry['x'] + len(runs[0][0]) * _PDF_PT_PER_COL, 1)
                    drawn_runs = runs[1:]
                want_text = CONTROL_RE.sub(b'', b''.join(_degrade(t) for t, _s in drawn_runs))
                if not want_text:
                    continue
                row = sorted(
                    (x, text) for x, y, text in spans
                    if y is not None and round(y, 1) == want_y)
                if not row:
                    mismatches.append(
                        f"page {pi + 1}: {kind}_lines[{li}] {entry['text']!r} "
                        f"at y={want_y} -- no PDF text drawn on that row at all")
                    continue
                got_x = row[0][0]
                got_text = CONTROL_RE.sub(b'', b''.join(t for _, t in row))
                if got_text != want_text:
                    mismatches.append(
                        f"page {pi + 1}: {kind}_lines[{li}] text {want_text!r} "
                        f"!= PDF row text {got_text!r} at y={want_y}")
                if got_x is not None and round(got_x, 1) != want_x:
                    mismatches.append(
                        f"page {pi + 1}: {kind}_lines[{li}] x {want_x} != "
                        f"PDF row x {round(got_x, 1)} at y={want_y}")
    return mismatches, None


def _sawyer_convertible_paths(archive):
    key_path = os.path.join(_HERE, '..', 'tests', 'answer_key.json')
    with open(key_path) as f:
        key = json.load(f)
    convertible = key['groups']['sawyer']['convertible']
    return sorted(os.path.join(archive, entry['path'])
                  for entry in convertible.values())


def _sample_paths():
    import importlib.resources
    from ctrlkd.cli import SAMPLE_NAMES
    out = []
    samples_dir = importlib.resources.files('ctrlkd').joinpath('samples')
    for name in SAMPLE_NAMES:
        with importlib.resources.as_file(samples_dir.joinpath(name)) as p:
            out.append(str(p))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='*', help='extra individual files to check '
                    '(e.g. a private overlay\'s own fixtures)')
    ap.add_argument('--archive', default=os.environ.get('CTRLKD_SAWYER_ARCHIVE'),
                    help='Sawyer archive root (default: $CTRLKD_SAWYER_ARCHIVE)')
    ap.add_argument('--all', action='store_true',
                    help='report every mismatching document, not just the first')
    args = ap.parse_args(argv)

    targets = list(_sample_paths())
    if args.archive:
        targets += _sawyer_convertible_paths(args.archive)
    else:
        print('note: --archive/$CTRLKD_SAWYER_ARCHIVE not set -- checking the '
              '4 bundled samples only', file=sys.stderr)
    targets += args.paths

    checked = 0
    failed_docs = 0
    errored_docs = 0
    total_mismatches = 0
    for path in targets:
        checked += 1
        mismatches, error = check_document(path)
        if error:
            errored_docs += 1
            print(f"ERROR {path}: {error}")
            if not args.all:
                return 1
            continue
        if mismatches:
            failed_docs += 1
            total_mismatches += len(mismatches)
            print(f"MISMATCH {path}:")
            for m in mismatches:
                print(f"  {m}")
            if not args.all:
                return 1

    print(f"\n{checked} document(s) checked, {failed_docs} with model/PDF "
          f"mismatches ({total_mismatches} total), {errored_docs} errored.")
    return 1 if (failed_docs or errored_docs) else 0


if __name__ == '__main__':
    raise SystemExit(main())
