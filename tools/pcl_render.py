#!/usr/bin/env python3
"""
pcl_render.py -- measurement-faithful PCL5 visualizer for WS7 captures.

WHY THIS EXISTS
----------------
A previous throwaway PNG renderer drew PCL text chunks with a stock font's
OWN glyph-advance metrics. Those metrics do not match WordStar 7's actual
printer fonts (CG Times, Courier), so the render showed fake "wide gaps"
and fused words -- an artifact of the wrong font's spacing, not of
anything WordStar actually did. That produced false visual conclusions.

This tool is width-faithful BY CONSTRUCTION: every character's advance
comes from ctrlkd/afm.py's Adobe/URW AFM width tables, scaled to the
chunk's point size, and NOTHING ELSE. The drawing font (a TTF/OTF) is used
ONLY for glyph shape -- its own hmtx/advance-width table is never
consulted. Positions (chunk x/y) are ground truth taken verbatim from the
PCL byte stream (ESC&a#H / ESC&a#V, decipoints = 1/720in) -- exactly what
WordStar 7's own driver told the printer to do.

PARSING
-------
This duplicates (does not import/modify) pcl_text.py's escape-sequence
grammar -- same two-character / parameterized-group / groupless rules,
same "only bytes >=0x20 outside any escape are text" principle -- and
extends it with one more interpreted field group: ESC(s<P>p<V>v[<H>h]<S>s
<B>b<T>T, PCL's "font selection by characteristics" sequence, whose
fields this tool needs (pcl_text.py has no font-command extraction, so
extending it needs a second implementation, not a patch to that file).

Font-selection fields observed in the WS7 capture corpus (LYING.pcl,
WARPRAYR.pcl) always arrive with every field present in the SAME escape
sequence (even when the value is empty), so this parser does not need to
model HP's "fields are independently sticky across separate commands"
behavior for real captures -- but each field is still resolved
independently per PCL rules: a field present with an empty numeric value
means value 0 for THAT command, not "carry the previous command's value".

TYPEFACE-ID MAPPING (see TYPEFACE_FAMILY below)
------------------------------------------------
Observed HP "typeface family" IDs in both validation captures: 4101 (CG
Times) and 4197 (a second proportional serif ID whose exact HP catalog
identity is NOT independently confirmed here -- see the report/JSON
'font_mapping_notes' field). Both are mapped to the Times AFM family per
this task's explicit instruction ("CG Times->Times"); the PCL spacing
field (P: 0=fixed, 1=proportional) is used as the authoritative
proportional/fixed signal, with typeface ID only picking the family
*within* that (Times vs Helvetica) for prop faces. Courier's scalable
typeface ID (4099) was also observed directly. Unknown proportional IDs
fall back to Times; unknown fixed IDs fall back to Courier -- per the
task's explicit "CG Times->Times, Courier->Courier" instruction.

Glyph shapes are drawn from the Nimbus Roman / Nimbus Sans / Nimbus Mono
PS OTF families (URW base-35 clones) -- the SAME font family afm.py's
own docstring says its width tables were transcribed from, so shape and
width metrics are drawn from the same lineage rather than an unrelated
substitute (Liberation/DejaVu also present on this system, but Nimbus is
the metric-compatible-by-construction choice).
"""

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from ctrlkd import afm  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow is required: pip install --user Pillow", file=sys.stderr)
    raise

DPI_DEFAULT = 150
PAGE_W_IN = 8.5
PAGE_H_IN = 11.0
DECIPT_PER_IN = 720
PT_PER_IN = 72
DECIPT_PER_PT = 10

# ---------------------------------------------------------------------
# Typeface-ID -> AFM family mapping (see module docstring)
# ---------------------------------------------------------------------
TYPEFACE_FAMILY = {
    4101: "Times",      # CG Times -- confirmed via title/byline/footnote text
    4197: "Times",       # proportional serif companion ID -- see docstring
    4099: "Courier",     # Courier scalable -- confirmed (10.00 pitch, fixed)
    3: "Courier",        # classic bitmap Courier ID
    1: "Times",          # classic bitmap "Pica" -- treated as Times-ish serif default
    4: "Helvetica",       # classic bitmap "Helv"
    4116: "Helvetica",    # Coronet -- speculative, not observed in validation set
    4148: "Helvetica",    # Univers Medium -- speculative
    4149: "Helvetica",    # Univers Bold -- speculative
    4150: "Helvetica",    # Univers Medium Italic -- speculative
    4151: "Helvetica",    # Univers Bold Italic -- speculative
}
TYPEFACE_FAMILY_SOURCE_NOTE = (
    "4101/4099 confirmed against LYING.pcl content (title/byline/footnote-"
    "attribution text vs. the Courier-pitched footnote-separator/numbered-"
    "list rule). 4197 is mapped to Times per task instruction and by its "
    "P=1 (proportional) field on every occurrence + prose usage context, "
    "but its exact HP typeface-catalog identity (e.g. a Times New Roman "
    "TrueType substitution vs. a second CG Times registration) is NOT "
    "independently verified. All other IDs in this table were never seen "
    "in either validation capture -- speculative, HP-catalog-recollection "
    "based, listed only so an unexpected sans typeface degrades to a named "
    "guess instead of a silent Times default."
)

