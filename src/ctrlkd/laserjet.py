"""WS7's LASERJET driver: which of its fonts a document's font prints in, and
where it puts each word of a proportional one.

WS7 places every word itself (an `&a#H` move before each one; a space is
never sent) at the running sum of the driver's own character widths, in
whole printer dots, and splits a word where a kerning pair tucks its
letters together (WS7 teardown, `wordstar-dos/11-print-engine.md` 11.17,
rules M1, W1, W2, K1, S1, P1):

- M1: a font record (width, height, typestyle) prints in the driver font
  `match` picks: an exact match first, then the closest by a fixed order of
  tests.
- W1: a character is `width x size x unit x num / (em x den)` dots, rounded
  half up, each on its own (a TrueType face rounds pixels per em first);
  the size is in twips, floored to a quarter point.
- K1: a kerning pair moves the pen `amount / 128` of the size in dots at 72
  to the inch, truncated toward zero.
- S1: a sub/superscript is set at the block's own script scale.
- P1: a piece is moved to `floor(x x 720 / unit)` decipoints.

The tables are `laserjet_tables.py`.
"""
from .laserjet_tables import BLOCKS, FONTS

_VARIANT = {(False, False): 0, (False, True): 1, (True, False): 2, (True, True): 3}


def _rhu(n, d):
    return (n + d // 2) // d


def match(w, h, k):
    """M1: the index in `FONTS` of the font a document's font record (width
    `w` in 1/1800 inch, height `h` in twips, typestyle word `k`) prints in.
    An exact match of all three first, with the request's 0200h bit forced
    to each font's; then each font against the best so far, the first test
    that tells them apart deciding, a later font winning a complete tie."""
    req = [w, h, k]
    for i, (_n, fw, fh, fk, _b) in enumerate(FONTS):
        req[2] ^= (fk ^ req[2]) & 0x200
        if [fw, fh, fk] == req:
            return i
    best, pick = (0xFFFF, 0xFFFF, 0xFFFF), None
    for i, (_n, fw, fh, fk, _b) in enumerate(FONTS):
        if fh == 0:
            fh, fw = req[1], fw * req[1] * 8 // 65536
        dw, dh, dk = abs(req[0] - fw), abs(req[1] - fh), req[2] ^ fk
        if dk & 0x3000 == 0x3000:
            dk &= 0xEFFF
        elif dk & 0x3000 == 0x1000 and req[2] & 0x3000 == 0x3000:
            dk ^= 0x3000
        bw, bh, bk = best
        if bk & 0x3000 != 0x3000 and (bk ^ dk) & 0x3000 not in (0, 0x1000):
            take = dk <= 0x1000
        elif (bw > 25 or dw > 25) and bw != dw:
            take = bw > dw
        elif (bk ^ dk) & 0x8000:
            take = not dk & 0x8000
        elif (bk ^ dk) & 0x4000:
            take = not dk & 0x4000
        elif (bk ^ dk) & 0x0C00:
            take = not dk & 0x0C00
        elif (bh > 30 or dh > 30) and bh != dh:
            take = bh > dh
        elif (bw > 15 or dw > 15) and bw != dw:
            take = bw > dw
        elif (bk ^ dk) & 0x3000:
            take = not dk & 0x3000
        elif (bk ^ dk) & 0xFF:
            take = not dk & 0xFF
        elif bw != dw:
            take = bw > dw
        else:
            take = bh >= dh
        if take:
            best, pick = (dw, dh, dk), i
    return pick


def block_for(entry, bold, italic):
    """The proportional driver block a document font entry (`core`'s
    `doc.fonts`) prints with in this variant, or None when the driver
    prints it in a fixed-pitch font."""
    i = match(entry['width_1800'], entry['height_1440'], entry['typestyle'])
    if i is None:
        return None
    return BLOCKS.get(FONTS[i][4][_VARIANT[(bool(bold), bool(italic))]])


def twips(block, pt, script=False):
    """The size the driver measures at, in twips: S1's script scale for a
    sub/superscript, floored to a quarter point."""
    tw = int(round(pt * 20))
    if script and block[5]:
        tw = tw * block[5] // 256
    return tw - tw % 5


def code(ch):
    """The printer character code (PC-8) of `ch`; 0, the table's default
    width, for a character it has none for."""
    try:
        return ch.encode('cp437')[0]
    except UnicodeEncodeError:
        return 0


def char_dots(block, tw, code):
    em, num, den, unit, ppem_first, _script, widths, _kern = block
    w = widths[code]
    if ppem_first:
        return _rhu(w * _rhu(num * tw * unit, 20 * den), em)
    return _rhu(w * num * tw * unit, 20 * em * den)


def kern_dots(block, tw, first, second):
    k = block[7].get(first, {}).get(second, 0)
    if not k:
        return 0
    d = abs(k) * (tw * block[3] // 1440) // 128
    return -d if k < 0 else d


def dots_to_pt(block, dots):
    return dots * 72.0 / block[3]


def pieces(text, block, tw, kerning=True):
    """`text` as the driver prints it: `[(piece, x_dots, width_dots)]`, x
    from the start of `text`. A run of blanks is one piece; a word is split
    where a kerning pair applies (with `kerning`, the `.KR` state), so each
    piece starts where WS7 moved to."""
    out = []
    x = 0
    start = piece_x = 0
    prev = None
    for i, ch in enumerate(text):
        c = code(ch)
        if ch == ' ':
            if i > start and prev is not None:
                out.append((text[start:i], piece_x, x - piece_x))
                start, piece_x = i, x
            prev = None
        else:
            k = kern_dots(block, tw, prev, c) if kerning and prev is not None else 0
            if i > start and (prev is None or k):
                out.append((text[start:i], piece_x, x - piece_x))
                x += k
                start, piece_x = i, x
            prev = c
        x += char_dots(block, tw, c)
    if start < len(text):
        out.append((text[start:], piece_x, x - piece_x))
    return out


def width_dots(text, block, tw, kerning=True):
    """The advance of `text`, kerning included."""
    p = pieces(text, block, tw, kerning)
    return p[-1][1] + p[-1][2] if p else 0
