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

    def text(self):
        return ''.join(s.text for s in self.spans)

@dataclass
class Block:
    kind: str                            # 'para' | 'pagebreak' | 'softpage'
    lines: list = field(default_factory=list)
    heading: int = 0                     # 0 = body text; 1-3 = WS5+ title/header/subheading

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
    for line in block.lines:
        if not line.spans:
            # A blank PHYSICAL line (2026-08-03). Printed renders it; reflow
            # does not -- Modern emits its own blank between paragraphs, and a
            # `.ls 2` filler line is typography, not a logical line of text.
            continue
        if cur is None:
            cur = Line(list(line.spans))
        else:
            cur.spans.extend(line.spans)
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
    headers: dict = field(default_factory=dict)       # {1..5: str}
    footers: dict = field(default_factory=dict)       # {1..5: str}
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
    notes: list = field(default_factory=list)         # list[Note], ALL kinds, document order:
                                                       # the authoritative structure; footnotes/
                                                       # endnotes/annotations/comments above are
                                                       # convenience views over this
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
                out.append((text, 'blank-soft' if kind == 'soft' else 'blank-hard'))
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
        # The blanks this run consumed, in document order, after the line they
        # follow. They were counted above to classify `sep` and are now also
        # kept as content -- the counting and the keeping are separate jobs.
        for b in range(i + 1, j):
            btext, bk = lines[b]
            if bk != 'eof':
                out.append((btext, 'blank-soft' if bk == 'soft' else 'blank-hard'))
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
WS_DROP = {0x01, 0x03, 0x0B, 0x0E, 0x10, 0x11, 0x12, 0x15, 0x17, 0x1C}

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


def era_for(variant):
    """The Era for a detected variant. Unknown variants get the WS5+ entry,
    which is the least destructive guess: it does NOT strip high bits, so an
    unrecognised file loses no extended characters."""
    return ERAS.get(variant, ERAS['ws5+'])


_DOT_CMD_RE = re.compile(rb'^\.([A-Za-z]{1,3})\s*(.*)$')
_DOT_NUM_RE = re.compile(rb'^\s*([0-9]*\.?[0-9]+)\s*("|[A-Za-z]{1,2})?')

_PAGE_DOT_KEYS = {b'PL': 'pl_lines', b'MT': 'mt_lines',
                  b'MB': 'mb_lines', b'PO': 'po_cols',
                  b'HM': 'hm_lines', b'FM': 'fm_lines',
                  b'LH': 'lh_48', b'LS': 'ls', b'CW': 'cw_120'}

# Named page sizes at 6 LPI (WordStar 7.0 file format spec: ".PL ... assuming
# 6 lines per inch. An eleven inch page contains 66 lines."): 66 lines/11in
# Letter, 84 lines/14in Legal, 81 lines/13.5in Foolscap Folio (the pre-ISO UK
# long sheet). All three share the same 8.5in width, so only page HEIGHT is
# resolved here -- there is no dot command for physical page width.
NAMED_PAGE_HEIGHTS = (('Letter', 11.0), ('Legal', 14.0), ('Foolscap Folio', 13.5))
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
    if u in (b'P', b'PM'):
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
    usable = pl_lines - mt_lines - mb_lines            # lines at 6 LPI
    if not math.isfinite(usable) or not math.isfinite(lh_48) or lh_48 <= 0:
        return 1
    return max(1, int(usable * 8.0 / lh_48))

def _resolve_page_size(pl_lines: float):
    """pl_lines -> (height_in, size_name). Snaps to a named size when close;
    otherwise reports the raw geometry under 'Custom' rather than forcing a
    label that doesn't fit."""
    height_in = pl_lines / 6.0
    name, named_in = min(NAMED_PAGE_HEIGHTS, key=lambda nh: abs(nh[1] - height_in))
    if abs(named_in - height_in) <= PAGE_SIZE_SNAP_IN:
        return named_in, name
    return height_in, 'Custom'

_HEAD_FOOT_RE = re.compile(rb'^\.(H[E1-5]|F[O1-5])\s?(.*)$', re.I)


