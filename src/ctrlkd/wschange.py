"""WSCHANGE .PAT interpreter: WordStar 7's saved-installation-patch format.

WSCHANGE (WordStar's installer/customiser) can dump the machine's current
patch state to a `.PAT` file and re-apply one later. Those dumps are the
closest thing that exists to a WordStar user's "settings file", and the
Sawyer archive carries seven of them -- two full 294-line dumps (factory
and Sawyer's own machine) plus five partial patch sets. The byte-level
decode this module implements lives in
~/vaults/jon_vault/Projects/software/WordStar/readings/INIEDT-full-decode.md
(hereafter "the decode doc"), which mapped the INIEDT struct and the RLRINI
ruler table field-by-field against PATCH.LST's own assembly listing and
sanity-checked every value against the WS7 factory defaults.

The format (decode doc, Method item 2 -- learned the hard way there):
`.PAT` files are NOT raw memory dumps at PATCH.LST addresses. They are
CRLF text: one line per named patch variable, `LABEL=hh,hh,...` with
comma-separated hex byte pairs, long values wrapped across continuation
lines that start with a bare `=`. Items can also be double-quoted ASCII
strings (`NOTYPE="BAK"` -- literal bytes, observed in NOTYPE.PAT; no
quoted item in the corpus contains a comma or an embedded quote, but
commas inside quotes are honoured anyway since splitting there would be
silent corruption). Files are padded to sector size with DOS ^Z (0x1A).

This is library-only plumbing for the machine layer of the page model:
document dot commands > machine settings > WordStar factory
(core.effective_page). The 'sawyer' preset in cli.py was hand-derived
from these very bytes; page_settings() below re-derives it mechanically,
and the tests hold the two against each other.
"""
from __future__ import annotations

# ---------------------------------------------------------------- .PAT text

def _split_items(rest: bytes) -> list:
    """Split one line's value part on commas, except inside double quotes.
    A quoted item is literal ASCII bytes; a comma in one is content."""
    items, cur, in_quote = [], bytearray(), False
    for ch in rest:
        if ch == 0x22:                        # '"'
            in_quote = not in_quote
            cur.append(ch)
        elif ch == 0x2C and not in_quote:     # ','
            items.append(bytes(cur))
            cur = bytearray()
        else:
            cur.append(ch)
    items.append(bytes(cur))
    return items


def parse_pat(data: bytes) -> dict:
    """Parse a WSCHANGE `.PAT` dump into {label: reassembled value bytes}.

    The mapping preserves every label in file order (a PARTIAL patch set
    simply yields a small dict -- subset semantics by construction). A
    repeated label RESTARTS its value, last occurrence winning: both full
    dumps in the archive really do carry `UDATE` twice (lines 1 and 559,
    identical bytes both times -- WSCHANGE stamps the dump date at both
    ends), which is also why "294 labels" in the decode doc is 293 unique
    names here.

    Tolerated: LF-only line ends, trailing whitespace, blank lines, empty
    continuation lines (`=` alone -- the full dumps end PRNID with one),
    trailing commas, and DOS ^Z padding (everything from the first 0x1A is
    discarded -- these are text files, so a bare 0x1A can only be the DOS
    EOF convention). Anything else raises ValueError naming the line: a
    line this parser cannot read means the file is not a .PAT, and
    guessing would corrupt a byte-level mapping silently.
    """
    eof = data.find(b'\x1a')
    if eof != -1:
        data = data[:eof]
    out: dict = {}
    last = None
    for lineno, raw in enumerate(data.split(b'\n'), 1):
        line = raw.rstrip(b'\r\t ')
        if not line:
            continue
        label, sep, rest = line.partition(b'=')
        if not sep:
            raise ValueError(f'.PAT line {lineno}: no "=" in {raw[:40]!r}')
        vals = bytearray()
        for item in _split_items(rest):
            item = item.strip()
            if not item:
                continue                      # trailing comma / bare '='
            if item[:1] == b'"' and item[-1:] == b'"' and len(item) >= 2:
                vals += item[1:-1]            # quoted literal ASCII
                continue
            try:
                byte = int(item, 16)
            except ValueError:
                byte = -1
            if not 0 <= byte <= 0xFF or len(item) > 2:
                raise ValueError(
                    f'.PAT line {lineno}: bad hex item {item!r}')
            vals.append(byte)
        if label:
            try:
                last = label.decode('ascii')
            except UnicodeDecodeError:
                raise ValueError(
                    f'.PAT line {lineno}: non-ASCII label {label!r}') from None
            out[last] = bytes(vals)
        else:
            if last is None:
                raise ValueError(
                    f'.PAT line {lineno}: continuation before any label')
            out[last] = out[last] + bytes(vals)
    return out

# ---------------------------------------------------------------- INIEDT

