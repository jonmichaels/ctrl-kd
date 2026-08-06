"""ctrl-kd PDF emitter — the page as it would have printed.

Hand-written PDF 1.4, zero dependencies: the base-14 Courier family needs no font
embedding and its fixed metrics make layout exact. That fits the tool's soul — a
WordStar document rendered as the typescript it was, on Letter pages:

  printed mode   line-for-line, form feeds / .pa / WordStar's own page breaks
                 honored — a facsimile of the 1990 printout, in the fonts and
                 sizes the document's own font blocks chose (base-14: Times,
                 Helvetica, Courier, Symbol, ZapfDingbats — still nothing
                 embedded, still zero dependencies), ON THE DOCUMENT'S OWN
                 LAYOUT GRID: each line advances by the `.lh` in force where it
                 appears, and each span starts at the x WordStar's own
                 per-character HMI advance puts it at (see _line_ops_printed)
  modern mode    reflowed paragraphs wrapped to the text column, headings bold,
                 footnotes at the end — still typewriter-set, still Courier

Styles: bold/italic map to the family's variants, underline is drawn,
superscript is raised and reduced. Non-Latin-1 characters degrade to '?'.
"""
import re as _re
from .core import merged_lines as _merged_lines, Span as _Span, \
    trailing_blank_lines as _trailing_blank_lines
from .emit import emitter, _printed, _annotated_notes, _ref_pairs, _font_family
from .symbolmap import font_translit_kind, untransliterate
from .afm import string_width_pt as _natural_width_pt

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
    if height_in == 0:
        # `.pl 0` = page breaks off (bug 12284; see core._text_lines_per_page).
        # The text model already never breaks; the PDF page box itself falls
        # back to Letter -- a truly unbounded page is not expressible in PDF.
        return PAGE_H
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
    not have, and inventing a detector is exactly what this change undoes.

    SECOND KNOWN LIMIT, added with stateful `.lh` (2026-08-05). Capacity is
    computed at the DOCUMENT-DEFAULT line height -- core._text_lines_per_page
    on meta['page']['lh_48'], the file's first `.lh`. A document that changes
    leading mid-page therefore paginates at a fixed lines-per-page while its
    lines advance at their own leads, so a page of tightly-led text ends
    early and a page of banners can run long. Whether WordStar RECOMPUTED
    lines-per-page as `.lh` changed is UNMEASURED -- register open question
    #15 -- and the honest options (recompute per line, or accumulate points
    until the text height is used up) are different answers to a question no
    manual page settles. Guessing here would silently repaginate every
    multi-`.lh` document on an assumption; leaving capacity where the
    evidence is keeps the change to what was ruled: leads, not pagination."""
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

def _lead_pt(lh_48):
    """One `.lh` value (1/48in units) as points: a point is 1/72in, so
    lh * 1.5. None/non-positive -> None, meaning "no answer here, use the
    document's default"."""
    if not lh_48 or lh_48 <= 0:
        return None
    return lh_48 * 1.5


def _printed_lead(doc):
    """The DOCUMENT-DEFAULT baseline-to-baseline distance in points for
    printed mode, from the file's first `.lh`. Default .lh 8 IS the 12pt lead
    this emitter always used. Print streams (no 'page' meta) keep the fixed
    LEAD.

    Only the default: `.lh` is stateful and a line that was set at a different
    leading carries its own (core.Line.lead_48 -> PageLine.lead), which
    _page_stream honours per line. This is what a line WITHOUT one falls back
    to, and what page CAPACITY is still computed at (see _printed_cap)."""
    page = doc.meta.get('page')
    if page is None:
        return LEAD
    return _lead_pt(page.get('lh_48', 8.0)) or LEAD

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

# ---------------------------------------------------------- the base-14 fonts
#
# Jon's ruling, 2026-08-04: a PRINTED-mode PDF of a WS5+ document renders
# WordStar's exact line breaks (it always has) PLUS the fonts the document
# chose -- through the PDF base-14 built-ins, so still zero dependencies and
# still nothing embedded. MODERN mode is unchanged: Courier-only typewriter
# setting, deliberately. WS4 and print streams carry no font blocks at all, so
# they stay Courier automatically -- there is nothing to look up.
#
# The base-14 set is what every PDF viewer must provide: Times x4, Helvetica
# x4, Courier x4, Symbol, ZapfDingbats. A WordStar typestyle is mapped to one
# of those five families by a strict three-way split -- serif, sans, mono --
# plus the two symbol faces (Jon's amendment: "every face we can't truly
# represent resolves by serif/sans/mono, no special flavoring"). Univers
# becomes Helvetica, Garamond becomes Times, Pica becomes Courier. The era
# name itself is never lost: it stays verbatim in doc.fonts and rides into the
# RTF/HTML exports, which CAN name a real face.
BASE14 = {
    'Courier':      ('Courier', 'Courier-Bold',
                     'Courier-Oblique', 'Courier-BoldOblique'),
    'Times':        ('Times-Roman', 'Times-Bold',
                     'Times-Italic', 'Times-BoldItalic'),
    'Helvetica':    ('Helvetica', 'Helvetica-Bold',
                     'Helvetica-Oblique', 'Helvetica-BoldOblique'),
    # neither symbol face has variants in the base-14 set: bold/italic on a
    # Symbol run has no face to go to, so the roman is used for all four.
    'Symbol':       ('Symbol',) * 4,
    'ZapfDingbats': ('ZapfDingbats',) * 4,
}

# Fixed-pitch era faces, matched on the typestyle NAME. This test must run
# BEFORE the generic-style bits, and the archive says why: the spec's own font
# block for `Courier` declares generic_style 'serif' (a slab serif, which is
# honest typography), and 48 of the 121 font blocks in the Sawyer corpus are
# exactly that. Reading the bits first would have set every Courier run in
# Times -- the one substitution a typescript facsimile must never make.
MONO_FAMILIES = ('courier', 'pica', 'elite', 'lineprinter')

# WordStar measures horizontal advance in HMIs -- 1/1800 inch -- and every
# font block in a WS5+ file carries the per-character width it laid the
# document out on. A PDF point is 1/72 inch, so 1800 HMI = 72 pt and the
# conversion is a division by 25. (The old per-family ADVANCE guesses --
# Times 0.5, Helvetica 0.55 -- are gone: afm.py carries the real per-glyph
# tables now, so nothing here has to approximate a width.)
HMI_PER_POINT = 1800.0 / 72.0                 # = 25

# Tz (horizontal scaling, percent) clamp. A span is scaled to land exactly on
# WordStar's grid; a ratio outside this range does not mean the author wanted
# glyphs at a quarter width, it means the file's HMI and the substituted
# face's metrics disagree -- a typestyle we can only approximate, a font block
# from a printer whose pitch had nothing to do with the base-14. Stretching to
# obey it would produce unreadable text in the name of fidelity, so outside
# the clamp the span keeps its natural advance and the grid loses that one
# argument. 40/250 is wide enough to cover every real substitution in the
# reference corpus (the worst honest case there is ~0.85) and narrow enough
# that a genuinely absurd ratio is caught.
TZ_MIN, TZ_MAX = 40.0, 250.0
TZ_DEFAULT = 100.0                            # PDF's own initial text state

# Face-constant Tz: one horizontal scale per (face, HMI pitch, size), chosen
# so the face's AVERAGE character lands on the document's grid. Per-SPAN
# scaling (the earlier model) forced every span to end exactly on the grid,
# which crushed any short span whose glyphs are wider than average -- a lone
# (c) squeezed to 70% is "not a circle" (Jon, 2026-08-05) -- and let a PDF
# viewer's substitute metrics accumulate error over a whole span before the
# next absolutely-placed span collided with it. A constant per-face scale
# keeps every glyph's true proportions (the driver printed real widths; the
# patched PS tables made WordStar's arithmetic use them too) while words are
# re-anchored to the grid at every space run (see _line_ops_printed).
_TZ_REF = 'abcdefghijklmnopqrstuvwxyz '
_FACE_TZ_CACHE = {}

def _face_tz(basefont, pitch, pt):
    key = (basefont, pitch, pt)
    tz = _FACE_TZ_CACHE.get(key)
    if tz is None:
        avg = _natural_width_pt(_TZ_REF, basefont, pt) / len(_TZ_REF)
        tz = round(pitch / avg * 100.0, 2) if avg > 0 else TZ_DEFAULT
        tz = min(TZ_MAX, max(TZ_MIN, tz))
        _FACE_TZ_CACHE[key] = tz
    return tz

