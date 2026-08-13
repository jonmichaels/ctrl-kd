"""ctrl-kd emitters: Document IR -> text / markdown / html / rtf.

Two rendering philosophies, chosen by the caller:
  modern   reflowed paragraphs, semantic markup (the IR already joined word
           wraps and kept deliberate breaks — emitters just express it)
  printed  every line as laid out, fixed-width — how it came off the printer.
           Print streams and columnar documents (WordStar ruler lines) force
           this: their alignment only exists in a fixed-width world.
"""
import html as _html
import re

from .core import merged_lines, Span, trailing_blank_lines
from .fontmap import font_stack, rtf_fonts

# ---------------------------------------------------------------- registry
#
# The extension point. An emitter is any callable (doc, mode='printed', **options)
# -> str, registered under a name. Two ways in:
#
#   @ctrlkd.emitter('latex', ext='.tex')            # in your own code
#   def emit_latex(doc, mode='printed', **options): ...
#
#   [project.entry-points."ctrlkd.emitters"]        # in an installable plugin's
#   docx = "ctrlkd_docx:emit_docx"                  # pyproject.toml
#
# Entry-point plugins are discovered at CLI startup; `pip install ctrl-kd-docx`
# is all a user needs. See EXTENDING.md for the IR contract and a worked example.

_REGISTRY = {}          # name -> {'fn': callable, 'ext': '.xyz'}
_ALIASES = {'txt': 'text', 'md': 'markdown'}

def emitter(name, ext=None, aliases=()):
    """Register an output format. Usable as a decorator."""
    def deco(fn):
        _REGISTRY[name] = {'fn': fn, 'ext': ext or '.' + name}
        for a in aliases:
            _ALIASES[a] = name
        return fn
    return deco

def get_emitter(name):
    return _REGISTRY[_ALIASES.get(name, name)]

def formats():
    """All registered format names (canonical + aliases), for CLI choices."""
    return sorted(set(_REGISTRY) | set(_ALIASES))

def load_plugins():
    """Discover third-party emitters via the 'ctrlkd.emitters' entry-point group."""
    from importlib.metadata import entry_points
    for ep in entry_points(group='ctrlkd.emitters'):
        if ep.name not in _REGISTRY:
            fn = ep.load()
            _REGISTRY[ep.name] = {'fn': fn, 'ext': getattr(fn, 'ext', '.' + ep.name)}

def _printed(doc):
    return doc.meta.get('variant') == 'printstream' or doc.meta.get('columnar')

# ---------------------------------------------------------------- notes
#
# doc.notes (see core.Note) is the authoritative, kind-tagged, document-order
# list every emitter below renders from. doc.footnotes/.endnotes/.annotations
# (Span-list shaped) stay untouched for the other consumers that already read
# them (pdf.py, cli.py) — the emitters here don't use them any more, because
# rendering footnotes/endnotes/annotations distinguishably (this rework's
# whole point) needs the kind/number/tag Note carries and a flat Span list
# doesn't.

ALL_NOTE_KINDS = frozenset({'footnote', 'endnote', 'annotation', 'comment'})
DEFAULT_NOTE_KINDS = frozenset({'footnote', 'endnote', 'annotation'})
# comments excluded by default: WordStar itself never printed them (spec-
# documented "not used" / never rendered) — a rescue tool opts them back in
# by passing a `notes=` set that includes 'comment' (or ALL_NOTE_KINDS).

_REF_KINDS = ('footnote', 'endnote', 'annotation', 'comment')
# All four kinds emit reference marks since 2026-08-06 (comments included --
# the mark is POSITION, not ink: WordStar printed nothing for a comment and
# printed mode still renders nothing). _ref_pairs must mirror exactly the
# kinds core.py numbers with the shared fn_counter, or every reference after
# a comment would resolve to the wrong note.

def select_notes(doc, kinds=DEFAULT_NOTE_KINDS):
    """doc.notes filtered to the requested kinds, in document order. Shared
    by convert()'s `notes=` option and usable standalone by an emitter (or a
    caller inspecting a Document before choosing a format)."""
    keep = frozenset(kinds)
    return [n for n in doc.notes if n.kind in keep]

def _annotated_notes(doc):
    """doc.notes, each paired with its DISPLAY LABEL, computed once so every
    emitter/section builds identical labels and inline markers stay in
    lockstep with the trailing note text:

      footnote/endnote  the file's own number (WordStar's real note number
                        for THAT kind — footnote #1 and endnote #1 are
                        different notes with the same number, which is why
                        they need separate counters, not one merged one)
      annotation        its own tag string (e.g. "AC1"), which is what
                        WordStar itself displays/prints for an annotation
                        instead of a number (spec: annotations carry no
                        numeric identity) — falls back to a running count
                        only when untagged
      comment           WordStar gives comments neither a number nor a tag
                        (spec: "not used"); a running count is the only
                        option, and comments have no inline reference to
                        keep in lockstep with anyway

    Numbering is computed over ALL of doc.notes regardless of any later
    `notes=` filtering, so the same note gets the same label whichever
    subset of kinds a given call chooses to render.
    """
    counters = {'footnote': 0, 'endnote': 0, 'annotation': 0, 'comment': 0}
    out = []
    for n in doc.notes:
        counters[n.kind] += 1
        if n.kind == 'annotation':
            label = n.tag or str(counters[n.kind])
        elif n.kind in ('footnote', 'endnote'):
            label = str(_display_number(doc, n, counters[n.kind] - 1))
        else:
            label = str(counters[n.kind])
        out.append((n, label))
    return out

def _display_number(doc, note, position):
    """The number WordStar would actually SHOW for a footnote/endnote --
    NOT note.number as stored.

    Verified against a real WS7 file: core.py's note.number is the file's
    raw internal index, and that index is 0-based, while WordStar's own
    documented numbering starts at 1 (a `.f#`-style dot command can move
    the start point, but the default is 1) -- so displaying note.number
    directly leaks a storage detail a WordStar user never saw ("footnote 0"
    never appeared on anyone's printed page). `position` is this note's
    0-based rank among its own kind, used as a fallback only for the rare/
    malformed case where the file never resolved a number at all.

    note.number itself is left untouched (preserve-what-you-find is a rule
    about the IR, not about presentation) -- this derives a display label
    without mutating anything. core.py doesn't parse a footnote/endnote
    start-value dot command yet (another agent is adding dot-command
    parsing separately); doc.meta['footnote_number_start'] /
    ['endnote_number_start'] is the one place designed to receive that
    value when it does. Until then both default to WordStar's documented 1.
    """
    start = doc.meta.get(f'{note.kind}_number_start', 1)
    index = note.number if note.number is not None else position
    return index + start

def _ref_pairs(pairs):
    """The subset of _annotated_notes() output that carries an inline
    reference, in the exact order core.py's fn_counter numbered them --
    index i (0-based) is the note an fnref span whose text is str(i+1)
    refers to. Needed because a fnref span's own .text is only that
    sequential position, not the note's kind-specific display label."""
    return [p for p in pairs if p[0].kind in _REF_KINDS]

