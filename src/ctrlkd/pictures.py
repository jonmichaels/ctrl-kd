"""ctrlkd.pictures -- turn a document's pix tags (doc.graphics, a WS5+ type
0x10 inset-graphic reference recorded per occurrence, one path per
placeholder in document order) into resolved, decoded images an emitter can
embed or export, per the --pictures flag (off / embed / export) and Jon's
ruled degradation rule: a format that can't honor the requested mode does
what it can and writes ONE stderr note; a missing/unreadable .PIX is
reported (tag name + probed locations) and NEVER fails the conversion --
the existing "[image: NAME]" placeholder (core.py, unchanged text) stays
exactly what it already was.

RULED (Register, "PIX images RULED IN" / "Flag UI + defaults RULED",
2026-08-17/18). Library convention (matching cli.py's own D5-notice
pattern): this module and every emit_* function stay SILENT -- only the
CLI (or a library caller that wants the same behavior) writes to stderr,
via report_misses() below.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import pix as pixdecode
from . import piximg

__all__ = ['PixResult', 'resolve_document_pictures', 'report_misses',
           'write_export_images']


@dataclass
class PixResult:
    """One doc.graphics entry, resolved and (if found) decoded.

    `error` is None on success, else one of:
      'unresolved'    -- no candidate file found near the document (or no
                          doc_path was given to search from at all)
      'unreadable'    -- resolve_pix found a path but it could not be read
      'text-mode'     -- a real .PIX file, but an alphanumeric-capture
                          variant this decoder does not implement
      'format-error'  -- a real file, but malformed or an unsupported shape

    `raw_bytes` (the original .PIX file's bytes) is kept, not just `png`,
    so a caller needing raw pixels (PDF's own Image XObject, built from
    pix.decode()'s RGB rows rather than parsing PNG back out) can decode
    once more without re-resolving or re-reading the file.
    """
    index: int
    raw_path: str
    resolved_path: str | None = None
    error: str | None = None
    raw_bytes: bytes | None = None
    png: bytes | None = None
    gcols: int | None = None
    grows: int | None = None
    width_in: float | None = None    # from the print-options record only;
    height_in: float | None = None   # None means "caller picks a fallback"

    @property
    def ok(self) -> bool:
        return self.png is not None


def resolve_document_pictures(doc, doc_path) -> list:
    """One PixResult per doc.graphics entry, in order. `doc_path` is the
    WordStar document's OWN path on disk -- resolution searches near it
    (piximg.resolve_pix's ancestor walk). None/falsy means no location to
    search from (e.g. a library caller holding only bytes in memory):
    every tag reports 'unresolved', exactly like a genuinely missing file
    -- this function never raises either way.

    Decoding happens ONCE per document here regardless of how many output
    formats get requested from the same doc -- call this once, pass the
    result list to every emit_* call for that document."""
    results = []
    for idx, raw_path in enumerate(doc.graphics):
        r = PixResult(index=idx, raw_path=raw_path)
        if not doc_path:
            r.error = 'unresolved'
            results.append(r)
            continue
        resolved = piximg.resolve_pix(raw_path, doc_path)
        if resolved is None:
            r.error = 'unresolved'
            results.append(r)
            continue
        r.resolved_path = resolved
        try:
            with open(resolved, 'rb') as f:
                data = f.read()
        except OSError:
            r.error = 'unreadable'
            results.append(r)
            continue
        r.raw_bytes = data
        try:
            gcols, grows, _rows = pixdecode.decode(data)
            png = pixdecode.to_png(data)
        except pixdecode.PixTextModeUnsupported:
            r.error = 'text-mode'
            results.append(r)
            continue
        except pixdecode.PixFormatError:
            r.error = 'format-error'
            results.append(r)
            continue
        r.gcols, r.grows, r.png = gcols, grows, png
        size = pixdecode.physical_size_in(data)
        if size:
            r.width_in, r.height_in = size
        results.append(r)
    return results


def _basename(raw_path: str) -> str:
    return raw_path.replace('\\', '/').rsplit('/', 1)[-1] or raw_path


def report_misses(results, path_label, doc_path, max_ancestors: int = 8,
                  file=None) -> None:
    """One stderr line per unresolved/undecodable tag: "report, never
    fail" (ruled 2026-08-17). Not called automatically by anything in this
    module -- the CLI calls it once per document after
    resolve_document_pictures; a library caller that wants the same
    behavior calls it itself."""
    import sys
    out = file if file is not None else sys.stderr
    for r in results:
        if r.error is None:
            continue
        name = _basename(r.raw_path)
        if r.error in ('unresolved', 'unreadable'):
            if doc_path:
                probed = piximg.probe_candidates(r.raw_path, doc_path, max_ancestors)
                shown = probed[:20]
                more = f' (+{len(probed) - 20} more location(s))' if len(probed) > 20 else ''
                where = ('; probed: ' + ', '.join(shown) + more) if shown else ''
            else:
                where = ' (no document path given to search near)'
            reason = 'not found' if r.error == 'unresolved' else 'found but not readable'
            print(f"ctrl-kd: {path_label}: PIX image '{name}' {reason}"
                  f"{where} -- placeholder kept", file=out)
        elif r.error == 'text-mode':
            print(f"ctrl-kd: {path_label}: PIX image '{name}' is a text-mode "
                  f"(alphanumeric) capture -- not previewable in WordStar "
                  f"either, decoding not implemented -- placeholder kept",
                  file=out)
        elif r.error == 'format-error':
            print(f"ctrl-kd: {path_label}: PIX image '{name}' could not be "
                  f"decoded (malformed or an unsupported .PIX shape) -- "
                  f"placeholder kept", file=out)


def write_export_images(results, images_dir: str) -> dict:
    """Write every successfully-decoded image as a PNG file under
    `images_dir` (created if needed), named from the tag's own basename
    (deduplicated when two tags share one). Returns {index: filename}
    (bare filename, not a path -- callers join it under whatever relative
    prefix their own output uses, e.g. f'{docname}-images/{filename}').

    Used for --pictures export (every applicable format), AND for MD's
    embed mode (ruled degradation: MD has no true embed, so "embed" for
    MD means "export files + one stderr note" -- the CLI decides when to
    call this; this function itself doesn't know which mode asked)."""
    written = {}
    ok_results = [r for r in results if r.ok]
    if not ok_results:
        return written
    os.makedirs(images_dir, exist_ok=True)
    used = set()
    for r in ok_results:
        stem = os.path.splitext(_basename(r.raw_path))[0] or f'image{r.index}'
        name = stem + '.png'
        n = 1
        while name in used:
            name = f'{stem}-{n}.png'
            n += 1
        used.add(name)
        with open(os.path.join(images_dir, name), 'wb') as f:
            f.write(r.png)
        written[r.index] = name
    return written