# INIEDT struct offsets, RELATIVE to the block start (PATCH.LST base
# 0x1219, 68 bytes, INISIZ assembler-enforced -- decode doc field map).
# All are LE16. Every field below is marked DOCUMENTED in the doc; the
# flagged/INFERRED fields (page-number placement, font/typestyle quad)
# are deliberately NOT interpreted here.
#
#   doc addr  rel    field                              units
_MT_OFF = 0x122D - 0x1219   # 0x14  top margin (.mt)           1/1440 in
_MB_OFF = 0x122F - 0x1219   # 0x16  bottom margin (.mb)        1/1440 in
_PL_OFF = 0x1231 - 0x1219   # 0x18  page length (.pl)          1/1440 in
_HM_OFF = 0x1238 - 0x1219   # 0x1F  heading margin (.hm)       1/1440 in
_FM_OFF = 0x123A - 0x1219   # 0x21  footing margin (.fm)       1/1440 in
_PO_EVEN_OFF = 0x123D - 0x1219  # 0x24  page offset, even pages (.po)  1/1800 in
_PO_ODD_OFF = 0x123F - 0x1219   # 0x26  page offset, odd pages  (.po)  1/1800 in
_LH_OFF = 0x1259 - 0x1219   # 0x40  line height (.lh)          1/1440 in


def _le16(block: bytes, off: int):
    """LE16 at `off`, or None when the block is too short to carry it --
    a truncated INIEDT yields the fields it has rather than a guess."""
    return int.from_bytes(block[off:off + 2], 'little') \
        if len(block) >= off + 2 else None


def page_settings(pat: dict) -> dict:
    """Interpret a parsed dump's INIEDT block into the page-geometry keys
    core.effective_page consumes: mt_lines/mb_lines/pl_lines/hm_lines/
    fm_lines (lines at 6 LPI), po_cols (10-CPI print columns), lh_48
    (1/48in units) -- the project's native units throughout, so the result
    plugs straight in as a machine-settings dict.

    Unit conversions (decode doc: VMI = 1/1440 in, confirmed by
    PATCH.LST's own 1440/6 idiom; HMI = 1/1800 in, PATCH.LST line 2613):
      1440ths -> lines at 6 LPI:  /1440 * 6   (720 -> 3.0, the .mt factory)
      1800ths -> 10-CPI columns:  /1800 * 10  (1440 -> 8.0, the .po factory)
      1440ths -> 48ths:           /1440 * 48  (240 -> 8.0, the .lh factory)

    .po is stored TWICE (even/odd pages, a duplexing refinement the dot
    command does not have); both files in the archive hold them equal, and
    core's page model has one po_cols, so the even-page value is used --
    an odd-page value that differed would be dropped here, accepted as the
    model's limitation rather than papered over.

    A dump with no INIEDT label (four of the five partial patch sets)
    returns {} -- "this machine says nothing about page geometry", which
    effective_page treats as no overrides at all.
    """
    ie = pat.get('INIEDT')
    if ie is None:
        return {}
    out = {}
    for key, off, per_unit in (
            ('mt_lines', _MT_OFF, 6.0 / 1440.0),
            ('mb_lines', _MB_OFF, 6.0 / 1440.0),
            ('pl_lines', _PL_OFF, 6.0 / 1440.0),
            ('hm_lines', _HM_OFF, 6.0 / 1440.0),
            ('fm_lines', _FM_OFF, 6.0 / 1440.0),
            ('po_cols', _PO_EVEN_OFF, 10.0 / 1800.0),
            ('lh_48', _LH_OFF, 48.0 / 1440.0)):
        raw = _le16(ie, off)
        if raw is not None:
            out[key] = raw * per_unit
    return out

# ---------------------------------------------------------------- RLRINI

# RLRINI: ten 74-byte ruler records (.RR 0 - .RR 9) + 1 reserved byte =
# 741, matching the .PAT block's byte count exactly (decode doc, PATCH.LST
# 0x1263-0x1547). Record layout, offsets within a record:
_RR_SIZE = 74
_RR_NTABS_OFF = 0x08        # 1 byte   number of tab stops in table
_RR_TABS_OFF = 0x0A         # 25 x LE16 tab positions, ascending, HMI
_RR_MAX_TABS = 25


def ruler_tabs(pat: dict) -> list:
    """Default tab stops from RLRINI's `.RR 0` record (the primary default
    ruler), as floats in 10-CPI print columns -- the same unit `.po` and
    the margin fields use everywhere in core. Factory decode: 11 stops
    every 900 HMI = every 5 columns, [5.0, 10.0, ... 55.0], which
    reproduces the WS7 manual's stated tab defaults exactly (decode doc:
    DOCUMENTED, high confidence -- and byte-identical in both full dumps;
    Sawyer never touched his ruler defaults).

    Positions only: the record also carries a decimal-tab COUNT (+0x09),
    but the doc does not map WHICH entries are decimal, so that
    distinction is not invented here -- future `.tb` work that needs it
    has to extend the decode first. Missing/short RLRINI returns [].
    """
    rl = pat.get('RLRINI')
    if rl is None or len(rl) < _RR_SIZE:
        return []
    rr0 = rl[:_RR_SIZE]
    n = min(rr0[_RR_NTABS_OFF], _RR_MAX_TABS)
    tabs = []
    for i in range(n):
        hmi = int.from_bytes(
            rr0[_RR_TABS_OFF + 2 * i:_RR_TABS_OFF + 2 * i + 2], 'little')
        if hmi == 0:
            continue                          # unused entries are 0 (doc)
        tabs.append(hmi * 10.0 / 1800.0)      # HMI -> 10-CPI columns
    return tabs
