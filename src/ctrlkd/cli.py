"""ctrl-kd command line: convert WordStar-era files to modern formats.

    ctrl-kd PAPER.WS                       # -> PAPER.rtf: modern reflow, the
                                           #    document's own fonts carried
    ctrl-kd --mode printed LETTER.WS       # -> LETTER.pdf: the 1990 facsimile
    ctrl-kd PAPER.WS -t md                 # modern markdown instead
    ctrl-kd --page-settings sawyer X.WS    # a known machine's page defaults
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
                    help='output format (repeatable). Default follows the '
                         'mode: modern -> rtf (the full-fidelity living '
                         'document), printed -> pdf (the closest thing to '
                         'actually printing).')
    ap.add_argument('-o', '--output', help='output file (single input only)')
    ap.add_argument('-d', '--outdir', help='output directory for batch conversion')
    ap.add_argument('--mode', choices=('modern', 'printed'), default=None,
                    help='modern: the document brought to a modern audience -- '
                         'reflowed, its own fonts carried, gaps filled with '
                         "today's conventions (DEFAULT). printed: the 1990 "
                         'facsimile -- line-for-line on the era page. Print '
                         'streams and ruler-line documents always render '
                         'printed (a notice is printed if you asked for '
                         'modern).')
    ap.add_argument('--variant', choices=('ws4', 'ws5+', 'printstream', 'text'),
                    help='override detection')
    ap.add_argument('--encoding', choices=('cp437',), default='cp437',
                    help='byte encoding of the source. Only cp437 is '
                         'accepted: every known WordStar file uses the IBM '
                         'PC code page, and no non-437 corpus exists to '
                         'validate another decoding against (see FAQ.md). '
                         'The library API (ctrlkd.core.parse) accepts any '
                         'codec name for experimenters with real material.')
    ap.add_argument('--fonts', choices=('office', 'mac', 'google', 'linux'),
                    default='office',
                    help='RTF font-name target: office (Word/Docs, default; '
                         'these fonts ship with MS Office, not bare Windows), '
                         'mac (Cocoa-native: TextEdit/Pages), google (Docs '
                         'catalog incl. its chancery script), linux (URW '
                         'base-35 -- free clones of exactly this era\'s '
                         'faces)')
    ap.add_argument('--page-settings', metavar='PRESET|mt=..,mb=..,po=..',
                    help='page geometry for everything the document does not '
                         'declare itself (its own dot commands always win). '
                         'Presets: "default" (WordStar factory: mt 0.5in, '
                         'mb 1.33in, po 0.8in), "sawyer" (Robert J. '
                         "Sawyer's own WSCHANGE-recovered machine: mt "
                         '0.83in, mb 1in, po 0.7in), "modern" (1in '
                         'margins). Or raw values -- keys mt, mb, po, hm, '
                         'fm; an "in" suffix means inches, bare numbers are '
                         'native units (lines at 6 LPI; po in 10-CPI '
                         'columns). size=letter|legal|a4 names the sheet '
                         'for files that declare no page length.')
    ap.add_argument('--force', action='store_true',
                    help='accepted for command-line compatibility with sr '
                         '(where it bypasses the overwrite prompt); ctrl-kd '
                         'always overwrites existing outputs')
    ap.add_argument('--note-refs', choices=('word', 'prefixed'),
                    default='word',
                    help='note reference-mark display in Modern output. '
                         '"word" (default): the Word standard -- arabic '
                         'footnotes, lowercase-roman endnotes, WordStar '
                         'tags for annotations. "prefixed": footnotes 1 2 '
                         '3, endnotes e1 e2, annotations a1 a2 -- the same '
                         'labels the markdown output always uses, matched '
                         'across formats. Printed output is a facsimile '
                         'and ignores this.')
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
    mode_explicit = a.mode is not None
    a.mode = a.mode or 'modern'
    # The default format follows the mode (ruling 2026-08-05): bare modern =
    # the full-fidelity RTF; bare printed = the facsimile PDF.
    formats = a.to or (['pdf'] if a.mode == 'printed' else ['rtf'])
    if a.no_notes:
        notes = frozenset()
    else:
        notes = set(DEFAULT_NOTE_KINDS) | ({'comment'} if a.comments else set())
    if a.output and (len(a.files) > 1 or len(formats) > 1):
        ap.error('-o works with a single input and a single format; use -d for batch')

    # --page-settings: a preset name, or raw values. "default" is the
    # explicit no-op (WordStar factory IS what an empty settings dict means).
    PAGE_PRESETS = {
        'default': {},
        'sawyer': {'mt_lines': 1195 / 1440 * 6, 'mb_lines': 6.0,
                   'po_cols': 7.0},
        'modern': {'mt_lines': 6.0, 'mb_lines': 6.0, 'po_cols': 10.0},
    }
    page_settings = None
    if a.page_settings:
        preset = a.page_settings.strip().lower()
        if preset in PAGE_PRESETS:
            page_settings = dict(PAGE_PRESETS[preset])
        else:
            # mt/mb/hm/fm -> lines at 6 LPI, po -> 10-CPI columns; an "in"
            # suffix converts from inches, a bare number is native units
            keymap = {'mt': ('mt_lines', 6.0), 'mb': ('mb_lines', 6.0),
                      'hm': ('hm_lines', 6.0), 'fm': ('fm_lines', 6.0),
                      'po': ('po_cols', 10.0)}
            # the three main page sizes (ruled 2026-08-06) as .pl lines;
            # width rides on the height inference in the page model
            sizes = {'letter': 66.0, 'legal': 84.0, 'a4': 11.693 * 6}
            page_settings = {}
            for part in a.page_settings.split(','):
                k, _, v = part.partition('=')
                k, v = k.strip().lower(), v.strip().lower()
                if k == 'size':
                    if v not in sizes:
                        ap.error(f'--page-settings: unknown size {v!r} '
                                 f"(choose from {', '.join(sizes)})")
                    page_settings['pl_lines'] = sizes[v]
                    continue
                if k not in keymap or not v:
                    ap.error(f'--page-settings: unknown or empty entry {part!r}'
                             f" (or use a preset: {', '.join(PAGE_PRESETS)})")
                dest, per_inch = keymap[k]
                try:
                    page_settings[dest] = (float(v[:-2]) * per_inch
                                           if v.endswith('in') else float(v))
                except ValueError:
                    ap.error(f'--page-settings: bad value in {part!r}')

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
        # D5 notice (ruled 2026-08-05): when the user EXPLICITLY asked for
        # modern and the input can only render printed, say so once instead
        # of silently disobeying the flag. The override itself stands -- a
        # print stream has no soft returns to unwrap.
        if (mode_explicit and a.mode == 'modern'
                and (doc.meta.get('variant') == 'printstream'
                     or doc.meta.get('columnar'))):
            kind = ('print stream' if doc.meta.get('variant') == 'printstream'
                    else 'ruler-line document')
            print(f'ctrl-kd: {path}: {kind} -- modern reflow is not '
                  f'possible; rendering printed', file=sys.stderr)
        # A driver-art document reflowed under modern will look strange, and
        # the log should say why (ruling 2026-08-06): the driver's page art
        # (colour knockouts, rules, hand-laid boxes) exists only at print
        # time. Its CHARACTER substitutions are content and ARE applied.
        # --comments + printed is a contradiction the CLI explains rather
        # than silently resolving (ruling 2026-08-06): WordStar printed
        # nothing for a comment, and the facsimile doesn't either.
        if (a.comments
                and (a.mode == 'printed'
                     or doc.meta.get('variant') == 'printstream'
                     or doc.meta.get('columnar'))
                and any(n.kind == 'comment' for n in doc.notes)):
            print(f'ctrl-kd: {path}: comments are never part of the printed '
                  f'page -- WordStar did not print them, so the facsimile '
                  f"doesn't either; convert with --mode modern to see them",
                  file=sys.stderr)
        if (a.mode == 'modern'
                and doc.meta.get('printer_driver') == 'LJ6DTP'):
            print(f'ctrl-kd: {path}: LJ6DTP driver document -- its '
                  f'print-time page art (boxes, rules, colour) does not '
                  f'reflow; character substitutions applied. '
                  f'--mode printed reproduces the page', file=sys.stderr)
        # --page-settings applies ONCE to the resolved page dict, so every
        # emitter (PDF geometry, RTF page setup) sees the same page.
        if page_settings and doc.meta.get('page') is not None:
            doc.meta['page'] = core.effective_page(doc.meta['page'],
                                                   page_settings)
        base = os.path.splitext(os.path.basename(path))[0]
        for fmt in formats:
            reg = emit.get_emitter(fmt)
            out = reg['fn'](doc, a.mode, title=base, notes=notes,
                            styles=not a.no_styles, fonts_target=a.fonts,
                            note_refs=a.note_refs)
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