FONT_DIR = "/usr/share/fonts/opentype/urw-base35"
FONT_TTF = {
    "Times-Roman": f"{FONT_DIR}/NimbusRoman-Regular.otf",
    "Times-Bold": f"{FONT_DIR}/NimbusRoman-Bold.otf",
    "Times-Italic": f"{FONT_DIR}/NimbusRoman-Italic.otf",
    "Times-BoldItalic": f"{FONT_DIR}/NimbusRoman-BoldItalic.otf",
    "Helvetica": f"{FONT_DIR}/NimbusSans-Regular.otf",
    "Helvetica-Bold": f"{FONT_DIR}/NimbusSans-Bold.otf",
    "Helvetica-Oblique": f"{FONT_DIR}/NimbusSans-Italic.otf",
    "Helvetica-BoldOblique": f"{FONT_DIR}/NimbusSans-BoldItalic.otf",
    "Courier": f"{FONT_DIR}/NimbusMonoPS-Regular.otf",
    "Courier-Bold": f"{FONT_DIR}/NimbusMonoPS-Bold.otf",
    "Courier-Oblique": f"{FONT_DIR}/NimbusMonoPS-Italic.otf",
    "Courier-BoldOblique": f"{FONT_DIR}/NimbusMonoPS-BoldItalic.otf",
}


def resolve_afm_basefont(spacing, style, weight, typeface):
    """(P, S, B, T) PCL font-characteristic fields -> AFM base-14 name."""
    is_bold = weight is not None and weight > 0
    is_italic = style in (1, 5)  # 1=italic, 5=condensed italic
    fam = TYPEFACE_FAMILY.get(typeface)
    if fam is None:
        fam = "Courier" if spacing == 0 else "Times"
    if fam == "Times":
        if is_bold and is_italic:
            return "Times-BoldItalic"
        if is_bold:
            return "Times-Bold"
        if is_italic:
            return "Times-Italic"
        return "Times-Roman"
    if fam == "Helvetica":
        if is_bold and is_italic:
            return "Helvetica-BoldOblique"
        if is_bold:
            return "Helvetica-Bold"
        if is_italic:
            return "Helvetica-Oblique"
        return "Helvetica"
    # Courier
    if is_bold and is_italic:
        return "Courier-BoldOblique"
    if is_bold:
        return "Courier-Bold"
    if is_italic:
        return "Courier-Oblique"
    return "Courier"


# ---------------------------------------------------------------------
# Raster/pattern fill color model (see 2026-08-20 raster-graphics addendum
# below the module docstring's original scope)
# ---------------------------------------------------------------------
#
# HP PCL5's "current pattern", selected by ESC*v#N#o#T ("Select Current
# Pattern"), governs the fill color of BOTH subsequent text glyphs and
# subsequent ESC*c#P rectangle fills (P=0 case) -- PCL draws glyphs as a
# pattern fill, not an unconditional "black ink" operation. Observed in
# LJ6DTP.pcl: ESC*v0n1o1T (pattern=solid white) issued immediately before
# a heading's text bytes, with a dense row of 0xDB (full-block) glyphs
# painted in the DEFAULT (T=0, black) pattern directly above/around it at
# a much larger point size -- i.e. the "black bar" is itself made of
# solid-black block-character glyphs, not a rectangle fill, and the
# reverse-video heading text sits inside that glyph-drawn band. Confirmed
# by byte inspection of LJ6DTP.pcl (grep for `*v0n1o1T` / `*v0n0o0T`
# around "Manual"/"White" text bytes).
#
# T (current-pattern) values observed: 0 solid black, 1 solid white,
# 2 shading (gray %, from the LAST-SET ESC*c#G sticky value), 3
# cross-hatch (id via G, HP predefined patterns 1-6). T=4 (user-defined
# pattern) never observed; approximated identically to 3 if it occurs.
# T=2's G value is used AS a direct percent-black (0-100) per HP's
# predefined shading-pattern numbering -- confirmed by the observed
# progression G=1,2,3,4,5,6,15,25,50,75,85,100 against LJ6DTP's own
# "Shading" demo section text.
#
# ESC*c#P ("Fill Rectangular Area") fill-type P is SEPARATE from T: P=0
# fills with the current pattern (T/G as above); P=1/2/3/4 are
# self-contained using the G field carried on the SAME *c command
# (confirmed: `*c0075a0075b0015g2P` and `*c0075a0075b0100g2P` pairs in
# LJ6DTP.pcl -- 15%/100% gray swatches, P=2 with an inline G, unrelated to
# the sticky *v pattern in effect at that point). Only P=0 and P=2 are
# observed in this corpus; P=1/3/4 implemented per HP's documented
# meanings but unexercised here.


