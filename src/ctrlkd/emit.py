"""ctrl-kd emitters: Document IR -> text / markdown / html / rtf.

Two rendering philosophies, chosen by the caller:
  modern   reflowed paragraphs, semantic markup (the IR already joined word
           wraps and kept deliberate breaks — emitters just express it)
  printed  every line as laid out, fixed-width — how it came off the printer.
           Print streams and columnar documents (WordStar ruler lines) force
           this: their alignment only exists in a fixed-width world.
"""
import html as _html

def _printed(doc):
    return doc.meta.get('variant') == 'printstream' or doc.meta.get('columnar')

# ---------------------------------------------------------------- text

def emit_text(doc, mode='modern'):
    out = []
    for b in doc.blocks:
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
    if not text.strip():
        return text
    esc = text.replace('\\', '\\\\')
    for ch in '*_#`[]':
        esc = esc.replace(ch, '\\' + ch)
    lead = esc[:len(esc) - len(esc.lstrip())]
    trail = esc[len(esc.rstrip()):]
    core = esc.strip()
    for st in s.styles:
        if st in _MD:
            core = f'{_MD[st]}{core}{_MD[st]}'
        elif st in _MD_HTML:
            t = _MD_HTML[st]
            core = f'<{t}>{core}</{t}>'
    return lead + core + trail

def emit_markdown(doc, mode='modern'):
    if mode == 'printed' or _printed(doc):
        # alignment is the content: a fenced block is the honest representation
        body = emit_text(doc, 'printed')
        return '```\n' + body.rstrip('\n') + '\n```\n'
    out = []
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            out.append('---')
            continue
        lines = [''.join(_md_span(s) for s in line.spans) for line in b.lines]
        para = '\\\n'.join(l for l in lines)          # hard breaks: trailing backslash
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
        t = _TAG[st]
        text = f'<{t}>{text}</{t}>'
    return text

def emit_html(doc, mode='modern', title=''):
    parts = []
    printed = mode == 'printed' or _printed(doc)
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            parts.append('<hr class="pb">')
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

def emit_rtf(doc, mode='modern'):
    printed = mode == 'printed' or _printed(doc)
    font = r'\f1' if printed else r'\f0'
    parts = []
    for b in doc.blocks:
        if b.kind == 'pagebreak':
            parts.append(r'\page ')
            continue
        lines = []
        for line in b.lines:
            seg = ''.join('{' + ''.join(_RTF_ON[s] for s in sorted(sp.styles))
                          + _rtf_escape(sp.text) + '}' for sp in line.spans)
            lines.append(seg)
        joiner = r'\line ' if not printed else r'\line '
        para = joiner.join(lines)
        if para.strip() or printed:
            parts.append(para + r'\par ')
        if not printed:
            parts.append(r'\par ')                    # blank line between paragraphs
    body = '\n'.join(parts)
    return (r'{\rtf1\ansi\deff0{\fonttbl{\f0 Times New Roman;}{\f1 Courier New;}}'
            + '\n' + font + r'\fs24 ' + '\n' + body + '\n}\n')

EMITTERS = {'text': emit_text, 'txt': emit_text, 'markdown': emit_markdown,
            'md': emit_markdown, 'html': emit_html, 'rtf': emit_rtf}
