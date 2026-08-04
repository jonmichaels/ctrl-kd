"""ctrl-kd PDF emitter — the page as it would have printed.

Hand-written PDF 1.4, zero dependencies: the base-14 Courier family needs no font
embedding and its fixed metrics make layout exact. That fits the tool's soul — a
WordStar document rendered as the typescript it was, on Letter pages:

  printed mode   line-for-line, form feeds / .pa / WordStar's own page breaks
                 honored — a facsimile of the 1990 printout
  modern mode    reflowed paragraphs wrapped to the text column, headings bold,
                 footnotes at the end — still typewriter-set, still Courier

Styles: bold/italic map to the Courier variants, underline is drawn, superscript
is raised and reduced. Non-Latin-1 characters degrade to '?'.
"""
import re as _re
from .core import merged_lines as _merged_lines
from .emit import emitter, _printed, _annotated_notes, _ref_pairs

PAGE_W, PAGE_H = 612, 792            # US Letter, points
MARGIN = 72                          # 1 inch
SIZE, LEAD = 12, 12                  # 10 CPI pica x 6 LPI — the dot-matrix standard;
                                     # a 65-col WordStar line is exactly 6.5in
TOP_MODERN, TOP_PRINTED = 72, 36     # printed: default when a stream has no geometry
                                     # meta (its margin blanks travel in-band); WS docs
                                     # get an .mt-derived top from _printed_top()
LINES_MODERN = (PAGE_H - 2 * 72) // LEAD                 # 54
# Printed capacity is per-document: _printed_cap() -- WordStar's own model
# (.pl - .mt - .mb at the .lh line height; 55 for WordStar's defaults). The
# old hardcoded (PAGE_H - 2*36)//LEAD = 60 was a naive Letter computation
# that matched no WordStar the manual describes.
MAX_COLS = int((PAGE_W - 2 * MARGIN) / (SIZE * 0.6))     # 65 — WordStar's own margin

# Period-authentic footnote layout (Printed mode only -- WordStar Professional
# 5 manual, pp. 138-139, and the WSCHANGE factory-defaults table, WS7 manual):
FOOTNOTE_SEPARATOR = '-' * 20     # "Footnotes are separated from the text by a
                                  # line of 20 dashes." -- a fixed count, not
                                  # the text measure.
CONTINUATION_TEXT = '...Continued...'   # WSCHANGE factory default (footnote
                                        # continuation text)
FOOTNOTE_FLOOR = 3               # "A minimum of three lines of regular text
                                  # are printed on a page regardless of the
                                  # size of the footnote area" (except the
                                  # last page of the document)

def _resolved_page_height(doc, printed):
    """Page height in points for THIS document. Printed mode honours the
    file's own .pl-derived geometry (core.py's doc.meta['page']['height_in']
    -- file geometry wins for page size, best-effort). Modern mode does NOT:
    it deliberately reflows to fill its own fixed page rather than preserve
    the original measure (Printed is the faithfulness mode; Modern's whole
    point is a page that's simply pleasant to read), so it always renders at
    the fixed US Letter height regardless of what the file declares."""
    if not printed:
        return PAGE_H
    height_in = doc.meta.get('page', {}).get('height_in', 11.0)
    return max(LEAD * (FOOTNOTE_FLOOR + 1), round(height_in * 72))