def pattern_rgb(t_value, gray_pct):
    """(*v current-pattern T, gray-percent G) -> RGB. See addendum above."""
    if t_value == 1:
        return (255, 255, 255)
    if t_value == 2:
        pct = max(0.0, min(100.0, gray_pct))
        level = round(255 * (1.0 - pct / 100.0))
        return (level, level, level)
    if t_value in (3, 4):
        # cross-hatch / user-defined pattern -- approximated as a flat 50%
        # gray (visual density placeholder, not the real hatch texture).
        return (128, 128, 128)
    return (0, 0, 0)  # T==0 or unrecognized -> PCL's default pattern: black


def rect_fill_rgb(p_value, inline_gray, cur_t, cur_gray):
    """ESC*c#P fill-type -> RGB (see addendum above)."""
    if p_value == 0:
        return pattern_rgb(cur_t, cur_gray)
    if p_value == 1:
        return (255, 255, 255)
    if p_value == 2:
        return pattern_rgb(2, inline_gray)
    if p_value in (3, 4):
        return pattern_rgb(3, inline_gray)
    return (0, 0, 0)


# ---------------------------------------------------------------------
# Raster row decompression (ESC*b#M compression mode)
# ---------------------------------------------------------------------
# Mode 0 (unencoded) is the ONLY mode observed in this corpus (-SCREEN,
# PREVIEW, -README all default -- no capture ever issues ESC*b#M).
# Modes 1 (HP run-length) and 2 (TIFF PackBits-style) are implemented
# below per HP's documented algorithms for completeness/robustness, but
# are UNEXERCISED and UNVALIDATED against any real sample in this task.


def decode_raster_mode0(raw):
    return raw


def decode_raster_mode1(raw):
    """HP RLE: (count, data) byte pairs; data repeated count+1 times."""
    out = bytearray()
    n = len(raw)
    i = 0
    while i + 1 < n:
        count = raw[i]
        out.extend(bytes([raw[i + 1]]) * (count + 1))
        i += 2
    return bytes(out)


def decode_raster_mode2(raw):
    """TIFF PackBits-style RLE ("Mode 2")."""
    out = bytearray()
    n = len(raw)
    i = 0
    while i < n:
        ctrl = raw[i]
        i += 1
        if ctrl <= 127:
            count = ctrl + 1
            out.extend(raw[i : i + count])
            i += count
        elif ctrl >= 129:
            count = 257 - ctrl
            if i < n:
                out.extend(bytes([raw[i]]) * count)
                i += 1
        # ctrl == 128: no-op / padding byte
    return bytes(out)


def decode_raster_row(raw, mode):
    if mode == 1:
        return decode_raster_mode1(raw)
    if mode == 2:
        return decode_raster_mode2(raw)
    return decode_raster_mode0(raw)


PCL_UNIT_PER_IN_DEFAULT = 300  # ESC&u#D (Unit of Measure) not seen in this
# corpus at all; 300/in is PCL5's documented default for ESC*p#X/#Y and
# ESC*c#A/#B ("PCL Units") absent an explicit override.


# ---------------------------------------------------------------------
# Parser: same grammar as pcl_text.py, extended with font-select tracking
# ---------------------------------------------------------------------

