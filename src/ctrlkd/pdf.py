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
from .emit import emitter, _printed

PAGE_W, PAGE_H = 612, 792            # US Letter, points
MARGIN = 72                          # 1 inch
SIZE, LEAD = 12, 12                  # 10 CPI pica x 6 LPI — the dot-matrix standard;
                                     # a 65-col WordStar line is exactly 6.5in
TOP_MODERN, TOP_PRINTED = 72, 36     # print streams carry their own top-margin blanks
LINES_MODERN = (PAGE_H - 2 * 72) // LEAD                 # 54
LINES_PRINTED = (PAGE_H - 2 * 36) // LEAD                # 60
MAX_COLS = int((PAGE_W - 2 * MARGIN) / (SIZE * 0.6))     # 65 — WordStar's own margin

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

def _doc_to_pagelines(doc, printed):
    """IR -> list of pages, each a list of segment-lines."""
    lines = []                                            # None = forced page break
    for b in doc.blocks:
        if b.kind == 'pagebreak' or (b.kind == 'softpage' and printed):
            lines.append(None)
            continue
        if b.kind == 'softpage':
            continue
        for line in b.lines:
            spans = [(s.text, s.styles) for s in line.spans]
            if printed:
                lines.append(spans)                       # verbatim, no wrap
            else:
                lines.extend(_wrap_line(spans, MAX_COLS))
        if not printed and b.lines:
            lines.append([])                              # blank line between paragraphs
    if doc.footnotes:
        lines += [[], [('-' * 20, frozenset())], []]
        for i, n in enumerate(doc.footnotes):
            note = f'[{i + 1}] ' + ''.join(s.text for s in n)
            lines.extend(_wrap_line([(note, frozenset())], MAX_COLS))
    cap = LINES_PRINTED if printed else LINES_MODERN
    pages, page = [], []
    for l in lines:
        if l is None or len(page) >= cap:
            if page or l is None:
                pages.append(page); page = []
            if l is None:
                continue
        page.append(l)
    if page:
        pages.append(page)
    # we supply the paper margins, so page-edge blank lines (WordStar's own
    # top/bottom margins in a print stream) would double up: strip them
    for pg in pages:
        while pg and not any(t.strip() for t, _ in pg[0]):
            pg.pop(0)
        while pg and not any(t.strip() for t, _ in pg[-1]):
            pg.pop()
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

def _page_stream(pagelines, top):
    ops = []
    y = PAGE_H - top - SIZE
    for line in pagelines:
        x = MARGIN
        for text, styles in _coalesce(line):
            if not text:
                continue
            sup = 'sup' in styles or 'sub' in styles
            size = 8 if sup else SIZE
            rise = 3 if 'sup' in styles else (-2 if 'sub' in styles else 0)
            font = FONTS[('b' in styles, 'i' in styles)]
            ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td (%s) Tj ET' %
                       (font.encode(), size, rise, x, y, _esc(text)))
            w = len(text) * size * 0.6
            if 'u' in styles and text.strip():
                ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S' % (x, y - 1.5, x + w, y - 1.5))
            if 'strike' in styles and text.strip():
                ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S' % (x, y + 3, x + w, y + 3))
            x += w
        y -= LEAD
    return b'\n'.join(ops)

@emitter('pdf')
def emit_pdf(doc, mode='modern', **options):
    """Assemble the PDF: catalog, page tree, four Courier fonts, one content
    stream per page, xref. Returns bytes — PDF is a binary format."""
    printed = mode == 'printed' or _printed(doc)
    pages = _doc_to_pagelines(doc, printed)
    top = TOP_PRINTED if printed else TOP_MODERN
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

    for pnum, cnum, pl in zip(page_nums, content_nums, pages):
        objs.append((pnum,
                     b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] '
                     b'/Resources << /Font << %s >> >> /Contents %d 0 R >>'
                     % (PAGE_W, PAGE_H, font_dict, cnum)))
        stream = _page_stream(pl, top)
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
