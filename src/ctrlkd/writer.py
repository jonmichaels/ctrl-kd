"""ctrl-kd writer: serialize a Document back to native WordStar bytes.

Tasks #20/#21 (ruled 2026-08-06): `emit_ws(parse(x)) == x`, byte for byte,
for as much of the corpus as achievable -- with the shortfall measured
honestly (tools/roundtrip_census.py) rather than papered over.

THE CONTRACT
------------
The body is serialized FROM THE IR -- spans, style sets, physical lines --
so an editor that mutates the IR and saves gets its mutations. What comes
from doc.roundtrip (the raw-source ledger parse_ws now carries) is only
what the IR proper cannot express without faking:

  * dot-command lines, byte-exact (the IR stores them bit-7-masked and
    rstripped; mailmerge lines must NEVER be re-serialized from an
    interpretation -- permanent ruling);
  * every consumed 0x1D symmetric sequence, spliced back verbatim at the
    cleaned-stream offset where its expansion sits (a font block, a note,
    a tab -- an editor treats these as opaque objects);
  * the raw separator bytes per line (<8D 8A> and friends);
  * the trailing-blank run lines_pass drops at EOF, and the file tail from
    the bare 0x1A onward (^Z padding, the WS5+ style library).

  * per-line byte restorations (Line.fixups) and trailing toggle runs
    (Line.tog_end) for the decode's known lossy spots -- masked WS4 flag
    bits, collapsed 0x0F/0x1F/0xA0, dropped controls, ^D-vs-^B, bare
    extended bytes, Symbol/Dingbats transliteration. Each is GUARDED: it
    patches only where the re-encode matches what the parse predicted, so
    an edited line keeps its clean re-encode instead of being corrupted.

A Document built without parse_ws (no ledger) still writes: breaks are
inferred from the flags and defaults stand in for the rest.

MEASURED RESULT (census of 2026-08-06, tools/roundtrip_census.py): all 83
.WS documents in the Sawyer archive round-trip byte-identical. What still
cannot (the census tail): binaries detect() misreads as documents, an
invisible line whose only content is toggles when its softness folded into
the previous line, and losses in the non-final parts of a form-feed-split
physical line.
"""
from __future__ import annotations

from .core import (CP437_GRAPHICS, Document, WS_TOGGLES, _bare_eof,
                   _rt_untranslit)
from .symbolmap import font_translit_kind

# Style tag -> the toggle byte that turns it on AND off. Built from core's
# own WS_TOGGLES, minus the ^D doublestrike alias (0x04 also maps to 'b';
# re-emitting bold as ^B is the one honest choice the collapsed IR allows).
_TOGGLE_FOR = {}
for _b, _tag in sorted(WS_TOGGLES.items()):
    _TOGGLE_FOR.setdefault(_tag, _b)
_TOGGLABLE = frozenset(_TOGGLE_FOR) | {'altfont'}

# Unicode -> cp437 byte, for everything above ASCII. Two producers, exactly
# mirroring _decode_spans: the cp437 high half (0x80-0xFF), and the IBM
# GRAPHICS glyphs at control positions -- minus 0x00, whose glyph is ' '
# (a space is a space; a wrapped NUL cannot win that collision).
_CP437_HIGH = {bytes([b]).decode('cp437'): b for b in range(0x80, 0x100)}
_GRAPHICS_REV = {ch: b for b, ch in CP437_GRAPHICS.items() if b != 0x00}


class WriteError(ValueError):
    """A Document this writer cannot faithfully serialize (e.g. a Shift-JIS
    document, whose parse rewrote the stream in a way no recorded offset
    survives). Refusal over corruption, with the reason attached."""


def _encode_text(text: str, ws5: bool, out: bytearray):
    """One span's text back to WordStar bytes. WS5+ wraps anything outside
    plain ASCII in the <1B x 1C> extended-character escape (that is how
    real extended characters travel -- bare high bytes are soft/flag
    forms); WS4 has no escape machinery, so a high character goes out as
    its bare cp437 byte."""
    for ch in text:
        o = ord(ch)
        if ch == '\t' or 0x20 <= o < 0x7F:
            out.append(o)
            continue
        b = _CP437_HIGH.get(ch)
        if b is None:
            b = _GRAPHICS_REV.get(ch)
        if b is None:
            out.append(0x3F)                       # '?' -- unencodable
        elif ws5:
            out += bytes((0x1B, b, 0x1C))
        else:
            out.append(b)


def _emit_spans(spans, active: set, ws5: bool, out: bytearray, fonts=()):
    """Spans -> bytes, emitting toggle bytes where the style set changes.
    `active` persists across lines, exactly as it did at parse. Synthetic
    spans (note references, dot-comment marks) carry 'fnref' and own no
    source bytes: the note's bytes are its 0x1D block (spliced back from
    the ledger) or its dot line -- skip them entirely."""
    for span in spans:
        if 'fnref' in span.styles:
            continue
        want = {t for t in span.styles if t in _TOGGLABLE}
        for tag in sorted(active - want,
                          key=lambda t: _TOGGLE_FOR.get(t, 0x0E)):
            out.append(0x0E if tag == 'altfont' else _TOGGLE_FOR[tag])
        for tag in sorted(want - active,
                          key=lambda t: _TOGGLE_FOR.get(t, 0x01)):
            out.append(0x01 if tag == 'altfont' else _TOGGLE_FOR[tag])
        active.clear()
        active |= want
        text = span.text
        # A Symbol/ZapfDingbats run was transliterated to real Unicode at
        # decode (symbolmap); the file's own bytes are the FONT's glyph
        # codes, so send the text back through the inverse before encoding.
        fidx = next((int(t[4:]) for t in span.styles
                     if t.startswith('font') and t[4:].isdigit()), None)
        if fidx is not None and fidx < len(fonts):
            kind = font_translit_kind(fonts[fidx])
            if kind:
                # core._rt_untranslit: the forward map's inverse with its
                # passthrough rule intact -- shared with the fixup capture,
                # which predicts this exact emission
                text = _rt_untranslit(text, kind)
        _encode_text(text, ws5, out)