def parse_pcl_extended(data: bytes):
    """Returns (pages, unhandled_counter, recognized_not_rendered_counter,
    meta) where pages is a list of per-page op-lists, in stream order.
    Ops carry "type": "text" (unchanged schema: x_decipoints, y_decipoints,
    size_pt, font, text, ...) | "rect" | "raster" (see docstring addendum
    above pattern_rgb() for the raster/rect/pattern command grammar this
    adds: ESC*t#R, ESC*r#A/#B/#C, ESC*b#M/#W, ESC*c#A/#B/#G/#P, ESC*v#N/#O/#T,
    ESC&f#S, and ESC*p#X/#Y as an alternate-unit alias for the SAME cursor
    ESC&a#H/#V sets -- confirmed by byte inspection: LJ6DTP.pcl interleaves
    *p and &a moves with no separate reset between them, and rectangle
    fills always land where the immediately-preceding *p (or &a) put the
    cursor.
    """
    n = len(data)
    i = 0
    pages = []
    cur_chunks = []
    underline = False
    cursor_x = None
    cursor_y = None
    # sticky-within-this-parse font state (each observed font-select in
    # the corpus supplies all fields anyway; see module docstring)
    font_P, font_S, font_B, font_T, font_V = 0, 0, 0, None, 12.0
    unhandled = Counter()
    recognized_not_rendered = Counter()
    meta = {"orientation_portrait_confirmed": False, "page_size_commands_seen": False}

    # -- graphics/pattern state (2026-08-20 addendum) --------------------
    pos_stack = []  # ESC&f0S push / ESC&f1S pop, of (cursor_x, cursor_y)
    raster_res_dpi = 75  # ESC*t#R sticky; 75 is PCL5's documented default
    raster_active = False
    raster_origin = None
    raster_rows = []
    raster_mode = 0  # ESC*b#M sticky, reset to 0 at each ESC*r#A
    rect_A = 0  # ESC*c#A sticky (rectangle width, PCL units)
    rect_B = 0  # ESC*c#B sticky (rectangle height, PCL units)
    pattern_G = 0  # ESC*c#G sticky (pattern id / gray-percent)
    pattern_N = 0  # ESC*v#N sticky (pattern transparency; tracked, not rendered)
    pattern_O = 0  # ESC*v#O sticky (source transparency; tracked, not rendered)
    pattern_T = 0  # ESC*v#T sticky (current pattern select)
    graphics_counts = Counter()  # raw command tallies for the RETURN report

    def parse_value(j):
        start = j
        if j < n and data[j] in (0x2B, 0x2D):
            j += 1
        while j < n and 0x30 <= data[j] <= 0x39:
            j += 1
        if j < n and data[j] == 0x2E:
            j += 1
            while j < n and 0x30 <= data[j] <= 0x39:
                j += 1
        return data[start:j].decode("ascii", "replace"), j

    def to_num(s):
        if not s or s in ("+", "-", "."):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def apply_axis(current, val_str):
        """ESC&a#H/#V / ESC*p#X/#Y share one PCL rule: an UNSIGNED value is
        an absolute position; a '+'/'-'-PREFIXED value is a relative move
        from the current position. Verified safe to apply generally (not
        just for the new commands): grepping all 15 captures for signed
        &a fields found exactly 2 occurrences, both in -SCREEN/-README/
        PREVIEW immediately preceding ESC*r#A (the raster origin) or at
        end-of-page with no text drawn against them before the next
        (absolute) position command -- so this NEVER changes any existing
        text chunk's rendered position in this corpus.
        """
        v = to_num(val_str)
        if v is None:
            return current
        if val_str[:1] in ("+", "-"):
            base = current if current is not None else 0
            return int(round(base + v))
        return int(round(v))

    def handle_group(param, group, toks, pos):
        nonlocal cursor_x, cursor_y, font_P, font_S, font_B, font_T, font_V, underline
        nonlocal raster_res_dpi, raster_active, raster_origin, raster_rows, raster_mode
        nonlocal rect_A, rect_B, pattern_G, pattern_N, pattern_O, pattern_T
        if param == "&" and group == "a":
            for val, fc in toks:
                if fc == "H":
                    cursor_x = apply_axis(cursor_x, val)
                elif fc == "V":
                    cursor_y = apply_axis(cursor_y, val)
            return pos
        if param == "*" and group == "p":
            # ESC*p#X/#Y -- cursor position in PCL units (default 300/in;
            # see PCL_UNIT_PER_IN_DEFAULT). Same logical cursor as &a, just
            # a different unit system -- see function docstring.
            graphics_counts["ESC*p#X/#Y (cursor position, PCL units)"] += 1
            scale = DECIPT_PER_IN / PCL_UNIT_PER_IN_DEFAULT
            for val, fc in toks:
                true_letter = fc.upper()
                v = to_num(val)
                if v is None:
                    continue
                if true_letter == "X":
                    if val[:1] in ("+", "-"):
                        cursor_x = int(round((cursor_x or 0) + v * scale))
                    else:
                        cursor_x = int(round(v * scale))
                elif true_letter == "Y":
                    if val[:1] in ("+", "-"):
                        cursor_y = int(round((cursor_y or 0) + v * scale))
                    else:
                        cursor_y = int(round(v * scale))
            return pos
        if param == "&" and group == "f":
            fc = toks[-1][1] if toks else ""
            val = toks[-1][0] if toks else ""
            v0 = int(to_num(val) or 0)
            if fc.upper() == "S":
                if v0 == 0:
                    pos_stack.append((cursor_x, cursor_y))
                    graphics_counts["ESC&f0S (push cursor position)"] += 1
                elif v0 == 1:
                    if pos_stack:
                        cursor_x, cursor_y = pos_stack.pop()
                    graphics_counts["ESC&f1S (pop cursor position)"] += 1
                else:
                    unhandled[f"ESC&f{v0}S (unknown push/pop value)"] += 1
                return pos
            unhandled[f"ESC&f group fields={tuple(t[1] for t in toks)}"] += 1
            return pos
        if param == "*" and group == "t":
            for val, fc in toks:
                if fc.upper() == "R":
                    v = to_num(val)
                    if v is not None:
                        raster_res_dpi = v
                        graphics_counts[f"ESC*t{val}R (raster resolution)"] += 1
            return pos
        if param == "*" and group == "r":
            for val, fc in toks:
                true_letter = fc.upper()
                if true_letter == "A":
                    raster_active = True
                    raster_origin = (cursor_x, cursor_y)
                    raster_rows = []
                    raster_mode = 0
                    graphics_counts[f"ESC*r{val}A (start raster graphics)"] += 1
                elif true_letter in ("B", "C"):
                    if raster_active and raster_rows:
                        row_stride = max(len(r) for r in raster_rows)
                        cur_chunks.append(
                            {
                                "type": "raster",
                                "x_decipoints": raster_origin[0] if raster_origin and raster_origin[0] is not None else 0,
                                "y_decipoints": raster_origin[1] if raster_origin and raster_origin[1] is not None else 0,
                                "resolution_dpi": raster_res_dpi,
                                "width_px": row_stride * 8,
                                "height_px": len(raster_rows),
                                "n_rows": len(raster_rows),
                                "total_row_bytes": sum(len(r) for r in raster_rows),
                                "_rows": raster_rows,
                            }
                        )
                    graphics_counts[f"ESC*r{true_letter} (end raster graphics)"] += 1
                    raster_active = False
                    raster_rows = []
                    raster_origin = None
            return pos
        if param == "*" and group == "b":
            for val, fc in toks:
                true_letter = fc.upper()
                if true_letter == "M":
                    v = to_num(val)
                    raster_mode = int(v) if v is not None else 0
                    graphics_counts[f"ESC*b{val}M (raster compression mode)"] += 1
                elif true_letter == "W":
                    count = int(to_num(val) or 0)
                    raw = data[pos : pos + count]
                    pos += count
                    if raster_active:
                        raster_rows.append(decode_raster_row(raw, raster_mode))
                    graphics_counts["ESC*b#W (raster row data)"] += 1
            return pos
        if param == "*" and group == "c":
            emit_rect = None
            for val, fc in toks:
                true_letter = fc.upper()
                v = to_num(val)
                if true_letter == "A":
                    rect_A = v if v is not None else rect_A
                elif true_letter == "B":
                    rect_B = v if v is not None else rect_B
                elif true_letter == "G":
                    pattern_G = v if v is not None else pattern_G
                    graphics_counts[f"ESC*c{val}G (pattern id/gray %)"] += 1
                elif true_letter == "P":
                    emit_rect = int(v) if v is not None else 0
            if emit_rect is not None:
                unit_scale = DECIPT_PER_IN / PCL_UNIT_PER_IN_DEFAULT
                w_dp = rect_A * unit_scale
                h_dp = rect_B * unit_scale
                # pattern_G already reflects an inline G field on THIS same
                # *c command (updated earlier in this same toks loop) if
                # one was present, else the last sticky standalone *c#G.
                inline_gray = pattern_G
                color = rect_fill_rgb(emit_rect, inline_gray, pattern_T, pattern_G)
                cur_chunks.append(
                    {
                        "type": "rect",
                        "x_decipoints": cursor_x if cursor_x is not None else 0,
                        "y_decipoints": cursor_y if cursor_y is not None else 0,
                        "w_decipoints": w_dp,
                        "h_decipoints": h_dp,
                        "fill_type": emit_rect,
                        "gray_pct": inline_gray,
                        "_fill": color,
                    }
                )
                graphics_counts[f"ESC*c...{emit_rect}P (fill rectangular area)"] += 1
            return pos
        if param == "*" and group == "v":
            for val, fc in toks:
                true_letter = fc.upper()
                v = to_num(val)
                v0 = int(v) if v is not None else 0
                if true_letter == "N":
                    pattern_N = v0
                elif true_letter == "O":
                    pattern_O = v0
                elif true_letter == "T":
                    pattern_T = v0
            graphics_counts[f"ESC*v fields={tuple(t[1] for t in toks)} (select pattern)"] += 1
            return pos
        if param == "(" and group == "s":
            # fields, in true-uppercase-letter terms, appear here in
            # whatever order WordStar emitted (observed: P,V,[H],S,B,T)
            for idx, (val, fc) in enumerate(toks):
                true_letter = fc.upper()
                v = to_num(val)
                v0 = int(v) if v is not None else 0
                if true_letter == "P":
                    font_P = v0
                elif true_letter == "V":
                    font_V = v if v is not None else font_V
                elif true_letter == "H":
                    pass  # pitch -- not needed, AFM width supersedes it
                elif true_letter == "S":
                    font_S = v0
                elif true_letter == "B":
                    font_B = v0
                elif true_letter == "T":
                    font_T = int(v) if v is not None else None
            return pos
        if param == "&" and group == "d":
            # Underline enable (ESC&d#D, any variant) / disable (ESC&d@).
            # RENDERED since 2026-08-20: per-chunk rules under printed
            # glyphs only -- LaserJet underlines printed characters, not
            # cursor moves, so word gaps stay bare exactly as on paper.
            fc = toks[-1][1]
            if fc == "@":
                underline = False
            elif fc.upper() == "D":
                underline = True
            return pos
        if param == "&" and group == "l":
            for val, fc in toks:
                true_letter = fc.upper()
                v = to_num(val)
                if true_letter == "O":
                    if v == 0:
                        meta["orientation_portrait_confirmed"] = True
                    else:
                        meta["orientation_portrait_confirmed"] = False
                        meta.setdefault("orientation_value_seen", v)
                elif true_letter in ("A",):
                    meta["page_size_commands_seen"] = True
            unhandled[f"ESC&l group fields={tuple(t[1] for t in toks)}"] += 1
            return pos
        # anything else in a lowercase-group escape: log as unhandled
        unhandled[f"ESC{param}{group} fields={tuple(t[1] for t in toks)}"] += 1
        return pos

    def handle_groupless(param, val, fc):
        if param == "(" and fc == "U":
            recognized_not_rendered[f"ESC({val}U (symbol set select)"] += 1
            return
        if param == "%" and fc == "X":
            recognized_not_rendered["UEL ESC%-####X (job boundary)"] += 1
            return
        unhandled[f"ESC{param}...{fc} (groupless)"] += 1

    def flush_page():
        nonlocal cur_chunks
        pages.append(cur_chunks)
        cur_chunks = []

    while i < n:
        b = data[i]
        if b == 0x1B:
            i += 1
            if i >= n:
                break
            c = data[i]
            if 0x21 <= c <= 0x2F:
                param = chr(c)
                i += 1
                if i < n and 0x60 <= data[i] <= 0x7A:
                    group = chr(data[i])
                    i += 1
                    toks = []
                    while True:
                        value_str, i = parse_value(i)
                        if i >= n:
                            break
                        fb = data[i]
                        i += 1
                        field_char = chr(fb)
                        toks.append((value_str, field_char))
                        if not (0x60 <= fb <= 0x7A):
                            break
                    i = handle_group(param, group, toks, i)
                else:
                    value_str, i = parse_value(i)
                    if i < n:
                        fb = data[i]
                        i += 1
                        handle_groupless(param, value_str, chr(fb))
            else:
                if chr(c) == "E":
                    recognized_not_rendered["ESC E (printer reset)"] += 1
                else:
                    unhandled[f"ESC{chr(c)} (2-char)"] += 1
                i += 1
        elif b == 0x0C:
            flush_page()
            cursor_x = None
            cursor_y = None
            i += 1
        elif b in (0x0D, 0x0A):
            i += 1
        elif b < 0x20:
            i += 1
        else:
            start = i
            while i < n and data[i] >= 0x20 and data[i] != 0x1B:
                i += 1
            text = bytes(data[start:i]).decode("cp437", "replace")
            if cursor_x is not None and cursor_y is not None:
                basefont = resolve_afm_basefont(font_P, font_S, font_B, font_T)
                cur_chunks.append(
                    {
                        "type": "text",
                        "x_decipoints": cursor_x,
                        "y_decipoints": cursor_y,
                        "size_pt": font_V,
                        "font": basefont,
                        "text": text,
                        "_P": font_P,
                        "_S": font_S,
                        "_B": font_B,
                        "_T": font_T,
                        "_UL": underline,
                        "_fill": pattern_rgb(pattern_T, pattern_G),
                    }
                )

    if cur_chunks or not pages:
        pages.append(cur_chunks)

    meta["graphics_commands"] = dict(graphics_counts)
    return pages, unhandled, recognized_not_rendered, meta


