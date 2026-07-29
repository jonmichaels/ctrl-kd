"""ctrl-kd — convert WordStar-era files to modern formats. ^KD: save and done."""
from .core import detect, parse, parse_ws, parse_printstream, Document, Block, Line, Span
from .emit import (emit_text, emit_markdown, emit_html, emit_rtf,
                   emitter, get_emitter, formats, load_plugins)

__version__ = '1.0.0'

def convert(data: bytes, to: str = 'markdown', mode: str = 'modern',
            encoding: str = 'cp437', **options) -> str:
    """One-call API: bytes in, converted string out."""
    return get_emitter(to)['fn'](parse(data, encoding=encoding), mode, **options)