def _infer_break(line) -> bytes:
    """Separator bytes for a Line with no recorded ones (a synthetic
    Document): WordStar's canonical forms, from the flags."""
    if line.overprint:
        return b'\x0d'                             # bare CR: ^PM overprint
    if line.soft:
        return b'\x8d\x0a'                         # soft return
    return b'\x0d\x0a'                             # the author's Return


def _apply_fixups(body: bytearray, start: int, fixups):
    """Patch one line's emission back to its source bytes. Each fixup says:
    at line offset p (SOURCE byte space) the writer emitted `expected`;
    the file had `original`. Guarded: the first mismatch stops patching for
    the line -- an edited line simply keeps its clean re-encode (the flags/
    controls belonged to bytes that no longer exist), never gets corrupted."""
    unpatched = bytes(body[start:])
    out = bytearray()
    u = 0
    for p, exp, orig in fixups:
        copy = p - len(out)
        if copy < 0 or u + copy > len(unpatched):
            break
        out += unpatched[u:u + copy]
        u += copy
        if unpatched[u:u + len(exp)] != exp:
            break
        out += orig
        u += len(exp)
    out += unpatched[u:]
    body[start:] = out


def emit_ws(doc: Document) -> bytes:
    """Serialize `doc` to native WordStar bytes.

    Raises WriteError for documents the writer cannot faithfully write:
    non-WordStar variants (a printstream is printer output, not a
    document -- there is nothing to write back to), and Shift-JIS
    documents (see doc.roundtrip['unsupported'])."""
    rt = getattr(doc, 'roundtrip', None) or {}
    era = rt.get('era') or doc.meta.get('era') or doc.meta.get('variant')
    if era not in ('ws4', 'ws3', 'ws5+'):
        raise WriteError(f'not a WordStar document (era: {era}) -- '
                         'only ws4/ws5+ documents serialize back to .WS')
    if rt.get('unsupported'):
        raise WriteError(f"cannot faithfully serialize: {rt['unsupported']} "
                         '(the parse rewrote the stream; offsets are '
                         'unreplayable)')
    ws5 = era == 'ws5+'
    from_parse = bool(rt)

    # Dot lines by event anchor: "emit before event N", N counting Lines and
    # form-feed pagebreaks in order (the same counter parse_ws stamped).
    dots = {}
    for anchor, raw, brk in rt.get('dots', ()):
        dots.setdefault(anchor, []).append(bytes(raw) + bytes(brk))

    body = bytearray()
    active = set()
    event = 0

    def flush_dots():
        for piece in dots.get(event, ()):
            body.extend(piece)

    for block in doc.blocks:
        if block.origin == 'fi':
            continue                     # fabricated `[insert:]` placeholder:
                                          # its bytes are the .fi dot line
        if block.kind == 'pagebreak':
            if block.origin == 'ff':
                flush_dots()
                body += b'\x0c'
                event += 1
            continue                     # `.pa` bytes are its dot line
        if block.kind == 'condpage':
            continue                     # `.cp` likewise
        for line in block.lines:
            flush_dots()
            start = len(body)
            _emit_spans(line.spans, active, ws5, body, doc.fonts)
            if line.fixups:
                _apply_fixups(body, start, line.fixups)
            if line.tog_end:
                # trailing toggles, verbatim (flag bits included) -- and the
                # writer's own style state must flip with them, or the next
                # line's span diff would emit each toggle a second time
                body += line.tog_end
                for tb in line.tog_end:
                    mb = tb & 0x7F
                    if mb == 0x01:
                        active.add('altfont')
                    elif mb == 0x0E:
                        active.discard('altfont')
                    else:
                        tag = WS_TOGGLES.get(mb)
                        if tag is not None:
                            (active.remove if tag in active
                             else active.add)(tag)
            brk = line.brk_raw
            if brk is None:
                # No recorded separator. From parse this happens in exactly
                # two shapes, and both correctly emit nothing here: a line
                # cut short by a literal form feed (the 0x0C is the next
                # block's byte), and the visible half of a whitespace-only
                # physical line, whose separator rides on the phantom blank
                # Line parse_ws appends right after it. A synthetic Document
                # infers canonical separators instead.
                brk = b'' if from_parse else _infer_break(line)
            body += brk
            event += 1
    flush_dots()                          # dot lines after the last event
    body += bytes(rt.get('eof_tail', b''))

    if ws5:
        # Un-translate the flagged control bytes (length-preserving, so the
        # recorded cleaned-stream offsets hold on the reconstruction)...
        for off, orig in rt.get('flagged_at', ()):
            if off < len(body):
                body[off] = orig
        # ...then splice every consumed symmetric sequence back over its own
        # expansion, in consumption order. Offsets are trusted, not searched:
        # if the body reconstruction drifted, the census reports the
        # divergence -- silently resynchronising would hide it.
        sym = rt.get('sym', ())
        if sym:
            spliced = bytearray()
            pos = 0
            for off, exp, raw in sym:
                if off < pos or off > len(body):
                    continue             # unreplayable entry; census will say
                spliced += body[pos:off]
                spliced += raw
                pos = off + max(exp, 0)
            spliced += body[pos:]
            body = spliced

    body += bytes(rt.get('tail', b''))
    if not from_parse and _bare_eof(bytes(body)) == -1:
        body += b'\x1a'                   # a synthetic document still ends
                                           # like a WordStar file
    return bytes(body)
