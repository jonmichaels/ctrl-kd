"""The Modern layout model — the semantic flow every Modern renderer shares.

This module is the PUBLIC face of the M-rules (the 2026-08-06 Modern review
rulings): alignment tags strip the spaces that implemented them, block
`.lm`/`.rm` margins indent and narrow the measure, only the author's blank
lines make space, running heads replay, footnotes ride their lines while
endnotes/annotations/comments collect at the end, print-control display
strings are screen-only, and driver character substitutions are content.

Three consumers, one model (ruled 2026-08-06, "the point is not to
reimplement everything"):
  - pdf.py measures these items into points and paints them;
  - Soft Return.app measures them through the native macOS text stack;
  - the `layout` emitter (below) serializes them as JSON so a viewer in ANY
    language can render a WordStar file without linking either engine —
    and so the two engines' layout output is parity-testable as data.

The items are deliberately plain (dicts, lists, strings, numbers): no
class instances, nothing that doesn't survive json.dumps. Measurements are
absent by design — a paragraph's `indent_cols` is in WordStar print
columns, and each consumer converts with its own metrics.

## The item contract (format 1)

modern_flow() returns {'items': [...], 'notes': [...]}.

Each item is a dict with a 'kind':
  para            a logical line to wrap: 'align' ('left'|'center'|'right'|
                  'justify'), 'indent_cols'/'cut_cols' (the block's .lm and
                  its .rm shortfall from the 65-column line, in columns),
                  'runs' (below), 'footnotes' (list of [note_index, label]
                  whose text belongs at the bottom of whatever page this
                  line lands on)
  blank           one blank line (the author's own)
  break           a forced page break (.pa)
  cond            conditional break: 'lines' remaining or break (.cp n)
  hf              running-head change: 'which' ('H'|'F'), 'line' (1-based
                  slot), 'text' (raw — consumers pass it through hf_runs
                  for toggle bytes, and replace '#' with the page number)
  note-separator  the 20-dash rule opening the end-notes section
  note            one end-matter note: 'index' (into notes), 'label',
                  'text' — endnotes/annotations/comments, document order

A run is {'text': str, 'styles': [sorted tags]}, or a reference mark
{'text': shown_label, 'styles': [...], 'ref': note_index}. Runs preserve
span boundaries; they never merge.

notes is [{'kind', 'label', 'shown', 'text', 'origin'}] for every note the
call kept, in document order — 'label' is the kind's own display number
(what a page-bottom footnote shows), 'shown' the reference-mark text under
the requested `note_refs` scheme.
"""

from .core import merged_lines, Span, trailing_blank_lines
from .emit import (DEFAULT_NOTE_KINDS, _annotated_notes, _ref_pairs,
                   note_ref_labels, emitter)

# The era line: 65 columns at 10 CPI is the full measure every `.rm` is
# read against (same constant printed layout wraps at).
FULL_COLS = 65

# LJ6DTP's character substitutions — the driver patches PC-8 slots so that
# typing `_` PRINTS an em dash, `«»` print curly doubles, ☻ prints ©, and
# so on. The map is the document's own chart (deep-read 2026-08-05). They
# are CONTENT, not layout (ruling 2026-08-06 M7), so the SEMANTIC flow
# applies them: an em dash is an em dash in any century, whichever renderer
# consumes these items. Face rules from the same chart: fixed-pitch faces
# are NOT patched, and the rounded corners exist in Univers only.
LJ_SUBST = str.maketrans({'☻': '©', '☼': '…', "'": '’', '_': '—',
                          '`': '‘', '«': '“', '»': '”', '≡': '–'})
LJ_SUBST_UNIVERS = str.maketrans({'♥': '┌', '♦': '┐', '♣': '└', '♠': '┘'})