def _printed_cap(doc):
    """Lines of vertical room on a printed page for THIS document -- the
    cap used both for plain pagination and as the footnote layout's page
    budget (see _paginate_printed_notes).

    WS documents carry doc.meta['page'] and get WordStar's own vertical
    model (core._text_lines_per_page: .pl - .mt - .mb at the .lh line
    height -- 55 for WordStar's defaults, NOT the 60 a naive 1in-margin
    computation gives).

    PRINT STREAMS GET THE SAME MODEL. Corrected 2026-08-03 (Jon's ruling:
    "printstreams need to follow WordStar standards, not our falsely invented
    ones"). This used to hand a print stream the FULL page height -- 66 lines
    on Letter -- justified by the claim that "their margin blanks travel
    in-band". That claim was checked against raw bytes and is FALSE for real
    print-to-disk output: such a stream carries no form feeds, and no top
    margin after its first page. It is not a stack of whole physical pages; it
    is a run of printed lines. Paginating it at 66 invented a page size
    WordStar does not document and no evidence supports.

    So a stream with no page metadata now falls back to WordStar's documented
    defaults, the same as a document that declares none: .pl 66 - .mt 3 - .mb 8
    = 55 lines. That is what WordStar 4 itself produces when run (its live
    output shows 11-line inter-page gaps = .mb 8 + .mt 3, on a 66-line pitch),
    and it makes the three renderings of one document -- the WS4 source, its
    print stream, and the live program -- finally agree.

    KNOWN LIMIT, recorded rather than papered over: a print stream that DOES
    carry its margins in band (WordStar 4's live output does) will now get
    margin on top of margin. Distinguishing the two cases needs evidence we do
    not have, and inventing a detector is exactly what this change undoes."""
    page = doc.meta.get('page')
    if page is not None:
        return max(FOOTNOTE_FLOOR + 1, page.get('text_lines', 55))
    from .core import (DEFAULT_PL_LINES, DEFAULT_MT_LINES, DEFAULT_MB_LINES,
                       DEFAULT_LH_48, _text_lines_per_page)
    return max(FOOTNOTE_FLOOR + 1,
               _text_lines_per_page(DEFAULT_PL_LINES, DEFAULT_MT_LINES,
                                    DEFAULT_MB_LINES, DEFAULT_LH_48))


def _printed_top(doc):
    """Top-of-text offset in points for printed mode. WS documents start
    where .mt says (lines at 6 LPI -> 12pt each; the default .mt 3 is the
    36pt this emitter always used). Print streams keep the fixed 36pt --
    their own top-margin blanks are in the data (minus the machine-margin
    strip in _doc_to_pagelines). Clamped inside the page so garbage .mt
    from a misdetected binary degrades to an ugly page, never an absurd
    coordinate space."""
    page = doc.meta.get('page')
    if page is None:
        return TOP_PRINTED
    page_h = _resolved_page_height(doc, True)
    return max(0, min(round(page.get('mt_lines', 3.0) * 12), page_h - LEAD))

def _printed_lead(doc):
    """Baseline-to-baseline distance in points for printed mode: .lh is
    1/48in units, a point is 1/72in -> lh * 1.5. Default .lh 8 IS the 12pt
    lead this emitter always used. Print streams (no 'page' meta) keep the
    fixed LEAD."""
    page = doc.meta.get('page')
    if page is None:
        return LEAD
    lh = page.get('lh_48', 8.0)
    return lh * 1.5 if lh > 0 else LEAD

def _printed_size(doc):
    """Type size in points for printed mode, from .cw: character width in
    1/120in units, and Courier advances 0.6em, so a pitch of cw/120in per
    character IS a (cw*72/120)/0.6 = cw*1.0 point font. The default .cw 12
    (10 CPI pica) IS the 12pt this emitter always used; .cw 10 is 12 CPI
    elite at 10pt. Rounded to whole points (the Tf operator is written as
    an integer, as it always has been), floored at 1. Print streams keep
    the fixed SIZE."""
    page = doc.meta.get('page')
    if page is None:
        return SIZE
    cw = page.get('cw_120', 12.0)
    return max(1, round(cw)) if cw > 0 else SIZE

def _printed_left(doc, size):
    """Left edge of text in points for printed mode, from .po: "the number
    of print columns from the left edge of the paper to the left margin of
    text. The current setting of character width (.CW) determines the
    actual amount of indentation" -- so the offset is po columns at this
    document's own advance (0.6em of `size`). The default .po 8 (the WS7
    manual's ".8 inch" at 10 CPI) lands at 57.6pt -- NOT the old fixed 72pt
    MARGIN, which was this emitter's guess, not WordStar's. Print streams
    keep MARGIN: their offset spaces, where a driver emitted them, are
    in-band. Clamped inside the page for garbage .po from misdetected
    binaries."""
    page = doc.meta.get('page')
    if page is None:
        return float(MARGIN)
    left = page.get('po_cols', 8.0) * size * 0.6
    return max(0.0, min(left, PAGE_W - size * 0.6))

