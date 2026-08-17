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

from .core import (merged_lines, Span, trailing_blank_lines, coalesce_spans,
                   assemble_paragraphs, split_leading_indent,
                   paragraph_layout_context, looks_like_verse,
                   block_dominant_styles, effective_span_styles,
                   DEFAULT_LH_48, GRAPHIC_CHARS, split_graphic_spans)
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


def _doc_margin(doc):
    """The block's own measured wrap point -- see PARAGRAPH_JOIN_SLACK's
    docstring. `lines_pass` always resolves and stores this (core.py's own
    65-column floor applies), but a synthetically built Document (most unit
    fixtures) has no `meta` at all -- fall back to the same floor."""
    return doc.meta.get('margin_estimate') or 65


def emit_text(doc, mode='printed', notes=DEFAULT_NOTE_KINDS, **_options):
    # RULED EXCLUSION (round 5, 2026-08-17, attribute-surface audit): plain
    # text has no character-attribute vocabulary at all -- no bold, no
    # italic, no underline/strikeout, no sub/superscript, style-declared
    # or run-toggled alike. This is BY DESIGN, not a gap: `render()` below
    # reads span TEXT only and never consults `s.styles` (besides the
    # structural pctl/fnref exceptions, which are position/reference
    # markers, not character formatting) or a block's own `style_attrs`.
    # Every other Modern format has a documented, honest mapping for the
    # full attribute set (see `_MD`/`_MD_HTML` for Markdown, `_TAG` for
    # HTML, `_RTF_ON` for RTF); Text's own mapping is "none of it survives."
    keep = frozenset(notes)
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    printed = mode == 'printed' or _printed(doc)
    if printed:
        # printed is always silent about comments (ruling 2026-08-06):
        # WordStar printed nothing for them, sections included
        keep = keep - {'comment'}
    margin = _doc_margin(doc)
    convention_indent, head_position = paragraph_layout_context(doc)

    def render(line):
        seg = []
        for s in line.spans:
            pctl = next((t for t in s.styles if t.startswith('pctl')), None)
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
        return ''.join(seg)

    out = []
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            out.append('\f' if mode == 'printed' else '\n' + '-' * 20 + '\n')
            continue
        if printed:
            # PHYSICAL lines: soft returns broke the line on paper
            lines = _align_lines([render(l) for l in b.lines], b.align, b)
            para = '\n'.join(lines)
            if para.strip() or mode == 'printed':
                out.append(para)
        else:
            # Modern: one `out` entry per PARAGRAPH UNIT, not per block, so
            # the blank-line join below (unchanged) now separates typed
            # paragraphs from each other, not just Blocks from each other.
            # Within a unit, a bare newline is reserved for a REAL
            # deliberate break -- a verified verse/stanza unit (round 3b,
            # 2026-08-17: "no hard line breaks inside paragraphs in ANY
            # Modern format," matching HTML's own <br>-vs-flow rule). A
            # multi-line unit that never got verse-verified (bare phase-1
            # flush-continuation) flows as ONE line instead.
            quote = _is_quote_style(b)
            dominant = block_dominant_styles(merged_lines(b))
            for unit in assemble_paragraphs(
                    b, margin, head_position=head_position.get(id(b), False),
                    convention_indent=convention_indent):
                # round 7 (2026-08-17): a wrap=off block's unit is ALWAYS
                # treated as verse here too -- assemble_paragraphs already
                # returns it as one whole-block unit unconditionally, but
                # this is where a NON-verse multi-line unit gets flowed
                # into one line (round 3b); without the `not b.wrap` guard
                # that flow logic would still run on a hand-positioned
                # block's lines and destroy the layout via a different
                # mechanism. Register C23.
                is_verse = len(unit) > 1 and (not b.wrap or looks_like_verse(unit, dominant))
                if len(unit) > 1 and not is_verse:
                    # only the unit's own FIRST line keeps its typed indent
                    # (the paragraph-start marker, unchanged from the
                    # single-line case); continuation lines lose theirs the
                    # same way a genuine soft-wrap already would have.
                    segs = [render(unit[0])] + [render(l).lstrip(' ') for l in unit[1:]]
                    lines = _align_lines([' '.join(t for t in segs if t.strip())],
                                        b.align, b)
                else:
                    lines = _align_lines([render(l) for l in unit], b.align, b)
                if quote:
                    # rule 3 (round 3, 2026-08-17): plain text's only
                    # "quote" vocabulary is indentation, and the source's
                    # own typed depth is inconsistent block to block (even
                    # paragraph to paragraph within one quote block --
                    # Jon's own screenshot: first line one depth, later
                    # paragraphs another). Normalize instead of passing
                    # the source's literal indent through: every line of
                    # every quote-block paragraph gets the SAME flat
                    # 4-space indent, distinct from a body paragraph's own
                    # 5-space-first-line-then-flush scheme.
                    lines = [('    ' + l.lstrip(' ')) if l.strip() else l
                             for l in lines]
                para = '\n'.join(lines)
                if para.strip():
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

# The full attribute mapping (round 5, 2026-08-17 audit -- every attribute
# the model carries, b/i/u/strike/sub/sup, gets an HONEST mapping here, not
# a silent drop): bold/italic/strikeout have native CommonMark syntax
# (`_MD`, delimiter pairs); underline/sub/superscript do NOT (no CommonMark
# construct means any of the three), so they fall through to raw inline
# HTML passthrough instead (`_MD_HTML`, tag pairs) -- explicitly permitted
# by the CommonMark spec, and the only honest way to say "underlined" in
# Markdown without inventing non-standard syntax. Neither table's
# attribute reaches `_md_span` unless it's actually EFFECTIVE on the span
# (`core.effective_span_styles` -- style-level attrs merged with the
# typist's own run-level toggles), which is what round 5 fixed: a style's
# own declared bold used to reach RTF's stylesheet and HTML's CSS class but
# never a Markdown run at all.
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


def _md_span(s, refs=(), keep=DEFAULT_NOTE_KINDS, plain=False):
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
    if plain:
        # rule 4 (round 3, 2026-08-17): a letterless marker line (a
        # centred '#' scene break, an ellipsis-only pause) gets NO
        # emphasis wrapping even when its source span carries one (real
        # evidence: OLDTIMES's own '#' markers ride the SAME italic run
        # as the body copy around them, so style alone can't tell "this
        # is a marker" from "this is prose" -- see looks_like_verse's own
        # letterless-line exclusion for the same distinction made on
        # content instead of style). The character escaping above still
        # applies -- a bare '#' at the start of a line would read as a
        # Markdown heading otherwise -- only the `*emphasis*`/`<tag>`
        # wrapping is skipped, so the result is the plain escaped
        # character and nothing else.
        return lead + core + trail
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

# A real scene-break marker ('#', '* * *', '...') is a handful of
# characters at most; see `_md_unit_lines`'s own docstring for why this
# bound exists at all (round 5, 2026-08-17).
_MARKER_MAX_LEN = 5