# ---------------------------------------------------------------------
# AFM-driven measurement helpers
# ---------------------------------------------------------------------

def char_advances_pt(text, basefont, size_pt):
    """Per-character advance widths in POINTS, AFM table only."""
    table = afm.WIDTHS.get(basefont, afm.WIDTHS["Courier"])
    out = []
    for ch in text:
        try:
            b = ch.encode("cp1252", "replace")
        except Exception:
            b = b"?"
        code = b[0] if b else 0x3F
        w1000 = table[code] if code < len(table) else 0
        out.append(w1000 * size_pt / 1000.0)
    return out


def chunk_width_pt(chunk):
    return sum(char_advances_pt(chunk["text"], chunk["font"], chunk["size_pt"]))


# ---------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------

_font_cache = {}


def get_ttf(basefont, px_size):
    key = (basefont, px_size)
    f = _font_cache.get(key)
    if f is not None:
        return f
    path = FONT_TTF.get(basefont, FONT_TTF["Times-Roman"])
    f = ImageFont.truetype(path, size=max(1, px_size))
    _font_cache[key] = f
    return f


def render_raster_op(img, op, dpi):
    """Paste one decoded raster block (op["_rows"], MSB-first bytes, PCL's
    1-bit=black) onto the page canvas, scaled from its native resolution
    (ESC*t#R) to the page's render dpi."""
    rows = op["_rows"]
    if not rows:
        return
    row_stride = max(len(r) for r in rows)
    if row_stride == 0:
        return
    width_bits = row_stride * 8
    height = len(rows)
    # Build a packed 1-bpp buffer, inverted (PCL 1=black but PIL mode "1"
    # frombytes treats bit=1 as pixel value 255/white) -- verified via a
    # tiny probe (byte 0x80 -> first pixel black only after inversion).
    buf = bytearray()
    for row in rows:
        padded = row + bytes(row_stride - len(row))  # trailing bytes omitted -> white (0x00)
        buf.extend((~byte) & 0xFF for byte in padded)
    raster_img = Image.frombytes("1", (width_bits, height), bytes(buf)).convert("L")
    scale = dpi / op["resolution_dpi"]
    new_w = max(1, round(width_bits * scale))
    new_h = max(1, round(height * scale))
    if (new_w, new_h) != (width_bits, height):
        raster_img = raster_img.resize((new_w, new_h), Image.LANCZOS)
    dp_scale = dpi / DECIPT_PER_IN
    x0 = round(op["x_decipoints"] * dp_scale)
    y0 = round(op["y_decipoints"] * dp_scale)
    img.paste(raster_img.convert("RGB"), (x0, y0))