FONTS = {(False, False): 'F1', (True, False): 'F2',
         (False, True): 'F3', (True, True): 'F4'}
FONT_NAMES = {'F1': 'Courier', 'F2': 'Courier-Bold',
              'F3': 'Courier-Oblique', 'F4': 'Courier-BoldOblique'}

def _esc(text):
    raw = text.encode('latin-1', 'replace')
    return raw.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')

def _wrap_line(spans, width):
    """Wrap one IR line's spans to `width` columns, preserving styles.
    Returns a list of segment-lines: [[(text, styles), ...], ...]."""
    tokens = []                                   # words and space-runs, styled
    for text, styles in spans:
        for piece in _re.split(r'( +)', text):
            if piece:
                tokens.append((piece, styles))
    lines, line, col = [], [], 0
    for text, styles in tokens:
        if not text.isspace() and col and col + len(text) > width:
            while line and line[-1][0].isspace():          # no trailing spaces
                col -= len(line.pop()[0])
            lines.append(line); line, col = [], 0
        line.append((text, styles)); col += len(text)
    while line and line[-1][0].isspace():
        line.pop()
    if line or not lines:
        lines.append(line)
    return lines

# ----------------------------------------------- printed footnote layout
#
# WordStar Professional 5 manual, pp. 138-139 (quoted in full in the module
# docstring's spirit, restated here at the point it's implemented):
#
#   "Footnotes are separated from the text by a line of 20 dashes. If a
#   footnote doesn't fit at the bottom of the page, the continued text is
#   printed in the footnote area at the bottom of the next page (except
#   after the last page of regular text, where footnotes are printed at
#   the top of the page). A minimum of three lines of regular text are
#   printed on a page regardless of the size of the footnote area except
#   on the last page of the document."
#
# The reference NEVER moves (no reserve-and-push/TeX-style lookahead --
# WordStar didn't do that); the footnote area at the page bottom grows to
# hold its notes, eating body-text space down to a floor of FOOTNOTE_FLOOR
# lines; whatever doesn't fit is split, continuing in the next page's area
# (marked with CONTINUATION_TEXT); the floor is lifted, and any final
# leftover prints at the page TOP instead, once there's no more body text.
#
# Endnotes never touch the per-page footnote area at all -- WordStar collects
# them at the true end of the document (no .pe support here -- see report),
# with NO heading (WordStar never printed one; see EXTENDING.md/report).
# Annotations print at the page bottom exactly like footnotes (same ruling).
# Comments never print (WordStar's own rule) and never reach this code --
# core.py never emits a reference sentinel for them.

def _note_marker(note, label):
    """Footnote reference-in-the-note, WSCHANGE factory default: no lead
    character, trailing '.' -> '1.'. Annotations have no documented mark of
    their own -- the spec gives them a free-text `tag` instead ("the text
    used to display and print the tag of the note"); `label` (from
    emit.py's _annotated_notes, shared so every format agrees) is already
    that tag when the author set one, falling back to a running count
    otherwise -- so this only ever needs to add the footnote's own
    trailing '.', never re-derive the tag-vs-number choice itself."""
    if note.kind == 'annotation':
        return f'{label} '
    return f'{label}. '

def _endnote_marker(label):
    """Endnote reference-in-the-note, WSCHANGE factory default: lead '(',
    trail ')' -> '(1)'."""
    return f'({label}) '

def _note_wrap(marker, text, width):
    """One note's rendered lines for the page-bottom area or the endnote
    listing -- wrapped with the same engine body text uses. WordStar prints
    note text in the default font (no styling carried from the reference),
    so this only ever wraps plain text."""
    return _wrap_line([(marker, frozenset()), (text, frozenset())], width) or [[]]

