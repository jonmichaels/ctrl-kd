"""ctrl-kd — convert WordStar-era files to modern formats. ^KD: save and done."""
from .core import detect, parse, parse_ws, parse_printstream, Document
from .emit import emit_text, emit_markdown, emit_html, emit_rtf

__version__ = '0.1.0'

def convert(data: bytes, to: str = 'markdown', mode: str = 'modern',
            encoding: str = 'cp437') -> str:
    """One-call API: bytes in, converted string out."""
    from .emit import EMITTERS
    return EMITTERS[to](parse(data, encoding=encoding), mode)