def _note_slug(label):
    """Sanitize a note's display label (a number or a WordStar tag string)
    into characters safe as both a Markdown pandoc footnote-label token and
    an HTML id fragment (no whitespace, brackets, or other delimiters)."""
    return re.sub(r'[^A-Za-z0-9_.-]+', '-', label).strip('-') or '0'

# ---------------------------------------------------------------- text

def _text_width(block) -> int:
    """The column this BLOCK's text is laid out within, for centring and
    right-alignment.

    `.rm` is what WordStar itself measures against, and it is per-block because it
    is stateful -- a quoted passage narrows the margin and the passage after it
    widens back. The archive's most common values are 65 and 60. Absent any `.rm`,
    fall back to the 65 the rest of this project already wraps at.

    `.lm` is added back on: WordStar centres between the two margins, so a block
    indented to column 5 with a right margin at 60 centres about column 32, not
    column 30.
    """
    rm = block.right_margin if block.right_margin and block.right_margin > 0 else 65
    lm = block.left_margin or 0
    # left_margin is OFFSET columns (normalised 2026-08-06): text occupies
    # columns lm+1 .. rm, so WordStar's centre line is (lm + 1 + rm) / 2
    return int(rm + lm + 1)


def _align_lines(lines, align, block):
    """Centre or right-align a block's lines within the text width.

    Register C16/C17. A centred heading used to render flush left in every
    format -- the dot command was parsed, recorded, and then had no effect
    anywhere, which is a gap rather than a decision.

    'justify' is deliberately NOT padded here: WordStar justifies by widening the
    spaces it already has, and a plain-text rendering that pads to a hard column
    would fabricate whitespace the author never typed. Left and justify therefore
    render identically in text, and the distinction is preserved in the IR for the
    formats that CAN express it (HTML/RTF below).
    """
    if align not in ('center', 'right'):
        return lines
    width = _text_width(block)
    out = []
    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            out.append(ln)
            continue
        pad = width - len(stripped)
        if pad <= 0:
            out.append(stripped)
        elif align == 'center':
            out.append(' ' * (pad // 2) + stripped)
        else:
            out.append(' ' * pad + stripped)
    return out


def emit_text(doc, mode='printed', notes=DEFAULT_NOTE_KINDS, **_options):
    keep = frozenset(notes)
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    printed = mode == 'printed' or _printed(doc)
    if printed:
        # printed is always silent about comments (ruling 2026-08-06):
        # WordStar printed nothing for them, sections included
        keep = keep - {'comment'}
    out = []
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            out.append('\f' if mode == 'printed' else '\n' + '-' * 20 + '\n')
            continue
        lines = []
        # printed: PHYSICAL lines (soft returns broke the line on paper);
        # modern: logical lines, soft runs joined back (core.merged_lines)
        for line in (b.lines if printed else merged_lines(b)):
            seg = []
            for s in line.spans:
                pctl = next((t for t in s.styles if t.startswith('pctl')),
                            None)
                if pctl is not None:
                    # screen-only display string: printed pads the declared
                    # width, modern shows nothing (M4 extended, 2026-08-06)
                    if printed:
                        seg.append(' ' * round(int(pctl[4:]) / 180))
                    continue
                note, label = (_resolve_ref(refs, s.text)
                               if 'fnref' in s.styles else (None, None))
                if note is not None:
                    # comments are never marked inline in plain text: the
                    # kind has no printed identity (word scheme = markless);
                    # opted-in comments appear in the Comments section
                    if note.kind in keep and note.kind != 'comment':
                        seg.append(f'[{label}]')
                else:
                    seg.append(s.text)
            lines.append(''.join(seg))
        lines = _align_lines(lines, b.align, b)
        para = '\n'.join(lines)
        if para.strip() or mode == 'printed':
            out.append(para)
    text = ('\n'.join(out) if mode == 'printed' or _printed(doc)
            else '\n\n'.join(o for o in out if o.strip()))
    sections = [('footnote', 'Footnotes'), ('endnote', 'Endnotes'),
                ('annotation', 'Annotations'), ('comment', 'Comments')]
    for kind, title in sections:
        if kind not in keep:
            continue
        items = [(label, n.text) for n, label in pairs if n.kind == kind]
        if items:
            text += (f'\n\n{title}:\n'
                     + '\n'.join(f'[{label}] {t}' for label, t in items))
    return text + '\n'

# ---------------------------------------------------------------- markdown

_MD = {'b': '**', 'i': '*', 'strike': '~~'}
_MD_HTML = {'u': 'u', 'sup': 'sup', 'sub': 'sub'}
_MD_NOTE_PREFIX = {'footnote': '', 'endnote': 'e', 'annotation': 'a', 'comment': 'c'}

def _md_note_id(kind, label):
    """Pandoc/GFM footnote label for one note. Footnotes stay bare (`[^1]`,
    real pandoc numbering, unchanged from before this rework) so existing
    footnote-only output doesn't churn; endnotes/annotations/comments get a
    kind prefix so they don't collide with a footnote of the same label
    (a footnote #1 and an endnote #1 are different notes)."""
    return _MD_NOTE_PREFIX[kind] + _note_slug(label)

def _resolve_ref(refs, text):
    """Resolve a fnref span's text to its (note, label), or (None, None).

    SENT_FNREF is a raw 0x07 byte, so a literal 0x07 in a real document's body
    gets miscounted as a footnote reference and yields an index with no note
    behind it. Out of range therefore means "not actually a reference": degrade
    to the raw text instead of raising. pdf.py guards the same way.
    """
    if text.isdigit():
        k = int(text)
        if 0 < k <= len(refs):
            return refs[k - 1]
    return None, None


def _md_span(s, refs=(), keep=DEFAULT_NOTE_KINDS):
    if any(t.startswith('pctl') for t in s.styles):
        return ''                  # screen-only print-control display string
    text = s.text
    if 'fnref' in s.styles:
        note, label = _resolve_ref(refs, text)
        if note is not None:
            if note.kind not in keep:
                return ''
            return f'[^{_md_note_id(note.kind, label)}]'
        # stray sentinel byte, not a real reference -- fall through as text
    if not text.strip():
        return text
    esc = text.replace('\\', '\\\\')
    for ch in '*_#`[]':
        esc = esc.replace(ch, '\\' + ch)
    lead = esc[:len(esc) - len(esc.lstrip())]
    trail = esc[len(esc.rstrip()):]
    core = esc.strip()
    # sorted: frozenset iteration order varies with hash seed, which made multi-style
    # nesting order (e.g. bold+strike) nondeterministic BETWEEN RUNS. Alphabetical
    # order happens to nest delimiter styles (b, i, strike) inside tag styles
    # (sub, sup, u), which is also what the Swift port documents. Found by the
    # ctrlkd-swift port's pre-vector determinism check (2026-07-29).
    for st in sorted(s.styles):
        if st in _MD:
            core = f'{_MD[st]}{core}{_MD[st]}'
        elif st in _MD_HTML:
            t = _MD_HTML[st]
            core = f'<{t}>{core}</{t}>'
    return lead + core + trail

def emit_markdown(doc, mode='printed', notes=DEFAULT_NOTE_KINDS, **_options):
    keep = frozenset(notes)
    if mode == 'printed' or _printed(doc):
        # alignment is the content: a fenced block is the honest representation
        body = emit_text(doc, 'printed', notes=notes)
        return '```\n' + body.rstrip('\n') + '\n```\n'
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    out = []
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            out.append('---')
            continue
        lines = [''.join(_md_span(s, refs, keep) for s in line.spans)
                 for line in merged_lines(b)]          # logical lines: soft wraps joined
        para = '\\\n'.join(l for l in lines)          # hard breaks: trailing backslash
        if b.heading and para.strip():
            para = '#' * b.heading + ' ' + para.strip()
        if para.strip():
            out.append(para)
    md = '\n\n'.join(out)
    defs = [f'[^{_md_note_id(n.kind, label)}]: {n.text}'
            for n, label in pairs if n.kind in keep]
    if defs:
        md += '\n\n' + '\n'.join(defs)
    return md + '\n'

# ---------------------------------------------------------------- html

# Body font: the sophisticated body ruling (2026-08-05) -- Georgia 14, the
# stack carrying the no-Georgia case by HTML's own nature.
_CSS = """body{max-width:42rem;margin:2rem auto;padding:0 1rem;
font:14pt/1.6 Georgia,'Times New Roman',P052,serif;color:#222}p{margin:0 0 1em}
pre{font:14px/1.5 ui-monospace,Menlo,Consolas,monospace;overflow-x:auto}
hr.pb{border:none;border-top:1px dashed #bbb;margin:2rem 0}
section[role=doc-endnotes]{margin-top:2rem}
section[role=doc-endnotes] h2{font-size:1.1rem}
@media(prefers-color-scheme:dark){body{background:#161616;color:#ddd}
hr.pb{border-top-color:#444}}"""

_TAG = {'b': 'strong', 'i': 'em', 'u': 'u', 'sup': 'sup', 'sub': 'sub', 'strike': 's'}

# DPUB-ARIA 1.1 (W3C Recommendation) roles used below, verified against the
# spec (https://www.w3.org/TR/dpub-aria-1.1/) rather than assumed:
#   doc-noteref   "a reference to a footnote or endnote ... superscripted
#                 number or symbol in the main body of text" (superclass:
#                 link) -- the inline <a>.
#   doc-endnotes  "a collection of notes at the end of a work or a section
#                 within it" (superclass: landmark). MUST contain at least
#                 one descendant list; MUST NOT be applied to the list
#                 itself; MUST NOT contain an element with role doc-footnote
#                 (redundant with the implied role). All four of our note
#                 kinds end up physically at the end of the document (Text/
#                 Markdown/HTML/RTF have no pages), so every section here --
#                 whatever the note's ORIGINAL WordStar kind -- is honestly
#                 a doc-endnotes collection, not a doc-footnote one.
#   doc-backlink  "a link that allows the user to return to a related
#                 location ... from a footnote to its reference".
#   doc-footnote  exists (superclass: section, not deprecated) but its own
#                 usage note says it's "only for representing individual
#                 notes that occur within the body of a work" -- i.e. a note
#                 rendered AT its reference point, which is exactly what our
#                 notes are NOT (they're moved to the end). Using it here
#                 would be wrong per the spec's own guidance, not just unlike
#                 the sketch.
#   doc-endnote   deprecated in DPUB-ARIA 1.1 as a listitem role ("not valid
#                 as a child of the list role" per WAI-ARIA clarifications);
#                 the spec's own replacement advice is plain list/listitem,
#                 which is what native <li> already provides with no ARIA
#                 override needed.
# Net effect: individual <li> entries carry no per-kind role at all (that
# would either be wrong or deprecated) — the KIND distinction lives in which
# doc-endnotes section an entry is in (its heading + id prefix), which is
# also how "could be re-parsed later" survives: a data-note-kind attribute
# on each entry besides.
_KIND_LABEL = {'footnote': 'Footnotes', 'endnote': 'Endnotes',
               'annotation': 'Annotations', 'comment': 'Comments'}
_KIND_PREFIX = {'footnote': 'fn', 'endnote': 'en', 'annotation': 'an', 'comment': 'cm'}

def _html_span(s, keep_ws=False):
    text = _html.escape(s.text)
    if keep_ws:
        pass
    elif text.startswith('     '):                    # typescript indent -> keep visible
        n = len(text) - len(text.lstrip())
        text = '&nbsp;' * n + text.lstrip()
    for st in sorted(s.styles):
        t = _TAG.get(st)                              # e.g. 'fnref' has no tag of its own
        if t:
            text = f'<{t}>{text}</{t}>'
    font = next((st for st in s.styles
                 if st.startswith('font') and st[4:].isdigit()), None)
    if font:
        # class only -- the matching .ws-font-N rule comes from _style_css,
        # so --no-styles leaves the class inert
        text = f'<span class="ws-{font.replace("font", "font-")}">{text}</span>'
    return text

def _html_ids(kind, label):
    """(ref_id, target_id) for one note: 'fnref1'/'fn1', 'enref1'/'en1',
    'anrefAC1'/'anAC1' -- kind-prefixed so a footnote #1 and an endnote #1
    (genuinely different notes) never collide."""
    prefix = _KIND_PREFIX[kind]
    slug = _note_slug(label)
    return f'{prefix}ref{slug}', f'{prefix}{slug}'

def _html_note_ref(note, label, shown=None):
    """<sup><a ...role="doc-noteref">N</a></sup>: an anchored, backlinkable
    inline reference -- the previous output was a bare <sup>1</sup> with no
    anchor at all, so nothing linked to the note and nothing linked back.
    `shown` overrides the visible text only (the `prefixed` scheme); the
    ids stay kind-prefixed and stable either way."""
    ref_id, target_id = _html_ids(note.kind, label)
    return (f'<sup><a id="{ref_id}" href="#{target_id}" role="doc-noteref">'
            f'{_html.escape(shown if shown is not None else label)}</a></sup>')

def _html_line(line, refs, keep, keep_ws=False, shown_map=None):
    out = []
    for s in line.spans:
        pctl = next((t for t in s.styles if t.startswith('pctl')), None)
        if pctl is not None:
            if keep_ws:                        # the printed physical layer
                out.append(' ' * round(int(pctl[4:]) / 180))
            continue
        if 'fnref' in s.styles:
            note, label = _resolve_ref(refs, s.text)
            if note is not None:
                if note.kind in keep:
                    if note.kind == 'comment' and shown_map is None:
                        # word scheme: comments are markless (a bubble in
                        # Word, a section entry here) -- an empty visible
                        # anchor would be noise, so none is emitted
                        continue
                    shown = (shown_map[id(note)]
                             if shown_map is not None else None)
                    out.append(_html_note_ref(note, label, shown))
                continue
        out.append(_html_span(s, keep_ws))
    return ''.join(out)

def _html_notes_sections(pairs, keep, linked_kinds=_REF_KINDS):
    sections = []
    for kind in ('footnote', 'endnote', 'annotation', 'comment'):
        if kind not in keep:
            continue
        items = [(n, label) for n, label in pairs if n.kind == kind]
        if not items:
            continue
        lis = []
        for n, label in items:
            ref_id, target_id = _html_ids(kind, label)
            text = _html.escape(n.text)
            tag_attr = f' data-note-tag="{_html.escape(n.tag)}"' if n.tag else ''
            back = (f' <a href="#{ref_id}" role="doc-backlink">↩</a>'
                    if kind in linked_kinds else '')
            lis.append(f'<li id="{target_id}" data-note-kind="{kind}"{tag_attr}>{text}{back}</li>')
        heading_id = f'{kind}s-label'
        sections.append(
            f'<section role="doc-endnotes" aria-labelledby="{heading_id}">'
            f'<h2 id="{heading_id}">{_KIND_LABEL[kind]}</h2>'
            f'<ol>{"".join(lis)}</ol></section>')
    return sections

_HTML_ALIGN = {'center': ' style="text-align:center"',
               'right': ' style="text-align:right"',
               'justify': ' style="text-align:justify"'}

# RTF paragraph-alignment controls. `\ql` is the default and is emitted only to
# CLOSE a previous alignment, since RTF alignment persists across \par.
_RTF_ALIGN = {'center': r'\qc ', 'right': r'\qr ', 'justify': r'\qj ',
              'left': r'\ql '}


def _font_family(name):
    """The renderable family from a spec typestyle name: 'Helv (also
    Helvetica, CG Triumvirate, and Swiss)' -> 'Helv'. The verbatim name
    stays in doc.fonts (pass-through); this is presentation only."""
    return (name or '').split(' (')[0].strip()


def _font_ctl_rtf(doc, target='office'):
    """(fonttbl_extra, {'fontN': control}) for RTF: one \fK per DISTINCT
    resolved primary (starting at \f2), plus \fs from the block's own height
    word.

    Primary + falt come from fontmap.rtf_fonts for the chosen render TARGET
    (office/mac/google -- Jon's ruling, 2026-08-04 night): the primary is
    the target's best available name, the falt the next-best MODERN name --
    never the era name, which nothing modern resolves ('PS SansSer Qual').
    Unmapped and even UNNAMED fonts land on the target's generic primary
    from the font block's own style bits, so every run gets a usable face.
    The verbatim era name stays first-class in doc.fonts and leads the HTML
    stacks, where CSS fallback works properly."""
    extra, ctl, prim_to_k = [], {}, {}
    next_k = 2
    for idx, f in enumerate(doc.fonts):
        parts = ''
        fam = _font_family(f.get('typestyle_name'))
        primary, falt = rtf_fonts(fam, f.get('generic_style'), target)
        if primary:
            if primary not in prim_to_k:
                prim_to_k[primary] = next_k
                safe = primary.replace('\\', '').replace('{', '').replace('}', '')
                if falt and falt != primary:
                    extra.append('{\\f%d %s{\\*\\falt %s};}' % (next_k, safe, falt))
                else:
                    extra.append('{\\f%d %s;}' % (next_k, safe))
                next_k += 1
            parts += '\\f%d' % prim_to_k[primary]
        pts = f.get('points')
        if pts:
            parts += '\\fs%d' % round(pts * 2)
        if parts:
            ctl['font%d' % idx] = parts + ' '
    return ''.join(extra), ctl


def _style_slug(entry):
    """A stable, readable CSS class for one library entry: slot + slugged
    name (slot disambiguates same-named entries)."""
    slug = re.sub(r'[^a-z0-9]+', '-', entry['name'].lower()).strip('-') or 'style'
    return f"ws-{entry['slot']}-{slug}"


def _style_css(doc):
    """CSS rules derived from the style records themselves -- a PASS-THROUGH
    of the file's own data (Jon, 2026-08-04: never hardwire a style name to
    a font or size; expose the data so a consumer can attach its own). Every
    property below comes from the entry's 102-byte record: alignment,
    margins (HMI/1800 = inches), print attributes, and the font block's
    height word (VMI/20 = points). Inherited fields emit nothing."""
    rules = []
    for entry in doc.styles:
        if 'attrs_on' not in entry:            # recordless base entry
            continue
        props = []
        if entry.get('justification') in ('left', 'center', 'right', 'justify'):
            props.append(f"text-align:{entry['justification']}")
        if entry.get('left_margin_hmi'):
            props.append('margin-left:%.2fin' % (entry['left_margin_hmi'] / 1800.0))
        if entry.get('right_margin_hmi'):
            props.append('margin-right:%.2fin' % (entry['right_margin_hmi'] / 1800.0))
        a = entry.get('attrs', frozenset())
        if 'b' in a:
            props.append('font-weight:bold')
        if 'i' in a:
            props.append('font-style:italic')
        deco = [d for tag, d in (('u', 'underline'), ('strike', 'line-through'))
                if tag in a]
        if deco:
            props.append('text-decoration:' + ' '.join(deco))
        font = entry.get('font')
        if font:
            w, h, ts = font
            if h:
                props.append('font-size:%.4gpt' % (h / 20.0))
            props.append(f'--ws-typestyle:{ts & 0x01FF}')
        if props:
            rules.append(f'.{_style_slug(entry)} {{ {"; ".join(props)} }}')
    for idx, f in enumerate(doc.fonts):
        props = []
        fam = _font_family(f.get('typestyle_name'))
        if fam:
            stack = font_stack(fam, f.get('generic_style'))
            css = ', '.join(n if ' ' not in n and n.islower() else f"'{n}'"
                            for n in stack)
            props.append(f'font-family:{css}')
        if f.get('points'):
            props.append('font-size:%.4gpt' % f['points'])
        if props:
            rules.append(f'.ws-font-{idx} {{ {"; ".join(props)} }}')
    return '\n'.join(rules)


def _slice_spans(spans, start, end=None):
    """`spans` cut to the character range [start, end) (end=None: to the
    end) -- modern_flow's own `.lm`-drop generalised to an arbitrary
    offset, so a marker/label/padding strip can happen on the STYLED spans
    (bold, italics, fonts) instead of the plain text classify_rows worked
    from, and stay stylistically correct on the way to HTML."""
    total = sum(len(sp.text) for sp in spans)
    if end is None:
        end = total
    out, pos = [], 0
    for sp in spans:
        sp_start, sp_end = pos, pos + len(sp.text)
        pos = sp_end
        lo, hi = max(start, sp_start), min(end, sp_end)
        if lo < hi:
            out.append(Span(sp.text[lo - sp_start:hi - sp_start], sp.styles))
    return out


_LIST_TAG = {'bullet': 'ul', 'def': 'dl'}


class _HtmlListBuilder:
    """Turns a stream of classified Modern rows (layout.py's
    classify_rows(), the same classification the `layout` JSON emitter
    exposes) into nested <ul>/<dl> markup -- HTML and layout.json agree on
    where a list starts, ends, and nests, because they share the one
    classifier. A row with no structure (kind=None) closes any open list
    back to the document flow and renders as an ordinary <p>, same as
    before this rule set existed."""

    def __init__(self):
        self._root = []
        # (level, kind, items-array-of-the-open-list, current-item's-own-
        # node-list); the root frame's "list" and "item" are both _root
        # itself, since top-level content is a flat flow, not <li> content
        self._stack = [(0, None, self._root, self._root)]

    def add_text(self, html):
        if html.strip():
            self._stack = self._stack[:1]
            self._root.append(('text', html))

    def add_bullet(self, level, cls, html):
        self._open(level, 'bullet', cls, html)

    def add_def(self, level, cls, dt_html, dd_html):
        self._open(level, 'def', cls, (dt_html, dd_html))

    def _open(self, level, kind, cls, content):
        while len(self._stack) > 1 and not (
                self._stack[-1][0] < level or
                (self._stack[-1][0] == level and self._stack[-1][1] == kind)):
            self._stack.pop()
        top_level, top_kind, top_items, top_cur_item = self._stack[-1]
        if top_level == level and top_kind == kind:
            new_item = []
            top_items.append(new_item)
            self._stack[-1] = (top_level, top_kind, top_items, new_item)
        else:
            new_items = []
            new_item = []
            new_items.append(new_item)
            top_cur_item.append(('list', kind, cls, new_items))
            self._stack.append((level, kind, new_items, new_item))
        self._stack[-1][3].append(('text', content))

    def flush(self, parts):
        parts.extend(_render_list_nodes(self._root))
        self._root = []
        self._stack = [(0, None, self._root, self._root)]


def _render_list_nodes(nodes):
    out = []
    for kind, *rest in nodes:
        if kind == 'text':
            out.append(rest[0])
            continue
        _, list_kind, cls, items = (kind,) + tuple(rest)
        if list_kind == 'def':
            entries = []
            for item in items:
                head, tail = item[0], item[1:]
                dt, dd = head[1]
                entries.append(f'<dt{cls}>{dt}</dt><dd{cls}>{dd}'
                                f'{"".join(_render_list_nodes(tail))}</dd>')
            out.append(f'<dl>{"".join(entries)}</dl>')
        else:
            entries = []
            for item in items:
                head, tail = item[0], item[1:]
                entries.append(f'<li{cls}>{head[1]}'
                                f'{"".join(_render_list_nodes(tail))}</li>')
            out.append(f'<ul>{"".join(entries)}</ul>')
    return out


def _classify_modern_blocks(doc):
    """{block_index: [(Line, structure_or_None), ...]} for every ordinary
    (non-heading, non-pagebreak, non-multi-column) block, classified as
    ONE document-wide row sequence -- bullet-marker discovery and nesting
    both need the whole order, not one block seen in isolation. Mirrors
    layout.modern_flow()'s own row-building exactly, so HTML sees the
    identical classification the `layout` JSON emitter would for the same
    document."""
    from .layout import classify_rows, FULL_COLS

    entries, plan = [], []
    for bi, b in enumerate(doc.blocks):
        if b.kind == 'pagebreak' or b.heading or (b.columns and b.columns > 1):
            entries.append(('hard',))
            plan.append(None)
            continue
        lm = b.left_margin or 0
        rm = b.right_margin or 0
        cut = max(0, FULL_COLS - rm) if rm else 0
        for line in merged_lines(b):
            text = ''.join(sp.text for sp in line.spans)
            entries.append(('para', lm, cut, b.align, text))
            plan.append((bi, line))

    by_block = {}
    for row, s in zip(plan, classify_rows(entries)):
        if row is None:
            continue
        bi, line = row
        by_block.setdefault(bi, []).append((line, s))
    return by_block


class _SpanRow:
    """A bare `.spans` holder -- just enough for _html_line(), which only
    ever reads that one attribute off whatever it's given."""
    __slots__ = ('spans',)

    def __init__(self, spans):
        self.spans = spans


def _html_slice(line, start, end, refs, keep, shown_map):
    return _html_line(_SpanRow(_slice_spans(line.spans, start, end)),
                      refs, keep, shown_map=shown_map)


def _html_centered_row(line, s, refs, keep, shown_map):
    """The centred line's own text with its alignment padding sliced off
    (both mechanisms: a real align=center tag already had the M3 strip
    upstream, so lead/trail are 0 and this is a no-op; spaces-only
    centering strips the padding here for the first time)."""
    raw = ''.join(sp.text for sp in line.spans)
    lead = len(raw) - len(raw.lstrip(' '))
    trail = len(raw) - len(raw.rstrip(' '))
    return _html_slice(line, lead, len(raw) - trail, refs, keep, shown_map)


def emit_html(doc, mode='printed', title='', notes=DEFAULT_NOTE_KINDS,
              styles=True, note_refs='word', **_options):
    keep = frozenset(notes)
    style_class = {}
    if styles:
        style_class = {s['slot']: ' class="%s"' % _style_slug(s)
                       for s in doc.styles}
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    parts = []
    printed = mode == 'printed' or _printed(doc)
    if printed:
        # printed is always silent about comments (ruling 2026-08-06)
        keep = keep - {'comment'}
    # `prefixed` reference labels (ruling 2026-08-06) change the visible
    # mark text only; ids and sections are structural and stay put
    shown_map = (note_ref_labels(pairs, 'prefixed')
                 if note_refs == 'prefixed' and not printed else None)
    # Structure rules (M-rules addendum, 2026-08-13) only apply to the
    # reflowed Modern view -- printed is a physical facsimile, its <pre>
    # blocks stay exactly the plain-text-of-the-page they always were.
    block_rows = {} if printed else _classify_modern_blocks(doc)
    builder = _HtmlListBuilder()
    for bi, b in enumerate(doc.blocks):
        if b.kind == 'pagebreak':
            if not printed:
                builder.flush(parts)
            parts.append('<hr class="pb">')
            continue
        cls = style_class.get(b.style_id, '')
        if b.heading:
            if not printed:
                builder.flush(parts)
            # merged either mode: a heading is a logical unit, and joining its
            # logical lines with a space is what this always rendered
            txt = ' '.join(_html_line(line, refs, keep, shown_map=shown_map) for line in merged_lines(b)).strip()
            if txt:
                parts.append(f'<h{b.heading}{cls}>{txt}</h{b.heading}>')
            continue
        if printed:
            # PHYSICAL lines: inside <pre>, a soft return is a real line break
            body = '\n'.join(_html_line(line, refs, keep, keep_ws=True, shown_map=shown_map) for line in b.lines)
            if body.strip():
                parts.append(f'<pre{cls}>{body}</pre>')
        elif b.columns and b.columns > 1:
            # C5: newspaper columns. CSS does this properly, so HTML is the one
            # format that can honour `.co` rather than merely record it. A gutter
            # is print columns at 10 CPI -> tenths of an inch. Opaque to the
            # structure rules today (excluded from classification above) --
            # flush first so a list never straddles one.
            builder.flush(parts)
            lines = [_html_line(line, refs, keep, shown_map=shown_map) for line in merged_lines(b)]
            para = '<br>\n'.join(lines)
            if para.strip():
                style = _HTML_ALIGN.get(b.align, '')
                gap = ('; column-gap:%.2fin' % (b.column_gutter / 10.0)
                       if b.column_gutter else '')
                col = f' style="column-count:{b.columns}{gap}"'
                parts.append(f'<div{col}><p{cls}{style}>{para}</p></div>')
        else:
            # A plain (non-list, non-centred) row joins the REST of its
            # own block's plain lines into one <p> with <br> between them,
            # exactly as before this rule set existed -- only a line that
            # actually matches one of the three rules ever breaks out of
            # that into its own element, so an ordinary multi-line block
            # (an address, a signature) still renders as one paragraph.
            plain_buf = []
            style = _HTML_ALIGN.get(b.align, '')

            def _flush_plain():
                if plain_buf:
                    html = '<br>\n'.join(plain_buf)
                    if html.strip():
                        builder.add_text(f'<p{cls}{style}>{html}</p>')
                    plain_buf.clear()

            for line, s in block_rows.get(bi, []):
                if s is None or s['kind'] is None:
                    # Only the untagged, spaces-padded mechanism is new
                    # here (rule 3's second half) -- a real align=center/
                    # right/justify tag already renders correctly via
                    # _HTML_ALIGN below and is left exactly as it was, so
                    # a document using only the tag stays byte-identical.
                    if s is not None and s['centered'] and s['center_via'] == 'spaces':
                        _flush_plain()
                        html = _html_centered_row(line, s, refs, keep, shown_map)
                        if html.strip():
                            builder.add_text(f'<p{cls} style="text-align:center">{html}</p>')
                    else:
                        plain_buf.append(_html_line(line, refs, keep, shown_map=shown_map))
                    continue
                _flush_plain()
                if s['kind'] == 'bullet':
                    raw = ''.join(sp.text for sp in line.spans)
                    body = _html_slice(line, len(raw) - len(s['body']), None,
                                       refs, keep, shown_map)
                    builder.add_bullet(s['level'], cls, body)
                else:  # 'def'
                    raw = ''.join(sp.text for sp in line.spans)
                    lead = len(raw) - len(raw.lstrip(' '))
                    dt = _html_slice(line, lead, lead + len(s['label']),
                                     refs, keep, shown_map)
                    dd = _html_slice(line, len(raw) - len(s['body']), None,
                                     refs, keep, shown_map)
                    builder.add_def(s['level'], cls, dt, dd)
            _flush_plain()
    builder.flush(parts)
    linked = (_REF_KINDS if shown_map is not None
              else tuple(k for k in _REF_KINDS if k != 'comment'))
    sections = _html_notes_sections(pairs, keep, linked)
    if sections:
        parts.append('<hr>')
        parts.extend(sections)
    css = _CSS
    if styles:
        extra = _style_css(doc)
        if extra:
            css = css + '\n' + extra
    return ('<!doctype html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_html.escape(title)}</title><style>{css}</style></head>\n'
            f'<body>\n' + '\n'.join(parts) + '\n</body></html>\n')

# ---------------------------------------------------------------- rtf

_RTF_ON = {'b': r'\b ', 'i': r'\i ', 'u': r'\ul ', 'sup': r'\super ',
           'sub': r'\sub ', 'strike': r'\strike '}

_RTF_COMMENT_AUTHOR = 'ctrl-kd'   # public repo: a tool name, not a person

def _rtf_escape(text):
    out = []
    for ch in text:
        if ch in '\\{}':
            out.append('\\' + ch)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            out.append(f'\\u{ord(ch)}?')
    return ''.join(out)

def note_ref_labels(pairs, scheme):
    """{id(note): shown_label} for the `prefixed` note-reference scheme
    (ruling 2026-08-06): footnotes bare (1, 2, 3), endnotes e1 e2,
    annotations a1 a2 -- the SAME labels the Markdown emitter has always
    written, so a document's reference marks match across every Modern
    format. Under `word` (the default) this returns the stored labels
    unchanged and each format applies its own Word-standard display on top
    (arabic footnotes, roman endnotes in the PDF, WordStar tags for
    annotations)."""
    shown, ords = {}, {}
    for note, label in pairs:
        k = ords.get(note.kind, 0) + 1
        ords[note.kind] = k
        if scheme == 'prefixed':
            if note.kind == 'endnote':
                shown[id(note)] = 'e%s' % label
            elif note.kind == 'annotation':
                shown[id(note)] = 'a%d' % k
            elif note.kind == 'comment':
                shown[id(note)] = 'c%d' % k
            else:
                shown[id(note)] = label
        else:
            shown[id(note)] = label
    return shown


def _rtf_note_dest(note, label, mark_override=None):
    """The genuine `{\\*\\footnote ...}` destination for one footnote,
    endnote, or annotation, plus the inline mark that anchors it (a
    footnote is anchored to the character(s) immediately preceding its
    destination group -- RTF spec, Footnotes section).

    Footnotes/endnotes get Word's own AUTOMATIC reference character,
    \\chftn -- exactly the spec's own worked example:
        ...amply annotated.\\chftn {\\*\\footnote \\pard\\plain \\fs20
        {\\up6\\chftn }See Sahlins...}
    i.e. \\chftn appears twice: once in the body as the anchor, once
    echoed (raised) as the first thing inside the note text -- so Word/
    Pages both number it for real AND paginate it at the true page bottom.

    Endnotes use the same \\footnote destination with the \\ftnalt flag,
    which marks that specific note as an endnote rather than a footnote
    (collected/placed separately by a \\ftnalt-aware reader; older readers
    that don't recognise the flag still show it as an ordinary footnote --
    graceful, not broken). RTF has no separate "\\endnote" control word;
    \\ftnalt on a \\footnote destination IS the real endnote mechanism.

    Annotations carry a WordStar TAG, not a number, so \\chftn (auto-
    numbered) would be dishonest -- \\chftn is optional, not mandatory, and
    a literal custom mark is equally valid RTF (this is how Word's own
    "custom mark" footnotes work). Annotations also get \\ftnalt: they were
    never page-bottom footnotes in WordStar either, and endnote-style
    end-of-section collection is the closer honest fit of the two RTF has.
    """
    flag = r'\ftnalt' if note.kind in ('endnote', 'annotation') else ''
    if note.kind == 'annotation' or mark_override is not None:
        # custom mark: the annotation's tag, or the `prefixed` scheme's
        # label (e1/a1) standing in for \chftn on any kind
        mark_txt = _rtf_escape(mark_override
                               if mark_override is not None else label)
        mark = '{' + r'\super ' + mark_txt + '}'
        echo = r'\super ' + mark_txt + ' '
    else:
        mark = '{' + r'\chftn' + '}'
        echo = r'\super\chftn '
    dest = ('{' + r'\*\footnote' + flag + r' \pard\plain\fs24 {' + echo + '}'
            + _rtf_escape(note.text) + '}')
    return mark + dest

def _rtf_comment_dest(note):
    """A real RTF `{\\*\\annotation ...}` -- Word's actual margin-comment
    feature (\\chatn / \\atnid / \\annotation), not a footnote repurposed.
    This is the closest honest match for a WordStar comment: Word comments
    are, like WordStar comments, hidden from the printed/reading view by
    default and only surfaced in a reviewing UI on request -- the same
    "never printed, only reachable on request" identity core.py already
    documents for this kind.

    WordStar comments carry no source anchor point at all (core.py never
    emits an inline reference sentinel for them -- WordStar itself never
    prints them inline either), so there is no true "character it follows"
    to attach to. Opted-in comments are therefore anchored together at the
    very end of the document text, each still using the real annotation
    destination rather than being dumped as plain trailing text.
    """
    return ('{' + r'\chatn}{\*\atnid ' + _RTF_COMMENT_AUTHOR + '}{'
            + r'\*\annotation \pard\plain\fs24 ' + _rtf_escape(note.text) + '}')

def _rtf_span(sp, refs, keep, fontctl=None, printed=False, shown_map=None):
    if 'fnref' in sp.styles:
        note, label = _resolve_ref(refs, sp.text)
        if note is not None:
            if note.kind not in keep:
                return ''
            if note.kind == 'comment':
                # printed is a facsimile: WordStar printed nothing for a
                # comment, so neither do we (the CLI explains on stderr).
                # Modern anchors a real Word margin comment at the TRUE
                # position (the end-of-document dump this replaces lost
                # it); `prefixed` adds the visible c-mark, `word` stays
                # markless -- Word's own convention is a bubble, not a
                # superscript.
                if printed:
                    return ''
                mark = ('{' + r'\super ' + _rtf_escape(shown_map[id(note)])
                        + '}' if shown_map is not None else '')
                return mark + _rtf_comment_dest(note)
            override = (shown_map[id(note)]
                        if shown_map is not None
                        and note.kind in ('endnote', 'annotation') else None)
            return _rtf_note_dest(note, label, override)
    pctl = next((t for t in sp.styles if t.startswith('pctl')), None)
    if pctl is not None:
        # A 0x0F print control's display string is SCREEN-ONLY: on paper
        # WordStar sent the raw printer payload and advanced by the block's
        # HMI word. Printed pads that width (10-CPI print columns); Modern
        # shows NOTHING -- the string is an editor-screen artifact, and
        # command codes are invisible (M4, extended to print controls,
        # ruling 2026-08-06 round 3).
        if printed:
            pad = ' ' * round(int(pctl[4:]) / 180)
            return '{' + pad + '}' if pad else ''
        return ''
    styles = sorted(st for st in sp.styles if st != 'fnref')
    ctl = ''.join(_RTF_ON.get(st, '') for st in styles)
    if fontctl:
        ctl += ''.join(fontctl.get(st, '') for st in styles if st.startswith('font'))
    return '{' + ctl + _rtf_escape(sp.text) + '}'

def _rtf_stylesheet(doc):
    """An RTF \\stylesheet group derived from the style records -- the same
    pass-through rule as the HTML CSS: properties come from the file's own
    data, names are carried verbatim, nothing is hardwired. \\sN numbers are
    slot+1 (RTF style 0 is reserved for Normal)."""
    entries = []
    for entry in doc.styles:
        if 'attrs_on' not in entry:
            continue
        props = ''
        props += {'center': r'\qc', 'right': r'\qr',
                  'justify': r'\qj'}.get(entry.get('justification'), '')
        if entry.get('left_margin_hmi'):
            props += r'\li%d' % round(entry['left_margin_hmi'] / 1800.0 * 1440)
        if entry.get('right_margin_hmi'):
            props += r'\ri%d' % round(entry['right_margin_hmi'] / 1800.0 * 1440)
        a = entry.get('attrs', frozenset())
        for tag, ctl in (('b', r'\b'), ('i', r'\i'), ('u', r'\ul'),
                         ('strike', r'\strike')):
            if tag in a:
                props += ctl
        font = entry.get('font')
        if font and font[1]:
            props += r'\fs%d' % round(font[1] / 20.0 * 2)     # half-points
        name = entry['name'].replace('\\', '').replace('{', '').replace('}', '')
        entries.append(r'{\s%d%s %s;}' % (entry['slot'] + 1, props, name))
    return (r'{\stylesheet{\s0 Normal;}' + ''.join(entries) + '}') if entries else ''


def _strip_align_spaces(spans):
    """Spans minus leading/trailing spaces -- for center/right blocks under
    Modern. WordStar 5+ aligned at EDITOR time, so the file carries BOTH the
    alignment tag and the spaces that implemented it; emitting both aligns
    twice (ruling 2026-08-06). The tag does the work now."""
    out = list(spans)
    while out:
        t = out[0].text.lstrip(' ')
        if t:
            if t != out[0].text:
                out[0] = Span(t, out[0].styles)
            break
        out.pop(0)
    while out:
        t = out[-1].text.rstrip(' ')
        if t:
            if t != out[-1].text:
                out[-1] = Span(t, out[-1].styles)
            break
        out.pop()
    return out


# WordStar print-toggle bytes that legitimately appear inside header/footer
# TEXT (a `.h1` line carries them raw -- LJ6DTP's is `^B^BLJ6DTP ... ^B`).
# Interpreted minimally here: toggles flip a style, every other control byte
# is stripped (0x0F print-control lead-ins included). U+2219 maps to the
# cp1252-friendly bullet so PDF measurement and drawing agree; one glyph,
# consistent across formats.
_HF_TOGGLES = {0x02: 'b', 0x19: 'i', 0x13: 'u',
               0x14: 'sup', 0x16: 'sub', 0x18: 'strike'}


def hf_runs(txt):
    """A running-head string -> [(text, styles)] with WordStar's own toggle
    bytes interpreted and remaining control bytes stripped. Returns [] for a
    head that is nothing but control bytes (LJ6DTP's `.f1` is two 0x0F
    bytes) -- callers skip those instead of rendering junk."""
    runs, buf, active = [], [], set()

    def flush():
        if buf:
            runs.append((''.join(buf), frozenset(active)))
            buf.clear()

    for ch in txt.replace('∙', '•'):
        code = ord(ch)
        if code in _HF_TOGGLES:
            flush()
            tag = _HF_TOGGLES[code]
            active.symmetric_difference_update({tag})
            continue
        if code < 0x20:
            continue
        buf.append(ch)
    flush()
    # whitespace runs SURVIVE (a head positions its parts with baked
    # spaces); only a head with no visible text at all empties out
    if not any(t.strip() for t, _ in runs):
        return []
    return runs


def _rtf_running_heads(doc):
    """Modern RTF `\\header`/`\\footer` groups from the document's own
    running heads (ruling 2026-08-06: Modern keeps headers).

    RTF carries ONE header per section; a document that redefines its head
    mid-file keeps the FIRST definition of each line slot (the common case
    -- OLDTIMES -- defines each exactly once). WordStar's `#` token becomes
    \\chpgn, Word's own page-number field. A head first defined after the
    opening block gets \\titlepg with an empty first-page header: the
    manuscript convention (no running head on page 1), and exactly what
    WordStar itself printed when `.h1` follows page 1's title."""
    hdr, ftr = {}, {}
    first_anchor = None
    for kind, lno, txt, anchor in getattr(doc, 'hf_events', ()):
        d = hdr if kind == 'H' else ftr
        if lno not in d and txt:
            d[lno] = txt
            if first_anchor is None or anchor < first_anchor:
                first_anchor = anchor
    if not hdr and not ftr:
        return ''

    def group(name, lines):
        if not lines:
            return ''
        rendered = []
        for n in sorted(lines):
            runs = hf_runs(lines[n])
            if not runs:
                continue                     # control-bytes-only head
            rendered.append(''.join(
                '{' + ''.join(_RTF_ON.get(st, '') for st in sorted(styles))
                + _rtf_escape(text).replace('#', r'{\chpgn }') + '}'
                for text, styles in runs))
        if not rendered:
            return ''
        return (r'{\%s \pard\plain \f0\fs22 %s\par}'
                % (name, r'\line '.join(rendered)))

    out = group('header', hdr) + group('footer', ftr)
    if first_anchor and first_anchor > 0:
        out = r'\titlepg{\headerf \pard\plain\par}' + out
    return out


def emit_rtf(doc, mode='printed', notes=DEFAULT_NOTE_KINDS, styles=True,
             fonts_target='office', note_refs='word', **_options):
    keep = frozenset(notes)
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    printed = mode == 'printed' or _printed(doc)
    if printed:
        # printed is always silent about comments (ruling 2026-08-06)
        keep = keep - {'comment'}
    # `prefixed` note references (ruling 2026-08-06): endnotes/annotations
    # anchor with literal e1/a1 custom marks instead of \chftn/tags -- the
    # Markdown emitter's own labels, matched across formats. Never printed:
    # the facsimile shows what WordStar printed.
    shown_map = (note_ref_labels(pairs, 'prefixed')
                 if note_refs == 'prefixed' and not printed else None)
    font = r'\f1' if printed else r'\f0'
    stylesheet = _rtf_stylesheet(doc) if styles else ''
    fonttbl_extra, fontctl = (_font_ctl_rtf(doc, fonts_target)
                              if styles else ('', {}))
    styled_slots = ({s['slot'] for s in doc.styles if 'attrs_on' in s}
                    if styles else set())
    parts = []
    rtf_align = 'left'          # RTF alignment persists across \par
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            parts.append(r'\page ')
            continue
        lines = []
        # printed: physical lines (\line at every printed break, soft or hard);
        # modern: logical lines only
        for line in (b.lines if printed else merged_lines(b)):
            spans = line.spans
            if not printed and b.align in ('center', 'right') and spans:
                # editor-time alignment: the spaces implemented the tag;
                # keeping both aligns twice (ruling 2026-08-06)
                spans = _strip_align_spaces(spans)
            seg = ''.join(_rtf_span(sp, refs, keep, fontctl, printed,
                                    shown_map)
                          for sp in spans)
            lines.append(seg)
        if b.heading:
            lines = ['{' + r'\b\fs28 ' + l + '}' for l in lines]
        joiner = r'\line ' if not printed else r'\line '
        para = joiner.join(lines)
        if para.strip() or printed:
            # C16/C17. RTF alignment PERSISTS across \par, so a block must emit its
            # control whenever the alignment differs from the one still in force --
            # including `\ql` to return to flush left. Tracking the running value
            # keeps a document that never aligns anything byte-identical to before.
            if b.align != rtf_align:
                parts.append(_RTF_ALIGN[b.align])
                rtf_align = b.align
            if b.style_id in styled_slots:
                # style pass-through: tag the paragraph with its \sN so a
                # consumer can act on the named style (the visible formatting
                # is still carried inline, as RTF readers expect)
                parts.append(r'\s%d ' % (b.style_id + 1))
            parts.append(para + r'\par ')
        if not printed:
            # Only the author's own blank lines make space (ruling
            # 2026-08-06): a block boundary is often just a dot command,
            # and command codes are invisible.
            parts.extend([r'\par '] * trailing_blank_lines(b))
    body = '\n'.join(parts)
    # The sophisticated body (Jon's specimen ruling, 2026-08-05): text with
    # no font information reads in Georgia 14 under Modern -- "like reading
    # a cozy book" -- one font for every target, the per-target variation
    # riding in the falt (RTF's own no-Georgia safety net). Printed keeps
    # Courier 12: a fontless document on the era's fixed grid IS a
    # typescript, and Printed gap-fills with 1990.
    from .fontmap import MODERN_BODY, MODERN_BODY_SIZE
    b_primary, b_falt = MODERN_BODY.get(fonts_target, MODERN_BODY['office'])
    f0 = (r'{\f0 %s{\*\falt %s};}' % (b_primary, b_falt) if b_falt
          else r'{\f0 %s;}' % b_primary)
    body_fs = r'\fs%d' % (MODERN_BODY_SIZE * 2)
    if printed:
        f0, body_fs = r'{\f0 Times New Roman;}', r'\fs24'
    # Page setup, emitted EXPLICITLY: without \paperw/\margl the opening
    # app's locale decides the paper (A4 in most of the world) and the
    # "Modern page settings" ruling would be fiction. Geometry per the
    # governing principle: the document's declared values win; silence is
    # filled by the mode's own page (Modern: 1in Letter; Printed: the era
    # page from doc.meta, which core already resolved with its defaults).
    page = doc.meta.get('page') or {}
    def _twips_lines(key, default_lines):
        v = page.get(key, default_lines)
        return int(round(float(v) * 240))            # 1 line at 6 LPI = 240 twips
    if printed:
        margt = _twips_lines('mt_lines', 3.0)
        margb = _twips_lines('mb_lines', 8.0)
        margl = int(round(float(page.get('po_cols', 8.0)) * 144))
        paperh = int(round(float(page.get('height_in', 11.0)) * 1440))
    else:
        margt = (_twips_lines('mt_lines', 6.0)
                 if page.get('mt_source', 'default') != 'default' else 1440)
        margb = (_twips_lines('mb_lines', 6.0)
                 if page.get('mb_source', 'default') != 'default' else 1440)
        margl = (int(round(float(page.get('po_cols', 10.0)) * 144))
                 if page.get('po_source', 'default') != 'default' else 1440)
        paperh = (int(round(float(page.get('height_in', 11.0)) * 1440))
                  if page.get('size_source', 'default') != 'default'
                  else 15840)
    # width joined the page model 2026-08-06: A4-tall documents get the
    # 210mm sheet; everything else (and every default) stays 12240 twips
    paperw = int(round(float(page.get('pw_in', 8.5)) * 1440))
    pagesetup = (r'\paperw%d\paperh%d\margl%d\margr%d\margt%d\margb%d'
                 % (paperw, paperh, margl, margl, margt, margb))
    running = '' if printed else _rtf_running_heads(doc)
    return (r'{\rtf1\ansi\deff0{\fonttbl' + f0 + r'{\f1 Courier New;}'
            + fonttbl_extra + '}'
            + stylesheet
            + pagesetup
            + running
            + '\n' + font + body_fs + ' ' + '\n' + body + '\n}\n')

# built-ins register through the same door plugins use
emitter('text', ext='.txt')(emit_text)
emitter('markdown', ext='.md')(emit_markdown)
emitter('html', ext='.html')(emit_html)
emitter('rtf', ext='.rtf')(emit_rtf)