def _body_stream_printed(doc):
    """Printed-mode body content as a flat stream for the layout loop below:
    each item is either None (a forced page break -- .pa/.cp or WordStar's
    own softpage) or (spans, refs), spans being one verbatim IR line (printed
    mode never wraps body text) and refs the ordered list of (label, Note)
    footnote/annotation references newly appearing on it. Endnote references
    are recognised (so a fnref span's index into `refs_all` stays intact)
    but never queued here -- they don't participate in the per-page footnote
    area, they collect at the document's end instead (_endnote_pages).

    The displayed body reference is `label`, NOT the fnref span's raw
    `.text` (core.py's shared fn_counter position across ALL non-comment
    kinds) -- footnotes and endnotes are numbered INDEPENDENTLY per kind
    (WordStar has separate `.f#`/`.e#` starting-value commands, which only
    make sense for two independent sequences), matching what emit.py's
    text/markdown/html output already does via _annotated_notes/
    _display_number. A bare superscript '1' can therefore legitimately mean
    footnote 1 OR endnote 1 in the body text -- WordStar resolved that
    ambiguity in the NOTE AREA via mark style ('1.' vs '(1)'), not by
    inventing a combined number, so the same label is used in both places."""
    refs_all = _ref_pairs(_annotated_notes(doc))
    stream = []
    for b in doc.blocks:
        if b.kind in ('pagebreak', 'softpage'):
            stream.append(None)
            continue
        for line in b.lines:
            spans = []
            refs = []
            for s in line.spans:
                styles = s.styles | {'b'} if b.heading else s.styles
                if 'fnref' in s.styles and s.text.isdigit():
                    k = int(s.text)
                    if 0 < k <= len(refs_all):
                        note, label = refs_all[k - 1]
                        spans.append((label, styles))          # per-kind number, not the
                                                                # raw shared fn_counter index
                        if note.kind in ('footnote', 'annotation'):
                            refs.append((label, note))
                        continue
                spans.append((s.text, styles))
            stream.append((spans, refs))
    return stream

def _area_size(entries):
    """Total lines the footnote area occupies: the fixed 3-line header
    (blank / 20-dash separator / blank -- VMI 240 = one blank line at 6 LPI)
    plus each entry's own lines plus one blank line between entries (VMI 240
    "between notes"). 0 when there's nothing to show at all."""
    if not entries:
        return 0
    return 3 + sum(len(e) for e in entries) + (len(entries) - 1)

def _render_area(entries):
    if not entries:
        return []
    out = [[], [(FOOTNOTE_SEPARATOR, frozenset())], []]
    for k, e in enumerate(entries):
        if k:
            out.append([])
        out.extend(e)
    return out

def _admit_footnotes(entries, queue, ceiling):
    """Move whole/partial rendered note-chunks from the FRONT of `queue`
    into `entries` (mutating both) until the footnote area would exceed
    `ceiling` lines. A chunk that only partly fits is split: the part that
    fits joins `entries`, and the remainder goes back on the front of
    `queue` with CONTINUATION_TEXT prepended, ready to resume on a later
    page's area -- this is the only place a note's text is ever cut."""
    while queue:
        chunk = queue[0]
        overhead = 1 if entries else 3          # inter-note blank, or the
                                                 # area's header if it's empty so far
        room = ceiling - _area_size(entries) - overhead
        if room >= len(chunk):
            entries.append(chunk)
            queue.pop(0)
            continue
        # Splitting prepends a CONTINUATION_TEXT line to the remainder, so it
        # only advances when room >= 2: at room == 1 we would admit one line
        # and add one straight back, forever. When the page cannot even manage
        # that AND the area is still empty, force two lines through -- a page
        # that overflows slightly beats a hang or lost text (Jon's ruling on
        # the Modern spill case: no text lost, no infinite loops).
        if room >= 2:
            split = room
        elif not entries:
            split = min(len(chunk), 2)
        else:
            break                                # defer: next page starts empty
        entries.append(chunk[:split])
        rest = chunk[split:]
        if rest:
            queue[0] = [[(CONTINUATION_TEXT, frozenset())]] + rest
        else:
            queue.pop(0)
        break

def _footnote_ceiling(cap, body_len, is_terminal):
    """Max lines the footnote area may occupy on a page where `body_len`
    lines are already committed. Always bounded by the room actually left
    on the page (cap - body_len) -- entries can never push the total past
    cap. Additionally bounded by cap - FOOTNOTE_FLOOR on every page EXCEPT
    the one holding the document's last line of regular text, where the
    floor's protection lifts (the WS5 manual's stated exception)."""
    room = cap - body_len
    return room if is_terminal else min(room, cap - FOOTNOTE_FLOOR)