def render_rect_op(draw, op, dpi):
    dp_scale = dpi / DECIPT_PER_IN
    x0 = op["x_decipoints"] * dp_scale
    y0 = op["y_decipoints"] * dp_scale
    w_px = max(1, round(op["w_decipoints"] * dp_scale))
    h_px = max(1, round(op["h_decipoints"] * dp_scale))
    draw.rectangle([x0, y0, x0 + w_px, y0 + h_px], fill=op["_fill"])


def render_text_op(draw, ch, dpi):
    scale = dpi / PT_PER_IN  # px per point
    dp_scale = dpi / DECIPT_PER_IN  # px per decipoint
    x0 = ch["x_decipoints"] * dp_scale
    y0 = ch["y_decipoints"] * dp_scale
    px_size = round(ch["size_pt"] * scale)
    font = get_ttf(ch["font"], px_size)
    advances = char_advances_pt(ch["text"], ch["font"], ch["size_pt"])
    fill = tuple(ch.get("_fill", (0, 0, 0)))
    x = x0
    for c, adv_pt in zip(ch["text"], advances):
        if c != " ":
            try:
                draw.text((x, y0), c, font=font, fill=fill, anchor="ls")
            except Exception:
                draw.text((x, y0 - px_size), c, font=font, fill=fill)
        x += adv_pt * scale
    if ch.get("_UL") and ch["text"].strip():
        ul_y = y0 + max(1.0, ch["size_pt"] * 0.11) * scale
        ul_w = max(1, round(ch["size_pt"] * 0.055 * scale))
        draw.line([(x0, ul_y), (x, ul_y)], fill=fill, width=ul_w)


