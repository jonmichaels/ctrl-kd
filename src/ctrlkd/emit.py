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

from .core import merged_lines
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

_REF_KINDS = ('footnote', 'endnote', 'annotation')  # the three WordStar DOES
                                                     # print inline; comments
                                                     # never get a reference
                                                     # mark (core.py never
                                                     # injects one for them)

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
    return int(rm + lm)


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
                note, label = (_resolve_ref(refs, s.text)
                               if 'fnref' in s.styles else (None, None))
                if note is not None:
                    if note.kind in keep:
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

_CSS = """body{max-width:42rem;margin:2rem auto;padding:0 1rem;
font:17px/1.6 Georgia,serif;color:#222}p{margin:0 0 1em}
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

def _html_note_ref(note, label):
    """<sup><a ...role="doc-noteref">N</a></sup>: an anchored, backlinkable
    inline reference -- the previous output was a bare <sup>1</sup> with no
    anchor at all, so nothing linked to the note and nothing linked back."""
    ref_id, target_id = _html_ids(note.kind, label)
    return (f'<sup><a id="{ref_id}" href="#{target_id}" role="doc-noteref">'
            f'{_html.escape(label)}</a></sup>')

def _html_line(line, refs, keep, keep_ws=False):
    out = []
    for s in line.spans:
        if 'fnref' in s.styles:
            note, label = _resolve_ref(refs, s.text)
            if note is not None:
                if note.kind in keep:
                    out.append(_html_note_ref(note, label))
                continue
        out.append(_html_span(s, keep_ws))
    return ''.join(out)

def _html_notes_sections(pairs, keep):
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
                    if kind in _REF_KINDS else '')
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


def emit_html(doc, mode='printed', title='', notes=DEFAULT_NOTE_KINDS,
              styles=True, **_options):
    keep = frozenset(notes)
    style_class = {}
    if styles:
        style_class = {s['slot']: ' class="%s"' % _style_slug(s)
                       for s in doc.styles}
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    parts = []
    printed = mode == 'printed' or _printed(doc)
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            parts.append('<hr class="pb">')
            continue
        cls = style_class.get(b.style_id, '')
        if b.heading:
            # merged either mode: a heading is a logical unit, and joining its
            # logical lines with a space is what this always rendered
            txt = ' '.join(_html_line(line, refs, keep) for line in merged_lines(b)).strip()
            if txt:
                parts.append(f'<h{b.heading}{cls}>{txt}</h{b.heading}>')
            continue
        if printed:
            # PHYSICAL lines: inside <pre>, a soft return is a real line break
            body = '\n'.join(_html_line(line, refs, keep, keep_ws=True) for line in b.lines)
            if body.strip():
                parts.append(f'<pre{cls}>{body}</pre>')
        else:
            lines = [_html_line(line, refs, keep) for line in merged_lines(b)]
            para = '<br>\n'.join(lines)
            if para.strip():
                # C16/C17: HTML can express all four alignments, so unlike the
                # plain-text renderer it does not have to collapse justify into
                # left. `left` is WordStar's default and gets no attribute, so
                # every document that never touches `.oc`/`.oj` emits byte-identical
                # HTML to before.
                style = _HTML_ALIGN.get(b.align, '')
                # C5: newspaper columns. CSS does this properly, so HTML is the one
                # format that can honour `.co` rather than merely record it. A gutter
                # is print columns at 10 CPI -> tenths of an inch.
                if b.columns and b.columns > 1:
                    gap = ('; column-gap:%.2fin' % (b.column_gutter / 10.0)
                           if b.column_gutter else '')
                    col = f' style="column-count:{b.columns}{gap}"'
                    parts.append(f'<div{col}><p{cls}{style}>{para}</p></div>')
                else:
                    parts.append(f'<p{cls}{style}>{para}</p>')
    sections = _html_notes_sections(pairs, keep)
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

def _rtf_note_dest(note, label):
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
    if note.kind == 'annotation':
        mark_txt = _rtf_escape(label)
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

def _rtf_span(sp, refs, keep, fontctl=None):
    if 'fnref' in sp.styles:
        note, label = _resolve_ref(refs, sp.text)
        if note is not None:
            return _rtf_note_dest(note, label) if note.kind in keep else ''
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


def emit_rtf(doc, mode='printed', notes=DEFAULT_NOTE_KINDS, styles=True,
             fonts_target='office', **_options):
    keep = frozenset(notes)
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    printed = mode == 'printed' or _printed(doc)
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
            seg = ''.join(_rtf_span(sp, refs, keep, fontctl) for sp in line.spans)
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
            parts.append(r'\par ')                    # blank line between paragraphs
    if 'comment' in keep:
        comments = ''.join(_rtf_comment_dest(n) for n, _ in pairs if n.kind == 'comment')
        if comments:
            parts.append(comments)
    body = '\n'.join(parts)
    return (r'{\rtf1\ansi\deff0{\fonttbl{\f0 Times New Roman;}{\f1 Courier New;}'
            + fonttbl_extra + '}'
            + stylesheet
            + '\n' + font + r'\fs24 ' + '\n' + body + '\n}\n')

# built-ins register through the same door plugins use
emitter('text', ext='.txt')(emit_text)
emitter('markdown', ext='.md')(emit_markdown)
emitter('html', ext='.html')(emit_html)
emitter('rtf', ext='.rtf')(emit_rtf)