def _md_unit_lines(unit, refs, keep, b):
    """One paragraph unit's Lines rendered to Markdown text, EVERY line's
    own leading indent dropped (Jon's ruling, round 3, 2026-08-17 --
    widened from "first line only" after real screenshots showed both
    halves of the same defect: a centred award citation kept its baked
    centering spaces on every line but the first, and a preserved stanza's
    continuation verses kept their source 5-space typed indent, landing
    flush-then-indented in the same paragraph). Markdown carries no
    first-line-indent concept (the paragraph gap itself is the "new
    paragraph" signal) and no verse-indent concept either -- the
    Markdown-native way to say either is to say nothing, letting the
    paragraph gap or the hard line-break do the whole job. A literal
    leading run would also risk CommonMark reading 4+ columns as an
    indented code block (the `_md_no_deep_indent` lint's whole reason to
    exist). A SHORT letterless marker line (a centred '#' scene break, at
    most `_MARKER_MAX_LEN` characters) renders with `plain=True` -- see
    `_md_span` -- so it never picks up emphasis wrapping from a source
    style it happens to share with body prose. Bounded to short runs only
    (round 5, 2026-08-17 attribute-mapping audit): an UNBOUNDED letterless
    check also caught a real fixture's own longer decorative letterless
    run (LJ6DTP.WS, 23 cp437 block-drawing characters carrying a genuine
    content `sup`) and silently dropped ITS formatting too -- a length a
    real scene-break marker never reaches, so bounding it costs nothing
    marker detection actually needs.

    Every span's EFFECTIVE styles (round 5: merged with the containing
    Block `b`'s own paragraph-style attrs, not just what the typist
    toggled inline) are what actually get rendered -- OLDTIMES's own
    'Award Citation' style declares bold+italic but its spans only
    re-toggle italic; reading `s.styles` alone silently dropped the
    style-level bold. See `core.effective_span_styles`."""
    out = []
    for line in unit:
        raw = ''.join(s.text for s in line.spans)
        stripped = raw.strip()
        plain = (bool(stripped) and len(stripped) <= _MARKER_MAX_LEN
                and not any(c.isalpha() for c in raw))
        spans = [Span(s.text, effective_span_styles(s, b)) for s in line.spans]
        text = ''.join(_md_span(s, refs, keep, plain=plain) for s in spans)
        out.append(text.lstrip(' '))
    return out


def emit_markdown(doc, mode='printed', notes=DEFAULT_NOTE_KINDS, **_options):
    keep = frozenset(notes)
    if mode == 'printed' or _printed(doc):
        # alignment is the content: a fenced block is the honest representation
        body = emit_text(doc, 'printed', notes=notes)
        return '```\n' + body.rstrip('\n') + '\n```\n'
    pairs = _annotated_notes(doc)
    refs = _ref_pairs(pairs)
    margin = _doc_margin(doc)
    convention_indent, head_position = paragraph_layout_context(doc)
    out = []
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            out.append('---')
            continue
        if b.heading:
            # a heading is a logical unit, not reflowed prose -- unaffected
            # by paragraph assembly, same as before. EVERY line's own
            # leading indent is dropped (round 3 lint, 2026-08-17 --
            # found against a real fixture: a multi-line heading's FIRST
            # and LAST line got trimmed by the final `.strip()` below, but
            # an interior line's own baked centering/typed indent leaked
            # straight into the output raw, the same CommonMark 4-space
            # hazard `_md_unit_lines` already guards against for ordinary
            # paragraphs).
            lines = [''.join(_md_span(Span(s.text, effective_span_styles(s, b)),
                                      refs, keep) for s in line.spans).lstrip(' ')
                     for line in merged_lines(b)]
            para = '  \n'.join(lines)
            if para.strip():
                out.append('#' * b.heading + ' ' + para.strip())
            continue
        quote = _is_quote_style(b)
        dominant = block_dominant_styles(merged_lines(b))
        for unit in assemble_paragraphs(
                    b, margin, head_position=head_position.get(id(b), False),
                    convention_indent=convention_indent):
            lines = _md_unit_lines(unit, refs, keep, b)
            if not any(l.strip() for l in lines):
                continue
            # round 3b (2026-08-17): a hard break is reserved for a REAL
            # deliberate line break -- a verified verse/stanza unit --
            # matching HTML/RTF/Text's own same-rule fix. A multi-line
            # unit that never got verse-verified (bare phase-1 flush-
            # continuation) flows as ONE line instead; every line was
            # already stripped of its own leading indent by
            # `_md_unit_lines`, so a plain space join is enough. round 7
            # (2026-08-17): `not b.wrap` short-circuits this for a hand-
            # positioned (.aw off) block -- never flowed, Register C23.
            if len(unit) > 1 and not (not b.wrap or looks_like_verse(unit, dominant)):
                lines = [' '.join(l for l in lines if l.strip())]
            if quote:
                # rule D: style-carried blockquote material keeps its own
                # handling -- Markdown's only way to say "quoted" is '>'
                out.append('\n'.join('> ' + l if l else '>' for l in lines))
            else:
                # round 4 (2026-08-17): a hard break is two TRAILING
                # SPACES before the newline (classic Markdown/CommonMark),
                # not a trailing backslash -- Jon's field report: some
                # renderers show the backslash literally, and it's text
                # that never existed in the WordStar source either way.
                # Invisible in the raw text, which a backslash is not.
                out.append('  \n'.join(lines))
    md = '\n\n'.join(out)
    # A note's own raw text is embedded verbatim below -- never routed
    # through `_md_unit_lines`, so a multi-line WordStar comment/footnote
    # (an annotator's own list, say) can carry the SAME baked-in leading
    # spaces on its internal lines that the round-3 lint exists to catch
    # everywhere else. Strip each embedded line's own leading run for the
    # same reason as everywhere else in this module: no first-line-indent
    # or verse-indent concept in Markdown, and 4+ columns risks CommonMark
    # reading it as an indented code block (found against a real fixture,
    # 2026-08-17).
    #
    # Round 12: also backslash-escape it, same as `_md_span` already does
    # for every other piece of rendered text. A note's text bypasses
    # `_md_span` entirely (it is emitted here, not through _md_unit_lines),
    # so it was the one path in this emitter a content backslash reached
    # CommonMark unescaped -- doubled at ANY position (not just end of
    # line), since a bare backslash is CommonMark's ESCAPE character
    # everywhere it appears, not only where it also happens to double as
    # the hard-break marker: `\*` would have silently suppressed a
    # following literal asterisk's own emphasis meaning just as easily as
    # a trailing `\` would have inserted a break the author never wrote.
    # Verified against the private corpus (metrics only): 8 documents,
    # 55 notes carry a literal backslash somewhere in their text.
    defs = [f'[^{_md_note_id(n.kind, label)}]: '
            + '\n'.join(l.lstrip(' ').replace('\\', '\\\\')
                       for l in n.text.split('\n'))
            for n, label in pairs if n.kind in keep]
    if defs:
        md += '\n\n' + '\n'.join(defs)
    return md + '\n'