def endnote_label(label):
    """Endnote display label under the `word` scheme: lowercase roman,
    Word's own default for \\ftnalt endnotes (MS-OI29500 §17.11.17: "In
    Word, the default value for endnote numbering format is lowerRoman") —
    a page can carry footnote [1] and endnote [i] without collision."""
    try:
        n = int(label)
    except (TypeError, ValueError):
        return label
    if n <= 0:
        return label
    out = ''
    for v, s in ((1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'),
                 (100, 'c'), (90, 'xc'), (50, 'l'), (40, 'xl'),
                 (10, 'x'), (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i')):
        while n >= v:
            out += s
            n -= v
    return out


def _entry_for(styles, fonts):
    """The font-block entry a span's fontN tag points at, or None."""
    idx = next((int(t[4:]) for t in styles
                if t.startswith('font') and t[4:].isdigit()), None)
    if idx is not None and idx < len(fonts):
        return fonts[idx]
    return None


def _shown_labels(pairs, note_refs):
    """{id(note): reference-mark text} under the requested scheme (M8)."""
    if note_refs == 'prefixed':
        return note_ref_labels(pairs, 'prefixed')
    shown, ords = {}, {}
    for n, l in pairs:
        k = ords.get(n.kind, 0) + 1
        ords[n.kind] = k
        if n.kind == 'endnote':
            shown[id(n)] = endnote_label(l)
        elif n.kind == 'comment':
            # self-identifying in the end list either scheme; under `word`
            # there is no inline mark to match anyway
            shown[id(n)] = 'c%d' % k
        else:
            shown[id(n)] = l
    return shown


def modern_flow(doc, notes=DEFAULT_NOTE_KINDS, note_refs='word'):
    """The document as the semantic Modern flow — see the module docstring
    for the item contract. This is the single implementation of the
    M-rules; measuring consumers (pdf.py, the app) convert columns to
    their own units and wrap at their own measure."""
    keep = frozenset(notes)
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    shown_by_id = _shown_labels(pairs, note_refs)

    # every kept note, in document order, with its indices stable for the
    # 'ref'/'footnotes'/'index' fields below
    note_rows, index_by_id = [], {}
    for n, label in pairs:
        if n.kind not in keep:
            continue
        index_by_id[id(n)] = len(note_rows)
        note_rows.append({'kind': n.kind, 'label': label,
                          'shown': shown_by_id[id(n)], 'text': n.text,
                          'origin': getattr(n, 'origin', 'block')})

    lj = doc.meta.get('printer_driver') == 'LJ6DTP'
    fonts = getattr(doc, 'fonts', ()) or ()
    hf_by_block = {}
    for kind, lno, txt, anchor in getattr(doc, 'hf_events', ()):
        hf_by_block.setdefault(anchor, []).append((kind, lno, txt))

    items = []
    end_rows, end_seen = [], set()    # end-matter note indices, doc order
    for bi, b in enumerate(doc.blocks):
        for kind, lno, txt in hf_by_block.get(bi, ()):
            items.append({'kind': 'hf', 'which': kind, 'line': lno,
                          'text': txt})
        if b.kind == 'pagebreak':
            items.append({'kind': 'break'})
            continue
        if b.kind == 'condpage':
            items.append({'kind': 'cond', 'lines': b.heading or 1})
            continue
        lm = b.left_margin or 0
        rm = b.right_margin or 0
        # `.rm` narrows the measure from the document's full line; a block
        # at the default 65 cuts nothing
        cut = max(0, FULL_COLS - rm) if rm else 0
        for line in merged_lines(b):
            if not line.spans:
                items.append({'kind': 'blank'})
                continue
            spans = list(line.spans)
            if lm:
                # WordStar stamps `.lm` onto every line it writes; the
                # indent is carried by the item now, so the stamped spaces
                # come off the front (whatever indent remains past `.lm`
                # is the author's own tab and stays)
                drop = lm
                while drop and spans:
                    t = spans[0].text
                    take = 0
                    while take < len(t) and take < drop and t[take] == ' ':
                        take += 1
                    if not take:
                        break
                    drop -= take
                    if t[take:]:
                        spans[0] = Span(t[take:], spans[0].styles)
                        break
                    spans.pop(0)
            runs, footnotes = [], []
            for sp in spans:
                if any(t.startswith('pctl') for t in sp.styles):
                    # a 0x0F print control's display string is SCREEN-ONLY;
                    # the paper got the raw payload. Modern shows nothing —
                    # command codes are invisible (M4, extended M10)
                    continue
                styles = sp.styles | ({'b'} if b.heading else frozenset()) \
                         | b.style_attrs
                if 'fnref' in sp.styles:
                    try:
                        note, label = refs[int(sp.text) - 1]
                    except (ValueError, IndexError):
                        continue
                    if note.kind not in keep:
                        continue
                    ni = index_by_id[id(note)]
                    shown = shown_by_id[id(note)]
                    if note.kind != 'comment' or note_refs == 'prefixed':
                        # `word` comments are markless (Word's bubble
                        # convention); `prefixed` shows the c-mark (M9)
                        runs.append({'text': shown,
                                     'styles': sorted(styles), 'ref': ni})
                    if note.kind == 'footnote':
                        footnotes.append([ni, label])
                    elif ni not in end_seen:
                        end_seen.add(ni)
                        end_rows.append(ni)
                    continue
                text = sp.text
                if lj:
                    entry = _entry_for(sp.styles, fonts)
                    if entry is not None and entry.get('proportional'):
                        text = text.translate(LJ_SUBST)
                        if (entry.get('typestyle_name') or
                                '').startswith('Univers'):
                            text = text.translate(LJ_SUBST_UNIVERS)
                if text:
                    runs.append({'text': text, 'styles': sorted(styles)})
            if b.align in ('center', 'right'):
                # WordStar 5+ aligned at EDITOR time — the centering is
                # already in the file as spaces (the WS4 `.oj` DOSBox probe
                # proved the same for justification). The spaces come off
                # and the tag does the work (M3 — no per-document
                # exceptions). Character-level, so a run like '   Title'
                # sheds its leading spaces without losing the word.
                while runs and 'ref' not in runs[0]:
                    t = runs[0]['text'].lstrip(' ')
                    if t:
                        if t != runs[0]['text']:
                            runs[0] = dict(runs[0], text=t)
                        break
                    runs.pop(0)
                while runs and 'ref' not in runs[-1]:
                    t = runs[-1]['text'].rstrip(' ')
                    if t:
                        if t != runs[-1]['text']:
                            runs[-1] = dict(runs[-1], text=t)
                        break
                    runs.pop()
            items.append({'kind': 'para', 'align': b.align,
                          'indent_cols': lm, 'cut_cols': cut,
                          'runs': runs, 'footnotes': footnotes})
        # Only the author's own blank lines make space (M4): a block
        # boundary is often just a dot command, and command codes are
        # invisible. merged_lines buffered these away; count them back.
        for _ in range(trailing_blank_lines(b)):
            items.append({'kind': 'blank'})
    if end_rows:
        # Endnotes/annotations/comments at the true end, after the last
        # body line — flowing, not bottom-anchored — behind the same
        # 20-dash separator the page-bottom notes use. No heading:
        # WordStar never printed one.
        items.append({'kind': 'blank'})
        items.append({'kind': 'note-separator'})
        for ni in end_rows:
            row = note_rows[ni]
            items.append({'kind': 'note', 'index': ni,
                          'label': row['shown'], 'text': row['text']})
    return {'items': items, 'notes': note_rows}


def _json_meta(doc):
    """The provenance block of the layout document."""
    meta = doc.meta or {}
    return {
        'variant': meta.get('variant'),
        'producer': meta.get('producer'),
        'printer_driver': meta.get('printer_driver'),
        'columnar': bool(meta.get('columnar')),
        'encoding': 'cp437',
    }


@emitter('layout', ext='.json')
def emit_layout(doc, mode='modern', notes=DEFAULT_NOTE_KINDS,
                note_refs='word', **_options):
    """The `layout` format: the full viewer contract as JSON — semantic
    Modern flow, printed page-lines, page geometry with provenance, notes,
    and the invisible layer (dot commands with anchors, running-head
    events) — so a renderer in any language can draw a WordStar file
    without linking an engine, and both engines' layout is comparable as
    data. Format version bumps only on breaking shape changes."""
    import json
    from . import pdf as _pdf       # lazy: pdf imports this module's flow

    printed_pages = []
    for page in _pdf._doc_to_pagelines(doc, True):
        lines = []
        for pl in page:
            lines.append({
                'segments': [{'text': t, 'styles': sorted(st)}
                             for t, st in pl],
                'soft': bool(getattr(pl, 'soft', False)),
                'overprint': bool(getattr(pl, 'overprint', False)),
                'lead': getattr(pl, 'lead', None),
            })
        printed_pages.append({
            'lines': lines,
            'headers': dict(getattr(page, 'headers', {}) or {}),
            'footers': dict(getattr(page, 'footers', {}) or {}),
        })

    out = {
        'format': 'ctrl-kd-layout',
        'version': 1,
        'meta': _json_meta(doc),
        'page': doc.meta.get('page'),
        'fonts': [dict(f) for f in (getattr(doc, 'fonts', ()) or ())],
        'modern': modern_flow(doc, notes=notes, note_refs=note_refs),
        'printed': {'pages': printed_pages},
        'invisibles': {
            'dot_commands': doc.meta.get('dot_commands', []),
            'dot_positions': doc.meta.get('dot_positions', []),
            'hf_events': [list(e) for e in getattr(doc, 'hf_events', ())],
            'notes': [{'kind': n.kind, 'text': n.text,
                       'origin': getattr(n, 'origin', 'block'),
                       'offset': getattr(n, 'offset', 0)}
                      for n in getattr(doc, 'notes', ())],
        },
    }
    return json.dumps(out, ensure_ascii=False, indent=1) + '\n'