# LJ6DTP's colour palette as PDF fill grays (`g`: 0 black, 1 white). The
# indices are DRIVER-DEFINED -- this table was recovered from the LJ6DTP
# printer description file's own string table and confirmed against the
# document's sample rows (deep-read 2026-08-05): 1-7 are 85/75/50/25/15/5/2%
# ink, 9-14 are HP fill patterns (approximated mid-gray -- texture is not
# expressible without pattern objects), 15 is White, the knockout. Index 8
# is ambiguous in the source and left black. Applied ONLY when the document
# declares driver LJ6DTP; any other driver's indices stay opaque, unrendered.
_COLOUR_GRAY_LJ6DTP = {
    1: 0.15, 2: 0.25, 3: 0.50, 4: 0.75, 5: 0.85, 6: 0.95, 7: 0.98,
    9: 0.5, 10: 0.5, 11: 0.5, 12: 0.5, 13: 0.5, 14: 0.5,
    15: 1.0,
}

# LJ6DTP's character substitutions -- the driver patches PC-8 slots so that
# typing `_` PRINTS an em dash, `«»` print curly doubles, ☻ prints ©, and so
# on (the whole point of the hack: proper typography out of a 1992 WordStar).
# The map is the document's own chart, recovered and confirmed in the
# deep-read. Face rules from the same chart: fixed-pitch faces (Courier,
# Letter Gothic, LinePrinter) are NOT patched, and the rounded box corners
# exist in Univers only (drawn here as square corners via the vector path --
# the shape is approximated, the position is exact).
_LJ_SUBST = str.maketrans({'☻': '©', '☼': '…', "'": '’', '_': '—',
                           '`': '‘', '«': '“', '»': '”', '≡': '–'})
_LJ_SUBST_UNIVERS = str.maketrans({'♥': '┌', '♦': '┐', '♣': '└', '♠': '┘'})


def _lj_substitute(segs):
    """Apply the LJ6DTP print-time substitutions to one line's spans."""
    out = []
    for text, styles, family, size_here, entry in segs:
        if entry is not None and entry.get('proportional'):
            text = text.translate(_LJ_SUBST)
            if (entry.get('typestyle_name') or '').startswith('Univers'):
                text = text.translate(_LJ_SUBST_UNIVERS)
        out.append((text, styles, family, size_here, entry))
    return out

# ------------------------------------------------- cp437 graphics as vectors
#
# Latin-1 has none of cp437's line-drawing repertoire, so the text path
# degrades every box/shade/block glyph to '?'. But these glyphs ARE geometry:
# a full block is a filled cell, a shade is a lighter fill, and each
# box-drawing character is up to four half-arms (up/down/left/right), single
# or double, meeting at the cell's center. Drawing them as rectangles is not
# an approximation of the printed page -- it is what the printer's own glyphs
# put on paper, minus the dot pitch. Only spans WITH a font block take this
# path (a fontless byte is never changed -- same rule as every other printed
# exception).
#
# Arms per glyph: (up, down, left, right); 0 none, 1 single, 2 double.
BOX_ARMS = {
    '─': (0, 0, 1, 1), '│': (1, 1, 0, 0), '┌': (0, 1, 0, 1), '┐': (0, 1, 1, 0),
    '└': (1, 0, 0, 1), '┘': (1, 0, 1, 0), '├': (1, 1, 0, 1), '┤': (1, 1, 1, 0),
    '┬': (0, 1, 1, 1), '┴': (1, 0, 1, 1), '┼': (1, 1, 1, 1),
    '═': (0, 0, 2, 2), '║': (2, 2, 0, 0), '╔': (0, 2, 0, 2), '╗': (0, 2, 2, 0),
    '╚': (2, 0, 0, 2), '╝': (2, 0, 2, 0), '╠': (2, 2, 0, 2), '╣': (2, 2, 2, 0),
    '╦': (0, 2, 2, 2), '╩': (2, 0, 2, 2), '╬': (2, 2, 2, 2),
    '╒': (0, 1, 0, 2), '╓': (0, 2, 0, 1), '╕': (0, 1, 2, 0), '╖': (0, 2, 1, 0),
    '╘': (1, 0, 0, 2), '╙': (2, 0, 0, 1), '╛': (1, 0, 2, 0), '╜': (2, 0, 1, 0),
    '╞': (1, 1, 0, 2), '╟': (2, 2, 0, 1), '╡': (1, 1, 2, 0), '╢': (2, 2, 1, 0),
    '╤': (0, 1, 2, 2), '╥': (0, 2, 1, 1), '╧': (1, 0, 2, 2), '╨': (2, 0, 1, 1),
    '╪': (1, 1, 2, 2), '╫': (2, 2, 1, 1),
}
# Shades: ink coverage -> PDF fill gray (1 = white paper).
SHADE_GRAY = {'░': 0.75, '▒': 0.50, '▓': 0.25}
# Partial blocks: (x-frac, y-frac, w-frac, h-frac) of the cell.
PART_BLOCKS = {'▀': (0, 0.5, 1, 0.5), '▄': (0, 0, 1, 0.5),
               '▌': (0, 0, 0.5, 1), '▐': (0.5, 0, 0.5, 1)}
GRAPHIC_CHARS = frozenset('█') | set(BOX_ARMS) | set(SHADE_GRAY) | set(PART_BLOCKS)
_GRAPHIC_RUN = _re.compile('[%s](?:[%s ]*[%s])?' % tuple(
    _re.escape(''.join(GRAPHIC_CHARS)) for _ in range(3)))


def _graphic_ops(text, x, y, pitch, pt):
    """Vector ops for one all-graphics span (spaces advance, draw nothing)."""
    ops = []
    yb, h = y - 0.25 * pt, 1.1 * pt
    my = yb + h / 2.0
    t = max(0.5, pt / 12.0)                  # line weight
    d = pt / 10.0                            # double-line half-gap
    def rect(rx, ry, rw, rh):
        ops.append(b'%.1f %.1f %.1f %.1f re f' % (rx, ry, rw, rh))
    for n, ch in enumerate(text):
        x0 = x + n * pitch
        if ch == ' ':
            continue
        if ch == '█':
            rect(x0, yb, pitch, h)
        elif ch in SHADE_GRAY:
            ops.append(b'q %.2f g' % SHADE_GRAY[ch])
            rect(x0, yb, pitch, h)
            ops.append(b'Q')
        elif ch in PART_BLOCKS:
            fx, fy, fw, fh = PART_BLOCKS[ch]
            rect(x0 + fx * pitch, yb + fy * h, fw * pitch, fh * h)
        else:
            u, dn, l, r = BOX_ARMS[ch]
            mx = x0 + pitch / 2.0
            for weight, xa, xb in ((l, x0, mx), (r, mx, x0 + pitch)):
                if weight == 1:
                    rect(xa, my - t / 2, xb - xa, t)
                elif weight == 2:
                    rect(xa, my + d - t / 2, xb - xa, t)
                    rect(xa, my - d - t / 2, xb - xa, t)
            for weight, ya, yc in ((u, my, yb + h), (dn, yb, my)):
                if weight == 1:
                    rect(mx - t / 2, ya, t, yc - ya)
                elif weight == 2:
                    rect(mx - d - t / 2, ya, t, yc - ya)
                    rect(mx + d - t / 2, ya, t, yc - ya)
    return ops


def _split_graphics(segs):
    """Break mixed text/graphics spans so each piece is all-one-kind. Spans
    without a font block pass through whole (they never take the vector
    path), as do spans with no graphic character at all."""
    out = []
    for seg in segs:
        text, styles, family, size_here, entry = seg
        if entry is None or not (set(text) & GRAPHIC_CHARS):
            out.append(seg)
            continue
        pos = 0
        for m in _GRAPHIC_RUN.finditer(text):
            if m.start() > pos:
                out.append((text[pos:m.start()], styles, family, size_here,
                            entry))
            out.append((m.group(0), styles, family, size_here, entry))
            pos = m.end()
        if pos < len(text):
            out.append((text[pos:], styles, family, size_here, entry))
    return out


