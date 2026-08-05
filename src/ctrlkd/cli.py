"""ctrl-kd command line: convert WordStar-era files to modern formats.

    ctrl-kd PAPER.WS                       # -> PAPER.md, modern reflow
    ctrl-kd PAPER.WS -t html -o out.html
    ctrl-kd --mode printed LETTER          # as it came off the printer
    ctrl-kd --diagnose MYSTERY.FIL         # what IS this file?
    ctrl-kd -t text -t html -d out/ *.WS   # batch, multiple formats
"""
import argparse, json, os, sys

BANNER = r"""        __       __      __       __
  _____/ /______/ /     / /______/ /
 / ___/ __/ ___/ /_____/ //_/ __  /
/ /__/ /_/ /  / /_____/ ,< / /_/ /
\___/\__/_/  /_/     /_/|_|\__,_/"""
# FIGlet "Slant" by Glenn Chappell (1993) -- FIGlet's own co-creator, the
# WordStar 7 release window. Jon's ruling: --version, --help, and the README
# carry it; conversion output and stderr status never do. A static constant
# because the name never changes; no .flf machinery needed.


from . import core, emit
from .convert import DEFAULT_NOTE_KINDS   # module attr, not the re-exported convert()

def diagnose(path, data):
    det = core.detect(data)
    info = {'file': path, **det}
    if det['variant'] in ('ws4', 'ws5+'):
        doc = core.parse_ws(data)
        info.update({k: doc.meta[k] for k in
                     ('margin_estimate', 'dot_commands', 'unknown_codes', 'columnar')})
        info['paragraphs'] = sum(1 for b in doc.blocks if b.kind == 'para')
        # note kinds, counted separately (footnote/endnote/annotation/comment)
        # rather than flattened, so a rescue tool can tell a file has hidden
        # comments even when this run is only converting to plain text
        info['notes'] = {kind: sum(1 for n in doc.notes if n.kind == kind)
                         for kind in ('footnote', 'endnote', 'annotation', 'comment')}
        # unrecognised symmetrical-sequence types: preserved, not silently
        # dropped, so --diagnose can report them instead of going quiet
        info['unknown_blocks'] = [
            {'type': f'0x{u.cmd:02x}' if u.cmd >= 0 else 'malformed',
             'offset': u.offset, 'length': len(u.data)}
            for u in doc.unknown_blocks]
        # page geometry from the file's own dot commands, with provenance --
        # a caller must be able to say "Legal (from file)" vs "Letter (default)"
        info['page'] = doc.meta.get('page')
        # .PT/.PSA/.PSB are WordTsar's inventions, not WordStar commands: their
        # presence identifies who WROTE the file, not how it is encoded
        if doc.meta.get('producer'):
            info['producer'] = doc.meta['producer']
    elif det['variant'] == 'printstream':
        doc = core.parse(data)
        # damage WordStar itself introduced at print time (comments + the
        # ASCII/ASC256/PRVIEW/WS4 drivers truncated the rest of the line);
        # reported so it reads as a 1990s defect, not our parse failing
        if doc.meta.get('comment_bug'):
            info['comment_bug'] = doc.meta['comment_bug']
    return info

