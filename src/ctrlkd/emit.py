"""ctrl-kd emitters: Document IR -> text / markdown / html / rtf.

Two rendering philosophies, chosen by the caller:
  modern   reflowed paragraphs, semantic markup (the IR already joined word
           wraps and kept deliberate breaks — emitters just express it)
  printed  every line as laid out, fixed-width — how it came off the printer.
           Print streams and columnar documents (WordStar ruler lines) force
           this: their alignment only exists in a fixed-width world.
"""
import html as _html

# ---------------------------------------------------------------- registry
#
# The extension point. An emitter is any callable (doc, mode='modern', **options)
# -> str, registered under a name. Two ways in:
#
#   @ctrlkd.emitter('latex', ext='.tex')            # in your own code
#   def emit_latex(doc, mode='modern', **options): ...
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

# ---------------------------------------------------------------- text

def emit_text(doc, mode='modern', **_options):
    out = []
    for b in doc.blocks:
        if b.kind == 'softpage':                 # WordStar's own pagination:
            if mode == 'printed':                # meaningful only line-for-line
                out.append('\f')
            continue
        if b.kind == 'pagebreak':
            out.append('\f' if mode == 'printed' else '\n' + '-' * 20 + '\n')
            continue
        para = '\n'.join(line.text() for line in b.lines)
        if para.strip() or mode == 'printed':
            out.append(para)
    text = ('\n'.join(out) if mode == 'printed' or _printed(doc)
            else '\n\n'.join(o for o in out if o.strip()))
    if doc.footnotes:
        text += '\n\n' + '\n'.join(f'[{i+1}] {"".join(s.text for s in n)}'
                                   for i, n in enumerate(doc.footnotes))
    return text + '\n'

# ---------------------------------------------------------------- markdown

_MD = {'b': '**', 'i': '*', 'strike': '~~'}
_MD_HTML = {'u': 'u', 'sup': 'sup', 'sub': 'sub'}

def _md_span(s):
    text = s.text
    if 'fnref' in s.styles:
        return f'[^{text}]'
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

def emit_markdown(doc, mode='modern', **_options):
    if mode == 'printed' or _printed(doc):
        # alignment is the content: a fenced block is the honest representation
        body = emit_text(doc, 'printed')
        return '```\n' + body.rstrip('\n') + '\n```\n'
    out = []
    for b in doc.blocks:
        if b.kind == 'softpage':
            continue
        if b.kind == 'pagebreak':
            out.append('---')
            continue
        lines = [''.join(_md_span(s) for s in line.spans) for line in b.lines]
        para = '\\\n'.join(l for l in lines)          # hard breaks: trailing backslash
        if b.heading and para.strip():
            para = '#' * b.heading + ' ' + para.strip()
        if para.strip():
            out.append(para)
    md = '\n\n'.join(out)
    if doc.footnotes:
        md += '\n\n' + '\n'.join(f'[^{i+1}]: {"".join(s.text for s in n)}'
                                 for i, n in enumerate(doc.footnotes))
    return md + '\n'

# ---------------------------------------------------------------- html

_CSS = """body{max-width:42rem;margin:2rem auto;padding:0 1rem;
font:17px/1.6 Georgia,serif;color:#222}p{margin:0 0 1em}
pre{font:14px/1.5 ui-monospace,Menlo,Consolas,monospace;overflow-x:auto}
hr.pb{border:none;border-top:1px dashed #bbb;margin:2rem 0}
@media(prefers-color-scheme:dark){body{background:#161616;color:#ddd}
hr.pb{border-top-color:#444}}"""

_TAG = {'b': 'strong', 'i': 'em', 'u': 'u', 'sup': 'sup', 'sub': 'sub', 'strike': 's'}

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
    return text

def emit_html(doc, mode='modern', title='', **_options):
    parts = []
    printed = mode == 'printed' or _printed(doc)
    for b in doc.blocks:
        if b.kind == 'softpage':
            if printed:
                parts.append('<hr class="pb">')
            continue
        if b.kind == 'pagebreak':
            parts.append('<hr class="pb">')
            continue
        if b.heading:
            txt = ' '.join(''.join(_html_span(s) for s in line.spans)
                           for line in b.lines).strip()
            if txt:
                parts.append(f'<h{b.heading}>{txt}</h{b.heading}>')
            continue
        if printed:
            body = '\n'.join(''.join(_html_span(s, keep_ws=True) for s in line.spans)
                             for line in b.lines)
            if body.strip():
                parts.append(f'<pre>{body}</pre>')
        else:
            lines = [''.join(_html_span(s) for s in line.spans) for line in b.lines]
            para = '<br>\n'.join(lines)
            if para.strip():
                parts.append(f'<p>{para}</p>')
    if doc.footnotes:
        notes = ''.join(f'<li>{"".join(_html.escape(s.text) for s in n)}</li>'
                        for n in doc.footnotes)
        parts.append(f'<hr><ol class="footnotes">{notes}</ol>')
    return ('<!doctype html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_html.escape(title)}</title><style>{_CSS}</style></head>\n'
            f'<body>\n' + '\n'.join(parts) + '\n</body></html>\n')

# ---------------------------------------------------------------- rtf

_RTF_ON = {'b': r'\b ', 'i': r'\i ', 'u': r'\ul ', 'sup': r'\super ',
           'sub': r'\sub ', 'strike': r'\strike '}

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

def emit_rtf(doc, mode='modern', **_options):
    printed = mode == 'printed' or _printed(doc)
    font = r'\f1' if printed else r'\f0'
    parts = []
    for b in doc.blocks:
        if b.kind == 'softpage':
            if printed:
                parts.append(r'\page ')
            continue
        if b.kind == 'pagebreak':
            parts.append(r'\page ')
            continue
        lines = []
        for line in b.lines:
            seg = ''.join('{' + ''.join(_RTF_ON.get(s, '') for s in sorted(sp.styles))
                          + _rtf_escape(sp.text) + '}' for sp in line.spans)
            lines.append(seg)
        if b.heading:
            lines = ['{' + r'\b\fs28 ' + l + '}' for l in lines]
        joiner = r'\line ' if not printed else r'\line '
        para = joiner.join(lines)
        if para.strip() or printed:
            parts.append(para + r'\par ')
        if not printed:
            parts.append(r'\par ')                    # blank line between paragraphs
    body = '\n'.join(parts)
    return (r'{\rtf1\ansi\deff0{\fonttbl{\f0 Times New Roman;}{\f1 Courier New;}}'
            + '\n' + font + r'\fs24 ' + '\n' + body + '\n}\n')

# built-ins register through the same door plugins use
emitter('text', ext='.txt')(emit_text)
emitter('markdown', ext='.md')(emit_markdown)
emitter('html', ext='.html')(emit_html)
emitter('rtf', ext='.rtf')(emit_rtf)
