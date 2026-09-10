"""Document inspection — the library home of `--diagnose` (task #17).

Moved out of the CLI (ruled 2026-08-06) because the report is not a
command-line nicety: it feeds Soft Return.app's Document Info window (⌘I),
the batch window's Get-Info panel, and error alerts that point at the
Inspector — none of which link the CLI target. The CLI's `--diagnose`
flag is now a thin wrapper that json.dumps this dict.

Everything here is derived from one parse; the dict is JSON-safe by
construction (the same discipline as layout.py's contract).
"""

import os

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
        # round 17b (RULINGS-LEDGER row 6/7's DIAG column): every flag-
        # governed or ruled-in item from this round, surfaced regardless of
        # whether the CALLER'S own flags happen to be on -- the standing
        # discoverability rule (register, "Flag UI + defaults" entry):
        # "everything these flags govern surfaces in Info/Diagnose
        # regardless of flag state... so a user can see 'there's a TOC
        # here, I should turn it on.'" `doc.meta['formatting']` already
        # carries `.pr`/`.sr`/`.ul`/`.sb`/`.ps` (`orientation`/
        # `sub_super_roll_48`/`underline_blanks`/`suppress_blanks`/
        # `proportional`) with no exclusion -- this is the FIRST time any
        # of it reaches the actual `--diagnose` surface (the internal
        # Document object always carried it; `document_info()` itself
        # never read the dict before this round).
        if doc.meta.get('formatting'):
            info['formatting'] = doc.meta['formatting']
        # `.ps` (register row 6): round 9's NLQ ruling made the font
        # block's own `proportional` bit decisive for any run a font block
        # actually covers -- `.ps` never overrides that, and still doesn't.
        # Planning #252 (Jon's ruling 2026-09-09) gave it exactly one job
        # beyond that: for a run NO font block covers, in a document that
        # declares fonts somewhere, `.ps off` is now the document's own
        # word for "non-proportional" -- Modern's uncovered-run fallback
        # reads Courier instead of Times (pdf.py's `_modern_tok_font`,
        # emit.py's RTF/HTML equivalents). `.ps on` (or never set) leaves
        # the fallback at Times, unchanged. Surfaced regardless of whether
        # this call's own render actually exercises the fallback (the
        # standing discoverability rule) -- a caller can see the document
        # made this declaration even from a Printed-only run.
        if 'proportional' in (doc.meta.get('formatting') or {}):
            prop = doc.meta['formatting']['proportional']
            info['ps_note'] = (
                '.ps off (non-proportional) is present -- Modern gives an '
                'uncovered run (no font block of its own) Courier instead '
                'of Times, when the document declares fonts elsewhere '
                '(planning #252); a run a font block DOES cover still goes '
                'by that block\'s own declared pitch (round 9)'
                if prop is False else
                '.ps on (proportional) is present -- no effect: Modern\'s '
                'uncovered-run fallback is already Times')
        # headers/footers/page numbers (ledger row 1): DECLARED content,
        # regardless of whether this call's own --headers flag would
        # render them.
        if getattr(doc, 'headers', None):
            info['headers'] = dict(doc.headers)
        if getattr(doc, 'footers', None):
            info['footers'] = dict(doc.footers)
        # `.l#` (ledger row 5/6, register C11): the interval, or absent
        # entirely when the file never set it -- matches `producer`'s own
        # "only report what's really there" shape.
        if doc.meta.get('line_numbering') is not None:
            info['line_numbering'] = doc.meta['line_numbering']
        # `.psa`/`.psb` (ledger row 7, register): WordTsar's own inventions,
        # tagged as such explicitly here (not just via the document-wide
        # `producer` field above) so a caller reading vertical-spacing
        # data alone still sees the provenance without cross-referencing.
        sb_lines = doc.meta.get('space_before_lines')
        sa_lines = doc.meta.get('space_after_lines')
        if sb_lines is not None or sa_lines is not None:
            info['vertical_spacing'] = {
                'space_before_lines': sb_lines,
                'space_after_lines': sa_lines,
                'origin': 'wordtsar',   # never a real WordStar 4/5/7 command
            }
        # `.pm` (ledger row 5/7): a per-BLOCK field, aggregated to a count
        # here -- diagnose reports document-shape facts, not a per-block
        # dump (matching `paragraphs`'s own aggregate shape above).
        pm_blocks = sum(1 for b in doc.blocks if b.para_margin is not None)
        if pm_blocks:
            info['pm_blocks'] = pm_blocks
        # round 18 (RULINGS-LEDGER row 4/10 DIAG): the standing
        # discoverability rule again -- "someone can say: there's a TOC
        # here, I should turn it on." Counts, not the entries themselves
        # (matching `notes`'/`pm_blocks`'s own aggregate shape): a
        # document-shape fact, not a content dump.
        if doc.toc_entries or doc.index_entries:
            info['toc_index'] = {
                'toc_entries': len(doc.toc_entries),
                'index_entries': len(doc.index_entries),
            }
        # inline colour (symmetric type 1) / size (a genuinely INLINE
        # type-2 font block, `offset is not None` -- a style-declared
        # font is document formatting, not authored inline styling, and
        # is not counted here, matching round 18's own --inline-styling
        # scope exactly).
        colour_spans = sum(
            1 for b in doc.blocks for line in b.lines for sp in line.spans
            for st in sp.styles if st.startswith('colour') and st[6:].isdigit())
        size_spans = sum(
            1 for b in doc.blocks for line in b.lines for sp in line.spans
            for st in sp.styles if st.startswith('font') and st[4:].isdigit()
            and int(st[4:]) < len(doc.fonts)
            and doc.fonts[int(st[4:])].get('offset') is not None)
        if colour_spans or size_spans:
            info['inline_styling'] = {
                'colour_spans': colour_spans,
                'size_spans': size_spans,
            }
        # Round 19 (PIX images RULED IN, ledger PIX row): pix tags,
        # resolved-or-not, regardless of the caller's own --pictures value
        # -- the standing discoverability rule again ("someone can say:
        # there's a picture here, I should turn it on"). Resolution needs
        # a real filesystem location to search near, same condition `path`
        # already gates elsewhere in this function; without one every tag
        # reports unresolved (ctrlkd.pictures' own documented behavior for
        # a doc_path of None), which is still useful ("this file HAS pix
        # tags") even when nothing can be located from bytes alone.
        if doc.graphics:
            from . import pictures as _pictures
            results = _pictures.resolve_document_pictures(doc, path)
            doc_dir = os.path.dirname(os.path.abspath(path)) if path else None
            entries = []
            for r in results:
                name = r.raw_path.replace('\\', '/').rsplit('/', 1)[-1] or r.raw_path
                entry = {'tag': name, 'resolved': r.ok}
                if r.ok:
                    rel = r.resolved_path
                    if doc_dir:
                        try:
                            rel = os.path.relpath(r.resolved_path, doc_dir)
                        except ValueError:
                            pass          # different drive/root -- keep absolute
                    entry['path'] = rel
                    entry['width'] = r.gcols
                    entry['height'] = r.grows
                else:
                    entry['error'] = r.error
                entries.append(entry)
            info['pix'] = entries
    elif det['variant'] == 'printstream':
        doc = core.parse(data)
        # damage WordStar itself introduced at print time (comments + the
        # ASCII/ASC256/PRVIEW/WS4 drivers truncated the rest of the line);
        # reported so it reads as a 1990s defect, not our parse failing
        if doc.meta.get('comment_bug'):
            info['comment_bug'] = doc.meta['comment_bug']
    return info