def _paginate_printed_notes(doc, cap, width):
    """The WS5-manual algorithm: paginate the body verbatim (references never
    move), growing each page's footnote area to hold whatever was referenced
    on it, splitting overflow into the next page's area (marked continued),
    floored at FOOTNOTE_FLOOR lines of body -- except on the page holding the
    last line of regular text, where the floor lifts and any leftover prints
    at the top of a fresh page instead of continuing to a bottom area that
    doesn't exist."""
    stream = _body_stream_printed(doc)
    last_idx = -1
    for i, item in enumerate(stream):
        if item is not None and any(t.strip() for t, _ in item[0]):
            last_idx = i

    pages = []
    queue = []                                  # list[list[line]]: rendered note
                                                 # chunks awaiting a footnote area,
                                                 # in document order
    i, n = 0, len(stream)
    while i < n:
        body, entries, is_terminal = [], [], False
        _admit_footnotes(entries, queue,
                         _footnote_ceiling(cap, len(body), is_terminal))   # carry-over first
        while i < n:
            item = stream[i]
            if item is None:
                i += 1
                break                            # forced break: page ends here
            spans, refs = item
            if len(body) + 1 + _area_size(entries) > cap:
                break                            # natural page-full: line moves on
            body.append(spans)
            if i == last_idx:
                is_terminal = True
            i += 1
            for label, note in refs:
                queue.append(_note_wrap(_note_marker(note, label), note.text, width))
            _admit_footnotes(entries, queue, _footnote_ceiling(cap, len(body), is_terminal))
        pages.append(body + _render_area(entries))
    # Whatever's STILL queued once the document is exhausted prints at the
    # TOP of its own page(s) -- "except after the last page of regular text,
    # where footnotes are printed at the top of the page."
    while queue:
        entries = []
        _admit_footnotes(entries, queue, _footnote_ceiling(cap, 0, True))
        pages.append(_render_area(entries))
    return pages

def _endnote_pages(doc, cap, width):
    """Endnotes collect at the true end of the document with NO heading
    (WordStar never printed one -- any "Notes"/"Sources" heading in a period
    document was typed by the author). No .pe support: this always renders
    them at document end, never at an earlier .pe point (see report).

    Numbered from endnotes' OWN independent sequence (via emit.py's
    _annotated_notes/_display_number, doc.meta['endnote_number_start']) --
    NOT the shared fn_counter position -- so a document with 2 footnotes
    then 2 endnotes shows endnotes (1)/(2), matching the same labels their
    body references now display (see _body_stream_printed), not (3)/(4)."""
    endnotes = [(note, label) for note, label in _annotated_notes(doc) if note.kind == 'endnote']
    if not endnotes:
        return []
    lines = []
    for k, (note, label) in enumerate(endnotes):
        if k:
            lines.append([])
        lines.extend(_note_wrap(_endnote_marker(label), note.text, width))
    pages, page = [], []
    for l in lines:
        if len(page) >= cap:
            pages.append(page); page = []
        page.append(l)
    if page:
        pages.append(page)
    return pages

def _has_placeable_notes(doc):
    return any(n.kind in ('footnote', 'endnote', 'annotation') for n in doc.notes)

class PageLine(list):
    """One laid-out line: a list of (text, styles) segments, plus the SOFT flag.

    Added 2026-08-03. A paginated line used to be a bare list, so `Line.soft` --
    which the IR has carried since 2.0.0 -- never reached the paginated
    representation. Anything working from pagelines therefore could not tell a
    soft return (WordStar's own word wrap, and the filler `.ls > 1` materialises)
    from a hard one (the author pressing Return). That distinction is not
    cosmetic: it is what carries authorial intent at a page top, and it is what
    Soft Return.app needs for Show Invisibles.

    Deliberately a LIST SUBCLASS rather than a new type: every existing consumer
    iterates a pageline as a list of segments and keeps working untouched, while
    new code can ask for `.soft`. Changing the contract outright would have
    touched the emitters, the footnote paginator and both geometry oracles at
    once, for no behavioural gain.
    """

    __slots__ = ('soft',)

    def __init__(self, segments=(), soft=False):
        super().__init__(segments)
        self.soft = soft


