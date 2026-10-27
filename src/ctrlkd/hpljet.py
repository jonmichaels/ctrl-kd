"""Where WS4's HPLJET driver puts each character of a body line.

WordStar 4 prints through a code module in WSPRINT.OVR; on a LaserJet that is
HPLJET, which places every word with an absolute move and spreads a justified
line itself (WS4 teardown, `wordstar4-dos/4-formatting-printing.md` 15, rules
M1-M14 of its model `tools/p_mj_model.py`, with the module's code addresses).
This is that model, run on a parsed line instead of raw bytes:

- A line is measured only when `.UJ` is on (WS4's factory "dis" is on for
  HPLJET), it ends in a soft return, and it holds more than two letters (M1,
  M2, M8).
- Its justified region starts at the first word holding a letter stored with
  bit 7, WS4's word-end flag (`Line.hibit`); text before it prints at its
  natural widths (M4).
- The slack is the line's nominal width, `.CW` per cell, less its device
  width, the font's own widths; an editor soft space (A0h) has no device
  width, so the driver re-spreads the editor's padding (M5, M7). A soft
  hyphen is measured as `?` and printed as `-` (M6).
- Letter spacing takes whole 1/120" units when the slack per blank is over
  THR, at most MAXL of them; the rest goes to the blanks, each taking the
  pool left over the blanks left, quantised to 1/120" under `.PS` (M9, M11).
- Under `.PS` a character advances by its proportional table width (1/600");
  at fixed pitch by the font's cell. An x is sent as `x * 720 // den`
  decipoints, truncated.

A negative slack (M10) is the module's code, not run by any capture. Tabs,
print controls and `^P@` are not modelled: such a line gets None and is drawn
at its natural widths.
"""
from __future__ import annotations

from . import hpljet_tables as T

# `.CW` for `^PA`: the factory alternate pitch, 10/120" (WS4 teardown 4
# §15.4, drv-hpljet: `ESC(s12H ESC&k10H`).
ALT_CW = 10
# [1821] in the module image, the blank-shrink factor (M10).
_SHRINK_1821 = 0x50


def font_for(cw, ps, bold=False, italic=False):
    """(record, extra) for a character at `.CW` `cw` (0x0F8D). Under `.PS` a
    map entry with 0x40/0x80 set has its italic and bold records after it."""
    rec, extra = (T.FONTMAP_PS if ps else T.FONTMAP_FIXED)[min(max(int(cw), 0), 30)]
    if ps and rec & 0xC0:
        rec = (rec & 0x3F) + (2 if bold else 1 if italic else 0)
    return rec & 0x3F, extra


def width(rec, extra, c):
    """(device width, extra) of printer character `c` in 1/den inch (0x14CF):
    a fixed font's cell, or a proportional table's width (A0h as 20h)."""
    w, _den, flags, table = T.FONTS[rec]
    if table is None:
        return w, extra
    if c == 0xA0:
        c = 0x20
    return T.PS[table][c] * (2 if flags & 0x100 else 1), 0


def compos(c):
    """The printer character for CP437 `c` (COMPOS, first byte)."""
    return T.COMPOS[c][0]


class Char:
    """One character of a line: the code the printer receives, after COMPOS
    (A0h for an editor soft space), whether it was stored with bit 7, and the
    font it is set in. `measure_as` is the CP437 code the driver measures it
    by when that differs: a soft hyphen, printed `-`, is measured as
    COMPOS[1Fh], `?` (M6)."""
    __slots__ = ('code', 'hib', 'cw', 'bold', 'italic', 'measure_as')

    def __init__(self, code, hib=False, cw=12, bold=False, italic=False,
                 measure_as=None):
        self.code, self.hib, self.cw = code, hib, cw
        self.bold, self.italic = bold, italic
        self.measure_as = measure_as      # a soft hyphen: '?' (M6)

    @property
    def blank(self):
        return self.code in (0x20, 0xA0)