def _pdf_family(entry):
    """The base-14 family for one doc.fonts entry.

    Order is deliberate:
      1. the font's own symbol-map/name verdict (symbolmap.font_translit_kind)
         -- 'math' IS Symbol, 'symbols' IS ZapfDingbats, and those two we can
         reproduce exactly rather than approximate;
      2. fixed-pitch names -> Courier (see MONO_FAMILIES for why this beats
         the bits);
      3. the font block's own generic-style bits: serif -> Times, sans ->
         Helvetica. 'script' also lands on Times and 'display' on Helvetica
         (Jon: "I don't think we have any option for script... maybe just
         Times"); the base-14 set has no chancery and no poster face, and the
         era's display typestyles are overwhelmingly sans-shaped, so those are
         the honest neighbours rather than an italic/bold pretence;
      4. anything unresolvable -> Courier, the emitter's own default.

    Bold and italic are NEVER decided here -- they come from the span's own
    b/i styles, exactly as they always have."""
    if not entry:
        return 'Courier'
    kind = font_translit_kind(entry)
    if kind == 'math':
        return 'Symbol'
    if kind == 'symbols':
        return 'ZapfDingbats'
    fam = _font_family(entry.get('typestyle_name')).lower()
    if any(fam.startswith(m) for m in MONO_FAMILIES):
        return 'Courier'
    return {'serif': 'Times', 'sans': 'Helvetica',
            'script': 'Times', 'display': 'Helvetica'}.get(
                entry.get('generic_style'), 'Courier')


class FontRes:
    """The page-resource font table, built as the content streams are written.

    The Courier four are ALWAYS /F1../F4 and always emitted, used or not. That
    is not laziness: it is what keeps a document with no font runs -- every WS4
    file, every print stream, and most WS5+ documents -- byte-for-byte
    identical to what this emitter produced before fonts existed here. Emitting
    only the fonts a page really touches would renumber the object table for
    those files and change every PDF the project has ever made. Fonts BEYOND
    the Courier four are added on demand, in first-use order, so a Courier
    document still ships exactly four font objects."""

    def __init__(self):
        self.names = dict(FONT_NAMES)                       # 'F1' -> basefont
        self._by_base = {b: f for f, b in FONT_NAMES.items()}

    def ref(self, basefont):
        """The /Fn name for a base-14 font, registering it if new."""
        key = self._by_base.get(basefont)
        if key is None:
            key = 'F%d' % (len(self.names) + 1)
            self.names[key] = basefont
            self._by_base[basefont] = key
        return key


def _span_font(styles, fonts):
    """The doc.fonts entry a span's active 'fontN' tag points at, or None.
    (The 'altfont' tag -- WS4's ^PA printer-alternate flag -- is deliberately
    not consulted: it names no font, it only says "the other wheel".)"""
    if not fonts:
        return None
    idx = min((int(t[4:]) for t in styles
               if t.startswith('font') and t[4:].isdigit()), default=None)
    if idx is None or idx >= len(fonts):
        return None
    return fonts[idx]


def _span_render(text, styles, fonts, size):
    """(text-as-written, family, size, font-entry) for one span.

    Symbol/ZapfDingbats runs were transliterated to real Unicode at parse time
    (symbolmap.py) so that every text format renders without a font. Here we
    have the font, so the transliteration is undone: the original byte codes go
    back on the page with the real face selected, and a viewer draws the actual
    glyph -- alpha, not the letter 'a', with nothing embedded."""
    entry = _span_font(styles, fonts)
    family = _pdf_family(entry)
    if family in ('Symbol', 'ZapfDingbats'):
        text = untransliterate(text, font_translit_kind(entry))
    pts = (entry or {}).get('points')
    # Tf has always been written as an integer here; the span's own size comes
    # from the font block's height word, falling back to the document's size.
    # The entry itself rides along because the LAYOUT needs its width word --
    # `width_1800`, the per-character advance WordStar used (_span_pitch).
    return text, family, (max(1, round(pts)) if pts else size), entry

# Lookalike degradations for glyphs cp1252 cannot carry -- applied before
# encoding so a middle dot from a header triple or a box glyph in a fontless
# span degrades to its nearest visible relative, not to '?'.
_ESC_FALLBACK = str.maketrans({'∙': '·', '•': '·', '‼': '!', '│': '|',
                               '─': '-', '═': '='})

def _esc(text):
    # cp1252, not latin-1: the declared /WinAnsiEncoding IS cp1252, and it is
    # what gives the base-14 faces curly quotes, en/em dashes, ellipsis and
    # the rest of the typographic range the LJ6DTP substitutions produce.
    raw = text.translate(_ESC_FALLBACK).encode('cp1252', 'replace')
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
        if b.kind == 'pagebreak':
            stream.append(None)
            continue
        for line in b.lines:
            spans = []
            refs = []
            for s in line.spans:
                styles = (s.styles | ({'b'} if b.heading else frozenset())
                          | b.style_attrs)
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
            # A PageLine, not a bare list, so the line's own `.lh` survives the
            # footnote paginator too -- body lines keep their lead whether or
            # not the document has notes.
            stream.append((PageLine(spans, soft=line.soft,
                                    lead=_lead_pt(line.lead_48),
                                    overprint=line.overprint), refs))
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
    """One laid-out line: a list of (text, styles) segments, plus the SOFT flag
    and the line's own LEAD.

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

    `lead` (added 2026-08-05) is this line's baseline-to-baseline advance in
    POINTS, or None for "the document's default". It is core.Line.lead_48 --
    the `.lh` in force where the line sat -- converted once here, so the
    layout loop never has to know about 48ths. Lines this emitter MAKES rather
    than reads (footnote areas, wrapped Modern text, blank fillers) leave it
    None by construction: they are the emitter's own furniture and belong on
    the document's default lead."""

    __slots__ = ('soft', 'lead', 'overprint')

    def __init__(self, segments=(), soft=False, lead=None, overprint=False):
        super().__init__(segments)
        self.soft = soft
        self.overprint = overprint      # bare-CR ^PM: the NEXT line prints
                                        # at THIS line's baseline
        self.lead = lead


class Page(list):
    """One paginated page: a list of PageLines plus the running head and
    foot IN FORCE when this page printed (replayed from doc.hf_events).
    A list subclass for the same reason PageLine is: every existing consumer
    iterates a page as a list and keeps working untouched."""

    __slots__ = ('headers', 'footers')

    def __init__(self, seq=()):
        super().__init__(seq)
        self.headers = {}
        self.footers = {}


def _doc_to_pagelines(doc, printed):
    """IR -> list of pages, each a list of segment-lines."""
    if printed and _has_placeable_notes(doc):
        cap = _printed_cap(doc)
        pages = _paginate_printed_notes(doc, cap, MAX_COLS)
        pages += _endnote_pages(doc, cap, MAX_COLS)
        while len(pages) > 1 and not pages[-1]:
            pages.pop()
        return pages or [[]]

    # Header/footer changes, replayed at the block they precede so each
    # page carries the running head IN FORCE when it printed (doc.hf_events;
    # OLDTIMES defines its head after page 1's title -- a manuscript has no
    # running head on page 1, and now doesn't get one).
    hf_by_block = {}
    for kind, lno, txt, anchor in getattr(doc, 'hf_events', ()):
        hf_by_block.setdefault(anchor, []).append((kind, lno, txt))
    lines = []                                            # None = forced page break
    for bi, b in enumerate(doc.blocks):
        for ev in hf_by_block.get(bi, ()):
            lines.append(('hf',) + ev)
        if b.kind == 'pagebreak':
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
        # printed renders PHYSICAL lines (a soft return broke the line on
        # paper); modern reflows LOGICAL lines (soft runs joined back --
        # core.merged_lines, the 2.0.0 split)
        for line in (b.lines if printed else _merged_lines(b)):
            # the docstring's "headings bold" promise: heading blocks render in
            # Courier-Bold (found unimplemented by the Swift port, job-011)
            spans = [(s.text, s.styles | ({'b'} if b.heading else frozenset())
                      | b.style_attrs)
                     for s in line.spans]
            if printed:
                # verbatim, no wrap -- carrying the line's own soft flag and
                # the `.lh` that was in force where it sat
                lines.append(PageLine(spans, soft=line.soft,
                                      lead=_lead_pt(line.lead_48),
                                      overprint=line.overprint))
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
    # Printed pagination is by ACCUMULATED POINTS, not line count. Paper is
    # physical: WordStar advances each line by the `.lh` in force and starts
    # a new page when the next advance would leave the text area -- so a
    # document that varies its leading (LJ6DTP's title page swaps 10pt/14pt/
    # 16pt leads around 72pt banners) fits more or fewer lines than the
    # default-lead count says. The budget is (cap - 1) leads at the document
    # default -- the first line sits at the top, each following line spends
    # its own lead -- which makes a uniform-lead document paginate EXACTLY as
    # the old line count did (n - 1 defaults == cap - 1 defaults at n == cap),
    # so no fontless byte moves. Overprint lines spend no lead at all, on
    # paper and here. (Resolves register #15's visible symptom -- an orphan
    # line pushed onto its own page ahead of a `.pa`.)
    default_lead = _printed_lead(doc) if printed else LEAD
    budget = (cap - 1) * default_lead
    pages, page, spent = [], [], 0.0
    cur_hdrs, cur_ftrs = {}, {}
    page_hdrs, page_ftrs = {}, {}      # state at the OPEN page's start
    def _cost(ln):
        if not page:                              # first line on page is free
            return 0.0
        if getattr(page[-1], 'overprint', False):
            return 0.0                             # this line shares a baseline
        return getattr(ln, 'lead', None) or default_lead
    def _close_page():
        pg = Page(page)
        pg.headers = {k: v for k, v in page_hdrs.items() if v}
        pg.footers = {k: v for k, v in page_ftrs.items() if v}
        pages.append(pg)
    for l in lines:
        if isinstance(l, tuple) and l and l[0] == 'hf':
            _, kind, lno, txt = l
            (cur_hdrs if kind == 'H' else cur_ftrs)[lno] = txt
            if not page:                   # nothing printed on this page yet:
                page_hdrs, page_ftrs = dict(cur_hdrs), dict(cur_ftrs)
            continue
        if isinstance(l, tuple) and l and l[0] == 'cond':
            # strictly fewer than n lines left -> break; exactly n is enough
            room = (budget - spent) / default_lead if printed \
                   else cap - len(page)
            if room < l[1] and page:
                _close_page(); page, spent = [], 0.0
                page_hdrs, page_ftrs = dict(cur_hdrs), dict(cur_ftrs)
            continue
        full = (spent + _cost(l) > budget + 1e-6) if printed \
               else len(page) >= cap
        if l is None or full:
            if page or l is None:
                _close_page(); page, spent = [], 0.0
                page_hdrs, page_ftrs = dict(cur_hdrs), dict(cur_ftrs)
            if l is None:
                continue
        if printed:
            spent += _cost(l)
        page.append(l)
    if page:
        _close_page()
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

