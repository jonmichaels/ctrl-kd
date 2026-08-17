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
                  line lands on), 'structure' (the M-rules structure
                  addendum, 2026-08-13 -- see classify_rows()): 'col'
                  (absolute column this row's text starts at), 'level'
                  (nesting depth), 'kind' ('bullet'|'def'|None), 'marker'
                  (bullet glyph), 'label'/'body' (def-list split),
                  'centered'/'center_via'/'center_text'. Purely additive
                  classification of the SAME text already in 'runs' --
                  never reshapes or removes anything; a consumer that
                  ignores it sees exactly what it always did.
  blank           one blank line (the author's own)
  break           a forced page break (.pa)
  cond            conditional break: 'lines' remaining or break (.cp n)
  hf              running-head change: 'which' ('H'|'F'), 'line' (1-based
                  slot), 'text' (raw — consumers pass it through hf_runs
                  for toggle bytes, and replace '#' with the page number)
  tabs            ruler tab stops changed: 'stops' (10-CPI columns). Tab
                  stops are editor-time state (they bake type-9 positions
                  at the keyboard) and change no rendered byte; carried for
                  Show Invisibles and editors. Absent until the first
                  change; None stops = back to the ruler default.
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

import re
from collections import Counter

from .core import merged_lines, Span, trailing_blank_lines, effective_span_styles
from .emit import (DEFAULT_NOTE_KINDS, _annotated_notes, _ref_pairs,
                   note_ref_labels, emitter)

# The era line: 65 columns at 10 CPI is the full measure every `.rm` is
# read against (same constant printed layout wraps at).
FULL_COLS = 65

# ---------------------------------------------------------- structure rules
#
# The three GENERIC Modern structure rules (Jon's field notes, 2026-08-13):
# def-list/hanging-indent, nested hierarchy (the same mechanism applied
# recursively), and centered lines -- detected from a paragraph's own
# column geometry, never keyed to a specific file (same "content-based,
# never extension-based" spirit as core.py's format detection).
#
# A definition-list label is a run's own first word glued to its
# description by 2+ spaces -- WordStar has no def-list markup, so a human
# author signals "this word IS the label" the only way the era's plain
# text allows: padding it out to a shared description column with spaces.
# One label alone is already unambiguous (EXTENDING.md-style: `word.py:
# does the thing`); no repetition is required to trust it, unlike a bullet
# marker below.
#
# The label must itself end in a colon. Found the hard way against the
# Sawyer WS7 archive's own prose corpus (OLDTIMES.WS): the era's own
# double-space-after-a-period typing convention means a short opening
# sentence -- dialogue like `"Right.  When the historical person...` --
# is column-for-column indistinguishable from a real label if a bare
# gap is all that's required. A colon is the one punctuation mark whose
# job in English IS introducing a label (a dictionary entry, `key: value`
# in code); a period/`!`/`?` ends a SENTENCE instead, never a label, so
# requiring it filters out every prose false positive found while keeping
# every genuine label in both real fixtures (`WS.EXE:`, `C:\WS\DEFAULT:`).
_DEFLIST_RE = re.compile(r'^(\S+:)( {2,})(\S.*)$')


def classify_rows(entries):
    """Structure classification for a sequence of rows, one call per
    document (bullet-marker discovery and nesting both need the WHOLE
    row order, not one paragraph in isolation). `entries` is, per row in
    document order:
      ('para', indent_cols, cut_cols, align, text)  a candidate row
      ('hard',)                                     a real break in flow
                                                      (heading, page break,
                                                      multi-column block) --
                                                      resets nesting
    Returns a parallel list: None for a 'hard' row, else a dict:
      col          the absolute column this row's visible text starts at
                   (indent_cols + this row's own residual leading spaces)
      level        nesting depth (1 = an outermost list item; 0 = this row
                   opens no container of its own, though it may still sit
                   visually inside one -- see 'kind')
      kind         'bullet' | 'def' | None
      marker       the bullet glyph, kind == 'bullet' only
      label, body  the def-list label and its description, kind == 'def'
                   only
      centered     True if this row reads as a centered line
      center_via   'tag' (a real align=center block) | 'spaces' (leading-
                   space padding, symmetric within the row's own measure)
                   | None
      center_text  the line with alignment padding stripped, when centered

    A row with no matching structure keeps kind=None; callers render it
    exactly as before (this function only ever ADDS classification, it
    never rejects or reshapes a row that doesn't match one of the rules).
    """
    rows = []
    for e in entries:
        if e[0] != 'para':
            rows.append(None)
            continue
        _, indent_cols, cut_cols, align, text = e
        lead = len(text) - len(text.lstrip(' '))
        rows.append({'indent_cols': indent_cols, 'cut_cols': cut_cols,
                     'align': align, 'lead': lead,
                     'col': indent_cols + lead, 'text': text[lead:],
                     'raw': text})

    # Bullet markers are discovered, never assumed: a single leading
    # non-alnum glyph immediately followed by one space and real text,
    # repeated at the SAME column at least twice, is this document's own
    # evidence that the glyph is a marker -- one occurrence alone can't be
    # told apart from ordinary punctuation starting a sentence. The glyph
    # must not recur later in its OWN body text either: an ASCII table's
    # box-drawing border (│) repeats down the left edge exactly like a
    # bullet would, but it also reappears as the column separator further
    # into the same row -- a real bullet is spent the moment it's used,
    # never showing up again in its own item's text (found against
    # BOXES.WS's own box-table rows in the Sawyer WS7 archive).
    def _marker_candidate(t):
        return (len(t) >= 3 and t[1] == ' ' and t[2] != ' '
                and not t[0].isalnum() and t[0] != ' '
                and t[0] not in t[2:])

    counts = Counter()
    for r in rows:
        if r is None:
            continue
        t = r['text']
        if _marker_candidate(t):
            counts[(r['col'], t[0])] += 1
    bullet_cols = {k for k, n in counts.items() if n >= 2}

    for r in rows:
        if r is None:
            continue
        t = r['text']
        is_bullet = (_marker_candidate(t)
                     and (r['col'], t[0]) in bullet_cols)
        m = None if is_bullet else _DEFLIST_RE.match(t)
        if is_bullet:
            r['kind'], r['marker'] = 'bullet', t[0]
            r['label'], r['body'] = None, t[2:]
        elif m:
            r['kind'], r['marker'] = 'def', None
            r['label'], r['body'] = m.group(1), m.group(3)
        else:
            r['kind'] = r['marker'] = r['label'] = r['body'] = None

    # The document's own routine first-line paragraph indent (if it has
    # one): whichever `lead` value shows up on the most otherwise-plain
    # rows. A real WS4-era author who indents every paragraph 5 spaces
    # produces dozens of SHORT paragraphs (dialogue, essay sentences)
    # whose particular length coincidentally lands that same 5-space
    # indent near the middle of THEIR OWN short line too -- found the
    # hard way against OLDTIMES.WS/KINGLEAR.ws/a-private-ws4-paper.ws, where treating
    # every symmetric-looking indent as a centered line swept up dozens of
    # ordinary paragraph openers. A deliberately centered line's own
    # padding varies with ITS length (there's no reason it would match
    # the paragraph-indent habit), so excluding the document's own most
    # common indent removes the routine convention while leaving actual
    # per-line centering (whose indent is evidence, not habit) alone.
    body_indent_counts = Counter(r['lead'] for r in rows
                                 if r and r['kind'] is None
                                 and r['lead'] >= 2 and r['text'])
    body_indent = (body_indent_counts.most_common(1)[0][0]
                  if body_indent_counts and
                  body_indent_counts.most_common(1)[0][1] >= 3 else None)

    # Nesting: a column stack, one entry per open container. A row strictly
    # shallower than the top closes it (and anything shallower still); a
    # row opening a container at the current top's own column is a
    # sibling, not a child. A non-list row never pops OR pushes on its
    # own -- it may sit inside an open container (a note between bullets)
    # without being one itself; only a real dedent, or a 'hard' break,
    # ever closes one.
    stack = []
    for e, r in zip(entries, rows):
        if e[0] == 'hard':
            stack = []
            continue
        while stack and r['col'] < stack[-1]:
            stack.pop()
        if r['kind']:
            if not (stack and stack[-1] == r['col']):
                stack.append(r['col'])
        r['level'] = len(stack)

    for r in rows:
        if r is None:
            continue
        r['centered'], r['center_via'], r['center_text'] = False, None, None
        content = r['raw'].strip(' ')
        if not content:
            continue
        if r['align'] == 'center':
            # WS5+ centred at editor time (M3): the tag AND the padding
            # both made it into the file. The tag already carries the
            # decision; this just names the mechanism for a caller that
            # wants one uniform 'centered' signal for both.
            r['centered'], r['center_via'], r['center_text'] = \
                True, 'tag', content
        elif r['align'] == 'left' and len(re.findall(r' {3,}', content)) < 2:
            # Undeclared centering: no tag at all, just spaces padding the
            # line so it SITS centred within this row's own printable
            # measure. Symmetric leading/trailing padding (within a little
            # rounding slack -- an odd leftover column rounds toward the
            # left in WordStar's own centering) is the only honest signal;
            # a merely-indented paragraph is never trailing-padded to
            # match, so this can't be confused with an ordinary `.lm`.
            #
            # The `findall` guard above: a fixed-width reference table row
            # (YOURWAY.WS's own byte tables: '1B4  1B8    ^JM       0A 0D
            # help with margins') has SEVERAL wide internal gaps from its
            # OWN column alignment, and enough of them coincidentally land
            # close to bisecting the line that this rule mis-fired across
            # dozens of table rows before this guard existed. A genuine
            # centered line carries at most one incidental wide gap (a
            # sentence-ending double-space); 2+ is a column layout, not
            # prose -- found the hard way against YOURWAY.WS/POWERUSE.WS.
            width = FULL_COLS - r['indent_cols'] - r['cut_cols']
            slack = width - len(content)
            # A near-full measure leaves almost no room to be off-centre in
            # the first place (a 1-column stray indent on a 62-of-65 line
            # is trivially "symmetric" with nowhere else to go) -- real
            # centering needs enough slack that landing near its middle is
            # actually evidence of intent, not an artifact of the line
            # nearly filling the width either way.
            if r['lead'] >= 2 and r['lead'] != body_indent and slack >= 4:
                ideal = slack / 2.0
                if abs(r['lead'] - ideal) <= 1.5:
                    r['centered'], r['center_via'], r['center_text'] = \
                        True, 'spaces', content
    return rows

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
    cur_tabs = None                    # ruler default until a block differs
    for bi, b in enumerate(doc.blocks):
        stops = getattr(b, 'tab_stops', None)
        if b.kind == 'para' and stops != cur_tabs:
            items.append({'kind': 'tabs', 'stops': stops})
            cur_tabs = stops
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
                styles = effective_span_styles(sp, b, heading_bold=True)
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

    # Structure classification (M-rules addendum, 2026-08-13): 'blank' and
    # the other carrier items (tabs/hf/note*) are soft -- they carry no
    # column of their own and never interrupt a list; 'break'/'cond' are
    # the only genuine hard resets modern_flow itself produces (headings
    # here are just bold paragraphs, not a distinct item kind).
    struct_entries, struct_idx = [], []
    for idx, it in enumerate(items):
        if it['kind'] == 'para':
            struct_entries.append(('para', it['indent_cols'] or 0,
                                   it['cut_cols'] or 0, it['align'],
                                   ''.join(r['text'] for r in it['runs'])))
            struct_idx.append(idx)
        elif it['kind'] in ('break', 'cond'):
            struct_entries.append(('hard',))
            struct_idx.append(idx)
    for idx, s in zip(struct_idx, classify_rows(struct_entries)):
        if s is not None:
            items[idx]['structure'] = {
                k: s[k] for k in ('col', 'level', 'kind', 'marker', 'label',
                                  'body', 'centered', 'center_via',
                                  'center_text')}
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