def place_line(chars, po, po_cw, ps, uj, soft):
    """[(x_dp, advance_dp), ...] for every character of one body line, x in
    decipoints from the logical page's left edge, or None when the line uses
    something this model does not cover.

    `po` is the page offset in cells, `po_cw` the `.CW` in force when `.PO`
    was read (x starts at `po * po_cw` 1/120", WS4 teardown 4 §15.3), `ps`
    `.PS`, `uj` `.UJ` ('on', 'off', 'dis'), `soft` whether the line ends in a
    soft return."""
    n = len(chars)
    if not n:
        return []
    fonts = [font_for(c.cw, ps, c.bold, c.italic) for c in chars]
    dens = {T.FONTS[f[0]][1] for f in fonts}
    if len(dens) != 1:
        return None
    den_font = dens.pop()
    q2000 = bool(T.FONTS[fonts[0][0]][2] & 0x2000)
    w_unit = T.FONTS[fonts[0][0]][0]

    # ---- measurement (0x054D-0x0697)
    on = uj in ('on', 'dis') and soft
    prefix = blanks = blankish = letters = pool_b = pool_l = 0
    neg = False
    if on:
        latch = False
        pre = nom = dev = ltr = blk = bl2 = 0
        i = 0
        while i < n:
            if not chars[i].blank:
                ch = dx = dv = 0
                while i < n and not chars[i].blank:
                    c = chars[i]
                    latch = latch or c.hib
                    rec, extra = fonts[i]
                    code = compos(c.measure_as) if c.measure_as is not None else c.code
                    dw, ex = width(rec, extra, code)
                    ch += 1
                    dv += dw + ex
                    dx += c.cw
                    i += 1
                if latch:
                    nom += dx
                    dev += dv
                    ltr = (ltr + ch) & 0xFF
                else:
                    pre = (pre + ch) & 0xFF
            else:
                cb = ca = dx = dv = 0
                while i < n and chars[i].blank:
                    c = chars[i]
                    rec, extra = fonts[i]
                    if c.code == 0x20:
                        cb += 1
                        dw, ex = width(rec, extra, compos(0x20))
                        dv += dw + ex
                    else:
                        ca += 1
                    dx += c.cw
                    i += 1
                if i >= n:
                    break                          # trailing blanks dropped
                if cb == 0:
                    cb, ca = 1, ca - 1             # 0x0741: one A0 is the blank
                if latch:
                    nom += dx
                    dev += dv
                    blk = (blk + cb) & 0xFF
                    bl2 = (bl2 + cb + ca) & 0xFF
                else:
                    pre = (pre + cb + ca) & 0xFF
        prefix, blanks, blankish, letters = pre, blk, bl2, ltr
        s = nom - dev * 120 // den_font
        s = ((s + 0x8000) & 0xFFFF) - 0x8000
        if letters <= 2:                           # M8
            on = False
            prefix = blanks = blankish = letters = 0
        else:
            letters = (letters - 1) & 0xFF
            if s < 0:                              # M10
                neg = True
                s = -s
                bw, ex = width(fonts[0][0], fonts[0][1], 0x20)
                cap = (((bw + ex) * _SHRINK_1821 // den_font) & 0xFF) * blanks & 0xFFFF
                s = min(s, cap)
            else:                                  # M9
                per = 0
                while per < T.MAX_LETTER_UNITS:
                    if (s >> 8) < blanks and blanks and (s // blanks) & 0xFF <= T.BLANK_THRESHOLD:
                        break
                    if s < letters:
                        break
                    s -= letters
                    pool_l += letters
                    per += 1
            pool_b = s
    if not on:
        prefix = blanks = blankish = letters = pool_b = pool_l = 0

    # ---- printing (0x0812-0x08D9, 0x0CD4-0x0D6E)
    printable = [k for k in range(n) if not chars[k].blank]
    if not printable:
        return [(0, 0)] * n
    first_p = printable[0]
    den = 120
    x = po * po_cw
    cell = po * po_cw
    snap = loaded = False
    prev = 0
    out = []

    def setden(new):
        nonlocal den, x, pool_b, pool_l
        if new != den:
            x = x * new // den
            pool_b = pool_b * new // den
            pool_l = pool_l * new // den
            den = new

    for k, c in enumerate(chars):
        blank = c.blank
        if snap:
            snap = False
            x = cell * den // 120
        if blank and ps and k < first_p:                     # M13
            setden(120)
            x0 = x
            x += c.cw
            prefix = (prefix - 1) & 0xFF
            if prefix == 0:
                snap = True
            loaded = False
            cell += c.cw
            out.append((x0 * 720 // den, c.cw * 6.0))
            continue
        if not loaded:
            setden(den_font)
            loaded = True
        rec, extra = fonts[k]
        dw, ex = width(rec, extra, c.code)
        if prefix:
            prefix = (prefix - 1) & 0xFF
            if prefix == 0:
                snap = ps
            share = 0
            wid = dw
        elif blank:
            wid = dw
            if blankish == 0:
                prev = c.code
                share = 0
            else:
                blankish -= 1
                if c.code == 0x20:
                    old, prev = prev, c.code
                    zero = old == 0xA0
                else:
                    zero = prev in (0x20, 0xA0)
                    if not zero:
                        prev = c.code
                if zero:
                    wid, share, ex = 0, 0, 0
                else:
                    cl = blanks
                    blanks = (blanks - 1) & 0xFF
                    q = pool_b // cl if pool_b and cl else 0
                    if q2000:
                        q = q // w_unit * w_unit
                    pool_b -= q
                    share = -q if neg else q
        else:
            prev = c.code
            cl = letters
            if cl:
                letters -= 1
            q = pool_l // cl if pool_l and cl else 0
            if q2000:
                q = q // w_unit * w_unit
            pool_l -= q
            share = -q if neg else q
            wid = dw
        adv = wid + share + ex
        out.append((x * 720 // den, adv * 720.0 / den))
        x += adv
        cell += c.cw
    return out
