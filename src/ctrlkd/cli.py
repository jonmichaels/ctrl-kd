"""ctrl-kd command line: convert WordStar-era files to modern formats.

    ctrl-kd PAPER.WS                       # -> PAPER.md, modern reflow
    ctrl-kd PAPER.WS -t html -o out.html
    ctrl-kd --mode printed LETTER          # as it came off the printer
    ctrl-kd --diagnose MYSTERY.FIL         # what IS this file?
    ctrl-kd -t text -t html -d out/ *.WS   # batch, multiple formats
"""
import argparse, json, os, sys
from . import core, emit

EXT = {'text': '.txt', 'txt': '.txt', 'markdown': '.md', 'md': '.md',
       'html': '.html', 'rtf': '.rtf'}

def diagnose(path, data):
    det = core.detect(data)
    info = {'file': path, **det}
    if det['variant'] in ('ws4', 'ws5+'):
        doc = core.parse_ws(data)
        info.update({k: doc.meta[k] for k in
                     ('margin_estimate', 'dot_commands', 'unknown_codes', 'columnar')})
        info['paragraphs'] = sum(1 for b in doc.blocks if b.kind == 'para')
        info['footnotes'] = len(doc.footnotes)
    return info

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='ctrl-kd',
        description='Convert WordStar 4-7 documents and print-to-disk files to '
                    'text, Markdown, HTML, or RTF. ^KD: save and done.')
    ap.add_argument('files', nargs='+', help='input file(s)')
    ap.add_argument('-t', '--to', action='append', choices=sorted(EXT),
                    help='output format (repeatable; default: markdown)')
    ap.add_argument('-o', '--output', help='output file (single input only)')
    ap.add_argument('-d', '--outdir', help='output directory for batch conversion')
    ap.add_argument('--mode', choices=('modern', 'printed'), default='modern',
                    help='modern: reflowed paragraphs. printed: line-for-line, '
                         'fixed-width, as it printed in 1990 (default: modern; '
                         'print streams and ruler-line documents always render printed)')
    ap.add_argument('--variant', choices=('ws4', 'ws5+', 'printstream', 'text'),
                    help='override detection')
    ap.add_argument('--encoding', default='cp437',
                    help='byte encoding of the source (default: cp437)')
    ap.add_argument('--diagnose', action='store_true',
                    help='report what the file is (variant, margin, dot commands, '
                         'unknown codes) as JSON; no conversion')
    a = ap.parse_args(argv)
    formats = a.to or ['markdown']
    if a.output and (len(a.files) > 1 or len(formats) > 1):
        ap.error('-o works with a single input and a single format; use -d for batch')

    status = 0
    for path in a.files:
        try:
            data = open(path, 'rb').read()
        except OSError as e:
            print(f'ctrl-kd: {e}', file=sys.stderr)
            status = 1
            continue
        if a.diagnose:
            print(json.dumps(diagnose(path, data), indent=2))
            continue
        try:
            doc = core.parse(data, encoding=a.encoding, variant=a.variant)
        except ValueError as e:
            print(f'ctrl-kd: {path}: {e} (use --diagnose to inspect, '
                  f'--variant to force)', file=sys.stderr)
            status = 1
            continue
        base = os.path.splitext(os.path.basename(path))[0]
        for fmt in formats:
            fn = emit.EMITTERS[fmt]
            out = (fn(doc, a.mode, title=base) if fmt == 'html'
                   else fn(doc, a.mode))
            if a.output:
                dest = a.output
            else:
                dest = os.path.join(a.outdir or os.path.dirname(path) or '.',
                                    base + EXT[fmt])
                if a.outdir:
                    os.makedirs(a.outdir, exist_ok=True)
            with open(dest, 'w', encoding='utf-8', newline='\n') as f:
                f.write(out)
            print(f'{path} -> {dest}')
    return status

if __name__ == '__main__':
    sys.exit(main())
