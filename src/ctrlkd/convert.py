"""ctrl-kd conversion API: parse + emit in one call, plus the shared note-kind
inclusion filter that both `convert()` and each emitter (see emit.py) apply.

WordStar 5+/7 notes come in four kinds (see core.Note): footnote, endnote,
annotation, comment. WordStar itself only ever PRINTED the first three --
comments are an author-only aside, never rendered by WordStar at all (spec-
documented). Text/Markdown/HTML/RTF have no notion of "don't print this" the
way WordStar did, so that behavior has to be modeled explicitly here instead
of falling out of the parse for free.
"""
from .core import parse
from .emit import get_emitter, DEFAULT_NOTE_KINDS, ALL_NOTE_KINDS, select_notes

__all__ = ['convert', 'select_notes', 'DEFAULT_NOTE_KINDS', 'ALL_NOTE_KINDS']


def convert(data: bytes, to: str = 'markdown', mode: str = 'modern',
            encoding: str = 'cp437', notes=DEFAULT_NOTE_KINDS, **options) -> str:
    """One-call API: bytes in, converted string out.

    `notes` selects which note kinds appear in the output: any iterable of
    'footnote' / 'endnote' / 'annotation' / 'comment' (the strings match
    Note.kind exactly). Default is DEFAULT_NOTE_KINDS -- footnotes, endnotes,
    annotations, matching what WordStar itself would have printed. Comments
    are excluded by default; pass a set that includes 'comment' (or the
    ALL_NOTE_KINDS constant) to surface them -- e.g. a rescue tool run on
    request to recover hidden author asides. Unrecognised kind strings are
    silently ignored rather than raising, so a caller (CLI flag, a Swift/
    macOS picker's checkbox state) can pass a fixed set without first
    validating spelling against this library's kind names.

    This is forwarded to the emitter as the same `notes=` keyword an emitter
    accepts when called directly (bypassing convert()); third-party emitters
    that don't know about it simply ignore it via **options, per the
    EXTENDING.md contract.
    """
    return get_emitter(to)['fn'](parse(data, encoding=encoding), mode, notes=notes, **options)