def render_page_png(chunks, dpi, out_path):
    w = round(PAGE_W_IN * dpi)
    h = round(PAGE_H_IN * dpi)
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    # Ops are drawn in stream order, exactly as PCL's sequential imaging
    # model would paint them (so e.g. white reverse-video text drawn after
    # a black glyph-bar in the byte stream stays on top).
    for op in chunks:
        kind = op.get("type", "text")
        if kind == "text":
            render_text_op(draw, op, dpi)
        elif kind == "rect":
            render_rect_op(draw, op, dpi)
        elif kind == "raster":
            render_raster_op(img, op, dpi)
            draw = ImageDraw.Draw(img)  # img pixels changed under the old draw handle
    img.save(out_path)


# ---------------------------------------------------------------------
# Baseline / residual analysis
# ---------------------------------------------------------------------

def analyze_page(chunks):
    by_y = defaultdict(list)
    for ch in chunks:
        by_y[ch["y_decipoints"]].append(ch)
    baselines_dp = sorted(by_y.keys())
    baselines_pt = [y / DECIPT_PER_PT for y in baselines_dp]
    gaps_pt = [
        (baselines_dp[k + 1] - baselines_dp[k]) / DECIPT_PER_PT
        for k in range(len(baselines_dp) - 1)
    ]

    residuals = []
    for y in baselines_dp:
        row = sorted(by_y[y], key=lambda c: c["x_decipoints"])
        for a, b in zip(row, row[1:]):
            w_pt = chunk_width_pt(a)
            expected_end_dp = a["x_decipoints"] + w_pt * DECIPT_PER_PT
            residual_dp = b["x_decipoints"] - expected_end_dp
            residuals.append(
                {
                    "y_decipoints": y,
                    "x1_decipoints": a["x_decipoints"],
                    "text1": a["text"],
                    "font1": a["font"],
                    "size1_pt": a["size_pt"],
                    "x2_decipoints": b["x_decipoints"],
                    "text2": b["text"],
                    "residual_pt": residual_dp / DECIPT_PER_PT,
                }
            )
    return baselines_pt, gaps_pt, residuals


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pcl_file")
    ap.add_argument("--out-prefix", required=True, help="PNG path prefix; pages become PREFIX-p1.png, -p2.png, ...")
    ap.add_argument("--json", required=True, help="path to write full measurement JSON")
    ap.add_argument("--dpi", type=int, default=DPI_DEFAULT)
    ap.add_argument("--no-png", action="store_true", help="skip PNG rendering (measurement-only run)")
    args = ap.parse_args(argv)

    with open(args.pcl_file, "rb") as f:
        data = f.read()

    pages, unhandled, recognized_not_rendered, meta = parse_pcl_extended(data)

    out = {
        "source": os.path.abspath(args.pcl_file),
        "dpi": args.dpi,
        "page_size_in": [PAGE_W_IN, PAGE_H_IN],
        "orientation": meta,
        "font_mapping": {str(k): v for k, v in TYPEFACE_FAMILY.items()},
        "font_mapping_notes": TYPEFACE_FAMILY_SOURCE_NOTE,
        "unhandled_pcl_commands": dict(unhandled),
        "recognized_not_rendered": dict(recognized_not_rendered),
        "pages": [],
    }

    png_files = []
    all_residuals = []
    total_rects = 0
    total_rasters = 0
    for pidx, chunks in enumerate(pages, start=1):
        text_chunks = [c for c in chunks if c.get("type", "text") == "text"]
        rect_ops = [c for c in chunks if c.get("type") == "rect"]
        raster_ops = [c for c in chunks if c.get("type") == "raster"]
        total_rects += len(rect_ops)
        total_rasters += len(raster_ops)
        pub_chunks = [
            {
                "page": pidx,
                "x_decipoints": c["x_decipoints"],
                "y_decipoints": c["y_decipoints"],
                "size_pt": c["size_pt"],
                "font": c["font"],
                "text": c["text"],
                "underline": bool(c.get("_UL")),
            }
            for c in text_chunks
        ]
        pub_rects = [
            {
                "page": pidx,
                "x_decipoints": r["x_decipoints"],
                "y_decipoints": r["y_decipoints"],
                "w_decipoints": r["w_decipoints"],
                "h_decipoints": r["h_decipoints"],
                "fill_type": r["fill_type"],
                "gray_pct": r["gray_pct"],
                "fill_rgb": list(r["_fill"]),
            }
            for r in rect_ops
        ]
        pub_rasters = [
            {
                "page": pidx,
                "x_decipoints": rs["x_decipoints"],
                "y_decipoints": rs["y_decipoints"],
                "resolution_dpi": rs["resolution_dpi"],
                "width_px": rs["width_px"],
                "height_px": rs["height_px"],
                "n_rows": rs["n_rows"],
                "total_row_bytes": rs["total_row_bytes"],
            }
            for rs in raster_ops
        ]
        baselines_pt, gaps_pt, residuals = analyze_page(text_chunks)
        for r in residuals:
            r["page"] = pidx
        all_residuals.extend(residuals)
        out["pages"].append(
            {
                "page": pidx,
                "n_chunks": len(text_chunks),
                "chunks": pub_chunks,
                "rects": pub_rects,
                "rasters": pub_rasters,
                "baselines_pt": baselines_pt,
                "baseline_gaps_pt": gaps_pt,
                "width_residuals": residuals,
            }
        )
        if not args.no_png:
            png_path = f"{args.out_prefix}-p{pidx}.png"
            render_page_png(chunks, args.dpi, png_path)
            png_files.append(png_path)

    abs_res = [abs(r["residual_pt"]) for r in all_residuals]
    if abs_res:
        stats = {
            "count": len(abs_res),
            "max_abs_pt": max(abs_res),
            "median_abs_pt": statistics.median(abs_res),
            "mean_abs_pt": statistics.mean(abs_res),
        }
    else:
        stats = {"count": 0}
    out["residual_stats"] = stats
    out["worst_residuals"] = sorted(all_residuals, key=lambda r: -abs(r["residual_pt"]))[:10]
    out["png_files"] = png_files

    with open(args.json, "w") as f:
        json.dump(out, f, indent=2)

    text_chunk_total = sum(len(p["chunks"]) for p in out["pages"])
    print(f"pages: {len(pages)}")
    print(f"text chunks total: {text_chunk_total}")
    print(f"rect ops total: {total_rects}")
    print(f"raster ops total: {total_rasters}")
    print(f"residual stats: {stats}")
    print("worst 10 residuals:")
    for r in out["worst_residuals"]:
        print(
            f"  page={r['page']} y={r['y_decipoints']}dp residual={r['residual_pt']:.2f}pt "
            f"'{r['text1']}'[{r['font1']}@{r['size1_pt']}pt] -> '{r['text2']}'"
        )
    if meta.get("graphics_commands"):
        print("Graphics/pattern commands handled:")
        for k, v in meta["graphics_commands"].items():
            print(f"  {v:5d}  {k}")
    if unhandled:
        print("UNHANDLED PCL commands (not interpreted):")
        for k, v in unhandled.items():
            print(f"  {v:5d}  {k}")
    if recognized_not_rendered:
        print("Recognized-but-not-rendered commands:")
        for k, v in recognized_not_rendered.items():
            print(f"  {v:5d}  {k}")
    print(f"JSON: {args.json}")
    for p in png_files:
        print(f"PNG: {p}")


if __name__ == "__main__":
    main()
