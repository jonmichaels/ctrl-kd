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
import math
import re
from dataclasses import dataclass, field

from .symbolmap import transliterate, font_translit_kind
from .typestyles import TYPESTYLE_NAMES

# The cp437 GLYPHS at control-code positions (and 0x7F). Python's cp437 codec
# maps 0x00-0x1F to the control characters themselves; the DISPLAY glyphs IBM
# put there need their own table. Used for <1B x 1C> wrapped characters, whose
# middle byte is "a character to display" for any value 00h-FFh (WSFORMAT).
CP437_GRAPHICS = {
    0x00: ' ',  0x01: '☺', 0x02: '☻', 0x03: '♥',
    0x04: '♦', 0x05: '♣', 0x06: '♠', 0x07: '•',
    0x08: '◘', 0x09: '○', 0x0A: '◙', 0x0B: '♂',
    0x0C: '♀', 0x0D: '♪', 0x0E: '♫', 0x0F: '☼',
    0x10: '►', 0x11: '◄', 0x12: '↕', 0x13: '‼',
    0x14: '¶', 0x15: '§', 0x16: '▬', 0x17: '↨',
    0x18: '↑', 0x19: '↓', 0x1A: '→', 0x1B: '←',
    0x1C: '∟', 0x1D: '↔', 0x1E: '▲', 0x1F: '▼',
    0x7F: '⌂',
}

# ---------------------------------------------------------------- IR

@dataclass
class Span:
    text: str
    styles: frozenset = frozenset()      # subset of {'b','i','u','sup','sub','strike'}

@dataclass
class Line:
    spans: list = field(default_factory=list)
    soft: bool = False                   # ends in WordStar's own word wrap (8D soft
                                          # return): ON PAPER this was a real line break;
                                          # for reflow it joins the next line (merged_lines)
    softpage: bool = False               # a 0x0B end-of-page mark fell at this line --
                                          # the EDITOR's last-seen pagination, transient
                                          # per WSFORMAT and ignored by WordStar's own
                                          # print pipeline (measured byte-identical,
                                          # 2026-08-04). Recorded for viewers; never a
                                          # page break, and never splits a block
    overprint: bool = False              # ends in a BARE CR -- ^PM Overprint Line: the
                                          # NEXT line prints at this line's own baseline
                                          # (LJ6DTP's white-on-black knockouts; strikeover
                                          # composites). Printed renderers re-use the y;
                                          # reflow modes treat it as a plain break
    # The line height IN FORCE ON THIS LINE, in `.lh`'s own 1/48in units --
    # None meaning "the document's own default" (doc.meta['page']['lh_48']),
    # which is the overwhelmingly common case and keeps the field free for
    # every file that never changes leading.
    #
    # `.lh` is STATEFUL: it applies from where it appears onward, exactly like
    # `.oc`/`.lm`, and real documents switch it constantly (one archive file
    # alternates `.lh10pt` and `.lh16pt` around its banner headings). The page
    # dict's `lh_48` is the FIRST occurrence -- one resolved answer per
    # document, which is what a consumer needs for a default and for
    # --diagnose -- and resolving ONLY that stacked 72pt banners on a single
    # 14pt lead, which is the bug this field exists to fix. Register C24.
    lead_48: float = None

    def text(self):
        return ''.join(s.text for s in self.spans)

@dataclass
class Block:
    kind: str            # 'para' | 'pagebreak' | 'condpage'
                         # ('softpage' RETIRED 2026-08-04: a 0x0B mark is
                         #  transient editor state, now Line.softpage -- it
                         #  never breaks a page and never splits a block)
    lines: list = field(default_factory=list)
    heading: int = 0     # 0 = body text; 1-3 = WS5+ title/header/subheading
                         # (for 'condpage' it carries `.cp`'s requested line count)
    # Horizontal alignment in force when this block was opened: 'left' (WordStar's
    # default), 'center', 'right' or 'justify'. From `.oc` (centering on/off) and
    # `.oj` (justification off/on/c/r), which are STATEFUL -- they apply from where
    # they appear until changed -- so the state is stamped onto each block as it
    # opens rather than looked up later. Register C16/C17.
    align: str = 'left'
    # Whether WordStar was word-wrapping when this block was opened (`.aw on|off`).
    # Register C23: with wrap off the author is positioning lines by hand, so a
    # reflowing consumer must NOT re-wrap them or the layout is destroyed.
    wrap: bool = True
    # `.lm` / `.rm` / `.pm` in force when this block opened, in print COLUMNS
    # (10 CPI, the same unit `.po` uses). None means the file never set it, so a
    # consumer applies its own default rather than a fabricated one. Register C9.
    #
    # Stateful like the alignment above, and emphatically NOT first-occurrence:
    # one archive file sets `.pm` seven hundred times. `.pm` is the PARAGRAPH
    # margin -- the first line's own indent -- which is why it is separate from
    # `.lm` rather than folded into it.
    left_margin: float = None
    right_margin: float = None
    para_margin: float = None
    # `.co <n>, <gutter>` -- newspaper columns in force when this block opened, and
    # the gutter between them in print columns. None means the file never asked,
    # which is not the same as asking for one column. Register C5.
    columns: int = None
    column_gutter: float = None
    # WordStar's paragraph style (symmetric type 0x11), when one was applied:
    # the 0-based library slot the block's style HANDLE resolves to, and the
    # resolved entry's name. `heading` derives from the NAME (see
    # _style_heading_level) -- the corpus proved slot numbers carry no
    # semantics. Full entry: doc.styles, matched on 'slot'. Register C1.
    style_id: int = None
    style_name: str = None
    style_attrs: frozenset = frozenset()   # print attributes the style turns ON
                                            # (span-style tags); emitters merge
                                            # them into every span, like heading
                                            # bold

def merged_lines(block: Block) -> list:
    """Block.lines with soft-wrapped runs joined back into logical lines --
    what Block.lines itself WAS before 2.0.0 stored physical lines.

    Printed mode renders Block.lines directly: a soft return is where
    WordStar broke the line on paper, so the physical line IS the printed
    line (merging them was the bug that printed thousand-column lines).
    Reflowing consumers (every Modern emitter) call this instead: a soft
    break is just word wrap, so the continuation belongs to the same logical
    line. The join rule is the one parse_ws itself used when it merged at
    parse time -- a space in the wrapped line's trailing style, suppressed
    after an existing space or a hyphenated break -- so Modern output is
    byte-identical either side of the 2.0.0 split."""
    out, cur = [], None
    # Hard blanks are emitted only BETWEEN content, never trailing. A block that
    # ENDS with the author's blank already gets a structural blank from the Modern
    # layout, and emitting both double-spaced every paragraph of a WS4 document
    # ([52, 26] where [54] was right). Buffering them until the next real line
    # arrives keeps the print-stream case (one block, interior blanks are the only
    # paragraph separation) without breaking the WS4 case (blank ends the block).
    pending_blanks = 0
    for line in block.lines:
        if not line.spans:
            # A blank PHYSICAL line, and the two kinds mean different things.
            #
            # SOFT is `.ls` filler -- typography, not a logical line of text, so
            # reflow drops it and lets the Modern layout do its own spacing.
            #
            # HARD is the author's own return, and it is the ONLY paragraph
            # separation a print stream has. Dropping it was correct only while
            # blank lines still delimited BLOCKS; once they became content
            # (2026-08-03) a whole print stream is one block, so "Modern emits
            # its own blank between paragraphs" fired exactly once for the
            # entire document and every paragraph ran together in the PDF.
            # emit_text kept its blanks and _doc_to_pagelines did not, which is
            # how the two disagreed for a day. Found by the Swift port.
            if not line.soft:
                if cur is not None:
                    out.append(cur)
                    cur = None
                pending_blanks += 1
            continue
        if pending_blanks:
            out.extend(Line([]) for _ in range(pending_blanks))
            pending_blanks = 0
        if cur is None:
            cur = Line(list(line.spans))
        else:
            # A soft-wrapped CONTINUATION line carries WordStar's own re-emitted
            # left indent -- a `.lm`/tab that the program stamps onto every
            # wrapped line, not something the author typed. Printed renders it
            # (it really is on the paper); reflow must not, or the indent ends
            # up embedded mid-paragraph and the wrapper breaks around it.
            # Diagnosed 2026-08-03 on a real file whose every physical line
            # begins with a type-9 tab sequence.
            spans = list(line.spans)
            while spans and not spans[0].text.strip():
                spans.pop(0)
            if spans:
                first = spans[0]
                stripped = first.text.lstrip()
                if stripped != first.text:
                    spans[0] = Span(stripped, first.styles)
            cur.spans.extend(spans)
        if line.soft:
            t = cur.spans[-1].text if cur.spans else ''
            if t and not t.endswith((' ', '-')):
                cur.spans.append(Span(' ', cur.spans[-1].styles))
            continue
        out.append(cur)
        cur = None
    if cur is not None:
        out.append(cur)
    return out

@dataclass
class Note:
    """One footnote/endnote/annotation/comment: WordStar 7.0 symmetrical
    sequence types 3-6 (WordStar International, 1992). All four share one
    layout (line-count word, tag/number word, conversion-flag byte, text) so
    one model covers them; `kind` is what lets callers tell them apart."""
    kind: str                  # 'footnote' | 'endnote' | 'annotation' | 'comment'
    text: str = ''
    number: int | None = None  # footnote/endnote only: the file's own note number
                                # (else None -- annotations/comments have no numeric
                                # identity in the spec, only annotations have `tag`)
    tag: str | None = None     # annotations only: the nested tag's display TEXT (can
                                # be null); footnote/endnote carry a number instead,
                                # comments carry neither -- spec-documented "not used"
    line_count: int = 0        # WordStar's stored text height -- cheap pagination
    number_format: int = 0     # conv-flag high nybble: 0 symbols,1 upper,2 lower,3
                                # numeric -- meaningless for annotations (spec: "not
                                # used"), left 0 there rather than reporting noise
    convert_to: int = 0        # conv-flag low nybble: 0 = none, else target note type
                                # (same annotation caveat as number_format)
    dot_commands: list = field(default_factory=list)  # the note's OWN dot-command
                                # lines (a ruler or comment can live inside a note's
                                # text same as the body) -- stripped from `text` but
                                # preserved verbatim, in order, not dropped
    offset: int = 0            # source byte offset of this block's opening 0x1D
                                # (0 for dot-line comments, which have no block --
                                # their stable anchor is doc.meta['dot_at'])
    origin: str = 'block'      # where this note came from: 'block' (a real
                                # ^ON/^FN symmetrical sequence) or the dot-line
                                # comment syntaxes '..' / '.ig' (ruling
                                # 2026-08-06: both WordStar comment forms unify
                                # into kind='comment'; origin is the provenance
                                # that explains an odd-looking entry -- a
                                # commented-out `..rm 60` is still a comment)

@dataclass
class UnknownBlock:
    """A symmetrical sequence whose type we don't interpret: kept verbatim
    (bytes + source offset) instead of being silently dropped, per the
    project rule to preserve what isn't understood -- so --diagnose can
    report it instead of going quiet."""
    cmd: int
    data: bytes
    offset: int