def _parse_head_foot(cmd: bytes, doc, encoding: str):
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
    text = m.group(2).decode(encoding, 'replace').rstrip()
    which = doc.headers if tag.startswith(b'H') else doc.footers
    second = tag[1:2]
    line = 1 if second in (b'E', b'O') else int(second)
    which[line] = text


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
        key = 'footnote_number_start' if head == b'F#' else 'endnote_number_start'
        if key not in meta_extra:
            num = _DOT_NUM_RE.match(cmd[3:])
            if num and num.group(1):
                meta_extra[key] = int(float(num.group(1)))
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
SENT_FNREF = 0x00
SENT_SOFTPAGE = 0x0B
SENT_HEADING = 0x11

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
# HMI -> columns: at 1440 units/inch and 10 CPI, one column is 1440/10 = 144
# HMI -- the same derivation the project's footnote-VMI research already
# used for VMI (1440/6 = 240 per line at 6 LPI); treated here as the matching
# inference for the horizontal axis, not a spec-stated constant.
TAB_HMI_PER_COL = 144
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
    against the 86 WS7 documents in Robert J. Sawyer's WordStar archive."""
    out = bytearray()
    notes = []
    unknown = []
    i = 0
    while i < len(data):
        if data[i] == 0x1D and i + 3 <= len(data):
            start = i
            jump = int.from_bytes(data[i + 1:i + 3], 'little')
            block = data[i + 1:i + 3 + jump]
            cmd = block[2] if len(block) > 2 else -1
            if cmd in NOTE_KINDS:
                content = block[3:-3] if len(block) >= 6 else block[3:]
                notes.append(_parse_note(cmd, content, start, encoding))
                if cmd != 0x06:                          # comments: never printed inline
                    out.append(SENT_FNREF)
            elif cmd == 0x09:                                     # tab (and dot leaders)
                content = block[3:-3] if len(block) >= 6 else block[3:]
                cols, leader = _tab_columns(content)
                out += leader * cols
            elif cmd == 0x0B:                                     # end of page
                out.append(SENT_SOFTPAGE)
            elif cmd == 0x0D:                                     # paragraph number
                # WordStar's AUTOMATIC outline/legal numbering (.p#) -- "2.1.3"
                # and the like. It used to fall through to UnknownBlock, which
                # DELETES the computed number from the output entirely: not
                # unstyled, gone. Outline-numbered essays, wills and structured
                # reports lost every generated number with no trace.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                out += bytes(c & 0x7F for c in content
                             if 0x20 <= (c & 0x7F) < 0x7F)
            elif cmd == 0x0E:                                     # index item
                # An inline indexed PHRASE. WordStar prints the phrase in the
                # body -- the index ENTRY is the non-printing part -- so
                # dropping the block risks losing text outright when the phrase
                # is not duplicated in the visible stream.
                content = block[3:-3] if len(block) >= 6 else block[3:]
                out += bytes(c & 0x7F for c in content
                             if 0x20 <= (c & 0x7F) < 0x7F)
            elif cmd == 0x11 and len(block) > 3:                  # paragraph style
                level = {0x05: 1, 0x02: 2, 0x03: 3}.get(block[3], 0)
                if level:
                    out += bytes([SENT_HEADING, 0x30 + level])
            else:
                unknown.append(UnknownBlock(cmd, bytes(block), start))
            i += jump + 3
        else:
            out.append(data[i])
            i += 1
    return bytes(out), notes, unknown

def parse_ws(data: bytes, encoding: str = 'cp437') -> Document:
    doc = Document()
    det = detect(data)
    doc.meta.update(det)
    era = era_for(det['variant'])
    doc.meta['era'] = era.name
    strip_hibit = era.high_bit_wordwrap
    ws5 = era.symmetric_blocks
    if ws5:
        data, notes, blobs = _symmetric_blocks(data, encoding)
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

    physical, margin = lines_pass(data)
    doc.meta['margin_estimate'] = margin

    active, unknown, dots, dot_at = set(), {}, [], []
    fn_counter = [0] if ws5 else None
    cur = Block('para')
    cur_line = Line()
    ruler = False
    page, meta_extra = {}, {}

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
            # Where in the document this command sat. `dot_commands` is a flat
            # list with no anchor, so a consumer that wants to SHOW a dot
            # command in place -- Soft Return.app's Show Invisibles -- has
            # nowhere to put the mark. Recording (block index, line index within
            # that block) costs nothing and is the coarsest anchor that is
            # actually stable: it survives reflow, which a byte offset does not.
            dot_at.append((len(doc.blocks), len(cur.lines), cmd.decode(encoding, 'replace')))
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
            _parse_head_foot(cmd, doc, encoding)
            _parse_page_dot(cmd, page, meta_extra)
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
        elif sep.startswith('blank-'):
            # A blank physical line. It is CONTENT in printed mode (it occupied
            # a line on paper) and it does NOT close the block -- the text line
            # before it already carried the 'para' separator if this run was a
            # paragraph boundary. `soft` records which kind it was: `.ls` filler
            # (soft) versus the author's own return (hard).
            close_line()
            blank = Line(spans=[], soft=(sep == 'blank-soft'))
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

    doc.meta['dot_commands'] = dots
    # (block, line, text) for each dot command, so a caller can render one in
    # place instead of only knowing that it existed somewhere.
    doc.meta['dot_positions'] = dot_at
    doc.meta['unknown_codes'] = {f'0x{k:02x}': v for k, v in sorted(unknown.items())}
    doc.meta['columnar'] = ruler

    pl_lines = page.get('pl_lines')
    height_in, size_name = _resolve_page_size(pl_lines if pl_lines is not None
                                              else DEFAULT_PL_LINES)
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
    doc.meta['page'] = {
        'pl_lines': pl_lines if pl_lines is not None else DEFAULT_PL_LINES,
        'height_in': height_in,
        'size_name': size_name,
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