# ---------------------------------------------------------------- html

# Body font: the sophisticated body ruling (2026-08-05) -- Georgia 14, the
# stack carrying the no-Georgia case by HTML's own nature.
#
# NO WIDTH/MEASURE DECLARATION ANYWHERE (Jon's ruling, round 3 addendum,
# 2026-08-17): an earlier version of this stylesheet capped the body at
# `max-width:42rem` as a READING-MEASURE nicety -- reasonable on its own,
# but it's still OUR OWN page-width opinion, the same category of thing as
# the WS-absolute geometry this whole round exists to strip. HTML has no
# page; width belongs entirely to the renderer/reader (the browser window),
# in both Modern AND Native output. `padding` below is a fixed breathing-
# room gutter, not a measure -- it doesn't cap anything, it just keeps text
# off the viewport edge.
_CSS = """body{margin:0;padding:2rem 1rem;
font:14pt/1.6 Georgia,'Times New Roman',P052,serif;color:#222}p{margin:0 0 1em}
.ws-native{white-space:pre-wrap;font:14px/1.5 ui-monospace,Menlo,Consolas,monospace}
span.ws-graphic{font-family:ui-monospace,Menlo,Consolas,monospace}
hr.pb{border:none;border-top:1px dashed #bbb;margin:2rem 0}
blockquote{margin:1em 2em;padding-left:1em;border-left:2px solid #ccc}
blockquote p{margin:0}
section[role=doc-endnotes]{margin-top:2rem}
section[role=doc-endnotes] h2{font-size:1.1rem}
@media(prefers-color-scheme:dark){body{background:#161616;color:#ddd}
hr.pb{border-top-color:#444}blockquote{border-left-color:#555}}"""

# The full attribute mapping (round 5 audit): every attribute the model
# carries gets a real semantic tag here -- all six, no exceptions, since
# HTML has native elements for every one of them. RUN-level attrs go
# through this per span (`_html_span`); a paragraph STYLE's own declared
# attrs take an entirely DIFFERENT path (`_style_css`'s CSS properties on
# the style's class, applied to the whole `<p>`/`<h#>` at once) rather
# than being merged into spans and run through this table -- which is
# exactly why HTML never had round 5's bug in the first place, and why
# `_style_css` needed its OWN sub/super rule (no tag to wrap a paragraph
# in) once the audit found the paragraph-level table was missing them.
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

def _is_graphic_text(text):
    """Whether TEXT is entirely cp437 box-drawing/shade/block/card-suit
    content (spaces allowed, e.g. a box's own top-border run of `─`) -- the
    HTML/RTF-side twin of PDF's own graphics doctrine ("the reason the box
    shows up is that it could be done in that era"), used to force a
    monospace face on exactly the pieces `split_graphic_spans` isolated,
    never on prose sharing their line (round 8, SCRIPT.WS)."""
    stripped = text.replace(' ', '')
    return bool(stripped) and all(c in GRAPHIC_CHARS for c in stripped)

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
    classes = []
    if font:
        classes.append('ws-' + font.replace('font', 'font-'))
    if _is_graphic_text(s.text):
        # `span.ws-graphic` (element+class) outranks the plain-class
        # `.ws-font-N` rule regardless of stylesheet order, so a box-
        # drawing run stays monospace even under a document font the
        # generated `.ws-font-N` rule made proportional.
        classes.append('ws-graphic')
    if classes:
        # class(es) only -- the matching CSS rules come from _CSS/
        # _style_css, so --no-styles leaves them inert
        text = f'<span class="{" ".join(classes)}">{text}</span>'
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

def _html_line(spans, refs, keep, keep_ws=False, shown_map=None):
    """Render one already-decided list of Spans (a logical line, or one
    Line's worth of a paragraph unit -- callers choose). Coalesces adjacent
    identically-styled spans unconditionally: cheap, idempotent for a
    caller that already coalesced (Modern's merged_lines), and the ONE
    place Printed's own physical-line spans get the same fix (item e of
    the overhaul -- the fragmentation gap applies there too). Graphic runs
    are split out AFTER coalescing, not before (round 8) -- coalescing
    merges by style equality alone, so a split-then-coalesce order would
    silently re-glue a box character back onto the prose beside it the
    moment they share a style."""
    out = []
    for s in split_graphic_spans(coalesce_spans(spans)):
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

_HTML_ALIGN_CSS = {'center': 'text-align:center', 'right': 'text-align:right',
                   'justify': 'text-align:justify'}

def _html_para_style(align, indent_cols=0):
    """One combined `style="..."` attribute for a Modern <p> -- alignment
    and first-line indent both live there, so a centred, indented paragraph
    doesn't need two competing style attributes (HTML allows only one)."""
    props = []
    css = _HTML_ALIGN_CSS.get(align)
    if css:
        props.append(css)
    if indent_cols:
        props.append(f'text-indent:{indent_cols}ch')
    return f' style="{";".join(props)}"' if props else ''

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
        primary, falt = rtf_fonts(fam, f.get('generic_style'), target,
                                  f.get('proportional'))
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


def _add_html_class(cls_attr, extra):
    """Merge an extra CSS class into an already-built `' class="..."'`
    attribute string (or start a fresh one if `cls_attr` is empty) --
    Native HTML's own per-style class (`_style_slug`, may be absent) plus
    the `ws-native` monospace/pre-wrap treatment both need to land on the
    same element now that Native no longer wraps in a bare `<pre>`."""
    if not cls_attr:
        return f' class="{extra}"'
    return cls_attr[:-1] + f' {extra}"'