@dataclass
class Document:
    blocks: list = field(default_factory=list)
    # Running head/foot text, by line number (1-5). `.he`/`.fo` are line 1.
    # Added 2026-08-03: these are fully-documented dot commands that had NO
    # field anywhere in the IR, so their text was captured only in the
    # dot_commands diagnostic string and silently discarded by every emitter --
    # the reserved SPACE was honoured, the content was not. A running title or
    # "Page #" line vanished from every page with no indication it existed.
    #
    # Geometry, MEASURED on WordStar 4 (2026-08-03) rather than inferred:
    #   line 1        header text          (.he/.h1-.h5)
    #   .hm lines     blank                (default 2)
    #   .pl-.mt-.mb   body                 (55 at the defaults)
    #   .fm lines     blank                (default 2)
    #   1 line        footer text          (.fo/.f1-.f5)
    #   remainder     blank                (to fill .mb)
    # so .mt 3 == header + .hm 2, and .mb 8 == .fm 2 + footer + 5.
    headers: dict = field(default_factory=dict)       # {1..5: str} (final state)
    footers: dict = field(default_factory=dict)       # {1..5: str} (final state)
    # Every .he/.h1-.h5/.fo/.f1-.f5 IN DOCUMENT ORDER, with the block it
    # precedes: ('H'|'F', line 1-5, text, block_index). WordStar applies a
    # running head from the page where it is defined -- on that page itself
    # only if no text has printed there yet, else from the next page. The
    # final-state dicts above cannot express that (OLDTIMES defines its head
    # after page 1's title block: a proper manuscript has NO running head on
    # page 1); the paginator replays these events instead.
    hf_events: list = field(default_factory=list)
    footnotes: list = field(default_factory=list)     # list[list[Span]] (WS5+): footnotes,
                                                       # endnotes, and annotations, in document
                                                       # order -- all three are rendered the
                                                       # same way (a numbered list at the end);
                                                       # see doc.notes to tell them apart
    endnotes: list = field(default_factory=list)      # list[list[Span]] (WS5+, type 4 only)
    annotations: list = field(default_factory=list)   # list[list[Span]] (WS5+, type 5 only)
    comments: list = field(default_factory=list)      # list[Note] (WS5+, type 6): never
                                                       # printed by WordStar itself, but kept
                                                       # here -- often the most interesting
                                                       # content in a file (hidden author asides)
    notes: list = field(default_factory=list)          # list[Note], ALL kinds, document order:
                                                       # the authoritative structure; footnotes/
                                                       # endnotes/annotations/comments above are
                                                       # convenience views over this
    # INSET picture paths, in document order -- one per `[image: NAME]` placeholder
    # in the text. A converter cannot render a 1987 .PIX, but recording the path
    # means a consumer can find the file, and the placeholder means the reader can
    # see that a figure belongs there. Register C10.
    graphics: list = field(default_factory=list)       # list[str]
    # `.tc` table-of-contents entries: (level, text, block_index). The block index
    # is what lets a consumer resolve an entry to a PAGE after pagination -- the
    # text alone cannot, since two chapters can share a title. Register C7.
    toc_entries: list = field(default_factory=list)
    # `.ix` index entries: (text, block_index). Register C6.
    index_entries: list = field(default_factory=list)
    # Colour changes: (byte_offset, foreground, background) -- indices into
    # WordStar's palette, not RGB. Recorded, not rendered: the printed page this
    # project reproduces was monochrome. Register C2.
    colours: list = field(default_factory=list)
    # Font changes: (byte_offset, height_20th_pt, width_20th_pt, driver_bytes).
    # The size is usable by any renderer; the driver bytes identify the face to a
    # 1987 printer and mean nothing without it. Register C3.
    fonts: list = field(default_factory=list)
    # Files the printer was told to pull in (`%F"PLEAD.PS"`), one per
    # `[include: NAME]` placeholder in the text. Same class as `graphics`: the
    # block holds a filename and used to be dropped whole.
    includes: list = field(default_factory=list)
    # Japanese runs: (offset, raw_bytes) -- the UNDECODED Shift-JIS that sat
    # between a shift-in and its shift-out, lifted out of the text stream and
    # replaced there by a placeholder. Per WSFORMAT.TXT the 0x17 block is a
    # one-byte MODE TOGGLE (1 = into Japanese, 0 = back), not a container of text,
    # so the run is the span BETWEEN two markers. Nothing is lost and no mojibake
    # is presented as text. Register C15.
    shift_runs: list = field(default_factory=list)
    # Paragraph style library (WS5.5+): the styles the document carries at its
    # end, reached via the header block's 32-bit pointer. Each entry is a dict:
    # name, plus the 102-byte record's fields where present (margins/tabs in
    # HMI 1/1800in, line height in VMI, attribute words) with each inheritable
    # field None when its sentinel says "inherit". Register C1. A styled
    # paragraph does not yet LOOK UP its entry -- that link is a separate,
    # still-open item (the 0x11 block carries a style code, not an index).
    styles: list = field(default_factory=list)
    unknown_blocks: list = field(default_factory=list)  # list[UnknownBlock]: unrecognised
                                                         # symmetrical-sequence types, preserved
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
    # The file may DECLARE itself before any statistics: a WS5+ document opens
    # with a type-0 header block (version BCD + driver + style pointer), and
    # WordStar writes it at offset 0. Check the full framing, not just the
    # marker byte, so a random 0x1D can't impersonate one. This must run
    # BEFORE the 0x1A truncation below: the header's own content can contain
    # 0x1A (SAWYER.WS does), and truncating there judged a 6.6 KB document on
    # its first 17 bytes -- "58% text but no structure" said the wreckage.
    if len(data) >= 8 and data[0] == 0x1D and data[3] == 0x00:
        jump = int.from_bytes(data[1:3], 'little')
        end = 2 + jump
        if (8 <= jump < 0x400 and end < len(data) and data[end] == 0x1D
                and int.from_bytes(data[end-2:end], 'little') == jump
                and data[4] in (0x50, 0x55, 0x60, 0x70)):
            return {'variant': 'ws5+',
                    'reason': 'opens with a valid header block (declared '
                              f'release {data[4] >> 4}.{data[4] & 0x0F})',
                    'size': len(data)}
    core = data[:data.index(0x1A)] if 0x1A in data else data
    if not core:
        return {'variant': 'binary', 'reason': 'empty (or ^Z at start)'}
    soft = core.count(b'\x8d\x0a')
    hard = core.count(b'\x0d\x0a')
    hi = sum(1 for x in core if x >= 0x80)
    blocks_1d = core.count(b'\x1d')
    # A wrapped extended character <1B x 1C> is three bytes of WS5+ machinery
    # around ONE text character; its frame bytes counted as binary noise, so a
    # document whose body is box-drawing (BOX.WS: ~90 triples in 304 bytes)
    # read as "63% text but no structure" and was refused.
    # DOTALL: the wrapped byte "can be any value in the range from 00h
    # through FFh" (WSFORMAT) -- a bare `.` would skip 0x0A-middled triples
    trips = len(re.findall(rb'\x1b.\x1c', core, re.S))
    txt = min(100, (sum(1 for x in core
                        if 0x20 <= (x & 0x7F) < 0x7F or x in (0x0D, 0x0A, 0x09))
                    + 2 * trips) * 100 // len(core))
    ev = {'soft_returns': soft, 'hard_returns': hard, 'high_bit_bytes': hi,
          'text_pct': txt, 'symmetric_blocks_1d': blocks_1d,
          'wrapped_extended': trips, 'size': len(core)}
    if txt < 40:
        return {'variant': 'binary', 'reason': f'only {txt}% text-like', **ev}
    if blocks_1d >= 2 or trips >= 3:
        # 1D symmetric blocks and 1B..1C wrapped extended characters are WS5+
        # machinery regardless of anything else
        return {'variant': 'ws5+', **ev}
    # soft returns are strong WS evidence on their own; high-bit density alone is
    # not — binaries are full of high bytes — unless the file is mostly text
    if soft >= 3 or (hi >= max(1, len(core) // 20) and txt >= 70):
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

def _split_bare_ff(raw: bytes) -> list:
    """raw.split(b'\\x0c'), except a 0x0C that is the middle byte of a
    <1B x 1C> wrapped extended character stays in its part -- it is the cp437
    glyph at that position, not a page eject."""
    parts, seg = [], 0
    for m in re.finditer(rb'\x1b.\x1c|\x0c', raw, re.S):
        if m.group(0) == b'\x0c':
            parts.append(raw[seg:m.start()])
            seg = m.end()
    parts.append(raw[seg:])
    return parts


def _bare_eof(data: bytes) -> int:
    """Offset of the first 0x1A that actually MEANS end-of-file -- i.e. one
    that is not the middle byte of a <1B x 1C> wrapped extended character.
    ASCIITAB.WS wraps every control code to print its chart, including
    <1B 1A 1C>, and cutting at that middle byte amputated 86% of the file.
    Returns -1 when no bare 0x1A exists."""
    at = -1
    while True:
        at = data.find(b'\x1a', at + 1)
        if at == -1:
            return -1
        if at >= 1 and data[at - 1] == 0x1B and at + 1 < len(data) \
                and data[at + 1] == 0x1C:
            continue
        return at


def lines_pass(data: bytes, tab_at=frozenset(), marks=None,
               soft_is_wrap=False, overprint_cr=False):
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

    `soft_is_wrap=True` (WS5+): a soft return is ALWAYS wrap, no heuristic.
    The would-it-have-fit test is a WS4-era inference over FIXED-PITCH byte
    lengths; WS5+ documents use proportional fonts, where byte length says
    nothing about printed width, and the archive's own documents misread as
    ~5 "deliberate" breaks per paragraph (204 spurious RTF line breaks in one
    story's RTF -- found by Jon reading the export, 2026-08-04). In WS5+ the
    editor re-wraps paragraphs dynamically, so a surviving soft return IS
    wrap by construction; deliberate breaks are hard returns.

    `marks` maps an offset in `data` to a structural event that used to be an
    in-band SENTINEL BYTE -- a note reference, a soft page break, a paragraph
    style. Every byte those sentinels used is a real WordStar control code
    (0x00 ^@, 0x0B ^K, 0x11 ^Q), so a document containing one was misread; see
    `_symmetric_blocks`. Marks travel as offsets for the same reason `tab_at`
    does, and each emitted line carries the marks that fall inside it, rebased
    to that line.
    """
    cut = _bare_eof(data)
    if cut != -1:
        data = data[:cut]
    # The LF of a return pair may carry the high bit too: MEASURED on a real
    # WS7 document (2026-08-04), the soft return written after every
    # end-of-page block is <8D 8A> -- both bytes flagged -- and a hard CR
    # can be followed by a flagged LF (<0D 8A>). WordStar's own printer
    # masks the flag and performs the line advance (traced in PCL: a
    # vertical-move escape, zero glyphs); decoding 0x8A as text invented an
    # 'e-grave' at 14 page boundaries in one document.
    #
    # A <1B x 1C> wrapped extended character is matched FIRST and treated as
    # TEXT: its middle byte can be any value 00h-FFh, and a wrapped 0x0A or
    # 0x0D is a chart glyph, not a line break -- ASCIITAB.WS's table rows
    # broke apart at those cells. The triple alternative wins the alternation
    # so a break inside one is never seen; only group(1) matches split.
    lines = []
    starts = []                              # (offset, length, index) per emitted line

    def _emit(text_start, text_end, brk):
        # A BARE CR is ^PM Overprint Line (WSFORMAT and the WS4 manual
        # agree): the next line prints at THIS line's baseline. Only WS
        # documents opt in (`overprint_cr`) -- a CR-only text file (classic
        # Mac line endings) must never have its every line overprint.
        if brk == b'\x0d' and overprint_cr:
            kind = 'over'
        else:
            kind = 'eof' if not brk else ('soft' if brk[0] in (0x8D, 0x8A) else 'hard')
        text = data[text_start:text_end]
        if text or kind != 'eof':
            # `machine_indent`: this line's leading whitespace was emitted by
            # WordStar from a TAB, not typed by the author. See the wrap test.
            starts.append((text_start, len(text), len(lines)))
            lines.append([text, kind, text_start in tab_at, []])

    seg = 0
    for m in re.finditer(
            rb'\x1b.\x1c|(\x8d\x8a|\x8d\x0a|\x0d\x8a|\x0d\x0a|\x8d|\x8a|\x0d|\x0a)',
            data, re.S):
        if m.group(1) is None:
            continue                          # wrapped triple: text, not a break
        _emit(seg, m.start(1), m.group(1))
        seg = m.end(1)
    _emit(seg, len(data), b'')

    # Attach each mark to the line that contains it. A mark landing INSIDE a
    # break (a soft page break sits between two lines, not within one) belongs
    # to the line that FOLLOWS it, at relative offset 0 -- otherwise it would be
    # silently dropped, which is the failure the sentinels were replaced to end.
    # Each offset carries a LIST of marks: adjacent 0x1D blocks add no text
    # between them, so a colour change and a font block (LJ6DTP, offset 178)
    # or a style and a font legitimately mark the same offset.
    for off, mlist in sorted((marks or {}).items()):
        for m in mlist:
            placed = False
            for a, ln, idx in starts:
                if a <= off < a + ln:
                    lines[idx][3].append((off - a, m))
                    placed = True
                    break
            if not placed:
                nxt = next((idx for a, ln, idx in starts if a >= off), None)
                if nxt is not None:
                    lines[nxt][3].append((0, m))
                elif lines:
                    lines[-1][3].append((len(lines[-1][0]), m))
    for _t, _k, _mi, mk in lines:
        mk.sort()

    softlens = sorted(len(_visible(t).rstrip()) for t, k, _, _ in lines
                      if k == 'soft' and _visible(t).strip())
    margin = max(65, softlens[int(len(softlens) * 0.9)] if softlens else 0)

    out = []
    i = 0
    while i < len(lines):
        text, kind, _mi, _mk = lines[i]
        if not _visible(text).strip():
            # A blank line is CONTENT, not a delimiter (fixed 2026-08-03).
            # It used to be skipped here and counted only to classify the
            # PREVIOUS line's separator, then discarded -- which deleted 221 of
            # 448 physical lines from a real double-spaced 1992 essay, took the
            # author's chapter-drop with it, and changed the page count.
            # The terminator KIND is carried because WordStar distinguishes
            # them: `.ls > 1` materialises its filler as SOFT blanks (WS7
            # Reference: "the blank lines become part of the file") and always
            # suppresses those at a page top, while HARD blanks are the
            # author's own returns and print (`.sb` defaults off, and does not
            # exist at all before WS5).
            # Keep the RAW bytes, not b'': a line can be VISUALLY blank while
            # still carrying style toggles (bold-on and nothing else). Emitting
            # b'' would drop the toggle and unstyle everything after it. The
            # consumer decodes spans as usual; they simply render to nothing.
            if kind != 'eof':
                out.append((text, 'blank-soft' if kind == 'soft' else 'blank-hard', _mk))
            i += 1
            continue
        if kind == 'over':
            # An overprint separator is its own thing: no blank-counting, no
            # wrap inference -- the next physical line shares this baseline.
            out.append((text, 'over', _mk))
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
            out.append((text, 'eof', _mk))
            break
        if n_hard >= 1 and n_total >= 2:
            sep = 'para'
        elif n_hard == 1:
            sep = 'line'
        else:
            nxt_vis = _visible(lines[j][0])
            if lines[j][2]:
                # Machine indent: WordStar re-stamped the left margin onto this
                # wrapped line from a TAB. Drop it before measuring, or the
                # "first word" is the empty string before the spaces, W is 0,
                # and the wrap test concludes the next word would have fit --
                # which lands back on 'deliberate' by a different route.
                nxt_vis = nxt_vis.lstrip(b' ')
            if nxt_vis[:1] == b' ' and not lines[j][2]:
                # An indented continuation the AUTHOR typed is a deliberate
                # break (a poem, a block quote). One WordStar itself emitted
                # from a tab is not: it re-stamps the left indent onto every
                # wrapped line, so treating that as deliberate stopped whole
                # paragraphs from ever reflowing in Modern -- they rendered as
                # physical lines with the wrong margins. Diagnosed 2026-08-03.
                sep = 'line'                      # indented continuation = deliberate
            elif soft_is_wrap:
                # WS5+: a surviving soft return IS wrap by construction (the
                # editor re-wraps dynamically; deliberate breaks are hard
                # returns). The fit heuristic below is a WS4 fixed-pitch
                # inference that misfires on proportional text -- 204 spurious
                # breaks in one story's RTF (Jon's export review, 2026-08-04).
                sep = 'wrap'
            else:
                L = len(_visible(text).rstrip())
                W = len(nxt_vis.split(b' ', 1)[0])
                sep = 'line' if L + 1 + W < margin else 'wrap'
        out.append((text, sep, _mk))
        # The blanks this run consumed, in document order, after the line they
        # follow. They were counted above to classify `sep` and are now also
        # kept as content -- the counting and the keeping are separate jobs.
        for b in range(i + 1, j):
            btext, bk, _, bmk = lines[b]
            if bk != 'eof':
                out.append((btext, 'blank-soft' if bk == 'soft' else 'blank-hard', bmk))
        i = j
    return out, margin

# ---------------------------------------------------------------- WS documents

# WordStar inline control codes (same core set WS4 through WS7)
WS_TOGGLES = {0x02: 'b', 0x13: 'u', 0x19: 'i', 0x14: 'sup', 0x16: 'sub',
              0x18: 'strike', 0x04: 'b'}         # ^D doublestrike -> bold
# Codes discarded without comment. 0x08 (^H overprint) was here until
# 2026-08-03 and is deliberately NOT any more: WordStar-era authors used
# backspace-and-overtype to compose accented letters and ad-hoc symbols, so
# dropping it SILENTLY loses content with no trace. It now falls through to the
# `unknown` tally, which `--diagnose` reports -- the project's own rule is never
# to go quiet. Composing the overprinted pair properly is a separate job; being
# able to SEE that a document contains overprints is the prerequisite for it.
WS_DROP = {0x03, 0x0B, 0x10, 0x11, 0x12, 0x15, 0x17, 0x1C}
# 0x01/0x0E left WS_DROP 2026-08-04 (Jon: 'Store that ws4 font switch
# flag. Don't lose it.'): ^PA alternate font / ^PN normal -- the ONLY
# typeface signal a WS4 file can carry (the face itself lived in the
# printer: a daisy wheel, a cartridge). Carried as the 'altfont' span
# tag; no emitter renders it yet.

DOT_PAGEBREAK = {b'PA'}                 # UNCONDITIONAL page break
# `.CP n` is CONDITIONAL and cannot be decided here: it depends on how many
# lines are left on the page, which only the pagination pass knows. It used to
# live in DOT_PAGEBREAK and so broke every time, inverting the author's intent
# -- `.cp` exists precisely so a heading does NOT get stranded, and firing it
# unconditionally inserts the break it was there to prevent.
DOT_CONDPAGE = b'CP'

# ------------------------------------------------------------ page geometry
#
# .pl (page length), .po (page offset), .mt (top margin), .mb (bottom margin)
# -- WordStar 7.0 file format spec (WordStar International, 1992). The trap:
# a UNIT-LESS numeric argument to .pl/.mt/.mb is LINES, and to .po is print
# COLUMNS -- never inches. (The only other modern implementation, WordTsar,
# admits via its own @todo that it falls back to inches when no unit is
# given; that is exactly the bug this avoids.) WordStar 5.0+ also allows an
# explicit unit suffix on these arguments -- '"'/I/IN for inches, C/CM for
# centimetres, P/PM for points, case-insensitive -- which this DOES convert,
# since at that point the file is telling us the unit rather than leaving it
# to the trap-default.
#
# Everything below assumes the fixed 6 LPI / 10 CPI baseline this project
# already uses elsewhere (pdf.py's Courier metrics; margin_estimate's WS4
# default). WordStar itself lets LPI/CPI vary (.lh, .cw), but tracking those
# per-line is well beyond what a page-geometry pass needs.

# ---------------------------------------------------------------- release eras
#
# WordStar changed behaviour between releases, and a converter has to know
# WHICH WordStar wrote a file. Until 2026-08-03 those decisions were scattered
# as inline `variant == 'ws4'` checks, which worked for two eras and would not
# survive a third. This table is the one place that knows.
#
# ADDING A RELEASE (e.g. WS3): add an entry here, make detect() able to return
# its name, and -- ideally -- confirm each field by RUNNING that WordStar under
# tools/wordstar_harness.sh rather than trusting a manual. Nothing else should
# need to grow a version check; if it does, the missing fact belongs in here.
#
# Sources for the current entries: WordStar Professional 4.0 (1987) Appendix G
# and Appendix B; WordStar 7.0 Reference; "Upgrading from a Previous Release"
# (WS7); WordStar Professional 5.0 "What's New" (1988). Where the last two
# disagree the field is marked UNVERIFIED -- see column_unit.

class Era:
    """What one WordStar release does differently. Fields are behaviours, not
    versions: ask `era.high_bit_wordwrap`, never `variant == 'ws4'`."""

    __slots__ = ('name', 'high_bit_wordwrap', 'symmetric_blocks', 'has_notes',
                 'has_sb', 'column_unit', 'pc_default')

    def __init__(self, name, high_bit_wordwrap, symmetric_blocks, has_notes,
                 has_sb, column_unit, pc_default):
        self.name = name
        # WS4 and earlier set bit 7 on the LAST character of each word
        # (microjustify flags). WS5+ dropped it, and a high byte there is an
        # extended cp437 character instead -- so this decides whether stripping
        # the high bit recovers text or destroys it.
        self.high_bit_wordwrap = high_bit_wordwrap
        # 0x1D-delimited symmetrical sequences: notes, fonts, colour, styles.
        self.symmetric_blocks = symmetric_blocks
        # ^ONF/^ONE/^ONA/^ONC. Blank in the 4.0/3.3 keystroke tables; appears
        # at 5.5/6.0. A WS4 file cannot contain a note.
        self.has_notes = has_notes
        # `.sb on|off` -- suppress blank lines at the top of a page. Absent
        # from WS4's and WS3.3's command lists entirely (exhaustive Appendix G
        # extraction, .AV through .XW), so a pre-WS5 file cannot mean it.
        self.has_sb = has_sb
        # What a "column" means in .rm/.lm/.pm/.po/.pc. Pre-WS5 it is one
        # character of the CURRENT FONT; WS5+ it is a fixed 0.1 inch. Equal at
        # the default .cw 12 (10 cpi), so this only bites a document that
        # changes .cw AND uses a margin dot command.
        # UNVERIFIED: WS7's "Upgrading" and WS5's "What's New" name DIFFERENT
        # command lists as affected. Settle by experiment before relying on it.
        self.column_unit = column_unit
        self.pc_default = pc_default          # page-number column

    def __repr__(self):
        return f'<Era {self.name}>'


ERAS = {
    # name      hibit  sym    notes  .sb    column_unit  .pc
    'ws3':  Era('ws3',  True,  False, False, False, 'font',       33),
    'ws4':  Era('ws4',  True,  False, False, False, 'font',       28),
    'ws5+': Era('ws5+', False, True,  True,  True,  'tenth-inch', 28),
}

# A print stream is printer output, not a document: no dot commands survive in
# it and none of the above applies. It gets the most conservative entry.
ERAS['printstream'] = Era('printstream', False, False, False, False, 'tenth-inch', 28)
ERAS['text'] = ERAS['printstream']

# 'binary' is a DETECTED variant, not an unknown one, and it must not inherit the
# ws5+ fallback below. Doing so switched symmetric-block parsing ON for a file
# detect() had already declined to identify, and _symmetric_blocks treats every
# 0x1D as a block-start marker: `A <ESC> 0x1D B` parsed to 'A', losing both the
# escaped byte and every byte after it. Caught by the Swift port's escape test,
# which this table had silently regressed; Python's own suite had no equivalent.
# Conservative on BOTH axes -- no high-bit stripping AND no symmetric blocks.
ERAS['binary'] = Era('binary', False, False, False, False, 'tenth-inch', 28)


def era_for(variant):
    """The Era for a detected variant. Variants detect() can actually return all
    have their own entry above; a name from nowhere gets the WS5+ entry, which
    does NOT strip high bits, so it loses no extended characters.

    That fallback is a guess about ENCODING only. It is emphatically not a
    licence to enable behaviour that can destroy text -- which is exactly what
    happened when 'binary' was left to inherit it and picked up symmetric-block
    parsing along the way. Any new variant belongs in the table, conservative on
    every axis, rather than relying on this."""
    return ERAS.get(variant, ERAS['ws5+'])


_DOT_CMD_RE = re.compile(rb'^\.([A-Za-z]{1,3})\s*(.*)$')
_DOT_NUM_RE = re.compile(rb'^\s*([0-9]*\.?[0-9]+)\s*("|[A-Za-z]{1,2})?')

_PAGE_DOT_KEYS = {b'PL': 'pl_lines', b'MT': 'mt_lines',
                  b'MB': 'mb_lines', b'PO': 'po_cols',
                  b'HM': 'hm_lines', b'FM': 'fm_lines',
                  b'LH': 'lh_48', b'LS': 'ls', b'CW': 'cw_120',
                  # `.pn n` sets the number of the page it appears on, so the
                  # document does not have to start at 1 -- a chapter file in a
                  # larger manuscript starts wherever the previous one stopped.
                  # MEASURED on WordStar 4 (2026-08-03): `.pn 7` numbers the
                  # pages 7, 8, 9 in both the header's `#` and the footer's.
                  b'PN': 'pn_start',
                  # `.pc n` is the column of the AUTOMATIC page number -- the one
                  # WordStar prints on its own. Measured: it does NOT move a `#`
                  # placed inside a header or footer, which prints where the
                  # author put it. Two separate mechanisms.
                  b'PC': 'pc_col'}

# Named page sizes at 6 LPI (WordStar 7.0 file format spec: ".PL ... assuming
# 6 lines per inch. An eleven inch page contains 66 lines."): 66 lines/11in
# Letter, 84 lines/14in Legal, 81 lines/13.5in Foolscap Folio (the pre-ISO UK
# long sheet), and A4 (297mm = 11.693in, ~70 lines -- ruled into the model
# 2026-08-06: "the 3 main page sizes" are Letter, Legal, A4). There is no
# dot command for physical page WIDTH, so width rides on the height
# inference: a page tall enough to be A4 is 210mm wide, everything else is
# the 8.5in American sheet -- and a Custom height keeps 8.5in, the only
# honest default the format allows.
NAMED_PAGE_SIZES = (('Letter', 11.0, 8.5), ('Legal', 14.0, 8.5),
                    ('Foolscap Folio', 13.5, 8.5),
                    ('A4', 11.693, 8.268))
# "Close" isn't spec-given -- a judgment call, not a reading. 0.25in is a
# bit over a line and a half at 6 LPI: near enough to call it the named
# size; farther out, honour the raw geometry instead of forcing a label
# onto it (Jon's ruling: "snap ... when close; otherwise honour the raw
# geometry").
PAGE_SIZE_SNAP_IN = 0.25

DEFAULT_PL_LINES = 66.0    # WordStar's own default: 66 lines = 11in = US Letter
DEFAULT_MT_LINES = 3.0     # spec: ".MT ... Default value is 3 lines."
DEFAULT_MB_LINES = 8.0     # spec: ".MB ... The default value is 8 lines."
DEFAULT_PO_COLS = 8.0      # WS7 manual, "Page Layout": "The default page offset
                           # is .8 inch" -- 8 print columns at the default 10 CPI.
                           # (Through 1.3.0 this was 0, "least presumptuous", from
                           # the file-format spec stating none; the manual DOES
                           # state one, and 2.0.0 actually renders the offset, so
                           # the manual's figure governs.)
DEFAULT_HM_LINES = 2.0     # spec: ".HM ... Default is 2." (header sits INSIDE .mt)
DEFAULT_FM_LINES = 2.0     # spec: ".FM ... Default is 2." (footer sits INSIDE .mb)
DEFAULT_LH_48 = 8.0        # spec: ".LH ... The default is 8/48 or 6 lines per inch."
DEFAULT_LS = 1.0           # single spacing (WS7 manual, "Line Spacing")
DEFAULT_CW_120 = 12.0      # spec: ".CW ... The default is 12 (12/120ths is 10
                           # characters per inch)."

def _dot_arg_inches(value: float, unit: bytes | None):
    """Convert a dot-command argument's optional unit suffix to inches.
    Returns None for no unit (caller applies the lines/columns default) or an
    unrecognised unit (treated the same as no unit -- defensive, not a crash)."""
    if not unit:
        return None
    u = unit.upper()
    if u in (b'"', b'I', b'IN'):
        return value
    if u in (b'C', b'CM'):
        return value / 2.54
    if u in (b'P', b'PM', b'PT'):
        # `PT` is not in the file-format spec's list (which gives P and PM), but
        # real files write it: the WS7 archive uses `.sr 5pt` and `.sr 3pt`. It can
        # only mean points, and without it those arguments fell through to the
        # unit-less default and were read as 48ths -- silently, and wrong by 1.5x.
        return value / 72.0
    return None

def _resolve_lines_arg(value: float, unit: bytes | None) -> float:
    """.pl/.mt/.mb argument -> lines, at 6 LPI. Unit-less IS lines already
    (see module note above); a unit suffix is inches/cm/points via 6 LPI."""
    inches = _dot_arg_inches(value, unit)
    return value if inches is None else inches * 6.0

def _resolve_cols_arg(value: float, unit: bytes | None) -> float:
    """.po argument -> print columns, at 10 CPI. Unit-less IS columns."""
    inches = _dot_arg_inches(value, unit)
    return value if inches is None else inches * 10.0

def _resolve_lh_arg(value: float, unit: bytes | None):
    """.lh argument -> line height in 1/48in units. Unit-less IS 48ths (WS7
    manual: "You can also type the dot command in 48ths of an inch. For
    example, .lh 8 is 8/48 inch, or the standard 6 lines per inch"); an
    explicit unit suffix converts. `.lh a` (auto-leading) never reaches here
    -- the numeric matcher won't match it, so it stays default + verbatim.
    A non-positive height is meaningless: rejected (None), default stands."""
    inches = _dot_arg_inches(value, unit)
    resolved = value if inches is None else inches * 48.0
    return resolved if resolved > 0 else None

def _resolve_ls_arg(value: float, unit: bytes | None):
    """.ls argument -> line spacing. "A line spacing of between 1 and 9"
    (WS7 file format spec); anything else is junk, rejected (None). Any unit
    suffix is likewise junk -- spacing is a count, not a measure."""
    if unit is not None or not 1 <= value <= 9:
        return None
    return value

def _resolve_cw_arg(value: float, unit: bytes | None):
    """.cw argument -> character width in 1/120in units. Unit-less IS 120ths
    (spec: ".CW ... the width of the characters in 1/120 inch increments. ...
    The default is 12 (12/120ths is 10 characters per inch)"); an explicit
    unit suffix converts. Non-positive width is meaningless: rejected."""
    inches = _dot_arg_inches(value, unit)
    resolved = value if inches is None else inches * 120.0
    return resolved if resolved > 0 else None

_PAGE_DOT_RESOLVERS = {'po_cols': _resolve_cols_arg, 'lh_48': _resolve_lh_arg,
                       'ls': _resolve_ls_arg,
                       'cw_120': _resolve_cw_arg}  # everything else: lines at 6 LPI

def _text_lines_per_page(pl_lines: float, mt_lines: float, mb_lines: float,
                         lh_48: float) -> int:
    """Printed text lines per page -- WordStar's own vertical model (WS7
    manual, "Page Layout"): "The top and bottom margins define the space
    between the text and the top and bottom of the paper. On an 8.5 x 11-inch
    page, if the top margin is .33 inches and the bottom margin is 1.33
    inches, the space left for text is 9.33 inches." Lines available is that
    text height divided by the line height (.lh, 1/48in units): "Changing the
    line height affects the number of lines that can be printed on a page."
    WordStar's own defaults (.pl 66 .mt 3 .mb 8 .lh 8) give 55.

    Deliberately NOT in the formula:
    - .hm/.fm -- the header prints WITHIN .mt and the footer WITHIN .mb
      (".MT ... The header is printed within this margin"; ".MB ... The
      footer or page number is printed within this margin"), so they position
      header/footer inside space already subtracted, never reserve more.
    - .ls -- line-spacing blanks are literal lines in the file ("when you use
      line spacing, the blank lines become part of the file", WS7 manual,
      "Line Spacing"), so the body text already carries them; dividing
      capacity by .ls would double-count.

    Unit-less .mt/.mb are lines at the fixed 6 LPI baseline (the module-note
    assumption); .lh at parse time is resolved once per document (first
    occurrence wins), not tracked per-line."""
    if pl_lines == 0:
        # `.pl 0` turns page breaks OFF entirely in 7.0 document mode --
        # MicroPro bug 12284 (note 649): DRIVERA.OVR inserts ".pl0" at the
        # start of PRVIEW output precisely so "displayed page breaks are thus
        # avoided" (bare ".pl" stopped meaning this in 7.0). Modelled as a
        # page too tall to fill rather than a zero-height page -- the old
        # arithmetic produced text_lines=1, i.e. MAXIMAL breakage, the exact
        # opposite of what the command asks.
        return 10**9
    usable = pl_lines - mt_lines - mb_lines            # lines at 6 LPI
    if not math.isfinite(usable) or not math.isfinite(lh_48) or lh_48 <= 0:
        return 1
    return max(1, int(usable * 8.0 / lh_48))

def _resolve_page_size(pl_lines: float):
    """pl_lines -> (height_in, size_name, width_in). Snaps to a named size
    when close; otherwise reports the raw geometry under 'Custom' (at the
    8.5in width -- see NAMED_PAGE_SIZES) rather than forcing a label that
    doesn't fit."""
    height_in = pl_lines / 6.0
    name, named_in, width_in = min(
        NAMED_PAGE_SIZES, key=lambda nhw: abs(nhw[1] - height_in))
    if abs(named_in - height_in) <= PAGE_SIZE_SNAP_IN:
        return named_in, name, width_in
    return height_in, 'Custom', 8.5

_HEAD_FOOT_RE = re.compile(rb'^\.(H[E1-5]|F[O1-5])\s?(.*)$', re.I)


_ONOFF_RE = re.compile(rb'^\.([A-Za-z]{2})\s+(ON|OFF|[CRD])\b', re.I)


def _onoff(arg: bytes):
    """`ON`/`OFF` -> True/False, anything else -> None.

    WordStar's on/off dot commands accept only those two words; an argument that
    is neither (a stray `.oc` inside a manual's own prose, say) leaves the state
    alone rather than guessing, which is why this returns None instead of False.
    """
    a = arg.strip().upper()
    if a.startswith(b'ON'):
        return True
    if a.startswith(b'OFF'):
        return False
    return None


def _parse_format_dot(cmd: bytes, state: dict) -> None:
    """Update running FORMATTING state from one dot-command line.

    These differ from the page-geometry commands in `_parse_page_dot`: those
    resolve once per document (first occurrence wins, because a page is a page),
    while these are STATEFUL and apply from where they appear onward. A document
    that centres one heading and then returns to flush left sets `.oc on` and
    `.oc off` around it, and both must be honoured in order.

    Register C16 (`.oc`), C17 (`.oj`), C21 (`.ul`), C23 (`.aw`), C8 (`.sb`),
    C19 (`.ps`), C20 (`.kr`). Argument forms taken from the Sawyer WS7 archive
    rather than from the manual alone -- `.oj` really is used as `.oj r` and
    `.oj c`, not only on/off.
    """
    m = _DOT_CMD_RE.match(cmd)
    if not m:
        return
    name = m.group(1).upper()
    arg = m.group(2)
    if name == b'P' and arg.startswith(b'#'):
        # `.p#` -- '#' is not a letter, so the shared name regex splits it
        # into name 'P', arg '#...'; rejoin before dispatch
        name, arg = b'P#', arg[1:]

    if name == b'OC':                       # centering on/off
        v = _onoff(arg)
        if v is not None:
            state['centering'] = v
    elif name == b'OJ':                     # justification off/on/c/r
        v = _onoff(arg)
        if v is True:
            state['justify'] = 'justify'
        elif v is False:
            state['justify'] = None
        else:
            first = arg.strip()[:1].upper()
            if first == b'C':
                state['justify'] = 'center'
            elif first == b'R':
                state['justify'] = 'right'
    elif name == b'AW':                     # align/word-wrap on/off
        v = _onoff(arg)
        if v is not None:
            state['wrap'] = v
    elif name == b'UL':                     # continuous underline of inter-word blanks
        v = _onoff(arg)
        if v is not None:
            state['underline_blanks'] = v
    elif name == b'SB':                     # suppress blank lines at page top
        v = _onoff(arg)
        if v is not None:
            state['suppress_blanks'] = v
    elif name == b'PS':                     # proportional spacing
        v = _onoff(arg)
        if v is not None:
            state['proportional'] = v
    elif name == b'KR':                     # kerning
        v = _onoff(arg)
        if v is not None:
            state['kerning'] = v
    elif name == b'PR':                     # printer control, incl. orientation
        # Real syntax, from the archive rather than the manual's prose: `.pr or=l`
        # / `.pr or=p`. 18 of the 22 files that use `.pr` set landscape this way.
        # A landscape document rendered portrait is wrong with no diagnostic --
        # register C18.
        a = arg.strip().lower()
        if a.startswith(b'or='):
            o = a[3:4]
            if o == b'l':
                state['orientation'] = 'landscape'
            elif o == b'p':
                state['orientation'] = 'portrait'
    elif name == b'LH':                     # line height, 1/48in units
        # Also read (first occurrence only) by `_parse_page_dot` into the page
        # dict, which is the DOCUMENT-LEVEL default -- page capacity, the
        # emitters' baseline lead, --diagnose. That reading is not wrong; it is
        # incomplete. `.lh` is stateful like every other command in this
        # function, and a document that sets `.lh10pt` before its body and
        # `.lh16pt` before each banner heading means both, in order. Carried
        # per LINE (Line.lead_48) because that is the granularity it acts at --
        # a lead is the distance to the next baseline, not a property of a
        # paragraph. Register C24.
        m = _DOT_NUM_RE.match(arg)
        if m:
            try:
                value = float(m.group(1))
            except (TypeError, ValueError):
                return
            if math.isfinite(value):
                resolved = _resolve_lh_arg(value, m.group(2))
                if resolved is not None:     # junk/non-positive: state stands
                    state['lead_48'] = resolved
    elif name in (b'LM', b'RM', b'PM'):     # left / right / paragraph margin
        # Print columns at 10 CPI, matching `.po`; a unit suffix converts. The
        # archive writes both (`.rm 65` and `.rm 6.5"`).
        m = _DOT_NUM_RE.match(arg)
        if m:
            try:
                value = float(m.group(1))
            except (TypeError, ValueError):
                value = None
            if value is not None and math.isfinite(value):
                key = {b'LM': 'left_margin', b'RM': 'right_margin',
                       b'PM': 'para_margin'}[name]
                cols = _resolve_cols_arg(value, m.group(2))
                if name == b'LM' and not m.group(2):
                    # `.lm 8` is a COLUMN NUMBER (1-based: text begins AT
                    # column 8 = 7 columns of offset), while a unit-suffixed
                    # `.lm 0.7"` and a paragraph style's left_margin_hmi are
                    # already offsets from the edge. Normalised here so
                    # left_margin means one thing -- offset columns -- to
                    # every consumer, whichever way the file said it
                    # (found 2026-08-06 wiring Modern block margins).
                    cols = max(0.0, cols - 1.0)
                state[key] = cols
    elif name == b'CO':                     # newspaper columns
        # `.co <n>, <gutter>` -- the archive writes `.co2, 0.3"`, `.CO3,  .20"`
        # and `.co1` (one column = columns off). Stateful like the margins: a
        # document turns columns on for a section and off again after.
        # Register C5.
        body = arg.strip()
        m = _DOT_NUM_RE.match(body)
        if not m:
            return
        try:
            cols = int(float(m.group(1)))
        except (TypeError, ValueError):
            return
        state['columns'] = max(1, cols)
        rest = body[m.end():].lstrip(b' \t,')
        g = _DOT_NUM_RE.match(rest)
        if g:
            try:
                value = float(g.group(1))
            except (TypeError, ValueError):
                value = None
            if value is not None and math.isfinite(value):
                # A bare gutter is columns, like `.po`; the archive's own values
                # carry an inch mark (`0.3"`), which converts.
                state['column_gutter'] = _resolve_cols_arg(value, g.group(2))
    elif name in (b'OP', b'PG'):            # automatic page numbering off / on
        # WSFORMAT.TXT: ".OP  Omit page number" / ".PG  Number pages ... Usually
        # used to restore page numbering after being turned off with .OP." A
        # STATEFUL pair -- front matter often turns it off and the body turns it
        # back on -- and only the AUTOMATIC number is affected. A `#` the author
        # placed in a header or footer prints either way; the spec names that as
        # the explicit exemption.
        state['auto_page_numbers'] = (name == b'PG')
    elif name == b'PE':                     # print endnotes HERE
        # `.pe` marks the point at which endnotes should print instead of the
        # document end. Recorded as a position so a consumer can honour the
        # author's placement -- previously endnotes always went to the end
        # regardless of what the file asked for. Register C4.
        state['endnotes_here'] = True
    elif name == b'P#':                     # outline paragraph numbering format
        # `.p#` sets the format and/or initial value for the 0x0D paragraph-
        # number blocks. Format alphabet, from Sawyer's own PARAGRAP.NUM
        # notes (a WS file, read with THIS converter): '1' numerals from 1,
        # '9' numerals from 0, 'Z'/'z' upper/lowercase letters, 'I' roman.
        # RECORDED, not rendered: zero documents in the archive use it, so a
        # format engine would be code with no real input to check against --
        # the 47 real 0x0D blocks all render with the default numeric form.
        state['paranum_format'] = arg.strip().decode('cp437', 'replace')
    elif name == b'CC':                     # conditional COLUMN break
        # `.cc n` is `.cp`'s partner for newspaper columns (WSFORMAT: "Like
        # the .CP command, but works with columnar breaks instead").
        # RECORDED, deliberately inert: this converter does not simulate
        # column filling (columns render as CSS column-count in HTML; the
        # browser decides the breaks), so there is no column fill state to
        # test n against. Zero archive documents use it.
        state.setdefault('cond_col', []).append(
            arg.strip().decode('cp437', 'replace'))
    elif name == b'TB':                     # tab stops for ASCII ^I tabs
        # `.tb` sets the stops a plain ASCII 0x09 tab expands to. RECORDED;
        # ASCII-tab expansion stays at the spec's own default ("At print time
        # the number of hard spaces required to reach a modulus 8 print
        # position is generated" -- WSFORMAT control-code table; HORTAB
        # concurs "as though tab stops were set every .8 inches"). Whether
        # `.tb` overrides that at print time is UNMEASURED, and zero archive
        # documents use `.tb` -- symseq tabs carry their own positions.
        stops = []
        for tok in arg.replace(b',', b' ').split():
            m2 = _DOT_NUM_RE.match(tok)
            if m2:
                try:
                    stops.append(_resolve_cols_arg(float(m2.group(1)), m2.group(2)))
                except (TypeError, ValueError):
                    pass
        if stops:
            state['tab_stops'] = stops
    elif name == b'CV':                     # convert note type
        # `.cv <from> <to>` retypes notes mid-document. Recorded verbatim: acting
        # on it means re-kinding notes already parsed, which is a separate pass;
        # what matters first is not silently pretending the command was absent.
        # Register C13.
        state.setdefault('convert_notes', []).append(
            arg.strip().decode('cp437', 'replace'))
    elif name == b'SR':                     # sub/superscript roll
        # Numeric with an optional unit, and the archive really does use `3/48"`
        # and `4/48i` as well as `5pt` and a bare `3`. Register C22.
        roll = _parse_sr_arg(arg)
        if roll is not None:
            state['sub_super_roll_48'] = roll


_SR_FRACTION_RE = re.compile(rb'^\s*([0-9]*\.?[0-9]+)\s*/\s*([0-9]*\.?[0-9]+)\s*("|[A-Za-z]{1,2})?')


def _parse_sr_arg(arg: bytes):
    """`.sr` -- the sub/superscript roll, in 1/48in units.

    WordStar's own unit for this command is 48ths, so a bare number IS 48ths.
    The archive also writes it as a fraction of an inch (`3/48"`, `4/48i`) and in
    points (`5pt`), both of which convert. A roll of 0 is meaningful -- it means
    do not shift at all -- so this returns None only for an argument it cannot
    read, never for a legitimate zero.
    """
    m = _SR_FRACTION_RE.match(arg)
    if m:
        try:
            num, den = float(m.group(1)), float(m.group(2))
        except ValueError:
            return None
        if den == 0:
            return None
        inches = num / den
        # A unit-less fraction is already a fraction OF AN INCH (`3/48` == 3/48in),
        # which is what the 48ths unit expresses, so both paths multiply by 48.
        return inches * 48.0
    m = _DOT_NUM_RE.match(arg)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    inches = _dot_arg_inches(value, m.group(2))
    return inches * 48.0 if inches is not None else value


def _block_format(state: dict) -> tuple:
    """Everything stamped onto a Block when it opens.

    A change to ANY of these has to close the current block, because a single
    block cannot hold two values of it: `.oc on` mid-paragraph means the lines
    after it are centred and the ones before are not, and `.lm 5` mid-paragraph
    means the same about the indent.
    """
    return (_align_now(state), state.get('wrap', True),
            state.get('left_margin'), state.get('right_margin'),
            state.get('para_margin'), state.get('columns'),
            state.get('column_gutter'))


def _align_now(state: dict) -> str:
    """The alignment in force, from the two commands that set it.

    `.oc on` (centering) wins over `.oj`: WordStar centres the line regardless of
    the justification setting, and the archive uses `.oc on` / `.oc off` around
    individual headings inside otherwise justified text.
    """
    if state.get('centering'):
        return 'center'
    return state.get('justify') or 'left'


_L_HASH_RE = re.compile(rb'^\.L#\s*(.*)$', re.I)
_TC_RE = re.compile(rb'^\.TC([1-9]?)\s?(.*)$', re.I)
_IX_RE = re.compile(rb'^\.IX\s?(.*)$', re.I)
_FI_RE = re.compile(rb'^\.FI\s+(.*)$', re.I)


def _parse_collect_dot(cmd: bytes, doc, encoding: str, block_index: int):
    """Dot commands that COLLECT an entry rather than set state.

    `.tc` (table of contents) and `.ix` (index) name a heading or a term that
    belongs in a generated list; `.l#` turns line numbering on and sets its
    interval. All three were parsed as text and discarded, so a document that
    asked for a table of contents produced none and said nothing about it.

    Entries are recorded WITH the block index they sat at, which is what lets a
    consumer resolve them to page numbers after pagination -- the entry's own
    text is not enough, because two chapters can share a title. Compiling the
    finished list is the consumer's job; not losing the entries is this one's.
    Register C6, C7, C11.
    """
    m = _TC_RE.match(cmd)
    if m:
        level = int(m.group(1)) if m.group(1) else 1
        doc.toc_entries.append((level, m.group(2).rstrip().decode(encoding, 'replace'),
                                block_index))
        return
    m = _IX_RE.match(cmd)
    if m:
        doc.index_entries.append((m.group(1).rstrip().decode(encoding, 'replace'),
                                  block_index))
        return
    m = _FI_RE.match(cmd)
    if m:
        # `.FI` -- "File insert.  Prints the specified file at that point in the
        # document." A whole file the document composes itself from, and it was
        # rendering as NOTHING: the filename sat in the dot_commands diagnostic
        # and no emitter said a word about it.
        #
        # Exactly the class already fixed for inset graphics (type 0x10) and for
        # the printer's own `%F"NAME"` includes (type 0x0F) -- this one was
        # missed because it is a dot command rather than a block. Same rule
        # applied: record the name, leave a visible placeholder.
        #
        # The file is NOT read. It may not exist, it may be a Lotus worksheet
        # (the spec allows those), and following it would need the containing
        # directory plus a nesting limit. Saying a file belongs here is the
        # honest half we can do.
        parts = m.group(1).split()
        if parts:
            name = parts[0].decode(encoding, 'replace')
            doc.includes.append(name)
            return name             # the CALLER places the marker, in document order
        return
    m = _L_HASH_RE.match(cmd)
    if m:
        # `.l# 0` turns line numbering OFF; any other number is the interval.
        n = _DOT_NUM_RE.match(m.group(1))
        if n:
            try:
                value = int(float(n.group(1)))
            except (TypeError, ValueError):
                return
            doc.meta['line_numbering'] = value if value > 0 else None


def _parse_head_foot(cmd: bytes, doc, encoding: str, anchor=None):
    """Record `.he`/`.h1`-`.h5` and `.fo`/`.f1`-`.f5` text on the Document.

    `.HE` and `.FO` are line 1; the numbered forms select their own line, so a
    document can carry up to five of each. An empty argument CLEARS that line,
    which is how WordStar turns a running head off part-way through -- so an
    empty value is stored as '' and not skipped.

    The text is kept verbatim, `#` included: the page-number substitution
    depends on which page it lands on and belongs to the emitter, not here.
    """
    m = _HEAD_FOOT_RE.match(cmd)
    if not m:
        return
    tag = m.group(1).upper()
    # Wrapped extended characters <1B x 1C> appear in header text exactly as
    # in the body (LJ6DTP separates its title from the `#` page number with
    # a wrapped middle dot): decode them through the same cp437 rule the
    # body uses -- control-range middles are chart glyphs, the rest are the
    # byte's own cp437 character.
    raw_txt = m.group(2)
    parts, pos = [], 0
    for t in re.finditer(rb'\x1b(.)\x1c', raw_txt, re.S):
        parts.append(raw_txt[pos:t.start()].decode(encoding, 'replace'))
        x = t.group(1)[0]
        parts.append(CP437_GRAPHICS[x] if x < 0x20 or x == 0x7F
                     else bytes([x]).decode(encoding, 'replace'))
        pos = t.end()
    parts.append(raw_txt[pos:].decode(encoding, 'replace'))
    text = ''.join(parts).rstrip()
    kind = 'H' if tag.startswith(b'H') else 'F'
    which = doc.headers if kind == 'H' else doc.footers
    second = tag[1:2]
    line = 1 if second in (b'E', b'O') else int(second)
    which[line] = text
    if anchor is not None:
        doc.hf_events.append((kind, line, text, anchor))


def _cp_lines(cmd: bytes) -> int:
    """The n of a `.cp n`, defaulting to 1 (a bare `.cp` asks for one line).

    Stored on the block so the paginator can apply the rule measured on
    WordStar 4 on 2026-08-03: break only when the lines REMAINING are strictly
    fewer than n. Exactly n remaining is enough room and does not break."""
    m = _DOT_NUM_RE.match(cmd[3:])
    if not m:
        return 1
    try:
        return max(1, int(float(m.group(1))))
    except (TypeError, ValueError):
        return 1


def _parse_page_dot(cmd: bytes, page: dict, meta_extra: dict):
    """Try to interpret one dot-command line as page geometry (.pl/.po/.mt/.mb)
    or a WordTsar-invented command (.PT/.PSA/.PSB -- "not a Wordstar command"
    per WordTsar's own source, so their mere presence is a producer signal).
    Mutates `page` (first occurrence per command wins -- WordStar dot commands
    are stateful and could recur mid-document, but one resolved answer per
    document is what a consumer needs; see EXTENDING.md/report) and
    `meta_extra` for producer-related findings. The line is ALWAYS also kept
    verbatim in doc.meta['dot_commands'] by the caller, recognised or not --
    this function only adds interpretation on top, never replaces preservation.

    .F#/.E# (same spec) set the footnote/endnote starting numbering value --
    the two-character command NAME itself ends in the literal '#' (like
    .L# line-numbering), which the generic [A-Za-z]{1,3} matcher below can't
    match, so it's handled directly first. Best-effort: only the NUMERIC
    starting-value form is modelled (doc.meta['footnote_number_start']/
    ['endnote_number_start'] -- the hook emit.py's per-kind note numbering
    already reads, so this makes it live rather than only defaulting to 1).
    A bare D/P consecutive-vs-restart-per-page mode argument is preserved
    verbatim in dot_commands but not modelled -- doing that correctly needs
    per-page state at PARSE time, before pagination exists."""
    head = cmd[1:3].upper()
    if head in (b'F#', b'E#'):
        which = 'footnote' if head == b'F#' else 'endnote'
        key = which + '_number_start'
        rest = cmd[3:]
        if key not in meta_extra:
            num = _DOT_NUM_RE.match(rest)
            if num and num.group(1):
                meta_extra[key] = int(float(num.group(1)))
        # C12: the MODE, which was read past and dropped. A numeric argument sets
        # the START value (handled above); the keyword forms say how numbering
        # RUNS -- `page` restarts on every page, `continuous`/`consecutive` does
        # not. A document that restarts per page numbered straight through, which
        # is a visible difference on paper and not a diagnostic-only one.
        #
        # Recorded rather than acted on: restarting per page needs pagination,
        # which does not exist at parse time. This is what pagination would read.
        low = rest.strip().lower()
        if low.startswith(b'page'):
            meta_extra[which + '_number_mode'] = 'page'
        elif low.startswith((b'cont', b'consec')):
            meta_extra[which + '_number_mode'] = 'continuous'
        return
    m = _DOT_CMD_RE.match(cmd)
    if not m:
        return
    name = m.group(1).upper()
    arg = m.group(2)
    key = _PAGE_DOT_KEYS.get(name)
    if key is not None:
        if page.get(key) is not None:
            return                                    # first occurrence wins
        num = _DOT_NUM_RE.match(arg)
        if not num or not num.group(1):
            return
        value = float(num.group(1))
        unit = num.group(2)
        resolver = _PAGE_DOT_RESOLVERS.get(key, _resolve_lines_arg)
        resolved = resolver(value, unit)
        if resolved is not None:                      # junk argument: default stands
            page[key] = resolved
    elif name in (b'PT', b'PSA', b'PSB'):
        # WordTsar's own invented dot commands (its source calls them "not a
        # Wordstar command"). A real WordStar file never contains these --
        # their presence IS the producer signal. `variant` stays what it is
        # (the ENCODING, still WS5+/7); this is provenance, not format.
        meta_extra['producer'] = 'wordtsar'
        num = _DOT_NUM_RE.match(arg)
        value = float(num.group(1)) if num and num.group(1) else None
        if name == b'PSA' and value is not None and 'space_after_lines' not in meta_extra:
            meta_extra['space_after_lines'] = value       # best-effort: honoured as
        elif name == b'PSB' and value is not None and 'space_before_lines' not in meta_extra:  # data only --
            meta_extra['space_before_lines'] = value       # no paragraph-spacing model exists yet
        elif name == b'PT' and 'pt_raw' not in meta_extra:
            # A Qt QPageSize enum index -- meaningless outside Qt and liable
            # to shift between Qt versions. Record it verbatim; do NOT
            # hardcode a mapping nobody has verified against Qt's own enum.
            meta_extra['pt_raw'] = arg.decode('latin-1', 'replace').strip()

def _font_entry(w, h, style, offset):
    """One doc.fonts entry from the three words every WordStar font carries
    (width in 1/1800in, height in 1/1440in, typestyle). Two producers: the
    inline type-2 Font block, and a paragraph style record's own font field --
    the SAME three words in the same order, so the same decode."""
    return {
        'offset': offset,
        'width_1800': w,
        'height_1440': h,
        'points': h / 20.0,           # 1/1440in == 1/20pt exactly
        'cpi': (1800.0 / w) if w else None,
        'typestyle': style,
        # High seven bits, per the spec's own bit table.
        'proportional': bool(style & 0x8000),
        'letter_quality': bool(style & 0x4000),
        'symbol_map': ('cp437', 'cp850', 'math',
                       'symbols')[(style >> 12) & 0x03],
        'generic_style': ('sans', 'serif', 'script',
                          'display')[(style >> 10) & 0x03],
        'typestyle_number': style & 0x01FF,
        # the spec's own 245-entry name table (typestyles.py);
        # None for numbers the table doesn't carry
        'typestyle_name': TYPESTYLE_NAMES.get(style & 0x01FF),
    }


def _decode_spans(raw: bytes, strip_hibit: bool, encoding: str, active: set,
                  unknown: dict, fn_counter: list = None, fnref_at=(),
                  font_at=(), fonts=(), pctl_at=(), colour_at=()) -> list:
    """One physical line of bytes -> list of Span. `active` persists across lines
    (WordStar styles span line breaks).

    `fnref_at` holds the OFFSETS within this line at which a note reference
    belongs. They used to be an in-band sentinel byte, but every byte available
    for one is a real WordStar control code -- SENT_FNREF sat on 0x00, which the
    spec assigns to ^@ "fix the print position" and which occurs 2328 times in
    five archive documents. A literal one was read as a note reference to a note
    that does not exist. `fn_counter` (ws5+ only) numbers them.
    """
    spans, buf = [], bytearray()

    def flush():
        if buf:
            text = buf.decode(encoding, 'replace')
            # A byte set in Symbol/ZapfDingbats is a GLYPH INDEX, not styled
            # text: transliterate through the font's own encoding into real
            # Unicode (symbolmap.py), after which no font is required at all.
            fidx = next((int(t[4:]) for t in active if t.startswith('font')), None)
            if fidx is not None and fidx < len(fonts):
                kind = font_translit_kind(fonts[fidx])
                if kind:
                    text = transliterate(text, kind)
            spans.append(Span(text, frozenset(active)))
            buf.clear()

    pending = sorted(fnref_at)
    # font changes, as (rel_offset, doc.fonts index): a change flushes the
    # current span and swaps the active fontN tag, so every following span
    # carries its font until the next change (active persists across lines)
    pending_fonts = sorted(font_at)
    # colour changes, same mechanism as fonts: swap the active colourN tag
    pending_colours = sorted(colour_at)
    # 0x0F user print controls, as (rel_offset, hmi_1800, byte_count): the
    # display string is decoded as ONE span tagged 'pctl<hmi>', so printed
    # renderers can replace it with the width the control declares while
    # reading modes show it verbatim.
    pending_pctl = sorted(pctl_at)
    i = 0
    while i < len(raw) or pending or pending_fonts or pending_colours:
        while pending_pctl and pending_pctl[0][0] <= i < len(raw):
            _, hmi, count = pending_pctl.pop(0)
            flush()
            text = raw[i:i + count].decode(encoding, 'replace')
            spans.append(Span(text, frozenset(active | {'pctl%d' % hmi})))
            i += count
        while pending_fonts and pending_fonts[0][0] <= i:
            _, fidx = pending_fonts.pop(0)
            flush()
            for t in [t for t in active if t.startswith('font')]:
                active.discard(t)
            active.add(f'font{fidx}')
        while pending_colours and pending_colours[0][0] <= i:
            _, cnum = pending_colours.pop(0)
            flush()
            for t in [t for t in active if t.startswith('colour')]:
                active.discard(t)
            if cnum:                        # colour 0 = Black, the default:
                active.add(f'colour{cnum}')  # no tag, so fontless output and
                                             # every all-black document is
                                             # byte-identical to before
        # A note reference sits BETWEEN bytes, so emit any that fall here before
        # decoding the byte at this offset.
        while pending and pending[0] <= i:
            pending.pop(0)
            if fn_counter is not None:
                flush()
                fn_counter[0] += 1
                spans.append(Span(str(fn_counter[0]),
                                  frozenset(active | {'sup', 'fnref'})))
        if i >= len(raw):
            break
        # WS4's bit-7-on-last-letter applies to CONTROL TOGGLES too (a word ending
        # at a style boundary yields e.g. 0x94 = ^T|0x80) — so mask BEFORE dispatch,
        # or high-bit toggles leak into text and styles never close.
        b = raw[i] & 0x7F if strip_hibit and raw[i] >= 0x80 else raw[i]
        if b == 0x1B and i + 1 < len(raw):        # extended char escape
            # <1B x 1C>: x is a CHARACTER TO DISPLAY, any value 00h-FFh
            # (WSFORMAT). For x in the control range that means the cp437
            # GLYPH at that position -- the smiley/arrow/music graphics --
            # never the control action: ASCIITAB.WS wraps every control
            # code to PRINT the chart, and emitting the raw byte put
            # literal tabs and CRs inside its table rows.
            x = raw[i + 1]
            if x < 0x20 or x == 0x7F:
                flush()
                spans.append(Span(CP437_GRAPHICS[x], frozenset(active)))
            else:
                buf.append(x)
            i += 2
            continue
        if b in WS_TOGGLES:
            flush()
            style = WS_TOGGLES[b]
            (active.remove if style in active else active.add)(style)
        elif b == 0x01:                           # ^PA: printer's ALTERNATE font
            flush()
            active.add('altfont')
        elif b == 0x0E:                           # ^PN: back to the normal font
            flush()
            active.discard('altfont')
        elif b == 0x0F:
            buf.append(0x20)                      # binding space
        elif b == 0x1E:
            pass                                  # inactive soft hyphen
        elif b == 0x1F:
            buf.append(0x2D)                      # active soft hyphen
        elif b == 0x09:
            buf.append(b)
        elif b == 0xA0 and not strip_hibit:
            # WS5+ soft space: justification/alignment padding WordStar
            # re-stamps at print time (615 bare A0s across the corpus, all
            # in layout contexts -- BOOKLET.WS alone has 296 rendering as
            # 'á'). A REAL á is carried as the wrapped triple <1B A0 1C>,
            # which the escape branch above already decodes through cp437.
            # WS4 needs nothing: its soft spaces are 0x20|0x80 and the bit-7
            # mask restores them.
            buf.append(0x20)
        elif b < 0x20 or b == 0x7F:
            if b not in WS_DROP:
                unknown[b] = unknown.get(b, 0) + 1
        else:
            buf.append(b)
        i += 1
    flush()
    return spans

# Sentinels injected into the cleaned stream. They must be bytes that CANNOT
# occur as content, or a document's own byte gets mistaken for one.
#
# SENT_FNREF was 0x07 until 2026-08-03. 0x07 is ^G, WordStar's phantom rubout --
# rare and print-time-only by 1990, but REAL, and a literal one in a WS5+ body
# was read as a note reference. Out-of-range degraded gracefully; an IN-range
# collision silently attached the WRONG footnote to a piece of body text. Moved
# to 0x00. NUL is not text in a WordStar body -- the format terminates on 0x1A
# and never emits a NUL as content -- and unlike 0x1B (the extended-character
# escape, tried first and rejected) nothing downstream consumes it.
# RETIRED 2026-08-04. These were IN-BAND SENTINEL BYTES injected into the cleaned
# stream, and every byte available for one is a real WordStar control code:
#
#   0x00  ^@  fix the print position      2328 occurrences in 5 archive documents
#   0x0B  ^K  index marker                  21 occurrences in 3
#   0x11  ^Q  custom print control          37 occurrences in 5
#
# A literal ^K produced a page break the author never wrote. SENT_FNREF was moved
# ONTO 0x00 earlier the same week, on the reasoning that "NUL is not text in a
# WordStar body" -- the spec says 0x00 is ^@, so that move traded a rare clash
# (^G, phantom rubout) for a common one.
#
# Structure now travels as OFFSETS in a `marks` map, which is what `tab_at`
# already did; its own comment read "that lesson is cheap to apply here", and it
# had not been applied backwards. The names are kept only so an external caller
# importing them fails loudly rather than silently reading a stale constant.
SENT_FNREF = None
SENT_SOFTPAGE = None
SENT_HEADING = None

# Symmetrical-sequence "Notes" types (WordStar 7.0 file format spec, WordStar
# International, 1992): 3 Footnote, 4 Endnote, 5 Annotation, 6 Comment. All
# four are rendered inline via a reference marker except comments, which
# WordStar never prints -- they're only reachable through the model.
NOTE_KINDS = {0x03: 'footnote', 0x04: 'endnote', 0x05: 'annotation', 0x06: 'comment'}

def _strip_dot_commands(raw: bytes, encoding: str):
    """Split note text into physical lines (the same hard-return bytes the
    body splits on) and pull any dot-command lines out of it -- a note can
    carry its own dot commands (a .rr ruler, a '..' comment line) exactly
    like the body can, and the body already never renders those as text.
    Unrecognised dot commands are kept verbatim, in order, not dropped;
    surviving text lines are cleaned the same way note text always was and
    rejoined with a space (notes are short callouts, not reflowed prose)."""
    lines = re.split(rb'\x8d\x0a|\x0d\x0a|\x8d|\x0d|\x0a', bytes(raw))
    kept, dots = [], []
    for line in lines:
        stripped = bytes(b & 0x7F for b in line)      # same masking the body uses
        if stripped[:1] == b'.':
            dots.append(stripped.rstrip().decode(encoding, 'replace'))
            continue
        clean = bytes(c for c in line if 0x20 <= c < 0x7F or c >= 0x80 or c == 0x09)
        piece = clean.decode(encoding, 'replace').strip()
        if piece:
            kept.append(piece)
    return ' '.join(kept), dots

def _parse_note(cmd: int, content: bytes, offset: int, encoding: str) -> Note:
    """Decode one note block's content (the bytes between the type byte and
    the closing count+0x1D), per the spec's Notes section:

        Word: line count of the note text
        Word: offset to the internal tag sequence (high bit set -> low 15
              bits are the offset) OR the note number itself (high bit clear)
        Byte: conversion flag (used only when there is no internal tag) --
              low nybble = target type if converted (0 = not converted),
              high nybble = numbering format (0 symbols,1 upper,2 lower,3 numeric)
        Remaining bytes: the note text, which may itself hold ONE nested
              symmetrical sequence (the internal tag, or a font change) --
              spec: "Currently only one level of this recursion is used."

    The tag/conversion-flag word and the internal tag mean different things
    per kind, though: only footnotes/endnotes carry a NUMBER (the spec is
    explicit that annotations'/comments' equivalent fields are "not used").
    Annotations instead carry a TEXT tag ("the text used to display and
    print the tag of the note") in the very same position a footnote's
    internal tag would carry its number -- so the same nested-sequence walk
    below extracts a number for footnote/endnote and a tag string for
    annotation, and the outer conversion flag is only trusted where the
    spec says it's actually used (not annotations).
    """
    kind = NOTE_KINDS[cmd]
    if len(content) < 5:
        return Note(kind=kind, offset=offset)
    line_count = int.from_bytes(content[0:2], 'little')
    tag_word = int.from_bytes(content[2:4], 'little')
    conv_flag = content[4]
    numeric = kind in ('footnote', 'endnote')
    number = (None if tag_word & 0x8000 else tag_word) if numeric else None
    tag = None
    remainder = content[5:]

    text_bytes = bytearray()
    i = 0
    while i < len(remainder):
        if remainder[i] == 0x1D and i + 3 <= len(remainder):
            jump = int.from_bytes(remainder[i + 1:i + 3], 'little')
            inner = remainder[i + 1:i + 3 + jump]
            inner_cmd = inner[2] if len(inner) > 2 else -1
            if inner_cmd == cmd:                        # the internal tag sequence
                inner_content = inner[3:-3] if len(inner) >= 6 else inner[3:]
                if numeric and len(inner_content) >= 5:
                    number = int.from_bytes(inner_content[2:4], 'little')
                    conv_flag = inner_content[4]
                elif kind == 'annotation' and len(inner_content) > 5:
                    raw_tag = bytes(c for c in inner_content[5:]
                                    if 0x20 <= c < 0x7F or c >= 0x80 or c == 0x09)
                    tag = raw_tag.decode(encoding, 'replace').strip() or None
            i += jump + 3                                # skip the whole nested sequence
        else:
            text_bytes.append(remainder[i])
            i += 1

    text, dots = _strip_dot_commands(bytes(text_bytes), encoding)
    if kind == 'annotation':
        # spec: "Byte: Conversion flag. Not used for annotations." -- don't
        # report noise from a byte the format documents as meaningless here.
        number_format, convert_to = 0, 0
    else:
        number_format, convert_to = (conv_flag >> 4) & 0x0F, conv_flag & 0x0F
    return Note(kind=kind, text=text, number=number, tag=tag, line_count=line_count,
                number_format=number_format, convert_to=convert_to,
                dot_commands=dots, offset=offset)

# Tabs and dot leaders (symmetrical sequence type 9, WordStar 7.0 file format
# spec): Word tab size in HMIs, Word absolute tab size in HMIs, Byte tab
# type, Byte tab size in tenths. Documented tab-type bytes: ' ' hard tab,
# soft space (0xA0) soft tab, '#' decimal, '!' center, '[' right-align. ']'
# is an UNDOCUMENTED right-align variant -- WordTsar's author found it by
# testing against MicroPro's own PRINT.TST (confirmed present here too: a
# type-9 block with tab type byte 0x5D, ']'). It renders identically to the
# documented '[': same right-align intent, just a second byte value nobody
# wrote down. Any other byte is a dot-leader character (spec: "Other
# character such as '.' or '*' are used for dot leaders.").
#
# HMI -> columns. An HMI is 1/1800 inch (HORTAB.TXT: "an HMI is 1/1800
# inch"; the font block's width word uses the same unit), so one 10-CPI
# column is 1800/10 = 180 HMI. The old value here was 144, derived by
# borrowing VMI's 1/1440in unit for the horizontal axis -- the same unit
# confusion as the font-block word swap, and it made every tab 25% too
# wide. MEASURED against every type-9 block in the archive (3,617 blocks):
# the block's own final byte -- "Tab size in 1/10th" (of an inch, and
# 0.1in IS 180 HMI) -- equals size//180 in all 3,617.
TAB_HMI_PER_COL = 180
TAB_RIGHT_TYPES = {0x5B, 0x5D}      # '[' documented, ']' undocumented -- same rendering

def _tab_columns(content: bytes):
    """Decode one type-9 block's content -> (columns, leader_byte). We can't
    reflow text to truly right/center/decimal-align a tab without knowing the
    width of what follows it -- this pass runs before line/word splitting --
    so those types degrade to plain space padding, but of the CORRECT width
    (from the tab's own HMI size) rather than a guessed constant. Dot-leader
    tabs (any byte outside the documented/undocumented set) repeat their own
    leader character, which is both more correct and directly observable."""
    if len(content) < 5:
        return 4, b' '                                 # malformed/short block: the old
                                                        # fixed-4-spaces behaviour as a
                                                        # safe fallback, never a crash
    size = int.from_bytes(content[0:2], 'little')
    tab_type = content[4]
    cols = max(1, round(size / TAB_HMI_PER_COL))
    if tab_type in (0x20, 0xA0, ord('#'), ord('!')) or tab_type in TAB_RIGHT_TYPES:
        leader = b' '
    elif 0x20 <= tab_type < 0x7F:
        leader = bytes([tab_type])                    # dot-leader character
    else:
        leader = b' '
    return cols, leader

def _symmetric_blocks(data: bytes, encoding: str):
    """Strip WS5+ 1D symmetric sequences (2-byte LE length, command type at +2),
    collecting notes (footnotes/endnotes/annotations/comments, types 3-6) and
    injecting sentinels for the block types that carry document structure.
    Types we don't interpret are preserved as opaque UnknownBlocks rather than
    dropped (project rule: preserve what you don't understand). Verified
    against the 86 WS7 documents in Robert J. Sawyer's WordStar archive.

    Also returns the offsets (into the returned stream) at which TAB-derived
    padding begins -- see lines_pass, which needs to tell a program-emitted
    indent from one the author typed."""
    out = bytearray()
    notes = []
    unknown = []
    graphics = []
    marks = {}
    colours = []
    fonts = []
    includes = []
    header = {}
    shift_runs = []
    shift_open = []
    driver = [None]
    tab_at = set()
    i = 0
    while i < len(data):
        if data[i] == 0x1B and i + 1 < len(data):
            # <1B x> extended-character escape (usually <1B x 1C>): x is DATA,
            # never a block start. Without this, ASCIITAB.WS's wrapped
            # <1B 1D 1C> chart cell read as a block whose overrunning "jump"
            # (the next two chart bytes) swallowed 3.5 KB to end of file.
            # Both bytes pass through for _decode_spans to render.
            out.append(data[i])
            out.append(data[i + 1])
            i += 2
            continue
        if data[i] == 0x1D and i + 3 <= len(data):
            start = i
            jump = int.from_bytes(data[i + 1:i + 3], 'little')
            end = i + 2 + jump
            if not (jump >= 4 and end < len(data) and data[end] == 0x1D
                    and int.from_bytes(data[end - 2:end], 'little') == jump):
                # A 0x1D whose framing does not close is NOT a block -- the
                # count must echo and the bracket must be there. The spec says
                # a bare 0x1D "should not appear in files"; WordStar itself
                # TRUNCATES the file when fooled by one (engineering note
                # 650, "false symmetrical sequences"). Skipping the byte
                # keeps the document.
                i += 1
                continue
            block = data[i + 1:i + 3 + jump]
            cmd = block[2] if len(block) > 2 else -1
            if cmd in NOTE_KINDS:
                content = block[3:-3] if len(block) >= 6 else block[3:]
                notes.append(_parse_note(cmd, content, start, encoding))
                # Comments included (ruling 2026-08-06): every note kind now
                # emits a reference mark so consumers know WHERE it lives --
                # Show Invisibles needs the position, RTF anchors its margin
                # comment there. WordStar printed nothing for a comment and
                # printed mode still renders nothing; the mark is position,
                # not ink.
                marks.setdefault(len(out), []).append(('fnref',))
            elif cmd == 0x09:                                     # tab (and dot leaders)
                content = block[3:-3] if len(block) >= 6 else block[3:]
                cols, leader = _tab_columns(content)
                # Remember that this padding came from a TAB, not from typed
                # spaces. Recorded as an offset into the CLEANED stream, which
                # is exactly what lines_pass then scans, so the mark stays
                # aligned without injecting a sentinel byte -- today's other
                # sentinel (0x07) collided with a real WordStar code, and that
                # lesson is cheap to apply here.
                tab_at.add(len(out))
                out += leader * cols
            elif cmd == 0x0B:                                     # end of page
                # WSFORMAT.TXT: "This sequence should usually be ignored. It's
                # used by the WordStar editor to keep track of page breaks. It
                # is transient, and moves around with the page break." MEASURED
                # on WordStar 7 (2026-08-04): a document printed with and
                # without 0x0B marks produced BYTE-IDENTICAL output -- the
                # print pipeline never looks at them. The block is still parsed
                # (it is real structure, and a viewer may want the editor's
                # last-seen pagination), but NO renderer may treat it as a page
                # break: honouring them changed the page count of 43 archive
                # documents.
                marks.setdefault(len(out), []).append(('softpage',))
            elif cmd == 0x0D:                                     # paragraph number
                # WordStar's AUTOMATIC outline/legal numbering (`.p#`) -- "2.1.3"
                # and the like. Documented layout (WSFORMAT.TXT, "0Dh Paragraph
                # number"):
                #
                #   Byte: level moves FORWARD from the previous number
                #   Byte: level moves BACKWARD
                #   Byte: level number of this paragraph number (1 based)
                #   Word x8: the level counters, 0 BASED
                #   31 bytes: the format string, zero-terminated
                #
                # It is BINARY. An earlier pass here scanned the block for
                # printable-looking bytes and emitted those, on the assumption the
                # number was stored as text -- it is not, and that both emitted
                # nothing for real blocks (the counters are small, below 0x20) and
                # would have injected stray characters for a counter that happened
                # to land in the printable range. The commit that introduced it
                # claimed to have recovered the numbers; it had not.
                #
                # The number is COMPUTED: take the first `level` counters, add one
                # to each (they are 0-based) and join with dots.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                if len(content) >= 3 + 2:
                    level = content[2]
                    parts = []
                    for k in range(min(level, 8)):
                        off = 3 + k * 2
                        if off + 2 > len(content):
                            break
                        parts.append(str(int.from_bytes(content[off:off + 2],
                                                        'little') + 1))
                    if parts:
                        out += '.'.join(parts).encode(encoding, 'replace')
            elif cmd == 0x01:                                     # colour change
                # WSFORMAT.TXT, type 1 Color:
                #     Byte: Color number (see below).
                #     Byte: Previous color in file.
                #
                # CURRENT and PREVIOUS, not foreground and background -- which is
                # what this recorded until 2026-08-04. The palette is named and
                # fixed (0 Black ... 0Fh White on black), so the number resolves
                # to a colour rather than being an opaque index.
                #
                # Recorded, not rendered: the printed page this project reproduces
                # was monochrome. Register C2.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                if len(content) >= 2:
                    colours.append((len(out), content[0], content[1]))
                    # A colour change is a RUN BOUNDARY too: spans carry the
                    # active colour so a driver-aware renderer can honour it
                    # (LJ6DTP maps the palette to grayscale/white knockouts).
                    marks.setdefault(len(out), []).append(
                        ('colour', content[0]))
            elif cmd in (0x02, 0x15):                             # font change
                # WSFORMAT.TXT, type 2 Font -- six little-endian words:
                #     Word: Font width in HMIs  (1/1800ths of an inch)
                #     Word: Font height in VMIs (1/1440ths of an inch)
                #     Word: Typestyle
                #     Word x3: the previous width, height and typestyle
                #
                # WIDTH COMES FIRST. Until 2026-08-04 this read word 1 as the
                # height "in 1/20 point" and word 2 as the width -- swapped. The
                # error survived because 1/1440in IS 1/20 point exactly (1440/72 =
                # 20), so treating the WIDTH word as 20ths-of-a-point produced
                # 9pt, 8pt, 11pt across 862 real blocks: sizes plausible enough
                # that they were cited as confirming the reading. They were the
                # right arithmetic on the wrong word.
                #
                # Register C3. Deliberate for PDF, which is Courier by design;
                # RTF/HTML can express a size change and now have the figures.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                if len(content) >= 6:
                    w = int.from_bytes(content[0:2], 'little')     # HMI, 1/1800in
                    h = int.from_bytes(content[2:4], 'little')     # VMI, 1/1440in
                    style = int.from_bytes(content[4:6], 'little')
                    fonts.append(_font_entry(w, h, style, len(out)))
                    # A font change is a RUN BOUNDARY in the text, not only
                    # metadata: Jon's export review (2026-08-04) found every
                    # RTF in Times because doc.fonts was recorded and never
                    # rendered. Same offset mechanism as every other mark.
                    marks.setdefault(len(out), []).append(('font', len(fonts) - 1))
            elif cmd == 0x0F:                                     # user print control
                # WSFORMAT.TXT, "0Fh User print control":
                #     Word:  number of hmis this sequence uses on the printed page
                #     Byte:  number of characters used for screen display
                #     Text:  the display string itself
                #     "The remaining bytes ... will be sent directly to the printer."
                #
                # This used to scan the whole block for printable bytes and look for
                # a `%F"NAME"` file reference, ignoring the structure entirely. The
                # DISPLAY STRING is real content -- it is what WordStar shows on
                # screen where the control sits, and three archive blocks carry 70
                # characters of it. Dropping it lost text; the file reference is one
                # thing inside the printer payload, not the whole payload.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                if len(content) >= 3:
                    nch = content[2]
                    display = bytes(content[3:3 + nch])
                    printer = bytes(content[3 + nch:])
                    # The display string is CP437 SCREEN TEXT -- LJ6DTP's
                    # rule-drawing controls label themselves with box-drawing
                    # art («Empty ┌00.300"hx...»). Masking bit 7 turned that
                    # into ASCII noise, and worse: a leading « (0xAE) masked
                    # to '.' (0x2E), so the whole line was later swallowed as
                    # a dot command -- 33 of LJ6DTP's 41 controls vanished.
                    shown = bytes(c for c in display
                                  if c >= 0x20 and c != 0x7F).decode(encoding, 'replace')
                    # `%F"NAME"` inside the printer payload names a file the printer
                    # is told to pull in -- same class as an inset graphic.
                    ptext = bytes(c & 0x7F for c in printer
                                  if 0x20 <= (c & 0x7F) < 0x7F).decode(encoding, 'replace')
                    mark = ptext.find('%F')
                    name = ptext[mark + 2:].strip().strip('"') if mark >= 0 else ''
                    if name:
                        includes.append(name)
                        out += b'[include: ' + name.encode(encoding, 'replace') + b']'
                    elif shown.strip():
                        # No file reference, but a display string the editor
                        # shows. SCREEN-ONLY: on paper WordStar sends the raw
                        # printer payload instead and advances by the block's
                        # own HMI word ("number of hmis this sequence uses on
                        # the printed page" -- 0 for LJ6DTP's rule-drawing
                        # controls). The mark carries (hmi, char count) so
                        # printed renderers can swap the string for its
                        # declared width; reading modes keep the string, the
                        # only human-visible trace of what the control does.
                        shown_b = shown.encode(encoding, 'replace')
                        marks.setdefault(len(out), []).append((
                            'pctl', int.from_bytes(content[0:2], 'little'),
                            len(shown_b)))
                        out += shown_b
                    else:
                        # Neither: pure printer bytes. Consuming them silently would
                        # turn a reported unknown into an unreported one.
                        unknown.append(UnknownBlock(cmd, bytes(block), start))
                else:
                    unknown.append(UnknownBlock(cmd, bytes(block), start))
            elif cmd == 0x00:                                     # HEADER sequence
                # WSFORMAT.TXT, type 0 Header -- 128 bytes in total:
                #     Byte:      version number in BCD (50h = Release 5.0,
                #                55h = 5.5, 60h = 6.0)
                #     9 bytes:   null-terminated driver name
                #     2 bytes:   reserved
                #     2 words:   32-bit pointer to the file's style library
                #     107 bytes: reserved
                #
                # This was read as nothing but a driver name. The VERSION BYTE is
                # the more valuable field by far: `detect` infers ws4-vs-ws5+ from
                # byte statistics, and the file states its release outright.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                if content and content[0] in (0x50, 0x55, 0x60, 0x70):
                    header['version_bcd'] = content[0]
                    header['release'] = '%d.%d' % (content[0] >> 4, content[0] & 0x0F)
                if len(content) >= 14:
                    lo = int.from_bytes(content[12:14], 'little')
                    hi = int.from_bytes(content[14:16], 'little') if len(content) >= 16 else 0
                    ptr = (hi << 16) | lo
                    if ptr:
                        header['style_library_offset'] = ptr
                # The name is the leading run of upper-case/digits; the byte before
                # it is a record tag, not part of the name (`pLASERJET`).
                name = bytearray()
                for c in content:
                    ch = c & 0x7F
                    if 0x41 <= ch <= 0x5A or 0x30 <= ch <= 0x39:
                        name.append(ch)
                    elif name:
                        break
                if not name:
                    # An EMPTY 0x00 block is a plain wrapper, not a driver record --
                    # same rule as an 0x0F with no `%F`: consuming it silently would
                    # turn a reported unknown into an unreported one.
                    unknown.append(UnknownBlock(cmd, bytes(block), start))
                elif driver[0] is None:
                    driver[0] = bytes(name).decode(encoding, 'replace')
            elif cmd == 0x17:                                     # Shift-In/Shift-Out
                # WSFORMAT.TXT, "17h Japanese Font Shift-In/Shift-Out":
                #     "Byte: Shift-In (to Japanese) = 1, Shift-Out (Back to
                #      Normal) = 0."
                #
                # A ONE-BYTE MODE TOGGLE, not a container of text. The Japanese
                # bytes live in the ordinary stream BETWEEN a shift-in and the
                # matching shift-out, as double-byte Shift-JIS.
                #
                # This was first implemented as if the block held the text itself,
                # emitting a `[shift-jis: N bytes]` placeholder for the marker --
                # which would have injected a bogus placeholder where a mode marker
                # belongs AND left the real Japanese text to be mangled by the
                # cp437 decoder. Corrected against the spec, which was sitting in
                # the archive the whole time. Register C15.
                #
                # The marker itself emits nothing. The run BETWEEN two markers is
                # lifted out and kept raw.
                #
                # Lifting it is CORRECTNESS, not tidiness. The spec continues:
                # "When shifted in, WordStar no longer uses the 1Bh/1Ch wrap
                # characters and interprets characters using the Asian Character
                # Standard which uses 81h-9Fh and E0h-FEh for a prefix followed by
                # 20-7Fh". _decode_spans treats 1Bh as the extended-character escape
                # UNCONDITIONALLY, so a 1Bh inside a Japanese run would be read as an
                # escape and would swallow the byte after it. Because the run never
                # reaches _decode_spans, that cannot happen.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                shift_in = bool(content and content[0])
                if shift_in:
                    shift_open.append(len(out))
                elif shift_open:
                    start = shift_open.pop()
                    raw = bytes(out[start:])
                    # The bytes are kept, and the STREAM gets a placeholder in their
                    # place. Leaving them in would hand the cp437 decoder double-byte
                    # Shift-JIS and print confident mojibake -- garbage that LOOKS
                    # like text, which is worse than saying plainly that there is
                    # Japanese here this converter cannot render.
                    del out[start:]
                    shift_runs.append((start, raw))
                    out += b'[shift-jis: %d bytes]' % len(raw)
            elif cmd == 0x16:                                     # truncation marker
                # The spec says a truncated line shows a literal marker. Nothing in
                # the WS7 archive contains one, so this is implemented FROM THE SPEC
                # and has never been checked against a file that really has it --
                # recorded here rather than claimed as verified. Register C14.
                out += b'<TRUNCATED>'
            elif cmd == 0x10:                                     # inset graphic
                # An INSET picture placed in the text. The block's content is the
                # image's path, and it was being dropped whole -- filename and all
                # -- so a document with figures rendered as if it had none, with no
                # indication anything was missing. Register C10.
                #
                # A converter cannot render a 1987 .PIX file, but it must not go
                # quiet about one: the path is recorded on the Document and a
                # visible placeholder goes into the text where the picture sat.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                path = bytes(c & 0x7F for c in content
                             if 0x20 <= (c & 0x7F) < 0x7F).decode(encoding, 'replace')
                graphics.append(path)
                name = path.replace('\\', '/').rsplit('/', 1)[-1] or path
                out += b'[image: ' + name.encode(encoding, 'replace') + b']'
            elif cmd == 0x0E:                                     # index item
                # An inline indexed PHRASE. WordStar prints the phrase in the
                # body -- the index ENTRY is the non-printing part -- so
                # dropping the block risks losing text outright when the phrase
                # is not duplicated in the visible stream.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                out += bytes(c & 0x7F for c in content
                             if 0x20 <= (c & 0x7F) < 0x7F)
            elif cmd == 0x11 and len(block) >= 6:                 # paragraph style
                # Four LE16 style HANDLES (WSFORMAT: new / previously selected /
                # previous 'modified' temp / previous-previous). All 1,727 blocks
                # across the archive are exactly 8 content bytes. Only word 0 --
                # the newly selected style -- is joinable: high byte 0x02 tags
                # this file's own library, low byte is the 0-BASED index-item
                # slot in allocation order, DELETED SLOTS COUNTED (validated
                # 60/60 distinct references, 22/22 documents). The 0x03xx pool
                # in word 2 names editing-temp styles that were never written to
                # the file: unresolvable by design, reject rather than mask.
                #
                # The old reading took content[0] alone -- the LOW BYTE of w0 --
                # and mapped three slot numbers to heading levels. Slot numbers
                # carry no semantics: 0x05 resolves to 'Bulleted List' in one
                # document and 'Body copy font' in another, and NOVEL.WS's real
                # H1/H2/H3 styles sat unmapped while its footer style rendered
                # as a heading. Heading meaning now comes from the RESOLVED
                # entry (see parse_ws), never from the slot.
                content = block[3:-3]
                if len(content) == 8:
                    w0 = int.from_bytes(content[0:2], 'little')
                    marks.setdefault(len(out), []).append(('style', w0))
                else:
                    unknown.append(UnknownBlock(cmd, bytes(block), start))
            else:
                unknown.append(UnknownBlock(cmd, bytes(block), start))
            i += jump + 3
        else:
            out.append(data[i])
            i += 1
    # An unterminated shift-in runs to the end of the document: the text is
    # Japanese from there on, and dropping the run would lose that fact entirely.
    while shift_open:
        start = shift_open.pop()
        raw = bytes(out[start:])
        del out[start:]
        shift_runs.append((start, raw))
        out += b'[shift-jis: %d bytes]' % len(raw)
    return (bytes(out), notes, unknown, tab_at, graphics, colours, fonts,
            includes, driver[0], sorted(shift_runs), marks, header)

def _parse_style_library(raw: bytes, base: int, encoding: str = 'cp437'):
    """The paragraph style library at file-absolute offset `base`.

    Layout per WSFORMAT.TXT ("Paragraph style library"), every field validated
    corpus-wide 2026-08-04 (21 documents carrying a library: 194/194 index
    entries, 59/59 style records, zero decode errors):

      master index header (13 bytes at base):
        1A 55, word next-512-block, byte n_objects, word n_alloc,
        word entry_size (102), dword object-index ptr (base-relative, obs. 13)
      object index blocks (chainable):
        byte n_entries, dword next-block link (base-relative, 0 = none), items
      index item, STRIDE 33 -- the spec's own field list sums to 24+1+2+2+4;
      rounding it to 32 desyncs every entry after the first, which is exactly
      the "some entries decode as garbage" symptom the first attempt hit:
        24 bytes name (blank-filled; 24 x 0x3F = unused/deleted slot),
        byte flag (observed 0x02 = has record, 0x00 = none, 194/194),
        2 words internal, dword style-record ptr (base-relative, 0 = none)
      style record (102 bytes): see field reads below.

    Inheritance sentinels, AS OBSERVED against the spec's prose: margins -2
    (0xFFFE); font word0, line height, justification, wrap, spacing, colour -1;
    tab COUNTS are 0xFF when inherited (the spec says 0, the corpus says 0xFF,
    56/118 fields) -- and when the count byte says inherited the 32-word tab
    array holds STALE bytes from prior edit state and must not be read; gate
    on the count byte only.

    A pointer equal to the file length is WordStar's "next available offset"
    default for documents that never defined a style -- not an error, just no
    library (56 of 85 corpus documents)."""
    styles = []
    if not (0 < base <= len(raw) - 13) or raw[base] != 0x1A or raw[base+1] != 0x55:
        return styles

    def word(off, signed=False):
        return int.from_bytes(raw[off:off+2], 'little', signed=signed)

    def sword_none(off, sentinel):
        v = word(off, signed=True)
        return None if v == sentinel else v

    n_alloc = word(base + 5)
    entry_size = word(base + 7)
    block_off = base + int.from_bytes(raw[base+9:base+13], 'little')
    seen_blocks, walked = set(), 0
    while block_off and base <= block_off <= len(raw) - 5 and block_off not in seen_blocks:
        seen_blocks.add(block_off)
        n_here = raw[block_off]
        link = int.from_bytes(raw[block_off+1:block_off+5], 'little')
        item = block_off + 5
        for _ in range(n_here):
            if walked >= n_alloc or item + 33 > len(raw):
                break
            name_raw = raw[item:item+24]
            flag = raw[item+24]
            sptr = int.from_bytes(raw[item+29:item+33], 'little')
            item += 33
            walked += 1
            if name_raw == b'\x3f' * 24:          # unused/deleted slot
                continue
            name = name_raw.decode(encoding, 'replace').rstrip()
            # slot = 0-based position in ALLOCATION ORDER, deleted slots
            # counted -- exactly what a 0x11 handle's low byte indexes
            entry = {'name': name, 'slot': walked - 1}
            rec = base + sptr
            if flag == 0x02 and sptr and rec + entry_size <= len(raw):
                f0 = word(rec, signed=True)
                entry['font'] = None if f0 == -1 else (
                    word(rec), word(rec+2), word(rec+4))
                entry['left_margin_hmi'] = sword_none(rec+10, -2)
                entry['right_margin_hmi'] = sword_none(rec+12, -2)
                entry['para_margin_hmi'] = sword_none(rec+14, -2)
                n_reg, n_dec = raw[rec+18], raw[rec+19]
                if n_reg == 0xFF or n_dec == 0xFF:
                    entry['tabs_hmi'] = None       # inherited; array is stale
                else:
                    n_tabs = min(n_reg + n_dec, 32)
                    entry['tabs_hmi'] = [word(rec+20 + 2*k) for k in range(n_tabs)]
                    entry['decimal_tabs'] = n_dec
                just = int.from_bytes(raw[rec+86:rec+87], signed=True)
                # Spec: "0 means no justification, -1 inherit, 1 right
                # justified, -2 centered, -3 flush right". In WordStar's own
                # vocabulary "right justified" is a JUSTIFIED right edge --
                # i.e. full justification (same term the .oj/.uj docs use);
                # "flush right" is what today reads as right-ALIGNED. Values
                # emitted in this parser's align vocabulary directly.
                entry['justification'] = None if just == -1 else {
                    0: 'left', 1: 'justify', -2: 'center', -3: 'right'
                }.get(just, just)
                wrap = int.from_bytes(raw[rec+87:rec+88], signed=True)
                entry['word_wrap'] = None if wrap == -1 else bool(wrap)
                entry['line_height_vmi'] = sword_none(rec+88, -1)
                ls = int.from_bytes(raw[rec+90:rec+91], signed=True)
                entry['line_spacing'] = None if ls == -1 else ls
                entry['attrs_on'] = word(rec+91)
                entry['attrs_off'] = word(rec+93)
                # The ON word as span styles (spec bit values, given in
                # binary: strikeout=1, doublestrike=10, underline=1000,
                # sub=10000, super=100000, bold=1000000, italic=10000000).
                # Doublestrike -- printing each character twice -- renders
                # as bold, the same degradation every emitter here uses.
                a = entry['attrs_on']
                entry['attrs'] = frozenset(
                    tag for bit, tag in ((0x01, 'strike'), (0x02, 'b'),
                                         (0x08, 'u'), (0x10, 'sub'),
                                         (0x20, 'sup'), (0x40, 'b'),
                                         (0x80, 'i'))
                    if a & bit)
                col = int.from_bytes(raw[rec+95:rec+96], signed=True)
                entry['colour'] = None if col == -1 else col
            styles.append(entry)
        block_off = base + link if link else 0
    return styles


def _style_heading_level(name: str) -> int:
    """Heading level from a RESOLVED style name -- never from the handle's
    slot number, which the corpus proved carries no semantics (NOVEL.WS's
    real H1/H2/H3 styles sat at arbitrary slots while its footer style was
    being rendered as a heading). HEURISTIC tiers, drawn from the archive's
    own style names: exact H1/H2/H3; 'chapter title' / trailing 'Title' ->
    1 (MS Chapter Title); 'subhead' / 'section heading' -> 2 (MS Subhead,
    Section Heading Font). Everything else is a non-heading style: the
    block still carries style_name for consumers with better taxonomy."""
    n = name.strip().lower()
    if n in ('h1', 'h2', 'h3'):
        return int(n[1])
    if 'chapter title' in n or n.endswith(' title') or n == 'title':
        return 1
    if 'subhead' in n or 'section heading' in n:
        return 2
    return 0


def parse_ws(data: bytes, encoding: str = 'cp437') -> Document:
    doc = Document()
    marks = {}
    det = detect(data)
    doc.meta.update(det)
    era = era_for(det['variant'])
    doc.meta['era'] = era.name
    strip_hibit = era.high_bit_wordwrap
    ws5 = era.symmetric_blocks
    # Offsets where WordStar emitted TAB-derived padding. Only WS5+ carries
    # symmetric blocks, so a WS4 file has none and every leading space in one
    # really was typed.
    tab_at = frozenset()
    style_slots = {}
    if ws5:
        raw_file = data           # the style-library pointer is file-absolute
        (data, notes, blobs, tab_at, graphics, colours, fonts,
         includes, driver, shift_runs, marks, header) = _symmetric_blocks(data, encoding)
        if header:
            doc.meta['ws_header'] = header
            ptr = header.get('style_library_offset')
            if ptr:
                doc.styles = _parse_style_library(raw_file, ptr, encoding)
                style_slots = {s['slot']: s for s in doc.styles}
        doc.shift_runs = shift_runs
        doc.graphics = graphics
        doc.colours = colours
        doc.fonts = fonts
        doc.includes = includes
        if driver:
            doc.meta['printer_driver'] = driver
        doc.notes = notes
        doc.unknown_blocks = blobs
        # footnotes/endnotes/annotations are all rendered the same way (a
        # numbered list at the end) and share one inline reference counter
        # below, so `footnotes` stays the flattened view emitters already
        # know how to render; endnotes/annotations are also split out so
        # callers that DO want to tell them apart don't have to re-filter
        # doc.notes themselves. Comments are never rendered inline -- they
        # only ever show up in doc.notes / doc.comments.
        doc.footnotes = [[Span(n.text)] for n in notes if n.kind in
                         ('footnote', 'endnote', 'annotation')]
        doc.endnotes = [[Span(n.text)] for n in notes if n.kind == 'endnote']
        doc.annotations = [[Span(n.text)] for n in notes if n.kind == 'annotation']
        doc.comments = [n for n in notes if n.kind == 'comment']
        # A bare high-bit byte whose low 7 bits are a CONTROL CODE is that
        # control with WordStar's soft/flag bit set, NOT a cp437 glyph.
        # MEASURED on WordStar 7 (2026-08-04, two independent traces): a
        # real document's 0x8A performed a line advance in the printed PCL
        # (zero glyphs -- flagged ^J); an injected 0x94 toggled superscript
        # (flagged ^T, the font size and baseline visibly changed). Real
        # extended characters travel as <1B xx 1C> triples -- the corpus
        # carries 10,000+ of them -- never as bare bytes.
        #
        # Masked by ALLOWLIST, not by range: a blanket 0x80-0x9F mask
        # CREATES structural bytes -- 0x9A becomes 0x1A (EOF: lines_pass
        # truncated a whole novel at its first occurrence), 0x9D becomes
        # 0x1D (block framing). The list is every value observed in real
        # BODY text (pre-EOF, outside blocks and 1B..1C wrappers) plus the
        # oracle-measured 0x94; extend it as evidence arrives. 0x8D/0x8A
        # stay flagged: lines_pass reads them as the soft-return pair.
        # Translation is length-preserving, so recorded offsets (marks,
        # tab_at) stay valid.
        # ... and applied OUTSIDE <1B x 1C> wrapped extended characters: the
        # middle byte is a character to display (any value 00h-FFh), so
        # translating it would corrupt wrapped chars that happen to share a
        # flagged value. Triples are opaque three-byte units everywhere
        # between the block walk and span decode. Segment-wise translation
        # preserves length, so offsets stay valid.
        _FLAGGED = bytes((
            {0x82: 0x02,          # flagged ^B bold toggle   (27x in 4 docs)
             0x8C: 0x0C,          # flagged ^L form feed     (20x in 5 docs)
             0x94: 0x14}          # flagged ^T sup toggle    (oracle-measured)
        ).get(b, b) for b in range(256))
        data = b''.join(
            seg if k % 2 else seg.translate(_FLAGGED)   # odd = captured triples
            for k, seg in enumerate(re.split(rb'(\x1b.\x1c)', data, flags=re.S)))

    physical, margin = lines_pass(data, tab_at, marks, soft_is_wrap=ws5,
                                  overprint_cr=True)
    doc.meta['margin_estimate'] = margin

    active, unknown, dots, dot_at = set(), {}, [], []
    # Always live, not ws5-only: dot-line comments ('..'/'.ig') exist in WS4
    # files too and now emit reference marks (ruling 2026-08-06)
    fn_counter = [0]
    # Running FORMATTING state (`.oc`/`.oj`/`.aw`/`.ul`/`.sb`/`.ps`/`.kr`), stamped
    # onto each block as it opens. Stateful, unlike page geometry -- see
    # `_parse_format_dot`.
    fmt = {}
    # Formatting from the ACTIVE paragraph style. A 0x11 selection applies
    # from its paragraph ON, until the next selection -- WordStar keeps the
    # selected style in force, and real documents switch back explicitly
    # (NOVEL.WS re-selects 'MS Body Copy' after every heading). Only fields
    # the style's record sets non-inherited appear here; everything else
    # falls back to the running dot-command state.
    style_fmt = {}

    # A style record's font field is a full (width, height, typestyle) triple
    # -- the same three words as an inline type-2 Font block, and WordStar
    # applies it the same way: selecting the style CHANGES THE ACTIVE FONT.
    # Left unapplied, the last inline font block bleeds across every
    # style-governed paragraph that follows -- LJ6DTP's Univers body copy
    # rendered at Courier's 7.2pt fixed pitch, pushing its 93-character
    # proportional lines 10 inches wide (Jon's page-width finding,
    # 2026-08-05). Styles that carry no font (recordless, or the record's
    # inherited -1) change nothing: 'inherit' means keep what is in force.
    style_font_cache = {}

    def _style_font(fs):
        idx = style_font_cache.get(fs)
        if idx is None:
            for j, f in enumerate(doc.fonts):
                if (f['width_1800'], f['height_1440'], f['typestyle']) == fs:
                    idx = j
                    break
            else:
                doc.fonts.append(_font_entry(fs[0], fs[1], fs[2], None))
                idx = len(doc.fonts) - 1
            style_font_cache[fs] = idx
        return idx

    def _new_block():
        return Block('para',
                     align=style_fmt.get('align') or _align_now(fmt),
                     wrap=style_fmt.get('wrap', fmt.get('wrap', True)),
                     left_margin=style_fmt.get('left_margin', fmt.get('left_margin')),
                     right_margin=style_fmt.get('right_margin', fmt.get('right_margin')),
                     para_margin=style_fmt.get('para_margin', fmt.get('para_margin')),
                     columns=fmt.get('columns'),
                     column_gutter=fmt.get('column_gutter'),
                     heading=style_fmt.get('heading', 0),
                     style_id=style_fmt.get('style_id'),
                     style_name=style_fmt.get('style_name'),
                     style_attrs=style_fmt.get('attrs', frozenset()))

    cur = _new_block()
    cur_line = Line()
    ruler = False
    page, meta_extra = {}, {}

    def close_line():
        nonlocal cur_line
        if cur_line.spans:
            # The `.lh` in force AS THIS LINE ENDS -- a dot command sits on its
            # own line, so `fmt` cannot change part-way through a text line.
            # Absolute here (WordStar's own 8/48 until the file says otherwise);
            # normalised against the document default once that is known, below.
            cur_line.lead_48 = fmt.get('lead_48', DEFAULT_LH_48)
            cur.lines.append(cur_line)
        cur_line = Line()

    def close_block():
        nonlocal cur
        close_line()
        if cur.lines:
            doc.blocks.append(cur)
        cur = _new_block()

    pending_marks = []      # dot-line comment marks awaiting a content line
    for raw, sep, line_marks in physical:
        stripped = bytes(b & 0x7F for b in raw)
        # A line that BEGINS with a 0x0F print control's display string is
        # content, not a dot command -- but its first character is often «
        # (0xAE), which the WS4 bit-7 masking above turns into '.' (0x2E).
        # 33 of LJ6DTP's 41 rule-drawing controls sat line-initial and were
        # swallowed whole as unknown dot commands.
        pctl_leads = any(r == 0 and m[0] == 'pctl' for r, m in line_marks)
        if stripped[:1] == b'.' and not pctl_leads:  # dot command line
            cmd = stripped.rstrip()
            dots.append(cmd.decode(encoding, 'replace'))
            # Where in the document this command sat. `dot_commands` is a flat
            # list with no anchor, so a consumer that wants to SHOW a dot
            # command in place -- Soft Return.app's Show Invisibles -- has
            # nowhere to put the mark. Recording (block index, line index within
            # that block) costs nothing and is the coarsest anchor that is
            # actually stable: it survives reflow, which a byte offset does not.
            dot_at.append((len(doc.blocks), len(cur.lines), cmd.decode(encoding, 'replace')))
            # '..' and '.ig' are COMMENT lines (ruling 2026-08-06): both
            # WordStar comment syntaxes unify into Note(kind='comment'),
            # each emitting a reference mark at its own position -- the
            # text is kept verbatim after the syntax (a commented-out
            # `..rm 60` is still a comment; `origin` says which syntax
            # carried it, so a consumer can explain odd-looking entries).
            # doc.notes must stay in reference-emission order, so the note
            # is INSERTED at the count of marks already numbered.
            if cmd[:2] == b'..' or cmd[1:3].upper() == b'IG':
                is_dotdot = cmd[:2] == b'..'
                cnote = Note(kind='comment',
                             text=(cmd[2:] if is_dotdot else cmd[3:])
                             .decode(encoding, 'replace').strip(),
                             origin='..' if is_dotdot else '.ig')
                doc.notes.insert(fn_counter[0], cnote)
                fn_counter[0] += 1
                # DEFERRED attachment: the mark rides at the head of the
                # next CONTENT line. Appending to cur_line here would let a
                # following blank line close a phantom line holding only the
                # mark -- one extra printed line WordStar never had.
                pending_marks.append(Span(str(fn_counter[0]),
                                          frozenset({'sup', 'fnref'})))
            if cmd[1:3].upper() in DOT_PAGEBREAK:
                close_block()
                doc.blocks.append(Block('pagebreak'))
            elif cmd[1:3].upper() == DOT_CONDPAGE:
                # Carry the requested line count to the paginator. Measured on
                # WordStar 4 (2026-08-03): it breaks only when the lines
                # REMAINING on the page are strictly fewer than n -- exactly n
                # remaining is enough room and does not break.
                close_block()
                blk = Block('condpage')
                blk.heading = _cp_lines(cmd)
                doc.blocks.append(blk)
            if cmd[1:2].lower() == b'r' and b'!' in cmd:
                ruler = True
            # Header/footer TEXT is content, not command syntax: hand it the
            # UNMASKED line. The bit-7 mask that protects WS4 command letters
            # corrupts 8-bit argument text -- LJ6DTP's `.h1` carries a wrapped
            # <1B F9 1C> middle dot whose F9 masked to 0x79, printing a 'y'
            # beside every page number. WS4 (strip_hibit) keeps the mask: its
            # flag bits really do ride on argument letters.
            _parse_head_foot(cmd if strip_hibit else raw.rstrip(), doc,
                             encoding,
                             anchor=len(doc.blocks) + (1 if cur.lines or
                                                       cur_line.spans else 0))
            # The index of the block this entry POINTS AT -- the one that follows it,
            # which is the block still open (if it has content) or the next to open.
            # "This heading is in the table of contents" refers forward, not back.
            inserted = _parse_collect_dot(
                cmd, doc, encoding,
                len(doc.blocks) + (1 if cur.lines or cur_line.spans else 0))
            if inserted:
                # `.fi` sits BETWEEN paragraphs in the printed result, so the text
                # before it has to be closed out first or the marker jumps to the
                # front of the document.
                close_block()
                doc.blocks.append(Block('para', lines=[
                    Line([Span('[insert: %s]' % inserted, frozenset())])]))
            # A formatting change starts a NEW block: `.oc on` mid-paragraph means
            # the lines after it are centred and the ones before it are not, and a
            # single block cannot hold both.
            before = _block_format(fmt)
            _parse_format_dot(cmd, fmt)
            if _block_format(fmt) != before:
                close_block()
            _parse_page_dot(cmd, page, meta_extra)
            continue
        # A LITERAL form feed is a page break, in any variant. WSFORMAT.TXT:
        # "0Ch ^L  Form Feed.  At print time causes page to be ejected.  No footer
        # lines are printed."
        #
        # parse_printstream has always honoured it; parse_ws did not, so a WS
        # document carrying ^L had its two pages run together into one paragraph
        # and the only trace was an "unknown code 0x0c" line in --diagnose. The
        # break was simply lost. Found by diffing all 32 low-order codes against
        # the spec, 2026-08-04.
        if 0x0C in raw:
            # split on BARE form feeds only -- a wrapped <1B 0C 1C> is the
            # cp437 glyph at 0x0C (the chart cell in ASCIITAB.WS), never a
            # page eject
            parts = _split_bare_ff(raw)
            for n, part in enumerate(parts):
                if n:
                    close_block()
                    doc.blocks.append(Block('pagebreak'))
                if part:
                    spans = _decode_spans(part, strip_hibit, encoding, active,
                                          unknown, fn_counter)
                    if pending_marks and spans:
                        cur_line.spans.extend(pending_marks)
                        pending_marks = []
                    for sp in spans:
                        cur_line.spans.append(sp)
            raw = b''
        # Structural marks, carried as OFFSETS rather than injected bytes -- every
        # byte the old sentinels used (0x00 ^@, 0x0B ^K, 0x11 ^Q) is a real
        # WordStar control code that occurs in real documents, so a literal one
        # was read as a page break, a heading or a note reference that the author
        # never wrote. See `_symmetric_blocks`.
        fnref_at = []
        font_at = []
        pctl_at = []
        colour_at = []
        for rel, m in line_marks:
            if m[0] == 'softpage':
                # NOT a block, NOT a break: the editor drops these wherever the
                # page currently ends, including mid-paragraph, so closing the
                # block here severed real paragraphs. See the 0x0B parse site
                # for the measurement.
                cur_line.softpage = True
            elif m[0] == 'style':
                # Resolve the handle against the file's own library. Pool tag
                # 0x02 = this file; anything else (0x03xx editing temps) is
                # unresolvable BY DESIGN and left unstyled rather than guessed.
                # Heading level comes from the RESOLVED NAME -- the corpus
                # proved slot numbers carry none (see the 0x11 parse site).
                # The selection PERSISTS: style_fmt stays in force for every
                # following block until the next 0x11. A recordless entry
                # (the inherit-everything base, e.g. 'WordStar Defaults')
                # resets formatting to the dot-command state by construction,
                # since it contributes no record fields.
                w0 = m[1]
                if (w0 >> 8) == 0x02:
                    slot = w0 & 0xFF
                    entry = style_slots.get(slot)
                    style_fmt.clear()
                    style_fmt['style_id'] = slot
                    if entry is not None:
                        style_fmt['style_name'] = entry['name']
                        style_fmt['heading'] = _style_heading_level(entry['name'])
                        if entry.get('justification') in ('left', 'justify',
                                                          'center', 'right'):
                            # 'left' means EXPLICIT no-justification -- it
                            # overrides a running .oj, so it must occupy the
                            # align slot rather than fall through
                            style_fmt['align'] = entry['justification']
                        if entry.get('word_wrap') is not None:
                            style_fmt['wrap'] = entry['word_wrap']
                        for src_k, dst_k in (('left_margin_hmi', 'left_margin'),
                                             ('right_margin_hmi', 'right_margin'),
                                             ('para_margin_hmi', 'para_margin')):
                            hmi = entry.get(src_k)
                            if hmi is not None:
                                # HMI 1/1800in -> print columns at 10 CPI,
                                # the unit .lm/.rm already use (180 = 1 col)
                                style_fmt[dst_k] = round(hmi / 180)
                        if entry.get('attrs'):
                            style_fmt['attrs'] = entry['attrs']
                        # an all-zero triple records NO font (OLDTIMES's
                        # 'Double-Indented Quote'), distinct from the -1
                        # inherit sentinel only in never having been set
                        if entry.get('font') and any(entry['font']):
                            font_at.append((rel, _style_font(entry['font'])))
                    # style_fmt is updated BEFORE this close: the previous
                    # block keeps its old style, the fresh block picks the
                    # new one up from _new_block()
                    close_block()
                else:
                    # 0x03xx temp-pool handle: unresolvable by design, but a
                    # selection is still a block boundary in the file
                    close_block()
            elif m[0] == 'fnref':
                fnref_at.append(rel)
            elif m[0] == 'font':
                font_at.append((rel, m[1]))
            elif m[0] == 'pctl':
                pctl_at.append((rel, m[1], m[2]))
            elif m[0] == 'colour':
                colour_at.append((rel, m[1]))
        spans = _decode_spans(raw, strip_hibit, encoding, active, unknown,
                              fn_counter, fnref_at, font_at, doc.fonts,
                              pctl_at, colour_at)
        if pending_marks and spans:
            # a content line arrived: deferred dot-comment marks land at
            # its head, the position the comment line occupied
            cur_line.spans.extend(pending_marks)
            pending_marks = []
        for s in spans:
            cur_line.spans.append(s)
        if sep == 'wrap':
            # A soft return: a REAL line break on paper (printed mode renders
            # it), just word wrap for reflow (merged_lines joins it back with
            # the space rule that used to live right here). 2.0.0: physical
            # lines are stored; merging is the consumer's choice now.
            if cur_line.spans:
                cur_line.soft = True
                close_line()
            elif cur.lines:
                cur.lines[-1].soft = True          # invisible (toggles-only) line:
                                                    # its softness binds the previous
                                                    # printed line, as the old merge did
        elif sep == 'line':
            close_line()
        elif sep == 'over':
            cur_line.overprint = True
            close_line()
        elif sep.startswith('blank-'):
            # A blank physical line. It is CONTENT in printed mode (it occupied
            # a line on paper) and it does NOT close the block -- the text line
            # before it already carried the 'para' separator if this run was a
            # paragraph boundary. `soft` records which kind it was: `.ls` filler
            # (soft) versus the author's own return (hard).
            close_line()
            blank = Line(spans=[], soft=(sep == 'blank-soft'),
                         lead_48=fmt.get('lead_48', DEFAULT_LH_48))
            if not cur.lines and doc.blocks and doc.blocks[-1].kind == 'para':
                # The text line before this one carried 'para' and already
                # closed its block, so `cur` is empty. On paper this blank
                # FOLLOWS that paragraph -- attach it there, so a paragraph
                # block still starts with text (which callers rely on) and the
                # linear order is unchanged.
                doc.blocks[-1].lines.append(blank)
            else:
                cur.lines.append(blank)
        else:                                      # para / eof
            close_block()
    close_block()

    if pending_marks:
        # trailing dot comments with no content line after them: the marks
        # attach to the END of the last content line (never a phantom line)
        tgt = next((b.lines[-1] for b in reversed(doc.blocks)
                    if b.kind == 'para' and b.lines and b.lines[-1].spans),
                   None)
        if tgt is not None:
            tgt.spans.extend(pending_marks)
        # a comment-only document has no line to anchor to; the notes exist
        # in doc.notes/doc.comments regardless, marks are dropped
    # Dot-line comments were inserted into doc.notes mid-pass; rebuild the
    # convenience view so it covers both origins ('block' and dot-line).
    doc.comments = [n for n in doc.notes if n.kind == 'comment']
    doc.meta['dot_commands'] = dots
    # The formatting commands that are document-wide rather than per-block. Only
    # keys the file actually SET appear, so a consumer can tell "the author asked
    # for portrait" from "nobody said" -- the same provenance rule the page
    # geometry follows. Register C8/C18/C19/C20/C21/C22.
    doc.meta['formatting'] = {
        k: v for k, v in fmt.items()
        if k not in ('centering', 'justify', 'wrap',
                     'left_margin', 'right_margin', 'para_margin',
                     'columns', 'column_gutter',
                     # per-LINE state, and already published twice: as the
                     # document default in meta['page']['lh_48'] and per line
                     # in Line.lead_48. A third copy here would be the LAST
                     # value the file happened to set, which means nothing.
                     'lead_48')}
    # (block, line, text) for each dot command, so a caller can render one in
    # place instead of only knowing that it existed somewhere.
    doc.meta['dot_positions'] = dot_at
    doc.meta['unknown_codes'] = {f'0x{k:02x}': v for k, v in sorted(unknown.items())}
    # Ruler lines mean "fixed-width table" only in the pre-symseq eras: a WS4
    # tab table's alignment exists solely in monospace. In WS5+ a `.rr` ruler
    # is just the editor's tab settings and rides along in practically every
    # styled document -- treating it as columnar forced NOVEL.WS and LJ6DTP.WS
    # (both fully reflowable prose) into physical-line rendering in EVERY
    # modern emitter, which is where Jon's "line wrapping isn't working"
    # screenshots actually came from (the wrap classifier itself was correct).
    doc.meta['columnar'] = ruler and not ws5

    pl_lines = page.get('pl_lines')
    height_in, size_name, pw_in = _resolve_page_size(
        pl_lines if pl_lines is not None else DEFAULT_PL_LINES)
    mt_lines = page.get('mt_lines')
    mb_lines = page.get('mb_lines')
    po_cols = page.get('po_cols')
    hm_lines = page.get('hm_lines')
    fm_lines = page.get('fm_lines')
    lh_48 = page.get('lh_48')
    ls = page.get('ls')
    cw_120 = page.get('cw_120')
    # Exposed per the IR contract: a consumer must be able to distinguish
    # "Legal (from file)" from "Letter (default)" -- provenance lives
    # alongside every resolved figure, not just the page size.
    pn_start = page.get('pn_start')
    pc_col = page.get('pc_col')
    doc.meta['page'] = {
        # `.pn n` -- the number of the page it appears on, so a chapter file in
        # a larger manuscript can start where the previous one stopped.
        # MEASURED on WordStar 4: `.pn 7` numbers the pages 7, 8, 9.
        'pn_start': int(pn_start) if pn_start is not None else 1,
        'pn_source': 'file' if pn_start is not None else 'default',
        # `.pc n` -- the column of the AUTOMATIC page number. Measured: it does
        # NOT move a `#` placed inside a header or footer, which prints where
        # the author put it. Two separate mechanisms.
        'pc_col': int(pc_col) if pc_col is not None else None,
        'pc_source': 'file' if pc_col is not None else 'default',
        'pl_lines': pl_lines if pl_lines is not None else DEFAULT_PL_LINES,
        'height_in': height_in,
        'size_name': size_name,
        # width is INFERRED from the height (no dot command exists for it);
        # its provenance is therefore the size's provenance
        'pw_in': pw_in,
        'size_source': 'file' if pl_lines is not None else 'default',
        'mt_lines': mt_lines if mt_lines is not None else DEFAULT_MT_LINES,
        'mt_source': 'file' if mt_lines is not None else 'default',
        'mb_lines': mb_lines if mb_lines is not None else DEFAULT_MB_LINES,
        'mb_source': 'file' if mb_lines is not None else 'default',
        'po_cols': po_cols if po_cols is not None else DEFAULT_PO_COLS,
        'po_source': 'file' if po_cols is not None else 'default',
        'hm_lines': hm_lines if hm_lines is not None else DEFAULT_HM_LINES,
        'hm_source': 'file' if hm_lines is not None else 'default',
        'fm_lines': fm_lines if fm_lines is not None else DEFAULT_FM_LINES,
        'fm_source': 'file' if fm_lines is not None else 'default',
        'lh_48': lh_48 if lh_48 is not None else DEFAULT_LH_48,
        'lh_source': 'file' if lh_48 is not None else 'default',
        'ls': ls if ls is not None else DEFAULT_LS,
        'ls_source': 'file' if ls is not None else 'default',
        'cw_120': cw_120 if cw_120 is not None else DEFAULT_CW_120,
        'cw_source': 'file' if cw_120 is not None else 'default',
    }
    # The one derived figure consumers actually need: printed text lines per
    # page, from WordStar's own vertical model (see _text_lines_per_page for
    # the formula and the deliberate exclusions). Defaults -> 55, NOT the 60
    # a naive 1in-margin Letter computation gives.
    doc.meta['page']['text_lines'] = _text_lines_per_page(
        doc.meta['page']['pl_lines'], doc.meta['page']['mt_lines'],
        doc.meta['page']['mb_lines'], doc.meta['page']['lh_48'])
    # Line.lead_48 was recorded absolutely; now that the document default is
    # known, every line that simply agrees with it goes back to None. The field
    # then means what it says -- "this line's lead DIFFERS" -- so the common
    # case (one `.lh`, or none) leaves the whole document clean and an emitter
    # can test one attribute instead of comparing floats on every line.
    #
    # Note the asymmetry this deliberately preserves: the default is the FIRST
    # `.lh` in the file, so lines BEFORE it keep an explicit 8.0 (WordStar's
    # own 6 LPI, which is what they really printed at) rather than being
    # back-dated to a setting that had not happened yet.
    default_lead = doc.meta['page']['lh_48']
    varying = False
    for blk in doc.blocks:
        for ln in blk.lines:
            if ln.lead_48 == default_lead:
                ln.lead_48 = None
            elif ln.lead_48 is not None:
                varying = True
    # One flag so a consumer (and the diagnostics) can say "this document
    # changes its leading" without walking every line.
    doc.meta['page']['lh_varies'] = varying
    if meta_extra:
        doc.meta.update(meta_extra)
    return doc

# ---------------------------------------------------------------- print streams

# Empirically derived from a late-80s dot-matrix driver (see README); pass a
# custom table if your printer differed.
PRINT_CODES = {0x18: ('sup', True), 0x12: ('sup', False),
               0x10: ('u', True), 0x11: ('u', False),
               0x13: ('i', True), 0x15: ('i', False),
               0x05: ('i', True), 0x06: ('i', False),
               0x1E: ('b', True), 0x1F: ('b', False)}

def _detect_comment_bug(data: bytes):
    """COMMENT.BUG: a documented WordStar bug (Sawyer, WS archive REF notes,
    2013) -- a document containing ^ONC comments, printed to disk with the
    ASCII/ASC256/PRVIEW/WS4 drivers (NOT XTRACT), has everything after the
    comment deleted from that line, may gain a stray ^T (0x14), and the line
    ends with a bare LF (0x0A) instead of CR LF (0x0D 0x0A). This is damage
    WordStar itself introduced at print time in the 1990s -- not a parse
    failure -- so it's reported as a signature, not silently swallowed or
    mistaken for something this tool got wrong.

    Detection is necessarily a heuristic (a bare-LF line ending is the
    documented signature, but a print stream that happens to use plain Unix
    line endings throughout would also match); callers should read the flag
    as "this signature is present", not "this file definitely hit the bug"."""
    count, first, prev = 0, None, -1
    for i, b in enumerate(data):
        if b == 0x0A and prev != 0x0D:
            count += 1
            if first is None:
                first = i
        prev = b
    if not count:
        return None
    return {'count': count, 'first_offset': first, 'stray_ctrl_t': b'\x14' in data}

def parse_printstream(data: bytes, encoding: str = 'cp437',
                      codes: dict = None) -> Document:
    """A print-to-disk capture IS the printed page: every line verbatim, printer
    style codes decoded, everything else below 0x20 stripped."""
    codes = PRINT_CODES if codes is None else codes
    doc = Document(meta={'variant': 'printstream', 'columnar': True})
    cut = data.find(b'\x1a')
    if cut != -1:
        data = data[:cut]
    bug = _detect_comment_bug(data)
    if bug:
        doc.meta['comment_bug'] = bug
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


def effective_page(page, settings):
    """A copy of a doc's resolved page dict with `settings` applied to every
    field the DOCUMENT did not declare itself (its *_source is 'default') --
    the machine layer of the page model: document dot commands > these
    settings > WordStar factory. Shared by the PDF emitter's page_settings
    option and the CLI's --page-settings flag (which mutates doc.meta['page']
    once so ALL emitters, RTF page setup included, see the same page)."""
    eff = dict(page)
    for key, val in settings.items():
        src = key[:2] + '_source'
        if key == 'pl_lines':
            # a page-size override (--page-settings size=...) carries the
            # whole trio: height, name, width recompute from the new .pl
            if eff.get('size_source', 'default') == 'default':
                eff['pl_lines'] = val
                (eff['height_in'], eff['size_name'],
                 eff['pw_in']) = _resolve_page_size(val)
                eff['size_source'] = 'machine-default'
            continue
        if eff.get(src, 'default') == 'default':
            eff[key] = val
            eff[src] = 'machine-default'
    eff['text_lines'] = _text_lines_per_page(
        eff.get('pl_lines', DEFAULT_PL_LINES), eff.get('mt_lines', DEFAULT_MT_LINES),
        eff.get('mb_lines', DEFAULT_MB_LINES), eff.get('lh_48', DEFAULT_LH_48))
    return eff


def trailing_blank_lines(block) -> int:
    """Hard blank lines at the END of a block -- the author's own paragraph
    spacing. merged_lines emits interior blanks and buffers trailing ones
    away; Modern layouts used to paper over the difference with a synthetic
    blank after EVERY block, which invented spacing wherever a dot command
    split the block (ruling 2026-08-06: command codes are invisible -- only
    the author's blank lines make space). Soft blanks are `.ls` filler and
    never count, same as in merged_lines."""
    n = 0
    for line in reversed(block.lines):
        if line.spans:
            break
        if not line.soft:
            n += 1
    return n
