"""ctrlkd.piximg -- resolve a WordStar pix tag (symmetric type 0x10, a DOS
filename payload) to a real .PIX file sitting somewhere near the document
that references it.

RULED (Jon, 2026-08-17/18 -- WordStar-Feature-Decision-Register.md, "PIX
images RULED IN"). The tags carry ABSOLUTE DOS PATHS (e.g.
``C:\\WS\\INSET\\PIX\\WORDSTAR.PIX``), captured from whatever machine authored
the document decades ago -- the drive and the leading directories are
meaningless on the machine doing the conversion today, but the *tail* of
that path is real evidence of where the image sat relative to the document,
one to a few directory levels up. Swept across the one real corpus (5
documents, all referencing C:\\WS\\INSET\\PIX\\WORDSTAR.PIX): root-level
documents hit ``INSET/PIX/`` one hop from their own directory; documents
nested under ``APP/`` need two-to-three hops up. Resolution order, in
full:

  1. Parse the DOS path into components (drive letter dropped). Build its
     TAIL SUFFIXES -- the full component list, then with the first
     component dropped, then the first two dropped, ... down to just the
     bare filename. Try each suffix, LONGEST first (most specific -- most
     of the recorded path corroborated), against the document's own
     directory, then each ancestor directory in turn (nearest first).
  2. If nothing matched, fall back to basename probing: the bare filename
     alone in the SAME probe order of locations -- same-dir, then
     ``INSET/PIX/``, ``INSET/`` (Jon, 2026-08-18, explicit -- real Inset
     installs keep the library flat there too), then the logical modern
     conventions ``media/``, ``attachments/``, ``images/`` -- each tried
     relative to the document's own directory, then each ancestor in turn.

Matching is CASE-INSENSITIVE throughout (DOS heritage: 8.3 names, no case
distinction ever existed in the source data) even though the filesystems
this runs on today are typically case-sensitive.

Degradation: this module only LOCATES a file; it makes no claim about
whether that file's bytes are the SAME image the original DOS machine
resolved. A missing file is reported by returning None -- callers are
expected to surface that as a diagnose-visible fact and render nothing
better than a placeholder, never raise (RULED 2026-08-17: "proper error
handling for missing/unreadable image files is required (report, never
fail the conversion)").
"""
from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = ['resolve_pix', 'probe_candidates']

# Fixed probe locations tried (each relative to the document's own
# directory, then each ancestor) once the DOS-path tail-suffix walk turns
# up nothing. Order matters: same-dir first (the documented default
# assumption), then the two Inset-native conventions, then the three
# modern ones. An empty tuple means "the probe directory itself" (i.e.
# same-dir).
_BASENAME_PROBES = (
    (),
    ('INSET', 'PIX'),
    ('INSET',),
    ('media',),
    ('attachments',),
    ('images',),
)


def _parse_dos_path(payload) -> list[str]:
    """A pix tag's raw payload -> path components, drive letter and any
    trailing NUL padding dropped. Accepts bytes (as stored in the
    document -- cp437, WordStar's native encoding) or str."""
    if isinstance(payload, (bytes, bytearray)):
        text = bytes(payload).split(b'\x00', 1)[0].decode('cp437', errors='replace')
    else:
        text = str(payload).split('\x00', 1)[0]
    text = text.strip()
    if len(text) >= 2 and text[1] == ':':
        text = text[2:]                    # drop "C:" -- meaningless here
    return [p for p in re.split(r'[\\/]+', text) if p]


def _tail_suffixes(parts: list[str]) -> list[list[str]]:
    """[a, b, c] -> [[a,b,c], [b,c], [c]] -- longest (most specific) first."""
    return [parts[i:] for i in range(len(parts))]


def _ancestors(start: Path, max_up: int) -> list[Path]:
    """`start` itself, then each parent, nearest first, up to `max_up`
    levels or the filesystem root, whichever comes first."""
    out = [start]
    cur = start
    for _ in range(max_up):
        parent = cur.parent
        if parent == cur:
            break
        out.append(parent)
        cur = parent
    return out


def _ci_resolve(base: Path, components: list[str]) -> Path | None:
    """Walk `components` under `base`, matching each one case-
    insensitively against the real directory listing (the filesystem
    underneath may be case-sensitive even though the recorded path
    never distinguished case). Returns the real, correctly-cased Path
    if every component was found and the result is a file; None
    otherwise -- never raises on a missing/unreadable directory."""
    cur = base
    for comp in components:
        try:
            if not cur.is_dir():
                return None
            entries = os.listdir(cur)
        except OSError:
            return None
        target = comp.lower()
        match = next((e for e in entries if e.lower() == target), None)
        if match is None:
            return None
        cur = cur / match
    try:
        return cur if cur.is_file() else None
    except OSError:
        return None


def resolve_pix(tag_payload, doc_path, max_ancestors: int = 8) -> str | None:
    """Resolve a pix tag's payload to a real file path near `doc_path`
    (the WordStar document that referenced it), per the ruled resolution
    order above. Returns the resolved path as a str, or None if no
    candidate exists -- callers report the miss, they don't raise.

    `tag_payload`: the tag's raw filename payload (bytes or str), a DOS
    absolute path such as ``C:\\WS\\INSET\\PIX\\WORDSTAR.PIX``.
    `doc_path`: the WordStar document's own path (file or its directory
    -- either works; a file path's parent is used).
    `max_ancestors`: how many directory levels up from the document to
    search (default 8 -- generous for any real archive shape; the one
    real corpus needs at most 3).
    """
    parts = _parse_dos_path(tag_payload)
    if not parts:
        return None

    doc_path = Path(doc_path)
    doc_dir = doc_path if doc_path.is_dir() else doc_path.parent
    ancestors = _ancestors(doc_dir, max_ancestors)

    # Step 1: tail suffixes of the parsed DOS path, longest first, tried
    # at each ancestor (nearest first).
    suffixes = _tail_suffixes(parts)
    for anc in ancestors:
        for suf in suffixes:
            hit = _ci_resolve(anc, suf)
            if hit is not None:
                return str(hit)

    # Step 2: basename-only probing across the fixed convention list.
    basename = parts[-1]
    for anc in ancestors:
        for probe in _BASENAME_PROBES:
            hit = _ci_resolve(anc, list(probe) + [basename])
            if hit is not None:
                return str(hit)

    return None


def probe_candidates(tag_payload, doc_path, max_ancestors: int = 8) -> list[str]:
    """Round 19: reconstruct, in the SAME order resolve_pix tries them, the
    full candidate paths a miss was checked against -- for diagnostics only
    (a failed resolve_pix already walked these; this just re-describes them
    without touching the filesystem again, so it is safe to call even after
    a resolve_pix(...) is None). Callers (the CLI's stderr report, ruled
    2026-08-17: "proper error handling for missing/unreadable image files
    is required") use this to say WHERE it looked, not just that it failed.

    Returns [] if the payload parses to nothing (resolve_pix would have
    returned None immediately too, before ever touching the filesystem)."""
    parts = _parse_dos_path(tag_payload)
    if not parts:
        return []

    doc_path = Path(doc_path)
    doc_dir = doc_path if doc_path.is_dir() else doc_path.parent
    ancestors = _ancestors(doc_dir, max_ancestors)

    out = []
    for anc in ancestors:
        for suf in _tail_suffixes(parts):
            out.append(str(anc.joinpath(*suf)))
    basename = parts[-1]
    for anc in ancestors:
        for probe in _BASENAME_PROBES:
            out.append(str(anc.joinpath(*probe, basename)))
    return out
