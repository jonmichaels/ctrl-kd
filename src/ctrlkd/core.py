"""ctrl-kd core: detection, parsing, and the intermediate representation.

Everything parses into one IR (a Document of Blocks of Lines of Spans), and every
export format is a small emitter over that IR — the architectural lesson from
wsconvert and WS-CON, which each go bytes->output in a single pass and each lose
something on the way.

WordStar background this code encodes:

* WS4 and earlier set bit 7 on the LAST character of each word ("microjustify"
  flags). WS5+ dropped that; high bytes there are extended (cp437) characters.
* Soft returns (8D 0A) mark where WordStar word-wrapped; hard returns (0D 0A) are
  the author pressing Return. WS4 stores the on-screen layout, so recovering
  intent takes the wrap test (see lines_pass).
* Print-to-disk files are not WordStar documents at all: they are the byte stream
  sent to the printer, captured to a file. They ARE the printed page.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- IR

@dataclass
class Span:
    text: str
    styles: frozenset = frozenset()      # subset of {'b','i','u','sup','sub','strike'}

@dataclass
class Line:
    spans: list = field(default_factory=list)

    def text(self):
        return ''.join(s.text for s in self.spans)

@dataclass
class Block:
    kind: str                            # 'para' | 'pagebreak' | 'softpage'
    lines: list = field(default_factory=list)
    heading: int = 0                     # 0 = body text; 1-3 = WS5+ title/header/subheading

@dataclass
class Document:
    blocks: list = field(default_factory=list)
    footnotes: list = field(default_factory=list)     # list[list[Span]] (WS5+)
    meta: dict = field(default_factory=dict)          # detection + diagnose info

    def iter_lines(self):
        for b in self.blocks:
            yield from b.lines

# ---------------------------------------------------------------- detection

def detect(data: bytes) -> dict:
    """Classify a file by CONTENT (names and extensions lie).

    Returns dict with 'variant': ws4 | ws5+ | printstream | text | binary
    plus the evidence, suitable for --diagnose output.
    """
    core = data[:data.index(0x1A)] if 0x1A in data else data
    if not core:
        return {'variant': 'binary', 'reason': 'empty (or ^Z at start)'}
    soft = core.count(b'\x8d\x0a')
    hard = core.count(b'\x0d\x0a')
    hi = sum(1 for x in core if x >= 0x80)
    blocks_1d = core.count(b'\x1d')
    txt = sum(1 for x in core if 0x20 <= (x & 0x7F) < 0x7F or x in (0x0D, 0x0A, 0x09)) * 100 // len(core)
    ev = {'soft_returns': soft, 'hard_returns': hard, 'high_bit_bytes': hi,
          'text_pct': txt, 'symmetric_blocks_1d': blocks_1d, 'size': len(core)}
    if txt < 40:
        return {'variant': 'binary', 'reason': f'only {txt}% text-like', **ev}
    if blocks_1d >= 2:
        # 1D symmetric blocks are WS5+ machinery regardless of anything else
        return {'variant': 'ws5+', **ev}
    if soft >= 3 or hi >= max(1, len(core) // 20):
        # WS5+ kept soft returns but dropped the bit-7-on-last-letter convention:
        # a wordstar file with many soft returns and near-zero high bits is WS5+,
        # as is one using 1D symmetric blocks (footnotes etc., WS5+ only)
        if blocks_1d >= 2 or (soft >= 3 and hi < soft // 4):
            return {'variant': 'ws5+', **ev}
        return {'variant': 'ws4', **ev}
    if txt >= 90 and hard >= 2:
        return {'variant': 'printstream', **ev}
    if txt >= 90:
        return {'variant': 'text', **ev}
    return {'variant': 'binary', 'reason': f'{txt}% text but no structure', **ev}

# ---------------------------------------------------------------- line engine

def _visible(text: bytes) -> bytes:
    return bytes(b & 0x7F for b in text if 0x20 <= (b & 0x7F) < 0x7F)

def lines_pass(data: bytes):
    """Split into physical lines and classify every break.

    Yields (line_bytes, sep) with sep in {'wrap','line','para','eof'}:
      para  a break run with >=1 hard return and >=2 breaks total (blank line)
      line  a single hard return (the author's Return), or a soft return where
            the next word WOULD have fit — WS4 wrapped only when it didn't fit,
            so breaking early was a choice (poem line, heading). Strict <:
            WS4 wrapped even when the word would land exactly at the margin.
      wrap  a soft return that is just word wrap: join with a space
    Margin is the 90th percentile of soft-wrapped line lengths (outliers from
    hanging punctuation sit 1-2 past the true margin), floor 65 (WS4 default).
    """
    cut = data.find(b'\x1a')
    if cut != -1:
        data = data[:cut]
    parts = re.split(rb'(\x8d\x0a|\x0d\x0a|\x8d|\x0d|\x0a)', data)
    lines = []
    for i in range(0, len(parts), 2):
        text = parts[i]
        brk = parts[i + 1] if i + 1 < len(parts) else b''
        kind = 'eof' if not brk else ('soft' if brk[0] == 0x8D else 'hard')
        if text or kind != 'eof':
            lines.append((text, kind))

    softlens = sorted(len(_visible(t).rstrip()) for t, k in lines
                      if k == 'soft' and _visible(t).strip())
    margin = max(65, softlens[int(len(softlens) * 0.9)] if softlens else 0)

    out = []
    i = 0
    while i < len(lines):
        text, kind = lines[i]
        if not _visible(text).strip():
            i += 1
            continue
        n_hard = 1 if kind == 'hard' else 0
        n_total = 0 if kind == 'eof' else 1
        j = i + 1
        while j < len(lines) and not _visible(lines[j][0]).strip():
            k = lines[j][1]
            if k != 'eof':
                n_total += 1
                n_hard += 1 if k == 'hard' else 0
            j += 1
        if j >= len(lines):
            out.append((text, 'eof'))
            break
        if n_hard >= 1 and n_total >= 2:
            sep = 'para'
        elif n_hard == 1:
            sep = 'line'
        else:
            nxt_vis = _visible(lines[j][0])
            if nxt_vis[:1] == b' ':
                sep = 'line'                      # indented continuation = deliberate
            else:
                L = len(_visible(text).rstrip())
                W = len(nxt_vis.split(b' ', 1)[0])
                sep = 'line' if L + 1 + W < margin else 'wrap'
        out.append((text, sep))
        i = j
    return out, margin

# ---------------------------------------------------------------- WS documents

# WordStar inline control codes (same core set WS4 through WS7)
WS_TOGGLES = {0x02: 'b', 0x13: 'u', 0x19: 'i', 0x14: 'sup', 0x16: 'sub',
              0x18: 'strike', 0x04: 'b'}         # ^D doublestrike -> bold
WS_DROP = {0x01, 0x03, 0x08, 0x0B, 0x0E, 0x10, 0x11, 0x12, 0x15, 0x17, 0x1C}

DOT_PAGEBREAK = {b'PA', b'CP'}

def _decode_spans(raw: bytes, strip_hibit: bool, encoding: str, active: set,
                  unknown: dict, fn_counter: list = None) -> list:
    """One physical line of bytes -> list of Span. `active` persists across lines
    (WordStar styles span line breaks). fn_counter (ws5+ only) numbers the
    footnote-reference sentinels injected by _symmetric_blocks."""
    spans, buf = [], bytearray()

    def flush():
        if buf:
            spans.append(Span(buf.decode(encoding, 'replace'), frozenset(active)))
            buf.clear()

    i = 0
    while i < len(raw):
        # WS4's bit-7-on-last-letter applies to CONTROL TOGGLES too (a word ending
        # at a style boundary yields e.g. 0x94 = ^T|0x80) — so mask BEFORE dispatch,
        # or high-bit toggles leak into text and styles never close.
        b = raw[i] & 0x7F if strip_hibit and raw[i] >= 0x80 else raw[i]
        if b == 0x1B and i + 1 < len(raw):        # extended char escape
            buf.append(raw[i + 1]); i += 2; continue
        if fn_counter is not None and b == SENT_FNREF:
            flush()
            fn_counter[0] += 1
            spans.append(Span(str(fn_counter[0]), frozenset(active | {'sup', 'fnref'})))
        elif b in WS_TOGGLES:
            flush()
            style = WS_TOGGLES[b]
            (active.remove if style in active else active.add)(style)
        elif b == 0x0F:
            buf.append(0x20)                      # binding space
        elif b == 0x1E:
            pass                                  # inactive soft hyphen
        elif b == 0x1F:
            buf.append(0x2D)                      # active soft hyphen
        elif b == 0x09:
            buf.append(b)
        elif b < 0x20 or b == 0x7F:
            if b not in WS_DROP:
                unknown[b] = unknown.get(b, 0) + 1
        else:
            buf.append(b)
        i += 1
    flush()
    return spans

SENT_FNREF = 0x07      # sentinels injected into the cleaned stream; these bytes
SENT_SOFTPAGE = 0x0B   # cannot appear as text in a WS5+ document body
SENT_HEADING = 0x11

def _note_text(block: bytes, encoding: str) -> str:
    """Note content is NESTED: header, then an inner 1D, the text, then a 2-byte
    length + 1D tail (verified on the Sawyer WS7 archive: 'Footnote\\r\\n,\\x00')."""
    inner = block.split(b'\x1d')
    text = inner[1][:-2] if len(inner) > 1 and len(inner[1]) > 2 else block[20:]
    clean = bytes(c for c in text if 0x20 <= c < 0x7F or c >= 0x80 or c == 0x09)
    return clean.decode(encoding, 'replace').strip()

def _symmetric_blocks(data: bytes, encoding: str):
    """Strip WS5+ 1D symmetric sequences (2-byte LE length, command type at +2),
    collecting footnotes/endnotes and injecting sentinels for the block types that
    carry document structure. Verified against the 86 WS7 documents in Robert J.
    Sawyer's WordStar archive."""
    out = bytearray()
    footnotes = []
    i = 0
    while i < len(data):
        if data[i] == 0x1D and i + 3 <= len(data):
            jump = int.from_bytes(data[i + 1:i + 3], 'little')
            block = data[i + 1:i + 3 + jump]
            cmd = block[2] if len(block) > 2 else -1
            if cmd in (0x03, 0x04):                               # foot/endnote
                footnotes.append(_note_text(block, encoding))
                out.append(SENT_FNREF)
            elif cmd == 0x09:                                     # tab
                out += b'    '
            elif cmd == 0x0B:                                     # end of page
                out.append(SENT_SOFTPAGE)
            elif cmd == 0x11 and len(block) > 3:                  # paragraph style
                level = {0x05: 1, 0x02: 2, 0x03: 3}.get(block[3], 0)
                if level:
                    out += bytes([SENT_HEADING, 0x30 + level])
            i += jump + 3
        else:
            out.append(data[i])
            i += 1
    return bytes(out), footnotes

def parse_ws(data: bytes, encoding: str = 'cp437') -> Document:
    doc = Document()
    det = detect(data)
    doc.meta.update(det)
    strip_hibit = det['variant'] == 'ws4'

    ws5 = det['variant'] == 'ws5+'
    if ws5:
        data, notes = _symmetric_blocks(data, encoding)
        doc.footnotes = [[Span(n)] for n in notes]

    physical, margin = lines_pass(data)
    doc.meta['margin_estimate'] = margin

    active, unknown, dots = set(), {}, []
    fn_counter = [0] if ws5 else None
    cur = Block('para')
    cur_line = Line()
    ruler = False

    def close_line():
        nonlocal cur_line
        if cur_line.spans:
            cur.lines.append(cur_line)
        cur_line = Line()

    def close_block():
        nonlocal cur
        close_line()
        if cur.lines:
            doc.blocks.append(cur)
        cur = Block('para')

    for raw, sep in physical:
        stripped = bytes(b & 0x7F for b in raw)
        if stripped[:1] == b'.':                   # dot command line
            cmd = stripped.rstrip()
            dots.append(cmd.decode(encoding, 'replace'))
            if cmd[1:3].upper() in DOT_PAGEBREAK:
                close_block()
                doc.blocks.append(Block('pagebreak'))
            if cmd[1:2].lower() == b'r' and b'!' in cmd:
                ruler = True
            continue
        if ws5:                                    # sentinels from _symmetric_blocks
            if raw.count(SENT_SOFTPAGE):
                close_block()
                doc.blocks.append(Block('softpage'))
                raw = raw.replace(bytes([SENT_SOFTPAGE]), b'')
            if raw[:1] == bytes([SENT_HEADING]) and len(raw) > 1:
                close_block()
                cur.heading = raw[1] - 0x30
                raw = raw[2:]
            raw = raw.replace(bytes([SENT_HEADING]), b'')
        spans = _decode_spans(raw, strip_hibit, encoding, active, unknown, fn_counter)
        for s in spans:
            cur_line.spans.append(s)
        if sep == 'wrap':
            t = cur_line.spans[-1].text if cur_line.spans else ''
            if t and not t.endswith((' ', '-')):
                cur_line.spans.append(Span(' ', cur_line.spans[-1].styles))
        elif sep == 'line':
            close_line()
        else:                                      # para / eof
            close_block()
    close_block()

    doc.meta['dot_commands'] = dots
    doc.meta['unknown_codes'] = {f'0x{k:02x}': v for k, v in sorted(unknown.items())}
    doc.meta['columnar'] = ruler
    return doc

# ---------------------------------------------------------------- print streams

# Empirically derived from a late-80s dot-matrix driver (see README); pass a
# custom table if your printer differed.
PRINT_CODES = {0x18: ('sup', True), 0x12: ('sup', False),
               0x10: ('u', True), 0x11: ('u', False),
               0x13: ('i', True), 0x15: ('i', False),
               0x05: ('i', True), 0x06: ('i', False),
               0x1E: ('b', True), 0x1F: ('b', False)}

def parse_printstream(data: bytes, encoding: str = 'cp437',
                      codes: dict = None) -> Document:
    """A print-to-disk capture IS the printed page: every line verbatim, printer
    style codes decoded, everything else below 0x20 stripped."""
    codes = PRINT_CODES if codes is None else codes
    doc = Document(meta={'variant': 'printstream', 'columnar': True})
    cut = data.find(b'\x1a')
    if cut != -1:
        data = data[:cut]
    active = set()
    cur = Block('para')
    line = Line()
    buf = bytearray()

    def flush():
        if buf:
            line.spans.append(Span(buf.decode(encoding, 'replace'), frozenset(active)))
            buf.clear()

    def endline():
        nonlocal line
        flush()
        cur.lines.append(line)                    # blank lines are page geometry: keep
        line = Line()

    for b in data:
        c = b & 0x7F
        if c in codes:
            flush()
            style, on = codes[c]
            (active.add if on else active.discard)(style)
        elif c == 0x0A:
            endline()
        elif c == 0x0C:
            endline()
            doc.blocks.append(cur)
            doc.blocks.append(Block('pagebreak'))
            cur = Block('para')
        elif c == 0x0D or (c < 0x20 and c != 0x09):
            continue
        else:
            buf.append(c)
    endline()
    doc.blocks.append(cur)
    return doc

# ---------------------------------------------------------------- front door

def parse(data: bytes, encoding: str = 'cp437', variant: str = None) -> Document:
    """Detect (unless told) and parse. This is the library's main entry."""
    v = variant or detect(data)['variant']
    if v in ('ws4', 'ws5+'):
        return parse_ws(data, encoding)
    if v in ('printstream', 'text'):
        return parse_printstream(data, encoding)
    raise ValueError(f'not a convertible file (detected: {v})')