def _doc_to_pagelines(doc, printed):
    """IR -> list of pages, each a list of segment-lines."""
    if printed and _has_placeable_notes(doc):
        cap = _printed_cap(doc)
        pages = _paginate_printed_notes(doc, cap, MAX_COLS)
        pages += _endnote_pages(doc, cap, MAX_COLS)
        while len(pages) > 1 and not pages[-1]:
            pages.pop()
        return pages or [[]]

    lines = []                                            # None = forced page break
    for b in doc.blocks:
        if b.kind == 'pagebreak' or (b.kind == 'softpage' and printed):
            lines.append(None)
            continue
        if b.kind == 'condpage':
            # `.cp n` -- a break ONLY if fewer than n lines remain. Measured on
            # WordStar 4 (2026-08-03): exactly n remaining is enough room and
            # does NOT break; the test is strictly `remaining < n`. Emitted as a
            # sentinel so the page-filling loop below, which is the only thing
            # that knows how full the page is, can decide.
            lines.append(('cond', b.heading or 1))
            continue
        if b.kind == 'softpage':
            continue
        # printed renders PHYSICAL lines (a soft return broke the line on
        # paper); modern reflows LOGICAL lines (soft runs joined back --
        # core.merged_lines, the 2.0.0 split)
        for line in (b.lines if printed else _merged_lines(b)):
            # the docstring's "headings bold" promise: heading blocks render in
            # Courier-Bold (found unimplemented by the Swift port, job-011)
            spans = [(s.text, s.styles | {'b'} if b.heading else s.styles)
                     for s in line.spans]
            if printed:
                # verbatim, no wrap -- and carrying the line's own soft flag
                lines.append(PageLine(spans, soft=line.soft))
            else:
                lines.extend(PageLine(w, soft=line.soft)
                             for w in _wrap_line(spans, MAX_COLS))
        if not printed and b.lines:
            lines.append([])                              # blank line between paragraphs
    if doc.footnotes and not printed:
        # Printed mode's own layout is handled above (period-authentic,
        # per-page); this end-of-document dump is Modern-only -- explicitly
        # out of scope to change (Modern's own layout is a separate task).
        lines += [[], [('-' * 20, frozenset())], []]
        for i, n in enumerate(doc.footnotes):
            note = f'[{i + 1}] ' + ''.join(s.text for s in n)
            lines.extend(_wrap_line([(note, frozenset())], MAX_COLS))
    cap = _printed_cap(doc) if printed else LINES_MODERN
    pages, page = [], []
    for l in lines:
        if isinstance(l, tuple) and l and l[0] == 'cond':
            # strictly fewer than n lines left -> break; exactly n is enough
            if cap - len(page) < l[1] and page:
                pages.append(page); page = []
            continue
        if l is None or len(page) >= cap:
            if page or l is None:
                pages.append(page); page = []
            if l is None:
                continue
        page.append(l)
    if page:
        pages.append(page)
    # We supply the paper margins, so WordStar's own margin blanks in a print
    # stream would double up. But deliberate spacing (a chapter-drop on page 1)
    # must survive: the MACHINE margin is uniform on every page, so strip only
    # the minimum leading-blank count seen on pages 2+ — anything beyond it on
    # any page is the author's layout. Trailing blanks are always machine.
    def leading(pg):
        n = 0
        while n < len(pg) and not any(t.strip() for t, _ in pg[n]):
            n += 1
        return n
    # ...but ONLY for a PRINT STREAM. Corrected 2026-08-03: this repair was
    # written for print-to-disk output, where WordStar physically emitted its
    # top margin as blank lines. A WS4/WS5+ DOCUMENT has no machine margin in
    # it at all -- `.mt` is a dot command and the emitter applies it as paper
    # margin -- so every leading blank in one is the author's. Running the
    # stripper on a document deleted an author's chapter drop outright, and on any
    # SINGLE-page document it deleted every leading blank, because the
    # `len(pages) > 1` fallback measures the only page against itself.
    if printed and pages and doc.meta.get('variant') == 'printstream':
        machine = min(leading(pg) for pg in pages[1:]) if len(pages) > 1 \
                  else leading(pages[0])
        for pg in pages:
            del pg[:min(machine, leading(pg))]
            while pg and not any(t.strip() for t, _ in pg[-1]):
                pg.pop()
    elif printed and pages:
        # A document: keep leading blanks (authorial), drop trailing (machine).
        for pg in pages:
            while pg and not any(t.strip() for t, _ in pg[-1]):
                pg.pop()
    else:
        for pg in pages:
            del pg[:leading(pg)]
            while pg and not any(t.strip() for t, _ in pg[-1]):
                pg.pop()
    # Trailing empty pages produce blank sheets. The pop must run AFTER the
    # blank-stripping above — stripping is what hollows out a final page that
    # held only blank lines (1.1.5 popped before stripping and missed it; found
    # by the Swift port, job-012). Interior blanks from .pa .pa are preserved.
    while len(pages) > 1 and not pages[-1]:
        pages.pop()
    return pages or [[]]