def _style_css(doc, printed=True):
    """CSS rules derived from the style records themselves -- a PASS-THROUGH
    of the file's own data (Jon, 2026-08-04: never hardwire a style name to
    a font or size; expose the data so a consumer can attach its own). Every
    property below comes from the entry's 102-byte record: alignment,
    margins (HMI/1800 = inches), print attributes, and the font block's
    height word (VMI/20 = points). Inherited fields emit nothing.

    PRINTED keeps the margins verbatim -- Printed's whole point is the
    file's own WS4-absolute page geometry, on an actual 8.5in page. MODERN
    drops `margin-left`/`margin-right` entirely (Jon's ruling, round 3,
    2026-08-17): those inch values were measured against the ORIGINAL
    page's own width, and a reflowed reader column is a different, much
    narrower measure -- `margin-right:5.8in` alone exceeds the body's own
    42rem column, which is what actually broke browsers (a quote paragraph
    rendering one word per line). Modern presentation NORMALIZES instead:
    body styles get the full reader measure (no geometry at all); a quote-
    classified style's visible inset comes structurally from `<blockquote>`
    (a flat, modest `margin` in the base stylesheet) at the call site in
    `emit_html`, not from this per-style CSS. Alignment, weight/style/
    decoration, and font-size are NOT page geometry -- unaffected either
    way."""
    rules = []
    for entry in doc.styles:
        if 'attrs_on' not in entry:            # recordless base entry
            continue
        props = []
        if entry.get('justification') in ('left', 'center', 'right', 'justify'):
            props.append(f"text-align:{entry['justification']}")
        if printed:
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
        # round 5 (2026-08-17): a paragraph STYLE can declare sub/super
        # (WSFORMAT's own attrs-on bits 0x10/0x20 -- verified against the
        # spec, not assumed), the same as it declares bold/italic/
        # underline/strikeout above; this CSS is the paragraph-level
        # equivalent of the run-level <sub>/<sup> tag `_html_span` already
        # uses, matching those elements' own default UA stylesheet
        # (vertical-align + a smaller font-size) since a CSS class can't
        # wrap content in a tag the way a run-level toggle can.
        if 'sub' in a:
            props.append('vertical-align:sub;font-size:smaller')
        elif 'sup' in a:
            props.append('vertical-align:super;font-size:smaller')
        font = entry.get('font')
        if font:
            w, h, ts = font
            if h:
                props.append('font-size:%.4gpt' % (h / 20.0))
            # `ts & 0x01FF` is the raw WS5+ font-record typestyle-index
            # bitfield -- internal wire format, not a rendering instruction
            # any CSS consumer can act on. It used to leak out as a literal
            # `--ws-typestyle:N` custom property (implementation state
            # escaping into a document a human or editor might open and
            # read); nothing in this project ever consumed it, so it is
            # simply not emitted rather than exposed on the CSS custom-
            # property namespace.
        if props:
            rules.append(f'.{_style_slug(entry)} {{ {"; ".join(props)} }}')
    for idx, f in enumerate(doc.fonts):
        props = []
        fam = _font_family(f.get('typestyle_name'))
        # round 9: an UNNAMED typestyle number (no TYPESTYLE_NAMES entry)
        # still carries a real proportional bit -- `fam` alone being empty
        # must not skip the monospace-or-not decision, or a nameless
        # proportional=False record would silently inherit whatever
        # proportional face the surrounding context has.
        if fam or f.get('proportional') is False:
            stack = font_stack(fam, f.get('generic_style'), f.get('proportional'))
            css = ', '.join(n if ' ' not in n and n.islower() else f"'{n}'"
                            for n in stack)
            props.append(f'font-family:{css}')
        if f.get('points'):
            props.append('font-size:%.4gpt' % f['points'])
        if props:
            rules.append(f'.ws-font-{idx} {{ {"; ".join(props)} }}')
    return '\n'.join(rules)


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
    margin = _doc_margin(doc)
    convention_indent, head_position = paragraph_layout_context(doc)
    # Quote-block CONTINUITY (Jon's ruling, round 4, 2026-08-17): consecutive
    # units in the same quote-classified style are ONE quote block, not one
    # <blockquote> per paragraph UNIT (the round-3 code) nor even one per
    # WordStar Block -- a real multi-paragraph newspaper quotation is often a
    # single indent-only-convention Block with several typed paragraphs
    # INSIDE it (OLDTIMES's own 'MS Double-Indented Quote' block: 5 units,
    # was rendering as 5 separate bordered <blockquote>s with vertical gaps).
    # The GROUPING key is "quote-classified at all", not the exact style
    # NAME: a real fixture (NOVEL.WS) alternates 'MS Quote Introductory'
    # and 'MS Quote Credit' block to block (an epigraph immediately
    # followed by its own attribution line) -- two DIFFERENT quote styles
    # with nothing between them read as one continuous quotation just as
    # much as OLDTIMES's single-style run does, and rendering them as two
    # adjacent boxes is the identical "stack of gapped boxes" defect.
    # `quote_buffer` accumulates <p> strings across units AND across
    # Blocks as long as SOME quote style keeps matching and nothing else
    # intervenes; `_flush_quote` closes it into one <blockquote> the
    # moment it doesn't. `quote_indent_cols` is the GROUP's own first-line
    # indent, computed once from the group's first paragraph and reused
    # for every paragraph in it (round 4: the source's own typed indent is
    # NOT reliable per paragraph -- OLDTIMES's own quote block opens its
    # first typed paragraph at column 7 and every later one at column 12,
    # a real inconsistency in the source, not a rendering choice -- so the
    # first paragraph's own value is what every paragraph in the group
    # uses, never each one's own raw count).
    quote_buffer = []
    quote_open = False
    quote_indent_cols = None

    def _flush_quote():
        nonlocal quote_open, quote_indent_cols
        if quote_buffer:
            parts.append('<blockquote>' + ''.join(quote_buffer) + '</blockquote>')
            quote_buffer.clear()
        quote_open = False
        quote_indent_cols = None

    for b in doc.blocks:
        if b.kind == 'pagebreak':
            _flush_quote()
            parts.append('<hr class="pb">')
            continue
        cls = style_class.get(b.style_id, '')
        if b.heading:
            _flush_quote()
            # merged either mode: a heading is a logical unit, and joining its
            # logical lines with a space is what this always rendered.
            # Alignment-space stripping applies here too now (defect b: a
            # centred heading used to keep its baked spaces as visible
            # &nbsp; runs on top of the CSS that already centres it).
            txt = ' '.join(_html_line(_maybe_strip_align(b, list(line.spans)),
                                      refs, keep, shown_map=shown_map)
                           for line in merged_lines(b)).strip()
            if txt:
                parts.append(f'<h{b.heading}{cls}>{txt}</h{b.heading}>')
            continue
        if printed:
            _flush_quote()
            # PHYSICAL lines, normal flow (Jon's ruling, round 3 addendum,
            # 2026-08-17 -- retires the earlier <pre> wrapper): a <pre> box
            # implies a WIDTH-CONSTRAINING monospace grid, which is exactly
            # the page-geometry opinion this round strips everywhere else.
            # Native's own identity is the FONT (kept via the `ws-native`
            # class: monospace, `white-space:pre-wrap` so literal column
            # spacing still lines up) -- not a boxed, non-wrapping element.
            # Every physical line break is now an explicit <br> rather than
            # a literal newline relying on <pre>'s own whitespace handling,
            # so a long physical line still wraps at the READER's window
            # (the fixed 65-column look stays Printed/PDF's own domain).
            lines = [_html_line(list(line.spans), refs, keep,
                                keep_ws=True, shown_map=shown_map)
                     for line in b.lines]
            body = '<br>\n'.join(lines)
            if body.strip():
                native_cls = _add_html_class(cls, 'ws-native')
                parts.append(f'<p{native_cls}>{body}</p>')
        else:
            # Modern: one <p> per PARAGRAPH UNIT, not per block. A unit's
            # own first line loses its typed/machine indent to a real
            # text-indent property (rule C: no literal leading indent
            # whitespace); every other line in the unit is untouched --
            # `_html_span`'s own &nbsp; idiom still renders ITS leading
            # run visibly, which is exactly right for a poem's second
            # verse (content, not a paragraph-start marker).
            quote = _is_quote_style(b)
            if quote:
                quote_open = True
            else:
                _flush_quote()
            dominant = block_dominant_styles(merged_lines(b))
            for unit in assemble_paragraphs(
                    b, margin, head_position=head_position.get(id(b), False),
                    convention_indent=convention_indent):
                first = _maybe_strip_align(b, list(unit[0].spans))
                indent_cols, first = split_leading_indent(first)
                if quote:
                    # round 4 (2026-08-17): a quote GROUP's first-line
                    # indent is computed ONCE, from its own first
                    # paragraph, and reused for every paragraph in the
                    # group -- not each paragraph's own raw typed column
                    # count, which the source itself carries
                    # inconsistently (see the block comment above
                    # `quote_buffer`). Still relative, still reader-
                    # proportional (ch); just no longer "absolute where it
                    # must be relative."
                    if quote_indent_cols is None:
                        quote_indent_cols = indent_cols
                    indent_cols = quote_indent_cols
                # rule (round 3 addendum, 2026-08-17): <br> is reserved for
                # a REAL deliberate line break -- a verified verse/stanza
                # unit. A multi-line unit that never got verse-verified (a
                # bare phase-1 flush-continuation grouping) is prose that
                # merely happens to carry more than one Line; it flows as
                # ONE paragraph, same as the ordinary single-line case,
                # rather than forcing a break neither the author nor
                # `looks_like_verse` ever asked for. Re-derives the SAME
                # verdict `assemble_paragraphs` used internally to build
                # this very unit (pure function, identical inputs).
                # round 7 (2026-08-17): a wrap=off block's unit is ALWAYS
                # treated as verse here too -- assemble_paragraphs already
                # returns it as one whole-block unit unconditionally, but
                # this is where a NON-verse multi-line unit gets flowed
                # into one line (round 3b); without the `not b.wrap` guard
                # that flow logic would still run on a hand-positioned
                # block's lines and destroy the layout via a different
                # mechanism. Register C23.
                is_verse = len(unit) > 1 and (not b.wrap or looks_like_verse(unit, dominant))
                rendered = [_html_line(first, refs, keep, shown_map=shown_map)]
                for line in unit[1:]:
                    spans = _maybe_strip_align(b, list(line.spans))
                    if not is_verse:
                        _, spans = split_leading_indent(spans)
                    rendered.append(_html_line(spans, refs, keep, shown_map=shown_map))
                if len(unit) > 1 and not is_verse:
                    para = ' '.join(t for t in rendered if t.strip())
                else:
                    para = '<br>\n'.join(rendered)
                if not para.strip():
                    continue
                # C16/C17: HTML can express all four alignments, so unlike the
                # plain-text renderer it does not have to collapse justify into
                # left. `left` is WordStar's default and gets no attribute, so
                # every document that never touches `.oc`/`.oj` emits byte-identical
                # HTML to before.
                style = _html_para_style(b.align, indent_cols)
                # C5: newspaper columns. CSS does this properly, so HTML is the one
                # format that can honour `.co` rather than merely record it. A gutter
                # is print columns at 10 CPI -> tenths of an inch.
                p_html = f'<p{cls}{style}>{para}</p>'
                if b.columns and b.columns > 1:
                    gap = ('; column-gap:%.2fin' % (b.column_gutter / 10.0)
                           if b.column_gutter else '')
                    col = f' style="column-count:{b.columns}{gap}"'
                    p_html = f'<div{col}>{p_html}</div>'
                if quote:
                    # rule 1 (round 3/4, 2026-08-17): quote-classified
                    # styles become a real <blockquote> -- the style's own
                    # margin-left/right (WS-absolute, sometimes 5+ inches)
                    # no longer carries the visible inset at all
                    # (`_style_css`, modern mode). CONSECUTIVE quote
                    # paragraphs (same style, nothing intervening) share
                    # ONE <blockquote> (round 4: was one per unit, which
                    # rendered a multi-paragraph quotation as a stack of
                    # separately-bordered, gapped boxes) -- buffered here,
                    # closed by `_flush_quote` the moment the run ends.
                    quote_buffer.append(p_html)
                else:
                    parts.append(p_html)
    _flush_quote()
    linked = (_REF_KINDS if shown_map is not None
              else tuple(k for k in _REF_KINDS if k != 'comment'))
    sections = _html_notes_sections(pairs, keep, linked)
    if sections:
        parts.append('<hr>')
        parts.extend(sections)
    css = _CSS
    if styles:
        extra = _style_css(doc, printed)
        if extra:
            css = css + '\n' + extra
    return ('<!doctype html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_html.escape(title)}</title><style>{css}</style></head>\n'
            f'<body>\n' + '\n'.join(parts) + '\n</body></html>\n')