def _running_ops(doc, page_no, page_h, lead, size, left, printed,
                 headers=None, footers=None):
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
    headers = doc.headers if headers is None else headers
    footers = doc.footers if footers is None else footers
    if not (headers or footers) or not printed:
        return []
    page = doc.meta.get('page') or {}
    # `.op` does NOT suppress a `#` in a header or footer. MEASURED on WordStar 4
    # (2026-08-03): a document carrying `.op` and `.fo Page #` printed "Page 1" on
    # page 1 and "Page 2" on page 2. WSFORMAT.TXT says the same -- ".OP  Omit page number.  At print time no page numbers are
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

    # The header block is anchored to the BODY, not the paper edge: its last
    # line sits `.hm` lines above the first body line, inside `.mt` (".MT ...
    # The header is printed within this margin"; ".HM ... the distance between
    # the header and the text"). At WordStar's defaults (.mt 3, .hm 2, one
    # header line) that IS paper line 0 -- which is why rendering headers at
    # the literal top of the sheet looked right for years -- but a document
    # that widens .mt (LJ6DTP's .mt 1.1") moves its header DOWN with the
    # body, where a laser printer can physically print it (Jon's finding,
    # 2026-08-05: no printer lays ink at y = 0).
    mt = float(page.get('mt_lines', 3))
    hm = float(page.get('hm_lines', 2))
    top_head = max(headers, default=1)
    head_base = max(0.0, mt - hm - top_head)
    ops = []
    for n, txt in sorted(headers.items()):
        if not txt:
            continue
        y = page_h - (head_base + n - 1) * lead - size
        ops.append(b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET' %
                   (FONTS[(False, False)].encode(), size, left, y,
                    _esc(render(txt))))
    foot_line = pl - mb + fm
    for n, txt in sorted(footers.items()):
        if not txt:
            continue
        y = page_h - (foot_line + n - 1) * lead - size
        if y < 0:
            continue
        ops.append(b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET' %
                   (FONTS[(False, False)].encode(), size, left, y,
                    _esc(render(txt))))
    return ops


def _sized(styles, size):
    """(point size, baseline rise) for a span set at `size`. Superscript is
    raised and reduced to 2/3 -- 8pt at the default 12, the ratio this emitter
    has always used."""
    if 'sup' in styles:
        return max(1, round(size * 2 / 3)), 3
    if 'sub' in styles:
        return max(1, round(size * 2 / 3)), -2
    return size, 0


def _rules(styles, text, x, y, w):
    """Underline / strikethrough as stroked paths (PDF has no text attribute
    for either), for a span occupying `w` points from `x`."""
    ops = []
    if not text.strip():
        return ops
    if 'u' in styles:
        ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S' % (x, y - 1.5, x + w, y - 1.5))
    if 'strike' in styles:
        ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S' % (x, y + 3, x + w, y + 3))
    return ops


def _span_pitch(entry, pt):
    """Per-character advance in POINTS for one span -- WordStar's own number.

    A WS5+ font block's FIRST word is the font width in HMIs (1/1800in): the
    pitch WordStar itself laid the document out on, and the pitch it sent the
    printer. 1800 HMI = 1 inch = 72 pt, so the conversion is /25.

    A span with no font block -- every WS4 file, every print stream, and every
    run before a WS5+ document's first font change -- gets the document's own
    `.cw`-derived pitch instead. `.cw` is character width in 1/120in, which
    _printed_size already resolved into the point size for exactly this
    reason (a Courier em advances 0.6, so cw/120in per character IS a cw-point
    font), so the pitch here is that size's 0.6em. Written in POINTS rather
    than converted through HMI on purpose: it is arithmetically the same
    number and it is the same float this emitter has always produced, which is
    what keeps a fontless PDF byte-identical."""
    w = (entry or {}).get('width_1800')
    if w:
        return w / HMI_PER_POINT
    return pt * 0.6


def _tz_scale(text, basefont, pt, target_w):
    """(Tz percentage or None, width actually occupied) for one span asked to
    fill `target_w` points.

    Courier lands on WordStar's grid by construction -- 600/1000 em is exactly
    the 0.6 the pitch was derived from -- so the ratio comes out 100 and no Tz
    is emitted at all. Nothing else does: Times at 12pt sets a word in
    whatever width Times wants, which is not the width WordStar reserved for
    it, and by the end of a line the accumulated error is a word or more.
    afm.py gives the natural width; Tz (horizontal scaling, percent) closes
    the gap, so the span occupies the grid slot the file asked for and the
    NEXT span starts where WordStar put it.

    None means "emit no scaling" and comes from three different places, all of
    which want the same operator (or the absence of one) but not the same
    width:
      * the ratio is 100 -- Courier, or any face whose metrics happen to agree.
        Occupies the target; nothing to say.
      * the ratio is outside [TZ_MIN, TZ_MAX] -- the metrics disagree
        pathologically (see the clamp's own note). The span keeps its NATURAL
        width and the rest of the line shifts with it, because overprinting
        the next span is worse than losing the grid.
      * there is no metric at all (a face afm.py cannot measure, or a string
        of glyphs it has no widths for). Nothing to compute a ratio from."""
    natural = _natural_width_pt(text, basefont, pt)
    if natural <= 0 or target_w <= 0:
        return None, natural
    scale = target_w / natural * 100.0
    if round(scale, 2) == TZ_DEFAULT:
        return None, target_w
    if not TZ_MIN <= scale <= TZ_MAX:
        return None, natural
    return scale, target_w


def _split_indent(segs):
    """`segs` with each entry gaining an INDENT flag, and the first span split
    where a line's leading whitespace ends.

    The indent is rarely a span of its own: a tab's padding and the text after
    it carry the same styles and the same font, so _coalesce has already
    merged them into one run by the time layout sees it. Peeling it off here
    is what lets the indent be measured in the document's own print columns
    while the text keeps the font's advance (see _line_ops_printed for why
    those are different measures).

    A span with NO font block is never flagged: the run's own pitch already IS
    the document's there, so the flag would change nothing -- and not raising
    it keeps every fontless line's arithmetic, and therefore its bytes,
    untouched. A FIXED-PITCH font block is never flagged either: its space
    advances at its own pitch on the printer, full stop -- LJ6DTP's PC-8
    chart draws its box in the 11.9-CPI COURIER PC 12, and measuring its
    border's leading spaces in 10-CPI document columns shoved the box top
    16pt right of the box sides. (For 10-CPI Courier the two measures are
    the same number, so nothing else moves.) The document-column rule is for
    PROPORTIONAL runs, where WordStar re-stamps tab/margin positioning as
    10-CPI machine spaces: the reference archive's 72pt shadow banner and
    LJ6DTP's own flush-right bar segment both land exactly on that measure."""
    out, leading = [], True
    for seg in segs:
        text, styles, family, size_here, entry = seg
        if not leading:
            out.append(seg + (False,))
            continue
        pad = len(text) - len(text.lstrip(' '))
        if entry is not None and entry.get('proportional') and pad:
            if pad < len(text):
                out.append((text[:pad], styles, family, size_here, entry, True))
                out.append((text[pad:], styles, family, size_here, entry, False))
                leading = False
            else:
                out.append(seg + (True,))       # the whole span is indent
            continue
        out.append(seg + (False,))
        if text.strip():
            leading = False
    return out