def _coalesce(line):
    """Merge adjacent same-style segments into single text runs."""
    out = []
    for text, styles in line:
        if out and out[-1][1] == styles:
            out[-1][0] += text
        else:
            out.append([text, styles])
    return out

def _running_ops(doc, page_no, page_h, lead, size, left, printed):
    """Header and footer text for one page, as content-stream ops.

    Geometry MEASURED on WordStar 4 (2026-08-03), not inferred:
        line 0                      header line 1
        ...                         header lines 2-5, if used
        .hm blank lines
        body
        .fm blank lines
        line pl-.mb+.fm             footer line 1
    so the header sits at the very top of the paper and the footer `.fm` lines
    below the body's last line. `#` becomes the page number -- WordStar's own
    token, seen rendering as "PAGE 1 / PAGE 2 / PAGE 3" in the probe.

    `.op` ("omit page number ... unless the # has been used in footers or
    headers") suppresses the substitution, leaving the literal token out.
    """
    if not (doc.headers or doc.footers) or not printed:
        return []
    page = doc.meta.get('page') or {}
    # `.op` does NOT suppress a `#` in a header or footer. WSFORMAT.TXT is
    # explicit -- ".OP  Omit page number.  At print time no page numbers are
    # printed UNLESS THE '#' HAS BEEN USED IN FOOTERS OR HEADERS." It suppresses
    # the AUTOMATIC page number, the one `.pc` positions; a `#` the author put in
    # a running head is the exemption, not the target.
    #
    # This was implemented backwards: `.op` blanked the `#`, so a document that
    # turned off the automatic number ALSO lost the page number it had explicitly
    # asked for. The spec sentence was quoted in this very docstring while the code
    # did the opposite of it. `.pg` (which restores numbering after `.op`) was not
    # handled at all, so the state was one-way as well.
    pl = int(page.get('pl_lines', 66))
    mb = int(page.get('mb_lines', 8))
    fm = int(page.get('fm_lines', 2))

    def render(txt):
        return txt.replace('#', str(page_no))

    ops = []
    for n, txt in sorted(doc.headers.items()):
        if not txt:
            continue
        y = page_h - (n - 1) * lead - size
        ops.append(b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET' %
                   (FONTS[(False, False)].encode(), size, left, y,
                    _esc(render(txt))))
    foot_line = pl - mb + fm
    for n, txt in sorted(doc.footers.items()):
        if not txt:
            continue
        y = page_h - (foot_line + n - 1) * lead - size
        if y < 0:
            continue
        ops.append(b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET' %
                   (FONTS[(False, False)].encode(), size, left, y,
                    _esc(render(txt))))
    return ops