# ---------------------------------------------------------------- rtf

# The full attribute mapping (round 5 audit): all six, one direct control
# word each, applied to every RUN via `rtf_seg`'s own effective-attribute
# merge (style-declared + run-toggled). Round 5's design ruling (Jon,
# 2026-08-17, after finding style-declared bold invisible in Word itself,
# not just non-Word readers): DIRECT FORMATTING IS THE ONLY RENDERING
# MECHANISM IN RTF. `\sN` in `_rtf_stylesheet` is provenance/naming only
# (so Sawyer's own style names still show up in Word's style pane) --
# nothing may depend on the stylesheet actually being applied, character
# attributes included.
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
    if _is_graphic_text(sp.text):
        # \f1 (Courier New) is ALWAYS in the font table (see the \fonttbl
        # literal in `emit_rtf`) regardless of the document's own fonts --
        # same reasoning as HTML's `ws-graphic` override, appended last so
        # it wins the font-table reference while any \fs size already
        # chosen above is left alone (round 8).
        ctl += r'\f1 '
    return '{' + ctl + _rtf_escape(sp.text) + '}'

_RTF_MODERN_QUOTE_INSET = 720   # 0.5in each side -- Jon's explicit ask, round 3

def _rtf_style_margins(entry, printed):
    """(li, ri) twips for ONE style-table entry -- the single source of
    truth `_rtf_stylesheet`'s own definition AND every body paragraph's
    DIRECT formatting both read (round 4, 2026-08-17: a property that
    exists only in the `\\stylesheet` group is invisible to Pages,
    TextEdit, and most non-Word RTF readers, which honour direct
    formatting only and ignore stylesheet definitions outright -- Jon's
    "visibly inset" claim for quotes failed in the field for exactly this
    reason). PRINTED keeps the WS4-absolute geometry verbatim -- Printed
    IS that geometry. MODERN drops it for ordinary body styles (full
    measure) and replaces a quote-classified style's own -- however large
    or lopsided in the source -- with a small FIXED symmetric inset
    (`_RTF_MODERN_QUOTE_INSET` each side)."""
    if printed:
        li = (round(entry['left_margin_hmi'] / 1800.0 * 1440)
              if entry.get('left_margin_hmi') else 0)
        ri = (round(entry['right_margin_hmi'] / 1800.0 * 1440)
              if entry.get('right_margin_hmi') else 0)
        return li, ri
    if _is_quote_name(entry.get('name')):
        return _RTF_MODERN_QUOTE_INSET, _RTF_MODERN_QUOTE_INSET
    return 0, 0


