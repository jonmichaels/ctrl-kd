"""ctrl-kd — convert WordStar-era files to modern formats. ^KD: save and done."""
from .core import (detect, parse, parse_ws, parse_printstream, merged_lines,
                   Document, Block, Line, Span)
from .emit import (emit_text, emit_markdown, emit_html, emit_rtf,
                   emitter, get_emitter, formats, load_plugins)
from .pdf import emit_pdf                        # registers the 'pdf' format
from .convert import convert, select_notes, DEFAULT_NOTE_KINDS, ALL_NOTE_KINDS

__version__ = '4.0.0'