def _line_ops_printed(segs, left, y, size, res, tz_state,
                      col_state=None, colour_map=None):
    """One laid-out line, on the document's own horizontal grid.

    Every span gets its own text object at an ABSOLUTE x, and that x is
    WordStar's: the characters before it, each at its own run's HMI advance
    (_span_pitch). This replaced two paths -- a Courier one that did exactly
    this arithmetic with a hardcoded 0.6, and a proportional one that put the
    whole line in a single text object and let PDF's natural advance carry the
    pen. The second was the right call while this emitter had no font metrics:
    with no way to know how wide Times actually set a word, a computed x was a
    guess and natural advance at least never overlapped. afm.py removes that
    limitation, and Jon's ruling followed it: "Printed that ignores fonts
    can't call itself Printed" -- the document's own layout math governs, so
    the grid is computed and each span is width-matched onto it with Tz.

    `tz_state` is a one-element list carrying the CURRENT horizontal scaling
    across calls. Tz is text state, and text state survives ET -- an 85 Tz set
    on one span would silently scale every span after it, on every following
    line of the same content stream. So the operator is written only when the
    value CHANGES, which also means a document that never needs scaling (every
    fontless file, and Modern mode entirely) never emits one and its bytes are
    exactly what they were before any of this existed.

    THE ONE EXCEPTION to the HMI grid, and it is the document's own math too:
    a line's LEADING WHITESPACE is positioning, measured in the document's
    print columns rather than in the font. WordStar re-stamps a left indent
    from `.tb`/`.lm`/`.po` as machine spaces, and every one of those commands
    is specified in 10-CPI print columns -- core._tab_columns literally
    converts the tab's HMI size to columns before emitting the padding. Run
    that padding at a 72pt display font's own advance and a one-column shadow
    offset becomes a six-inch one: the reference archive's own banner document
    tabs to 1.39in on one line and 1.4in on the next, an offset of exactly one
    print column (7.2pt at 10 CPI), to print a display face twice with a
    shadow. On the font's advance the second copy landed off the right edge of
    the paper. Interior spaces -- inside a run, after real text -- are the
    author's own characters and stay on the font's advance.

    (The exception only fires for a span that HAS a font block: without one
    the run's pitch already IS the document's, so it cannot change a fontless
    byte.)"""
    ops, x = [], left
    if colour_map:
        # colour_map is non-empty exactly when the document declares driver
        # LJ6DTP -- the same gate covers its character substitutions.
        segs = _lj_substitute(segs)
    for text, styles, family, size_here, entry, indent in _split_indent(
            _split_graphics(segs)):
        # A 0x0F user print control's display string is SCREEN-ONLY: on paper
        # WordStar sent the raw printer payload and advanced by the block's
        # own HMI word (0 for LJ6DTP's rule-drawing controls, whose payload
        # draws with no character advance at all). The facsimile does the
        # same: no text, the declared width of empty space.
        pctl = next((t for t in styles if t.startswith('pctl')), None)
        if pctl:
            x += int(pctl[4:]) / HMI_PER_POINT
            continue
        pt, rise = _sized(styles, size_here)
        basefont = BASE14[family][('b' in styles) + 2 * ('i' in styles)]
        font = res.ref(basefont)
        # Driver-aware colour: a span tagged colourN under a driver whose
        # palette we know renders at that palette's gray. Emitted only when
        # the value CHANGES (fill gray is graphics state, like Tz), so every
        # all-black document -- and every driver we cannot read -- writes not
        # one extra byte. This is what makes LJ6DTP's knockouts work: white
        # (15) text overprinted onto a black bar punches out of it exactly
        # as the LaserJet printed it.
        if col_state is not None and colour_map:
            ctag = next((t for t in styles if t.startswith('colour')), None)
            gray = colour_map.get(int(ctag[6:]), 0.0) if ctag else 0.0
            if gray != col_state[0]:
                ops.append(b'%.2f g' % gray)
                col_state[0] = gray
        # cp437 graphics (blocks, shades, box-drawing) draw as vectors at the
        # span's own advance -- see BOX_ARMS/_graphic_ops. _split_graphics
        # guarantees a span reaching here is either all-graphics or has none.
        #
        # In a PROPORTIONAL face a block advances at the EM, not the face's
        # nominal average width. The document proves it in its own prose:
        # LJ6DTP's "full line of black ... precisely the length of your ruler
        # line" is two 24-block segments, one left-anchored and one
        # flush-right, that "overlap" -- at 13pt Univers that arithmetic only
        # closes at 24 x 13pt per segment (312 + 312 over a 468pt measure,
        # overlapping exactly as described); at the nominal 6.72pt the
        # segments cannot even meet. Fixed-pitch blocks stay on the pitch --
        # the same document's COURIER PC bars are correct there.
        if entry is not None and (set(text) & GRAPHIC_CHARS):
            pitch = pt if entry.get('proportional') else _span_pitch(entry, pt)
            ops += _graphic_ops(text, x, y, pitch, pt)
            x += len(text) * pitch
            continue
        if entry is not None and entry.get('proportional') and not indent:
            # PROPORTIONAL runs advance at NATURAL widths, face-scaled. Every
            # piece (word or space run) occupies its own AFM width times the
            # FACE-constant Tz -- the scale that lands the face's AVERAGE
            # character on its HMI grid, so a line's total comes out on the
            # author's measure while every glyph and every space keeps its
            # true proportion. This is what the printer did: the driver
            # advanced real per-character widths, and the patched PS tables
            # made WordStar's own arithmetic use them too -- LJ6DTP's
            # space-count-tuned tables were designed against real widths, so
            # real widths are what reproduce them. One op per word bounds a
            # viewer's substitute-metric drift to a single word.
            #
            # (A one-day detour anchored each word to its CHARACTER-COUNT
            # grid position instead: any caps-heavy word overran its
            # count-based slot into the next word, and grid-width spaces --
            # an average CHARACTER wide, ~0.46em -- read as gaping and
            # uneven. Word overlaps everywhere; Jon's review, 2026-08-05.)
            pitch = _span_pitch(entry, pt)
            want = _face_tz(basefont, pitch, pt)
            factor = want / 100.0
            for m in _re.finditer(r' +|[^ ]+', text):
                piece = m.group(0)
                nat = _natural_width_pt(piece, basefont, pt)
                pw = nat * factor if nat > 0 else len(piece) * pitch
                if piece[0] != ' ':
                    if want == tz_state[0]:
                        ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td (%s)'
                                   b' Tj ET' %
                                   (font.encode(), pt, rise, x, y,
                                    _esc(piece)))
                    else:
                        ops.append(b'BT /%s %d Tf %d Ts %.2f Tz %.1f %.1f'
                                   b' Td (%s) Tj ET' %
                                   (font.encode(), pt, rise, want, x, y,
                                    _esc(piece)))
                        tz_state[0] = want
                ops += _rules(styles, piece, x, y, pw)
                x += pw
            continue
        if indent:
            scale, w = None, len(text) * size * 0.6      # document print columns
        else:
            # Fixed-pitch (and metric-less) runs: width-matched onto the font
            # block's own HMI grid with Tz -- for Courier the ratio is 100 by
            # construction and no operator is ever written, which is what
            # keeps every fontless PDF byte-identical.
            target = len(text) * _span_pitch(entry, pt)
            scale, w = _tz_scale(text, basefont, pt, target)
        want = TZ_DEFAULT if scale is None else round(scale, 2)
        if want == tz_state[0]:
            ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td (%s) Tj ET' %
                       (font.encode(), pt, rise, x, y, _esc(text)))
        else:
            ops.append(b'BT /%s %d Tf %d Ts %.2f Tz %.1f %.1f Td (%s) Tj ET' %
                       (font.encode(), pt, rise, want, x, y, _esc(text)))
            tz_state[0] = want
        ops += _rules(styles, text, x, y, w)
        x += w
    return ops