def _rtf_direct_margins(doc, printed):
    """{slot: (li, ri)} for every real style-table entry -- computed once
    per `emit_rtf` call so every paragraph referencing a style can carry
    its li/ri as DIRECT formatting (see `_rtf_style_margins`), not only
    via the `\\sN` stylesheet reference."""
    return {entry['slot']: _rtf_style_margins(entry, printed)
            for entry in doc.styles if 'attrs_on' in entry}


def _rtf_stylesheet(doc, printed=True):
    """An RTF \\stylesheet group derived from the style records -- the same
    pass-through rule as the HTML CSS: properties come from the file's own
    data, names are carried verbatim, nothing is hardwired. \\sN numbers are
    slot+1 (RTF style 0 is reserved for Normal).

    Kept for WORD'S benefit (round 4, 2026-08-17): Word and other style-
    aware readers still get named, editable styles. Every property here
    that must actually RENDER is also emitted as direct formatting on each
    referencing paragraph (`_rtf_emit_para`'s own `li`/`ri` args, sourced
    from `_rtf_direct_margins`) -- this definition is no longer the only
    place li/ri exists."""
    entries = []
    for entry in doc.styles:
        if 'attrs_on' not in entry:
            continue
        props = ''
        props += {'center': r'\qc', 'right': r'\qr',
                  'justify': r'\qj'}.get(entry.get('justification'), '')
        li, ri = _rtf_style_margins(entry, printed)
        if li:
            props += r'\li%d' % li
        if ri:
            props += r'\ri%d' % ri
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


def _maybe_strip_align(b, spans):
    """`_strip_align_spaces(spans)` when this block's own alignment tag will
    already render the same visual effect, spans unchanged otherwise.

    Shared by every Modern body AND heading path so a centred heading and a
    centred paragraph are never treated differently -- `emit_html`'s
    heading branch used to call `_html_span` directly and skip this
    entirely (the double-centering defect: a centred `<h1>` kept its baked
    centering spaces as visible `&nbsp;` runs ON TOP of the CSS that
    already centres it); Modern RTF's heading branch got the fix only by
    accident of loop order (it re-used `lines`, already built by the body
    loop just above it, which DID call this). Same helper, called
    explicitly by both paths and both formats now."""
    if b.align in ('center', 'right') and spans:
        return _strip_align_spaces(spans)
    return spans


def _is_quote_name(name):
    """Whether a WordStar paragraph-style NAME (block-level `b.style_name`
    or a style-table entry's own `entry['name']`) marks quoted material --
    e.g. 'Double-Indented Quote', 'MS Double-Indented Quote'. One substring
    test shared by every Modern format's own quote treatment (Jon's ruling,
    round 3, 2026-08-17): Markdown's '>' prefix, HTML's <blockquote> wrap,
    RTF's modest symmetric \\li/\\ri override, and Text's uniform 4-space
    block indent all key off this same signal."""
    return 'quote' in (name or '').lower()


def _is_quote_style(b):
    """`_is_quote_name` for a Block's own style. See `_is_quote_name`."""
    return _is_quote_name(b.style_name)


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


# ------------------------------------------------------- printed vertical space
#
# Jon's ruling (2026-08-17, branch printed-vertical-space): line spacing/
# leading, `.pm` (paragraph margin), and `.psa`/`.psb` (WordTsar's paragraph
# spacing before/after) "need to be handled on Printed and Native RTF. The
# other formats TXT, MD, and HTML probably shouldn't deal with line
# spacing." Modern RTF stays out too -- the reader owns presentation there,
# same logic as the no-page-width ruling (round 3). Scoped entirely to
# `emit_rtf`'s PRINTED branch, which -- per the app's own current audit --
# serves both the Printed and Native styles through this one code path.
#
# 1/48in -> twips: 1 inch is 1440 twips, so 1/48in is 1440/48 = 30 twips.
# pdf.py's own `_lead_pt` (the reference behavior this ports) computes the
# SAME unit as points (lh_48 * 1.5, since 1/48in = 1.5pt); 1.5pt * 20
# twips/pt is the identical 30 -- both routes agree.
_RTF_LEAD_TWIPS_PER_48 = 30

# print columns (10 CPI) -> twips: 1440 twips/in / 10 cols/in = 144/col.
# The same constant `_rtf_emit_para`'s own `\fi` (from Modern's indent_cols)
# already uses inline; named here too since `.pm` shares the unit.
_RTF_TWIPS_PER_COL = 144


def _rtf_block_lead_48(doc, b):
    """The 1/48in leading in force for block `b`'s own printed lines --
    mirrors pdf.py's `_lead_pt`/`_printed_lead`, the REFERENCE behavior
    this round ports to RTF. A block's first Line carries its own `.lh`
    override (`Line.lead_48`) only when it DIFFERS from the document
    default (core.py's own space-saving convention -- see the parse-time
    comment by `DEFAULT_LH_48`'s usage); None there means "use the
    document's own default", the SAME fallback pdf.py's `_lead_pt`
    applies. RTF's `\\sl` is a PARAGRAPH property -- there is no per-line
    leading control word -- so a block whose OWN physical lines carry
    DIFFERENT `.lh` values (a real but rare case: `.lh` changing
    mid-paragraph) is approximated at its first line's own value; this is
    the ceiling of what RTF can express per paragraph, not a shortcut."""
    if b.lines and b.lines[0].lead_48:
        return b.lines[0].lead_48
    page = doc.meta.get('page')
    return page.get('lh_48', DEFAULT_LH_48) if page is not None else DEFAULT_LH_48


def _rtf_sl_twips(lead_48):
    """`\\sl` value (signed twips) for one `.lh`-derived leading. NEGATIVE,
    per the RTF spec's own distinction: a positive `\\sl` is a MINIMUM
    (the reader may expand it for a taller font); negative is EXACT,
    unconditionally. WordStar's own printed page is the latter -- the
    physical Y advance per line is the `.lh` VMI, full stop, regardless of
    what font is set (pdf.py's `_page_stream` advances by exactly `lead`
    for every line, never "at least") -- so `\\slmult0` (a literal twip
    count, not a multiple of single-spacing) with a negative value is the
    faithful translation, not the bare positive `\\slN` a first reading of
    "double-spaced" might suggest."""
    return -round(lead_48 * _RTF_LEAD_TWIPS_PER_48)