def _page_stream(pagelines, top, page_h=PAGE_H, lead=LEAD, size=SIZE,
                 left=float(MARGIN), running=()):
    ops = list(running)
    sup_size = max(1, round(size * 2 / 3))       # 8 at the default 12 -- the
                                                  # ratio this emitter always used
    y = page_h - top - size
    for line in pagelines:
        x = left
        for text, styles in _coalesce(line):
            if not text:
                continue
            sup = 'sup' in styles or 'sub' in styles
            size_here = sup_size if sup else size
            rise = 3 if 'sup' in styles else (-2 if 'sub' in styles else 0)
            font = FONTS[('b' in styles, 'i' in styles)]
            ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td (%s) Tj ET' %
                       (font.encode(), size_here, rise, x, y, _esc(text)))
            w = len(text) * size_here * 0.6
            if 'u' in styles and text.strip():
                ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S' % (x, y - 1.5, x + w, y - 1.5))
            if 'strike' in styles and text.strip():
                ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S' % (x, y + 3, x + w, y + 3))
            x += w
        y -= lead
    return b'\n'.join(ops)

@emitter('pdf')
def emit_pdf(doc, mode='printed', **options):
    """Assemble the PDF: catalog, page tree, four Courier fonts, one content
    stream per page, xref. Returns bytes — PDF is a binary format."""
    printed = mode == 'printed' or _printed(doc)
    pages = _doc_to_pagelines(doc, printed)
    top = _printed_top(doc) if printed else TOP_MODERN    # .mt-derived for WS docs;
                                                           # default .mt 3 IS the old 36pt
    lead = _printed_lead(doc) if printed else LEAD        # .lh-derived; .lh 8 IS 12pt
    size = _printed_size(doc) if printed else SIZE        # .cw-derived; .cw 12 IS 12pt
    left = _printed_left(doc, size) if printed else float(MARGIN)   # .po-derived;
                                                           # default .po 8 = 57.6pt, the
                                                           # manual's .8in -- see _printed_left
    page_h = _resolved_page_height(doc, printed)          # file geometry wins in
                                                           # printed mode (Task: .pl);
                                                           # modern stays fixed Letter
    objs = []                                             # (obj_number, bytes)

    n_pages = len(pages)
    font_objs = {}                                        # F1..F4 -> obj num
    next_num = 3
    for f in ('F1', 'F2', 'F3', 'F4'):
        font_objs[f] = next_num
        objs.append((next_num,
                     b'<< /Type /Font /Subtype /Type1 /BaseFont /%s >>'
                     % FONT_NAMES[f].encode()))
        next_num += 1
    font_dict = b' '.join(b'/%s %d 0 R' % (f.encode(), n) for f, n in font_objs.items())

    page_nums, content_nums = [], []
    for _ in range(n_pages):
        page_nums.append(next_num); next_num += 1
        content_nums.append(next_num); next_num += 1

    kids = b' '.join(b'%d 0 R' % n for n in page_nums)
    objs.insert(0, (1, b'<< /Type /Catalog /Pages 2 0 R >>'))
    objs.insert(1, (2, b'<< /Type /Pages /Kids [%s] /Count %d >>' % (kids, n_pages)))

    start_no = int((doc.meta.get('page') or {}).get('pn_start', 1))
    for page_index, (pnum, cnum, pl) in enumerate(
            zip(page_nums, content_nums, pages)):
        objs.append((pnum,
                     b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] '
                     b'/Resources << /Font << %s >> >> /Contents %d 0 R >>'
                     % (PAGE_W, page_h, font_dict, cnum)))
        running = _running_ops(doc, start_no + page_index, page_h, lead,
                               size, left, printed)
        stream = _page_stream(pl, top, page_h, lead, size, left, running)
        objs.append((cnum, b'<< /Length %d >>\nstream\n%s\nendstream'
                     % (len(stream), stream)))

    objs.sort()
    out = bytearray(b'%PDF-1.4\n')
    offsets = {}
    for num, body in objs:
        offsets[num] = len(out)
        out += b'%d 0 obj\n%s\nendobj\n' % (num, body)
    xref_at = len(out)
    count = max(offsets) + 1
    out += b'xref\n0 %d\n0000000000 65535 f \n' % count
    for n in range(1, count):
        out += b'%010d 00000 n \n' % offsets[n]
    out += (b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
            % (count, xref_at))
    return bytes(out)

emit_pdf.ext = '.pdf'