def _page_stream(pagelines, top, page_h=PAGE_H, lead=LEAD, size=SIZE,
                 left=float(MARGIN), running=(), fonts=(), res=None,
                 colour_map=None):
    """One page's content stream. `fonts` is doc.fonts in PRINTED mode and
    empty everywhere else (Modern is Courier by design), so a span only leaves
    the document's own fixed pitch when the file itself asked for another face,
    another size or another advance.

    `lead` is the DOCUMENT DEFAULT. A line that carries its own (PageLine.lead,
    from the `.lh` in force where it sat) advances by that instead -- the
    stateful-`.lh` half of the same ruling.

    A LINE'S LEAD IS THE SPACE ABOVE IT, not below it, and that is measured
    rather than assumed. `.lh` is a printer VMI: WordStar sets the vertical
    motion index and the line feeds that follow use it, so the command --
    which sits in the file before the line it was typed for -- governs the
    feed that arrives ON that line. The reference archive's banner document
    proves it: it prints one 72pt word, sets `.lh.05"`, and prints the same
    word again, to overprint a shadow 0.05in (3.6pt) below the first. Read the
    other way round -- each lead spending itself below its own line -- the two
    copies land 14pt apart and the shadow is just a second, blurry banner.
    The first line of a page takes its position from `top` and no lead at
    all."""
    res = FontRes() if res is None else res
    ops = list(running)
    y = page_h - top - size
    # Horizontal scaling persists across text objects within a content stream;
    # it starts at PDF's own default on every page. See _line_ops_printed.
    tz_state = [TZ_DEFAULT]
    # Fill gray likewise: graphics state, reset per page. [gray, driver-aware]
    col_state = [0.0]
    prev_overprint = False
    for n, line in enumerate(pagelines):
        if n and not prev_overprint:
            y -= getattr(line, 'lead', None) or lead
        prev_overprint = getattr(line, 'overprint', False)
        segs = []
        for text, styles in _coalesce(line):
            if not text:
                continue
            written, family, size_here, entry = _span_render(
                text, styles, fonts, size)
            segs.append((written, styles, family, size_here, entry))
        ops += _line_ops_printed(segs, left, y, size, res, tz_state,
                                 col_state, colour_map or {})
    return b'\n'.join(ops)


# ---- Modern layout: the printed form of the Modern RTF ---------------------
#
# Ruled 2026-08-05: "Modern PDF needs to be the printed version of Modern
# RTF." One content model for the Modern column -- the RTF model (reflowed,
# document fonts carried, footnotes anchored) -- with PDF as its paper
# rendering. Everything here mirrors what Word does when you print the RTF:
# proportional wrap at the real measure, single spacing by the line's own
# type size, footnotes at the page bottom, paragraph gaps, .pa honored.
# Fontless text is base-14 Times at the sophisticated size (Georgia has no
# base-14 seat; "the PDF needs to work no matter what").

MODERN_BODY_PT = 14           # the sophisticated size (Jon's specimen ruling)
MODERN_NOTE_PT = 11
MODERN_LINE = 1.2             # single-spacing: baseline advance = 1.2 x size


def _modern_geometry(doc):
    """(left, top_margin, bottom_margin, text_width) in points. The
    document's declared geometry wins (governing principle); silence is the
    modern page: 1in margins on Letter. The right margin is always 1in --
    WordStar's right edge is a text measure, not a page property."""
    page = doc.meta.get('page') or {}
    margt = (float(page.get('mt_lines', 6.0)) * 12.0
             if page.get('mt_source', 'default') != 'default' else 72.0)
    margb = (float(page.get('mb_lines', 6.0)) * 12.0
             if page.get('mb_source', 'default') != 'default' else 72.0)
    margl = (float(page.get('po_cols', 10.0)) * 7.2
             if page.get('po_source', 'default') != 'default' else 72.0)
    return margl, margt, margb, max(144.0, PAGE_W - margl - 72.0)


def _modern_tok_font(text, styles, fonts):
    """(written, family, pt, entry) for one modern token. _span_render does
    the real work (untransliteration, entry sizes); the one modern rule on
    top: a token with NO font information reads in Times at the
    sophisticated size, never Courier -- the typescript aesthetic lives
    only in Printed now."""
    written, family, pt, entry = _span_render(text, styles, fonts,
                                              MODERN_BODY_PT)
    if entry is None:
        family = 'Times'
    return written, family, pt, entry


def _modern_w(text, styles, family, pt, entry):
    """A token's advance in points under modern layout: natural face widths
    (face-scaled for entries, straight AFM for fontless Times), the fixed
    grid only where a fixed-pitch font block asks for it."""
    spt, _rise = _sized(styles, pt)
    basefont = BASE14[family][('b' in styles) + 2 * ('i' in styles)]
    if entry is not None and (set(text) & GRAPHIC_CHARS):
        # mixed tokens split into graphic runs (cell advance) and text
        # (natural), same rule as printed's _split_graphics
        total = 0.0
        pitch = spt if entry.get('proportional') else _span_pitch(entry, spt)
        pos = 0
        for m in _GRAPHIC_RUN.finditer(text):
            if m.start() > pos:
                total += _modern_w(text[pos:m.start()], styles, family, pt,
                                   entry if not (set(text[pos:m.start()])
                                                 & GRAPHIC_CHARS) else entry)
            total += len(m.group(0)) * pitch
            pos = m.end()
        if pos < len(text):
            total += _modern_w(text[pos:], styles, family, pt, entry)
        return total
    if entry is not None and not entry.get('proportional'):
        return len(text) * _span_pitch(entry, spt)
    nat = _natural_width_pt(text, basefont, spt)
    if entry is not None:
        return nat * _face_tz(basefont, _span_pitch(entry, spt), spt) / 100.0
    return nat


def _endnote_label(label):
    """Endnote display label under Modern: lowercase roman, Word's own
    default for \\ftnalt endnotes -- the PDF matches the RTF it mirrors,
    and a page can carry footnote [1] and endnote [i] without collision
    (ruling 2026-08-06)."""
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