def _rtf_pm_fi_twips(b, li_twips):
    """`\\fi` (RTF's first-line indent, relative to `\\li`) from `.pm` --
    `block.para_margin`, currently read by no emitter. WSFORMAT semantics,
    corroborated by `core.py`'s own `Block.para_margin` docstring: ".pm is
    the PARAGRAPH margin -- the first line's own indent", a column
    position in the SAME absolute frame `.lm`/`.po` use, not a delta
    against `.lm`. RTF's own model reads `\\fi` as relative to `\\li`, so
    the direct token is the DIFFERENCE between .pm's absolute column (in
    twips) and wherever `\\li` (the block's own style margin, round 4) is
    already placing the body of the paragraph -- `\\li + \\fi` then lands
    exactly on .pm's column, whether that's deeper (an ordinary indent) or
    shallower (a hanging indent) than the body. None (the block never set
    `.pm`) leaves `\\fi` untouched -- no override where there is no
    evidence."""
    if b.para_margin is None:
        return None
    return round(b.para_margin * _RTF_TWIPS_PER_COL) - li_twips


def _rtf_doc_spacing_twips(doc):
    """(sb, sa) in twips from WordTsar's own `.psa`/`.psb` extensions
    (`doc.meta['space_before_lines']`/`['space_after_lines']` -- "not a
    WordStar command" per WordTsar's own source, so their presence is a
    producer signal; a real WordStar 4/5/7 file never carries them).
    MINIMAL MODEL (2026-08-17): both are recorded as ONE document-wide
    value each (first occurrence wins -- core.py's own existing design,
    "one resolved answer per document"), so applied uniformly to every
    printed paragraph rather than inventing per-block granularity no
    evidence supports. Lines convert to twips via the document's own
    DEFAULT leading -- the same unit `\\sl` itself uses -- consistent with
    "N lines of space" meaning N times this document's own line advance.
    (None, None) when neither command was ever seen."""
    sb_lines = doc.meta.get('space_before_lines')
    sa_lines = doc.meta.get('space_after_lines')
    if sb_lines is None and sa_lines is None:
        return None, None
    page = doc.meta.get('page')
    default_lead_48 = page.get('lh_48', DEFAULT_LH_48) if page is not None else DEFAULT_LH_48
    lead_twips = round(default_lead_48 * _RTF_LEAD_TWIPS_PER_48)
    sb = round(sb_lines * lead_twips) if sb_lines is not None else None
    sa = round(sa_lines * lead_twips) if sa_lines is not None else None
    return sb, sa