def main(argv=None):
    emit.load_plugins()          # third-party emitters (ctrlkd.emitters entry points)
    ap = argparse.ArgumentParser(
        prog='ctrl-kd',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=BANNER + '\n\n' + 'Convert WordStar 4-7 documents and print-to-disk files to '
                    'text, Markdown, HTML, RTF, or PDF (extensible: see '
                    'EXTENDING.md). ^KD: save and done.')
    from . import __version__
    ap.add_argument('--version', action='version',
                    version=BANNER + f'\nctrl-kd {__version__}')
    ap.add_argument('files', nargs='+', help='input file(s)')
    ap.add_argument('-t', '--to', action='append', choices=emit.formats(),
                    help='output format (repeatable; default: markdown)')
    ap.add_argument('-o', '--output', help='output file (single input only)')
    ap.add_argument('-d', '--outdir', help='output directory for batch conversion')
    ap.add_argument('--mode', choices=('modern', 'printed'), default='printed',
                    help='printed: line-for-line, fixed-width, as it printed in '
                         '1990 (DEFAULT). modern: reflowed paragraphs for '
                         'reading. Print streams and ruler-line documents '
                         'always render printed regardless.')
    ap.add_argument('--variant', choices=('ws4', 'ws5+', 'printstream', 'text'),
                    help='override detection')
    ap.add_argument('--encoding', default='cp437',
                    help='byte encoding of the source (default: cp437)')
    ap.add_argument('--fonts', choices=('office', 'mac', 'google', 'linux'),
                    default='office',
                    help='RTF font-name target: office (Word/Docs, default; '
                         'these fonts ship with MS Office, not bare Windows), '
                         'mac (Cocoa-native: TextEdit/Pages), google (Docs '
                         'catalog incl. its chancery script), linux (URW '
                         'base-35 -- free clones of exactly this era\'s '
                         'faces)')
    ap.add_argument('--page-defaults', metavar='mt=0.83in,mb=1in,po=0.7in',
                    help='replacement DEFAULTS for page geometry the document '
                         'does not declare (its own dot commands always win). '
                         'Keys: mt, mb (top/bottom margin), po (page offset), '
                         'hm, fm (header/footer margin). Values take an "in" '
                         'suffix for inches, else native units (lines at 6 '
                         'LPI; po in 10-CPI columns). Use when the printing '
                         "machine's WSCHANGE-patched defaults are known -- "
                         'stock WordStar is not what every printer produced')
    ap.add_argument('--no-styles', action='store_true',
                    help='omit paragraph-style pass-through (HTML classes + '
                         'generated CSS, RTF stylesheet) from the output')
    ap.add_argument('--no-notes', action='store_true',
                    help='omit footnotes, endnotes and annotations from the output')
    ap.add_argument('--comments', action='store_true',
                    help="include WordStar comments, which it never printed "
                         "(author's asides, hidden since the file was written)")
    ap.add_argument('--diagnose', action='store_true',
                    help='report what the file is (variant, margin, dot commands, '
                         'unknown codes) as JSON; no conversion')
    a = ap.parse_args(argv)
    formats = a.to or ['markdown']
    if a.no_notes:
        notes = frozenset()
    else:
        notes = set(DEFAULT_NOTE_KINDS) | ({'comment'} if a.comments else set())
    if a.output and (len(a.files) > 1 or len(formats) > 1):
        ap.error('-o works with a single input and a single format; use -d for batch')

    page_defaults = None
    if a.page_defaults:
        # mt/mb/hm/fm -> lines at 6 LPI, po -> 10-CPI columns; an "in" suffix
        # converts from inches, a bare number is already native units
        keymap = {'mt': ('mt_lines', 6.0), 'mb': ('mb_lines', 6.0),
                  'hm': ('hm_lines', 6.0), 'fm': ('fm_lines', 6.0),
                  'po': ('po_cols', 10.0)}
        page_defaults = {}
        for part in a.page_defaults.split(','):
            k, _, v = part.partition('=')
            k, v = k.strip().lower(), v.strip().lower()
            if k not in keymap or not v:
                ap.error(f'--page-defaults: unknown or empty entry {part!r}')
            dest, per_inch = keymap[k]
            try:
                page_defaults[dest] = (float(v[:-2]) * per_inch
                                       if v.endswith('in') else float(v))
            except ValueError:
                ap.error(f'--page-defaults: bad value in {part!r}')

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
            reg = emit.get_emitter(fmt)
            out = reg['fn'](doc, a.mode, title=base, notes=notes,
                            styles=not a.no_styles, fonts_target=a.fonts,
                            page_defaults=page_defaults)
            if a.output:
                dest = a.output
            else:
                dest = os.path.join(a.outdir or os.path.dirname(path) or '.',
                                    base + reg['ext'])
                if a.outdir:
                    os.makedirs(a.outdir, exist_ok=True)
            if isinstance(out, bytes):           # binary formats (e.g. pdf)
                with open(dest, 'wb') as f:
                    f.write(out)
            else:
                with open(dest, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(out)
            # Status goes to STDERR: with `-o /dev/stdout` (or a pipe) a
            # status line on stdout lands INSIDE the converted document --
            # found 2026-08-04 when a Python-vs-Swift archive comparison
            # flagged all 81 convertible documents as differing by exactly
            # this line. Both CLIs carried the defect; both fixed together.
            print(f'{path} -> {dest}', file=sys.stderr)
    return status

if __name__ == '__main__':
    sys.exit(main())
