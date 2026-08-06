"""Document inspection — the library home of `--diagnose` (task #17).

Moved out of the CLI (ruled 2026-08-06) because the report is not a
command-line nicety: it feeds Soft Return.app's Document Info window (⌘I),
the batch window's Get-Info panel, and error alerts that point at the
Inspector — none of which link the CLI target. The CLI's `--diagnose`
flag is now a thin wrapper that json.dumps this dict.

Everything here is derived from one parse; the dict is JSON-safe by
construction (the same discipline as layout.py's contract).
"""

from . import core


def document_info(data, path=None):
    """What IS this file — variant detection, page geometry with
    provenance, note counts by kind, unknown blocks, producer signals,
    print-time damage. `path` is echoed back as 'file' when given (the
    CLI passes it; an app passing bytes may not have one)."""
    det = core.detect(data)
    info = {**det} if path is None else {'file': path, **det}
    if det['variant'] in ('ws4', 'ws5+'):
        doc = core.parse_ws(data)
        info.update({k: doc.meta[k] for k in
                     ('margin_estimate', 'dot_commands', 'unknown_codes',
                      'columnar')})
        info['paragraphs'] = sum(1 for b in doc.blocks if b.kind == 'para')
        # note kinds, counted separately (footnote/endnote/annotation/
        # comment) rather than flattened, so a rescue tool can tell a file
        # has hidden comments even when this run is only converting to
        # plain text -- and since M9 the comment count covers BOTH origins
        # ('block' ^ON notes and '..'/'.ig' dot lines)
        info['notes'] = {kind: sum(1 for n in doc.notes if n.kind == kind)
                         for kind in ('footnote', 'endnote', 'annotation',
                                      'comment')}
        # unrecognised symmetrical-sequence types: preserved, not silently
        # dropped, so the report can say so instead of going quiet
        info['unknown_blocks'] = [
            {'type': f'0x{u.cmd:02x}' if u.cmd >= 0 else 'malformed',
             'offset': u.offset, 'length': len(u.data)}
            for u in doc.unknown_blocks]
        # page geometry from the file's own dot commands, with provenance --
        # a caller must be able to say "Legal (from file)" vs
        # "Letter (default)"
        info['page'] = doc.meta.get('page')
        # .PT/.PSA/.PSB are WordTsar's inventions, not WordStar commands:
        # their presence identifies who WROTE the file, not how it is
        # encoded
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