def _modern_flow(doc, keep):
    """The document as a flat list of layout items:
        ('para', toks, align, [(note, label)...], indent_pt, cut_pt)
        ('blank', height) | ('break',) | ('cond', n)
        ('hf', 'H'|'F', line_no, text)
    A tok is (text, styles, family, pt, entry, width). FOOTNOTES referenced
    on a line ride with it so the paginator can reserve their page-bottom
    room; endnotes and annotations collect at the document's end instead
    (ruling 2026-08-06 -- Word sends \\ftnalt notes to the back, and Modern
    PDF is the printed Modern RTF). indent/cut carry the block's own
    `.lm`/`.rm` in points -- the document's explicit margins win in Modern
    exactly as its fonts do."""
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    # LJ6DTP substitutions apply in Modern too (ruling 2026-08-06): the
    # driver's patched slots are CONTENT -- an em dash is an em dash in any
    # century -- while its page art (colour, rules, boxes) stays print-time.
    lj = doc.meta.get('printer_driver') == 'LJ6DTP'
    # one WordStar column in points, at the document's own `.cw`
    col_pt = float((doc.meta.get('page') or {}).get('cw_120', 12.0)) * 0.6
    hf_by_block = {}
    for kind, lno, txt, anchor in getattr(doc, 'hf_events', ()):
        hf_by_block.setdefault(anchor, []).append((kind, lno, txt))
    flow = []
    end_pairs, end_seen = [], set()   # endnotes/annotations, document order
    blank_h = MODERN_LINE * MODERN_BODY_PT
    for bi, b in enumerate(doc.blocks):
        for ev in hf_by_block.get(bi, ()):
            flow.append(('hf',) + ev)
        if b.kind == 'pagebreak':
            flow.append(('break',))
            continue
        if b.kind == 'condpage':
            flow.append(('cond', b.heading or 1))
            continue
        lm = b.left_margin or 0
        indent = lm * col_pt
        rm = b.right_margin or 0
        # `.rm` narrows the measure from the document's full line (MAX_COLS,
        # the same 65 columns the era page gives); a block at the default 65
        # cuts nothing
        cut = max(0, MAX_COLS - rm) * col_pt if rm else 0.0
        for line in _merged_lines(b):
            if not line.spans:
                flow.append(('blank', blank_h))
                continue
            spans = list(line.spans)
            if lm:
                # WordStar stamps `.lm` onto every line it writes; the
                # indent is carried by the BLOCK now, so the stamped spaces
                # come off the front (whatever indent remains past `.lm` is
                # the author's own tab and stays)
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
                        spans[0] = _Span(t[take:], spans[0].styles)
                        break
                    spans.pop(0)
            toks, notes = [], []
            for sp in spans:
                styles = sp.styles | ({'b'} if b.heading else frozenset()) \
                         | b.style_attrs
                if 'fnref' in sp.styles:
                    try:
                        note, label = refs[int(sp.text) - 1]
                    except (ValueError, IndexError):
                        continue
                    if note.kind not in keep:
                        continue
                    shown = (_endnote_label(label) if note.kind == 'endnote'
                             else label)
                    marker = (shown, styles, 'Times', MODERN_BODY_PT, None)
                    w = _modern_w(*marker)
                    toks.append(marker + (w,))
                    if note.kind == 'footnote':
                        notes.append((note, label))
                    elif id(note) not in end_seen:
                        end_seen.add(id(note))
                        end_pairs.append((note, shown))
                    continue
                for m in _re.finditer(r' +|[^ ]+', sp.text):
                    written, family, pt, entry = _modern_tok_font(
                        m.group(0), styles, doc.fonts)
                    if lj and entry is not None and entry.get('proportional'):
                        written = written.translate(_LJ_SUBST)
                        if (entry.get('typestyle_name') or
                                '').startswith('Univers'):
                            written = written.translate(_LJ_SUBST_UNIVERS)
                    w = _modern_w(written, styles, family, pt, entry)
                    toks.append((written, styles, family, pt, entry, w))
            if b.align in ('center', 'right'):
                # WordStar 5+ aligned at EDITOR time -- the centering is
                # already in the file as spaces (the same fact the WS4 `.oj`
                # DOSBox probe proved for justification). Applying the
                # stored tag on top of the baked spaces aligned twice; the
                # spaces come off and the tag does the work (ruling
                # 2026-08-06 -- no per-document exceptions).
                while toks and not toks[0][0].strip():
                    toks.pop(0)
                while toks and not toks[-1][0].strip():
                    toks.pop()
            flow.append(('para', toks, b.align, notes, indent, cut))
        # Only the author's own blank lines make space (ruling 2026-08-06):
        # a block boundary is often just a dot command, and command codes
        # are invisible. merged_lines buffered these away; count them back.
        for _ in range(_trailing_blank_lines(b)):
            flow.append(('blank', blank_h))
    if end_pairs:
        # Endnotes and annotations at the true end, after the last body
        # line -- flowing, not bottom-anchored -- behind the same 20-dash
        # separator the page-bottom notes use. No heading: WordStar never
        # printed one (any "Notes" heading in a period document was typed).
        flow.append(('blank', blank_h))
        sep_w = _natural_width_pt(FOOTNOTE_SEPARATOR, 'Times-Roman',
                                  MODERN_NOTE_PT)
        flow.append(('para', [(FOOTNOTE_SEPARATOR, frozenset(), 'Times',
                               MODERN_NOTE_PT, None, sep_w)],
                     'left', [], 0.0, 0.0))
        for note, shown in end_pairs:
            flow.append(('para', _modern_note_toks(note, shown),
                         'left', [], 0.0, 0.0))
    return flow


def _modern_wrap(toks, width):
    """Greedy wrap of one logical line's tokens -> visual lines. Leading
    whitespace stays (paragraph indent); a space token at a wrap point is
    swallowed, exactly as any renderer would."""
    lines, cur, curw = [], [], 0.0
    for tok in toks:
        text, w = tok[0], tok[5]
        if cur and curw + w > width and text.strip():
            lines.append(cur)
            cur, curw = [], 0.0
        if not cur and not text.strip() and lines:
            continue                      # swallow the wrap-point space
        cur.append(tok)
        curw += w
    if cur or not lines:
        lines.append(cur)
    return lines


def _modern_note_toks(note, label):
    """One note as `[label] text` tokens of Times MODERN_NOTE_PT."""
    text = '[%s] %s' % (label, note.text)
    toks = []
    for m in _re.finditer(r' +|[^ ]+', text):
        w = _natural_width_pt(m.group(0), 'Times-Roman', MODERN_NOTE_PT)
        toks.append((m.group(0), frozenset(), 'Times', MODERN_NOTE_PT, None, w))
    return toks


def _modern_note_lines(note, label, width):
    """A page-bottom note as wrapped visual lines of Times MODERN_NOTE_PT."""
    return _modern_wrap(_modern_note_toks(note, label), width)


def _modern_hf_ops(txt, page_no, left, y, width, res, tz_state):
    """One modern running-head/foot line: Times MODERN_NOTE_PT in the margin
    zone, WordStar's `#` token as the page number (same rule as printed:
    `.op` never suppresses an explicit `#`). The header keeps its own baked
    spaces -- that is how a 1990 head positioned its parts, and a running
    head is a page fixture, not reflowing text."""
    text = txt.replace('#', str(page_no))
    toks = []
    for m in _re.finditer(r' +|[^ ]+', text):
        w = _natural_width_pt(m.group(0), 'Times-Roman', MODERN_NOTE_PT)
        toks.append((m.group(0), frozenset(), 'Times', MODERN_NOTE_PT, None, w))
    return _modern_line_ops(toks, left, y, width, 'left', res, tz_state)


def _modern_line_ops(toks, left, y, width, align, res, tz_state):
    """Content-stream ops for one modern visual line. One op per word keeps
    a viewer's substitute-metric drift bounded, same as printed."""
    lw = sum(t[5] for t in toks)
    while toks and not toks[-1][0].strip():
        lw -= toks[-1][5]
        toks = toks[:-1]
    x = left
    if align == 'center':
        x += max(0.0, (width - lw) / 2)
    elif align == 'right':
        x += max(0.0, width - lw)
    ops = []
    for text, styles, family, pt, entry, w in toks:
        spt, rise = _sized(styles, pt)
        basefont = BASE14[family][('b' in styles) + 2 * ('i' in styles)]
        font = res.ref(basefont)
        if entry is not None and (set(text) & GRAPHIC_CHARS):
            # split mixed tokens: graphic runs draw as vectors at the cell
            # advance, interleaved text renders through the normal path
            pitch = spt if entry.get('proportional') else _span_pitch(entry, spt)
            pos, gx = 0, x
            for m in _GRAPHIC_RUN.finditer(text):
                if m.start() > pos:
                    piece = text[pos:m.start()]
                    pw = _modern_w(piece, styles, family, pt, entry)
                    ops += _modern_line_ops(
                        [(piece, styles, family, pt, entry, pw)],
                        gx, y, width, 'left', res, tz_state)
                    gx += pw
                run = m.group(0)
                ops += _graphic_ops(run, gx, y, pitch, spt)
                gx += len(run) * pitch
                pos = m.end()
            if pos < len(text):
                piece = text[pos:]
                pw = _modern_w(piece, styles, family, pt, entry)
                ops += _modern_line_ops(
                    [(piece, styles, family, pt, entry, pw)],
                    gx, y, width, 'left', res, tz_state)
            x += w
            continue
        if text.strip():
            if entry is not None and not entry.get('proportional'):
                want, _w = _tz_scale(text, basefont, spt,
                                     len(text) * _span_pitch(entry, spt))
                want = TZ_DEFAULT if want is None else round(want, 2)
            elif entry is not None:
                want = _face_tz(basefont, _span_pitch(entry, spt), spt)
            else:
                want = TZ_DEFAULT
            if want == tz_state[0]:
                ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td (%s) Tj ET' %
                           (font.encode(), spt, rise, x, y, _esc(text)))
            else:
                ops.append(b'BT /%s %d Tf %d Ts %.2f Tz %.1f %.1f Td (%s)'
                           b' Tj ET' %
                           (font.encode(), spt, rise, want, x, y, _esc(text)))
                tz_state[0] = want
        ops += _rules(styles, text, x, y, w)
        x += w
    return ops