def _rtf_emit_para(parts, rtf_state, b, lines, fi_cols=0, force=False, li=0, ri=0,
                   sl=0, sb=0, sa=0, fi_twips=None):
    """Append one `\\par`-terminated paragraph to `parts`.

    `fi_twips`, when given, OVERRIDES `fi_cols` with an exact twip value
    computed elsewhere (`.pm`'s own `_rtf_pm_fi_twips`, round 6) --
    `fi_cols * 144` would round-trip a twip value that was never actually
    columns through a lossy columns-shaped parameter twice.

    RTF paragraph properties -- alignment, first-line indent, left/right
    inset, line spacing, and paragraph spacing before/after alike --
    PERSIST across `\\par` until changed, so all SIX must be tracked and
    re-emitted (even back to 0/`\\ql`) whenever they differ from what is
    still in force, or a later plain paragraph would silently inherit an
    earlier one's. `rtf_state` is the running {'align', 'fi', 'li', 'ri',
    'sl', 'sb', 'sa'} a single `emit_rtf` call threads through every block
    (printed, heading, and Modern body paragraphs alike -- only Modern
    body paragraphs ever pass a nonzero `fi_cols`/`li`/`ri`, and only
    PRINTED paragraphs ever pass a nonzero `sl`/`sb`/`sa` -- round 6,
    2026-08-17, "the other formats [TXT/MD/HTML] probably shouldn't deal
    with line spacing", Modern RTF included -- but every OTHER paragraph
    still needs the chance to reset any of these back to 0).

    `li`/`ri`/`sl`/`sb`/`sa` are all DIRECT formatting (round 4 established
    this for li/ri; round 6 extends the same doctrine to vertical space),
    not just the `\\sN` stylesheet reference below -- most non-Word RTF
    readers ignore `\\stylesheet` definitions entirely and honour only
    direct paragraph formatting, so a property that exists ONLY in the
    stylesheet is invisible to them. Same persistence-across-\\par
    optimisation as `\\fi`: only re-emitted when the value actually
    changes, which is also what keeps a run of consecutive quote
    paragraphs reading as one continuous inset block with no reset in
    between."""
    para = r'\line '.join(lines)
    if not para.strip() and not force:
        return
    if b.align != rtf_state['align']:
        parts.append(_RTF_ALIGN[b.align])
        rtf_state['align'] = b.align
    fi = fi_twips if fi_twips is not None else fi_cols * 144   # 144 twips/col
    if fi != rtf_state['fi']:
        parts.append(r'\fi%d ' % fi)
        rtf_state['fi'] = fi
    if li != rtf_state['li']:
        parts.append(r'\li%d ' % li)
        rtf_state['li'] = li
    if ri != rtf_state['ri']:
        parts.append(r'\ri%d ' % ri)
        rtf_state['ri'] = ri
    if sl != rtf_state['sl']:
        # \slmult0: the value is a literal twip count, not a multiple of
        # single-line spacing -- see `_rtf_sl_twips` for why it's signed.
        parts.append(r'\sl%d\slmult0 ' % sl)
        rtf_state['sl'] = sl
    if sb != rtf_state['sb']:
        parts.append(r'\sb%d ' % sb)
        rtf_state['sb'] = sb
    if sa != rtf_state['sa']:
        parts.append(r'\sa%d ' % sa)
        rtf_state['sa'] = sa
    if b.style_id in rtf_state['styled_slots']:
        # style pass-through: tag the paragraph with its \sN so a
        # consumer can act on the named style (Word can still edit it by
        # name) -- the visible formatting above is now ALSO direct, so a
        # reader that ignores \sN entirely still renders correctly.
        parts.append(r'\s%d ' % (b.style_id + 1))
    parts.append(para + r'\par ')


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
    stylesheet = _rtf_stylesheet(doc, printed) if styles else ''
    fonttbl_extra, fontctl = (_font_ctl_rtf(doc, fonts_target)
                              if styles else ('', {}))
    styled_slots = ({s['slot'] for s in doc.styles if 'attrs_on' in s}
                    if styles else set())
    # round 4 (2026-08-17): li/ri per style, looked up per paragraph so
    # they can ride along as DIRECT formatting -- see _rtf_direct_margins.
    direct_margins = _rtf_direct_margins(doc, printed) if styles else {}
    # round 6 (2026-08-17): .psa/.psb are ONE document-wide value each
    # (see _rtf_doc_spacing_twips) -- resolved once, not per block. Only
    # ever non-(None,None) for a WordTsar-produced file (a real WordStar
    # 4/5/7 document never carries these). Applied in PRINTED mode only
    # (below); Modern never reads doc_sb/doc_sa at all.
    doc_sb, doc_sa = _rtf_doc_spacing_twips(doc) if printed else (None, None)
    parts = []
    rtf_state = {'align': 'left', 'fi': 0, 'li': 0, 'ri': 0,
                 'sl': 0, 'sb': 0, 'sa': 0, 'styled_slots': styled_slots}
    margin = _doc_margin(doc)
    convention_indent, head_position = paragraph_layout_context(doc)
    # Quote-group first-line indent (round 4, mirrors emit_html): computed
    # once from the group's own first paragraph, reused for every
    # paragraph in a run of CONSECUTIVE quote-classified blocks -- the
    # source's own typed indent is NOT reliable per paragraph (OLDTIMES's
    # own quote block: 7 columns on its first typed paragraph, 12 on
    # every later one, a real inconsistency in the source). Grouped by
    # "quote-classified at all", not the exact style name -- a real
    # fixture (NOVEL.WS) alternates 'MS Quote Introductory' and 'MS Quote
    # Credit' block to block (an epigraph immediately followed by its own
    # attribution line), which reads as one continuous quotation despite
    # the style-name change, same as emit_html's identical fix. CONTINUITY
    # itself (Jon's "one continuous inset block") needs no separate
    # buffering the way HTML's <blockquote> DOM does -- li/ri already
    # come from each block's OWN style, so consecutive quote paragraphs
    # already carry their own correct inset; only \fi needed normalizing.
    quote_open = False
    quote_fi_cols = None

    def rtf_seg(spans, b):
        # round 5 (2026-08-17): DIRECT FORMATTING IS THE ONLY RENDERING
        # MECHANISM IN RTF, full stop -- Jon opened a delivered file in
        # Word itself and found style-declared bold invisible there too,
        # which kills any "the stylesheet is fine for Word" premise (the
        # RTF spec's own \sN is nominal, a style-pane label; a writer
        # must emit the complete effective formatting as direct tokens,
        # and no reader is obliged to apply \stylesheet on load). Every
        # run's effective attributes -- its own toggles merged with
        # whatever the containing Block's paragraph STYLE declares --
        # are merged in BEFORE rendering, here, so every call site gets
        # it free. `coalesce_spans` runs again after the merge, which
        # also correctly re-joins runs that only differed because one
        # carried a redundant inline toggle the style already covered.
        merged = [Span(sp.text, effective_span_styles(sp, b)) for sp in spans]
        # Graphic runs split out AFTER coalescing, same ordering reason as
        # HTML's identical step in `_html_line` (round 8): splitting first
        # would just get re-glued back onto the prose beside it the moment
        # both share a style.
        return ''.join(_rtf_span(sp, refs, keep, fontctl, printed, shown_map)
                       for sp in split_graphic_spans(coalesce_spans(merged)))

    for b in doc.blocks:
        if b.kind == 'pagebreak':
            quote_open = False
            quote_fi_cols = None
            parts.append(r'\page ')
            continue
        li, ri = direct_margins.get(b.style_id, (0, 0))
        if printed:
            # physical lines: \line at every printed break, soft or hard
            lines = [rtf_seg(line.spans, b) for line in b.lines]
            if b.heading:
                lines = ['{' + r'\b\fs28 ' + l + '}' for l in lines]
            # round 6 (2026-08-17): line spacing/.pm/.psa+.psb -- Printed
            # and Native RTF's own domain (this IS that one shared code
            # path -- see the module-level ruling above _rtf_block_lead_48).
            sl = _rtf_sl_twips(_rtf_block_lead_48(doc, b))
            pm_fi = _rtf_pm_fi_twips(b, li)
            _rtf_emit_para(parts, rtf_state, b, lines, force=True, li=li, ri=ri,
                           sl=sl, sb=(doc_sb or 0), sa=(doc_sa or 0),
                           fi_twips=pm_fi)
            continue
        if b.heading:
            quote_open = False
            quote_fi_cols = None
            # a heading is a logical unit, not reflowed prose -- unaffected
            # by paragraph assembly, same as before. Alignment stripping now
            # goes through the shared helper explicitly (it used to inherit
            # the fix only by accident of loop order).
            lines = [rtf_seg(_maybe_strip_align(b, list(line.spans)), b)
                     for line in merged_lines(b)]
            lines = ['{' + r'\b\fs28 ' + l + '}' for l in lines]
            _rtf_emit_para(parts, rtf_state, b, lines, li=li, ri=ri)
            parts.extend([r'\par '] * trailing_blank_lines(b))
            continue
        quote = _is_quote_style(b)
        if quote:
            quote_open = True
        else:
            quote_open = False
            quote_fi_cols = None
        # Modern body: one \par per PARAGRAPH UNIT (was: one \par per
        # BLOCK, with every hard-terminated typed paragraph inside it
        # collapsed to a forced \line). A unit's own first line loses its
        # typed/machine indent to a real \fi (rule B: no literal leading
        # indent whitespace); every other line in the unit keeps its
        # literal leading spaces exactly as before (a poem's second verse
        # is content, not a paragraph-start marker) UNLESS the unit never
        # got verse-verified, in which case it flows as one line instead
        # (round 3b, 2026-08-17: \line is reserved for a REAL deliberate
        # break -- a verified verse/stanza unit -- matching HTML/Text/
        # Markdown's own same-rule fix; a bare phase-1 flush-continuation
        # grouping is prose that merely happens to carry more than one
        # Line).
        dominant = block_dominant_styles(merged_lines(b))
        for unit in assemble_paragraphs(
                    b, margin, head_position=head_position.get(id(b), False),
                    convention_indent=convention_indent):
            first = _maybe_strip_align(b, list(unit[0].spans))
            indent_cols, first = split_leading_indent(first)
            if quote:
                # round 4: same relative-not-absolute fix as HTML -- the
                # quote GROUP's own first paragraph sets \fi for every
                # paragraph in the group, not each one's own raw column
                # count (see the block comment above `quote_open`).
                if quote_fi_cols is None:
                    quote_fi_cols = indent_cols
                indent_cols = quote_fi_cols
            is_verse = len(unit) > 1 and looks_like_verse(unit, dominant)
            rendered = [rtf_seg(first, b)]
            for line in unit[1:]:
                spans = _maybe_strip_align(b, list(line.spans))
                if not is_verse:
                    _, spans = split_leading_indent(spans)
                rendered.append(rtf_seg(spans, b))
            if len(unit) > 1 and not is_verse:
                lines = [' '.join(t for t in rendered if t.strip())]
            else:
                lines = rendered
            _rtf_emit_para(parts, rtf_state, b, lines, indent_cols, li=li, ri=ri)
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
