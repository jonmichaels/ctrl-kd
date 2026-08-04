#!/usr/bin/env python3
"""Regenerate the Swift port's ground-truth vectors from THIS Python implementation.

WHY THIS EXISTS
---------------
The vectors are the equivalence proof between the two implementations: the Swift
port must reproduce, byte for byte, what Python produces for a fixed set of
inputs. Until 2026-08-03 each vector file had been pasted by hand out of a job
document, and there was no way to make a new one -- so when Python's behaviour
deliberately changed, the only options were to hand-edit expectations (which
turns the oracle into a mirror of whatever you just wrote) or to leave the port
red forever.

THE RULE THIS ENFORCES
----------------------
INPUTS ARE FROZEN. Every `input_hex` in every file is left exactly as found --
this script never invents a case and never alters one. Only the EXPECTATIONS are
recomputed, and only from Python. Nothing here ever reads the Swift side, so a
regenerated vector can still fail the port, which is the entire point: after a
run, a remaining Swift failure is a real divergence and not a stale expectation.

Because inputs are frozen, `git diff` on the vector files after a run IS the
audit. Every changed line should be explainable by a specific commit to the
Python implementation. A diff you cannot explain is a bug you just found.

USAGE
    tools/gen_vectors.py <swift-tests-dir>          # rewrite in place
    tools/gen_vectors.py <swift-tests-dir> --check  # report, change nothing

`<swift-tests-dir>` is the directory holding `Resources/` and `Fixtures/` (the
Swift package is a separate repository, so the path is an argument -- there is
nothing to hardcode and nothing about the caller's filesystem is assumed).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from ctrlkd import core, pdf                                    # noqa: E402
from ctrlkd.emit import (emit_text, emit_markdown, emit_html, emit_rtf,   # noqa: E402
                         ALL_NOTE_KINDS, DEFAULT_NOTE_KINDS)


# ------------------------------------------------------------ serialization
#
# One shape per vector section, matching what the Swift tests already read. These
# mirror the job documents that produced the files originally; where a field name
# looks odd it is because the Swift side reads that exact key.

def _spans(line):
    return [{'text': s.text, 'styles': sorted(s.styles)} for s in line.spans]


def _doc_json(doc):
    return {
        'blocks': [
            {
                'kind': b.kind,
                'heading': b.heading,
                'lines': [_spans(l) for l in b.lines],
            }
            for b in doc.blocks
        ],
        # Flattened to one string per footnote -- the shape the Swift side decodes.
        # `doc.footnotes` is the convenience view over `doc.notes` (spans, so an
        # emitter can style them); the vector only needs the text.
        'footnotes': [''.join(s.text for s in fn) for fn in doc.footnotes],
        'meta': {
            'variant': doc.meta.get('variant'),
            'margin_estimate': doc.meta.get('margin_estimate'),
            'dot_commands': doc.meta.get('dot_commands', []),
            'unknown_codes': doc.meta.get('unknown_codes', {}),
            'columnar': doc.meta.get('columnar', False),
        },
    }


def _pages_json(doc, printed):
    return [[[{'text': t, 'styles': sorted(st)} for t, st in line] for line in page]
            for page in pdf._doc_to_pagelines(doc, printed)]


EMITTERS = {
    'text': emit_text,
    'md': emit_markdown,
    'markdown': emit_markdown,
    'html': emit_html,
    'rtf': emit_rtf,
}


# ------------------------------------------------------------ section rewriters
#
# Each returns the section with expectations recomputed. Unknown sections are
# left untouched rather than guessed at -- a section this script does not
# understand must stay hand-maintained and visibly so, not be silently emptied.

def _rw_symmetric_blocks(cases):
    out = []
    for c in cases:
        data = bytes.fromhex(c['input_hex'])
        body, notes = core._symmetric_blocks(data, 'cp437')[:2]
        new = dict(c)
        new['output_hex'] = body.hex()
        if 'footnotes' in c:
            new['footnotes'] = [n.text for n in notes
                                if n.kind in ('footnote', 'endnote', 'annotation')]
        out.append(new)
    return out


def _rw_parse_ws(cases):
    out = []
    for c in cases:
        new = dict(c)
        new['document'] = _doc_json(core.parse_ws(bytes.fromhex(c['input_hex'])))
        out.append(new)
    return out


def _rw_pagelines(cases):
    """Layout cases. HONOUR THE `parser` FIELD: a case that says `parse_ws` means it,
    and routing it through the front door instead silently changes the answer.

    `.pa` is the case that exposes this. Through `parse_ws` it is a dot command and
    becomes a page break; through `parse` a short plain-ASCII file detects as a PRINT
    STREAM, where dot commands are literal text and `.pa` stays a line that reads
    ".pa". So the same bytes give three pages one way and one page of three lines the
    other -- and the vector that declared `parse_ws` had been generated the wrong way,
    which is why the Swift side (which does read the field) could never match it."""
    out = []
    for c in cases:
        data = bytes.fromhex(c['input_hex'])
        doc = core.parse_ws(data) if c.get('parser') == 'parse_ws' else core.parse(data)
        new = dict(c)
        new['pages'] = _pages_json(doc, c['printed'])
        out.append(new)
    return out


def _rw_emit(cases):
    out = []
    for c in cases:
        fn = EMITTERS.get(c['format'])
        if fn is None:
            out.append(c)
            continue
        doc = core.parse(bytes.fromhex(c['input_hex']))
        new = dict(c)
        # `title` is HTML-only and OPTIONAL, and dropping it silently produced 15
        # failures that looked like emitter divergence: the Swift side passes the
        # vector's own title through, so a regeneration that ignores it compares a
        # titled document against an untitled expectation.
        kwargs = {'mode': c['mode']}
        if c.get('title') is not None and fn is emit_html:
            kwargs['title'] = c['title']
        new['expected'] = fn(doc, **kwargs)
        out.append(new)
    return out


def _rw_line_cases(cases):
    out = []
    for c in cases:
        doc = core.parse_ws(bytes.fromhex(c['input_hex']))
        new = dict(c)
        # Both views of the same block: the PHYSICAL lines WordStar put on paper, and
        # the reflowed logical lines `merged_lines` joins them back into. The pair is
        # the whole point of the 2.0.0 split, so a rewriter that emitted only one of
        # them would silently delete half the coverage.
        new['blocks'] = [
            {
                'kind': b.kind,
                'physical': [{'text': ''.join(s.text for s in l.spans), 'soft': l.soft}
                             for l in b.lines],
                'merged': [''.join(s.text for s in l.spans)
                           for l in core.merged_lines(b)],
            }
            for b in doc.blocks
        ]
        # The same case also carries per-format emit expectations. Regenerating the
        # blocks but not these left the Swift side comparing new inputs against old
        # output -- a mismatch that reads as a port bug and is not one.
        for key, fn, mode in (('emit_text_printed', emit_text, 'printed'),
                              ('emit_text_modern', emit_text, 'modern'),
                              ('emit_markdown_modern', emit_markdown, 'modern'),
                              ('emit_rtf_modern', emit_rtf, 'modern'),
                              ('emit_html_modern', emit_html, 'modern')):
            if key in c:
                new[key] = fn(doc, mode=mode)
        out.append(new)
    return out


def _rw_convert(cases):
    """job-010's front-door cases: `convert(data, to=<format>)`, one per registered
    name plus the `md` alias. These prove the registry wires each name to the right
    emitter, so they go through `convert` rather than calling an emitter directly."""
    from ctrlkd.convert import convert
    out = []
    for c in cases:
        new = dict(c)
        new['expected'] = convert(bytes.fromhex(c['input_hex']), to=c['to'])
        out.append(new)
    return out


def _rw_notes_cases(cases):
    out = {}
    for name, c in cases.items():
        doc = core.parse_ws(bytes.fromhex(c['input_hex']))
        new = dict(c)
        new['notes'] = [
            {
                'kind': n.kind,
                'text': n.text,
                'number': n.number,
                'tag': n.tag,
                'dot_commands': n.dot_commands,
            }
            for n in doc.notes
        ]
        if 'emit' in c:
            # {format: {note-selection setting: output}} -- the three settings are
            # which note KINDS get rendered, not a mode. Comments are the difference:
            # WordStar never printed them, so `default` omits them and `all_notes`
            # asks for them explicitly.
            settings = {
                'default': DEFAULT_NOTE_KINDS,
                'all_notes': ALL_NOTE_KINDS,
                'no_notes': frozenset(),
            }
            new['emit'] = {
                # MODERN mode: these vectors exercise note SELECTION, and the
                # reflowing emitters are where note rendering differs per kind
                # (markdown footnote refs, HTML doc-endnote sections). Printed mode
                # is covered separately by `printed_pagelines` below.
                fmt: {name: fn(doc, mode='modern', notes=kinds)
                      for name, kinds in settings.items()}
                for fmt, fn in (('text', emit_text), ('markdown', emit_markdown),
                                ('html', emit_html), ('rtf', emit_rtf))
            }
        if 'printed_pagelines' in c:
            new['printed_pagelines'] = [
                [''.join(t for t, _ in ln) for ln in page]
                for page in pdf._doc_to_pagelines(doc, True)
            ]
        out[name] = new
    return out


REWRITERS = {
    'symmetric_blocks': _rw_symmetric_blocks,
    'symmetric_blocks_extra': _rw_symmetric_blocks,
    'parse_ws': _rw_parse_ws,
    'doc_to_pagelines': _rw_pagelines,
    'layout_updates': _rw_pagelines,
    'layout_116': _rw_pagelines,
    'emit': _rw_emit,
    'emit2': _rw_emit,
    'line_cases': _rw_line_cases,
}


def _rewrite_file(path):
    """Recompute every section this script understands. Returns (changed, notes)."""
    with open(path) as fh:
        original = fh.read()
    doc = json.loads(original)
    touched = []

    for key, rewriter in REWRITERS.items():
        if key in doc and isinstance(doc[key], list):
            doc[key] = rewriter(doc[key])
            touched.append(key)

    # notes-vectors keeps its cases in a dict keyed by name, not a list.
    if 'cases' in doc and isinstance(doc['cases'], dict):
        doc['cases'] = _rw_notes_cases(doc['cases'])
        touched.append('cases')

    if 'convert' in doc and isinstance(doc['convert'], list):
        doc['convert'] = _rw_convert(doc['convert'])
        touched.append('convert')

    # A print stream carrying form feeds, with its own per-format expectations.
    ff = doc.get('formfeed_printstream')
    if isinstance(ff, dict) and 'input_hex' in ff and isinstance(ff.get('emit'), list):
        stream = core.parse(bytes.fromhex(ff['input_hex']))
        ff['emit'] = [dict(e, expected=EMITTERS[e['format']](stream, mode=e['mode']))
                      for e in ff['emit'] if e['format'] in EMITTERS]
        touched.append('formfeed_printstream')

    # Sentinel byte values are documentation inside the vector file itself; they
    # must track the implementation or the file contradicts its own data.
    if 'sentinels' in doc:
        doc['sentinels'].update({
            'SENT_FNREF': f'0x{core.SENT_FNREF:02x}',
            'SENT_SOFTPAGE': f'0x{core.SENT_SOFTPAGE:02x}',
        })
        touched.append('sentinels')

    # A print stream's own geometry, which the printstream page-model change moved.
    if 'printstream' in doc and isinstance(doc['printstream'], dict):
        stream = core.parse_printstream(b'x\r\n')
        for field, fn in (('printed_cap', pdf._printed_cap),
                          ('printed_top', pdf._printed_top),
                          ('printed_lead', pdf._printed_lead),
                          ('printed_size', pdf._printed_size),
                          ('printed_left', lambda d: pdf._printed_left(d, pdf._printed_size(d)))):
            if field in doc['printstream']:
                doc['printstream'][field] = fn(stream)
        touched.append('printstream')

    updated = json.dumps(doc, indent=1) + '\n'
    return original != updated, updated, touched


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 2
    tests_dir = argv[0]
    check_only = '--check' in argv[1:]

    files = []
    for sub in ('Resources', 'Fixtures'):
        d = os.path.join(tests_dir, sub)
        if os.path.isdir(d):
            files += [os.path.join(d, f) for f in sorted(os.listdir(d))
                      if f.endswith('.json')]
    if not files:
        print(f'no vector files under {tests_dir}', file=sys.stderr)
        return 2

    changed_any = False
    for path in files:
        changed, updated, touched = _rewrite_file(path)
        name = os.path.basename(path)
        if not touched:
            print(f'  {name:<34} no regenerable section -- left alone')
            continue
        if changed:
            changed_any = True
            if not check_only:
                with open(path, 'w') as fh:
                    fh.write(updated)
            verb = 'WOULD CHANGE' if check_only else 'regenerated'
            print(f'  {name:<34} {verb}: {", ".join(touched)}')
        else:
            print(f'  {name:<34} unchanged ({len(touched)} section(s))')

    print()
    print('Inputs were not touched. `git diff` on the vector files is the audit:')
    print('every changed expectation must be explainable by a specific commit.')
    return 1 if (check_only and changed_any) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