def _modern_streams(doc, options, res):
    """All page content streams for Modern mode."""
    keep = frozenset(options.get('notes', ())) or frozenset(
        ('footnote', 'endnote', 'annotation'))
    margl, margt, margb, width = _modern_geometry(doc)
    flow = _modern_flow(doc, keep)
    note_lead = MODERN_LINE * MODERN_NOTE_PT
    sep_h = note_lead

    pages = []            # each: (body, [note lines], headers, footers)
    body, notes_lines, seen_notes = [], [], set()
    y = PAGE_H - margt
    cur_h, cur_f = {}, {}          # running-head state as events replay
    page_h, page_f = {}, {}        # state when the OPEN page took content
    opened = False

    def note_block_h():
        return (sep_h + note_lead * len(notes_lines)) if notes_lines else 0.0

    def open_page():
        # the page's running heads are the state in force when it takes its
        # first content -- OLDTIMES defines .h1 after page 1's title, and a
        # manuscript has no running head on page 1 (same rule as printed)
        nonlocal opened, page_h, page_f
        if not opened:
            page_h, page_f = dict(cur_h), dict(cur_f)
            opened = True

    def close():
        nonlocal body, notes_lines, y, opened
        open_page()
        pages.append((body, list(notes_lines), page_h, page_f))
        body, notes_lines[:] = [], []
        y = PAGE_H - margt
        opened = False

    for item in flow:
        if item[0] == 'hf':
            _, kind, lno, txt = item
            (cur_h if kind == 'H' else cur_f)[lno] = txt
            continue
        if item[0] == 'break':
            close()
            continue
        if item[0] == 'cond':
            need = item[1] * MODERN_LINE * MODERN_BODY_PT
            if body and y - (margb + note_block_h()) < need:
                close()
            continue
        if item[0] == 'blank':
            if not body:
                continue                      # no blank at a page top
            h = item[1]
            if y - h < margb + note_block_h():
                close()
                continue
            y -= h
            continue
        _, toks, align, notes, indent, cut = item
        line_w = max(36.0, width - indent - cut)
        vis = _modern_wrap(toks, line_w)
        new_note_lines = []
        for note, label in notes:
            if id(note) in seen_notes:
                continue
            new_note_lines += _modern_note_lines(note, label, width)
        for vi, vline in enumerate(vis):
            h = MODERN_LINE * max([_sized(t[1], t[3])[0] for t in vline]
                                  or [MODERN_BODY_PT])
            extra = ((sep_h if not notes_lines else 0.0)
                     + note_lead * len(new_note_lines)) if (vi == 0 and
                                                            new_note_lines) else 0.0
            if body and y - h < margb + note_block_h() + extra:
                close()
            open_page()
            y -= h
            body.append((y, vline, align, indent, cut))
            if vi == 0 and new_note_lines:
                notes_lines.extend(new_note_lines)
                for note, label in notes:
                    seen_notes.add(id(note))
                new_note_lines = []
    close()
    while len(pages) > 1 and not pages[-1][0] and not pages[-1][1]:
        pages.pop()

    streams = []
    start_no = int((doc.meta.get('page') or {}).get('pn_start', 1))
    for pi, (body, nlines, hdrs, ftrs) in enumerate(pages):
        tz_state = [TZ_DEFAULT]
        ops = []
        page_no = start_no + pi
        # running heads live in the margin zones: header lines walk down
        # from ~0.6in off the top edge, footer lines sit ~0.6in off the
        # bottom -- inside Modern's 1in margins, clear of the body
        for lno in sorted(hdrs):
            if not hdrs[lno]:
                continue
            hy = PAGE_H - 44.0 - (lno - 1) * note_lead
            ops += _modern_hf_ops(hdrs[lno], page_no, margl, hy, width,
                                  res, tz_state)
        for lno in sorted(ftrs):
            if not ftrs[lno]:
                continue
            fy = max(8.0, 44.0 - (lno - 1) * note_lead)
            ops += _modern_hf_ops(ftrs[lno], page_no, margl, fy, width,
                                  res, tz_state)
        for y, toks, align, indent, cut in body:
            ops += _modern_line_ops(list(toks), margl + indent, y,
                                    max(36.0, width - indent - cut),
                                    align, res, tz_state)
        if nlines:
            block = [None] + nlines           # None = the separator rule
            total = len(block)
            for i, ln in enumerate(block):
                ly = margb + note_lead * (total - 1 - i)
                if ln is None:
                    f = res.ref('Times-Roman')
                    ops.append(b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET' %
                               (f.encode(), MODERN_NOTE_PT, margl, ly,
                                _esc(FOOTNOTE_SEPARATOR)))
                else:
                    ops += _modern_line_ops(list(ln), margl, ly, width,
                                            'left', res, tz_state)
        streams.append(b'\n'.join(ops))
    return streams


@emitter('pdf')
def emit_pdf(doc, mode='printed', **options):
    """Assemble the PDF: catalog, page tree, the font table (the Courier four
    always, plus whatever base-14 faces a document's own font runs reached
    for), one content stream per page, xref. Returns bytes — PDF is a binary
    format.

    `page_settings` (option): {'mt_lines': .., 'mb_lines': .., 'po_cols': ..,
    'hm_lines': .., 'fm_lines': ..} -- replacement DEFAULTS for geometry the
    document does not declare itself (a field is overridden only when its
    *_source is 'default'; a document's own dot commands always win). The CLI
    resolves its --page-settings flag (presets `default`/`sawyer`/`modern`,
    or raw values) into this dict. Named "Page Settings" at every layer by
    ruling (2026-08-05)."""
    printed = mode == 'printed' or _printed(doc)
    page_settings = options.get('page_settings')
    saved_page = None
    if page_settings and doc.meta.get('page') is not None:
        from .core import effective_page
        saved_page = doc.meta['page']
        doc.meta['page'] = effective_page(saved_page, page_settings)
    try:
        return _emit_pdf_inner(doc, printed, options)
    finally:
        if saved_page is not None:
            doc.meta['page'] = saved_page


def _emit_pdf_inner(doc, printed, options):
    if printed:
        pages = _doc_to_pagelines(doc, printed)
        top = _printed_top(doc)
        lead = _printed_lead(doc)
        size = _printed_size(doc)
        left = _printed_left(doc, size)
        page_h = _resolved_page_height(doc, printed)
        fonts = doc.fonts
        colour_map = _COLOUR_GRAY_LJ6DTP if (
            doc.meta.get('printer_driver') == 'LJ6DTP') else {}
        start_no = int((doc.meta.get('page') or {}).get('pn_start', 1))
        res = FontRes()
        streams = []
        for page_index, pl in enumerate(pages):
            running = _running_ops(doc, start_no + page_index, page_h, lead,
                                   size, left, printed,
                                   headers=getattr(pl, 'headers', None),
                                   footers=getattr(pl, 'footers', None))
            streams.append(_page_stream(pl, top, page_h, lead, size, left,
                                        running, fonts, res, colour_map))
    else:
        # Modern: the printed form of the Modern RTF (ruling 2026-08-05) --
        # document fonts carried, proportional reflow at the real measure,
        # footnotes at the page bottom, fontless body Times 14. Always
        # US Letter, like the RTF's own page setup.
        page_h = PAGE_H
        res = FontRes()
        streams = _modern_streams(doc, options, res)
    n_pages = len(streams)
    objs = []                                             # (obj_number, bytes)

    font_objs = {}                                        # F1..Fn -> obj num
    next_num = 3
    for f, basefont in res.names.items():
        font_objs[f] = next_num
        # /WinAnsiEncoding on the ALPHABETIC faces: without a declared
        # encoding a Type1 font falls back to its built-in StandardEncoding,
        # where the cp1252 bytes _esc writes for curly quotes, dashes and ©
        # name the WRONG glyphs. Symbol and ZapfDingbats keep their built-in
        # encodings -- their bytes are glyph indices by design (symbolmap).
        if basefont in ('Symbol', 'ZapfDingbats'):
            objs.append((next_num,
                         b'<< /Type /Font /Subtype /Type1 /BaseFont /%s >>'
                         % basefont.encode()))
        else:
            objs.append((next_num,
                         b'<< /Type /Font /Subtype /Type1 /BaseFont /%s'
                         b' /Encoding /WinAnsiEncoding >>'
                         % basefont.encode()))
        next_num += 1
    font_dict = b' '.join(b'/%s %d 0 R' % (f.encode(), n) for f, n in font_objs.items())

    page_nums, content_nums = [], []
    for _ in range(n_pages):
        page_nums.append(next_num); next_num += 1
        content_nums.append(next_num); next_num += 1

    kids = b' '.join(b'%d 0 R' % n for n in page_nums)
    objs.insert(0, (1, b'<< /Type /Catalog /Pages 2 0 R >>'))
    objs.insert(1, (2, b'<< /Type /Pages /Kids [%s] /Count %d >>' % (kids, n_pages)))

    for pnum, cnum, stream in zip(page_nums, content_nums, streams):
        objs.append((pnum,
                     b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] '
                     b'/Resources << /Font << %s >> >> /Contents %d 0 R >>'
                     % (PAGE_W, page_h, font_dict, cnum)))
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
