#!/usr/bin/env python3
"""
pcl_text.py -- standalone PCL text/position extractor (stdlib only).

Decodes the PCL subset emitted by WordStar 7's LASERJET driver (under
DOSBox-X) well enough to recover, per page, the sequence of text runs and
the exact cursor position (in PCL decipoints, i.e. 1/720 inch) at which
each run was placed -- as set by ESC&a<n>H (horizontal) and ESC&a<n>V
(vertical).

Design goal: NEVER regex-grep printable text out of the byte stream.
Instead implement the real PCL escape-sequence grammar (HP PCL5 spec) so
that any escape sequence -- known or not -- is parsed and skipped
correctly, keeping the byte offset in sync. Only bytes that are not part
of any escape sequence and are >= 0x20 are ever treated as text.

Grammar implemented
--------------------
1. Two-character escape sequences:  ESC <c>  where <c> is NOT in the
   range 0x21-0x2F.  E.g. ESC E (printer reset).

2. Parameterized escape sequences:  ESC <param-char> ...
   <param-char> is one of the "class" bytes in range 0x21-0x2F
   (observed: '%' 0x25, '&' 0x26, '(' 0x28, ')' 0x29, '*' 0x2A).

   a) If the next byte is a lowercase letter (0x60-0x7A), it is the
      "group character".  What follows is one or more
          <value><field-char>
      tokens, where <value> is an optional signed decimal number
      (digits, optional leading sign, optional '.' and more digits --
      any part may be absent) and <field-char> is a single byte:
        - 0x60-0x7A (lowercase)  -> this field ends, but the escape
          sequence CONTINUES with another <value><field-char> token in
          the same group (per HP's "combine parameters" convention,
          e.g. ESC&l0l1T == ESC&l0L combined with ESC&l1T).
        - 0x40-0x5A or '@'/other bytes in 0x40-0x5A (uppercase letters
          and '@') -> this field ends AND terminates the whole escape
          sequence.

   b) If the next byte is NOT a lowercase letter (typically a digit or
      sign -- the "groupless" form used for things like symbol-set
      selection, ESC(10U, or the UEL ESC%-12345X), there is no group
      character: parse a single <value><terminator> token directly and
      the escape sequence ends there.

3. 0x0C (form feed) ejects the current page.
4. 0x0D / 0x0A (CR/LF) and other bytes < 0x20 (e.g. 0x1A SUB padding at
   EOF) are control bytes with no PCL meaning here; skipped.
5. Any other byte (>= 0x20, including 0x80-0xFF "high" bytes for the
   PC-8/cp437-ish symbol set WordStar selects) is text: a *run* is the
   longest contiguous span of such bytes, decoded with the cp437
   codec (ASCII-compatible for 0x20-0x7E, WordStar's driver selects
   symbol set "10U" = PC-8 which corresponds to code page 437 for the
   upper half).

Only ESC&a<n>H / ESC&a<n>V are given semantic meaning (cursor position,
decipoints). Every other escape sequence -- font selection ESC(s...,
symbol set ESC(10U, page setup ESC&l..., underline ESC&d@/ESC&dD, PJL
UEL wrappers, etc. -- is parsed generically and discarded. This means
new/unknown sequences never desync the parser or leak into text runs.

A "run" is only emitted once BOTH a horizontal and a vertical position
have been established (this naturally excludes the leading "@PJL ENTER
LANGUAGE=PCL" preamble line, which prints before any cursor-positioning
escape has been seen).

KNOWN LIMIT: PCL sequences carrying a BINARY payload (soft-font or
raster downloads: ESC(s#W / ESC*b#W followed by # raw bytes) are not
consumed as data -- the payload bytes would be misread as text/escapes
and desync the stream. WordStar's LASERJET driver emits none of these
for plain documents (all validation samples clean); documents whose
0x0F user-print-controls inject raw printer payloads WILL confuse this
decoder. Teach it byte-count consumption before trusting it on those.

A trailing empty page (produced by the FF that ejects the final sheet
right before the closing ESC E / UEL) is dropped so page counts reflect
actual printed pages, not the eject-to-cassette artifact.
"""

import argparse
import json
import sys


def parse_pcl(data: bytes):
    """Parse a PCL byte stream. Returns a list of pages, each a list of
    run dicts: {"x_decipoints": int, "y_decipoints": int, "text": str}.
    """
    n = len(data)
    i = 0
    pages = []
    cur_runs = []
    cursor_x = None
    cursor_y = None

    def parse_value(j):
        """Parse an optional signed decimal number starting at j.
        Returns (value_str, new_j)."""
        start = j
        if j < n and data[j] in (0x2B, 0x2D):  # + or -
            j += 1
        while j < n and 0x30 <= data[j] <= 0x39:
            j += 1
        if j < n and data[j] == 0x2E:  # '.'
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

    def handle_field(param, group, value_str, field_char):
        nonlocal cursor_x, cursor_y
        if param == "&" and group == "a":
            v = to_num(value_str)
            if v is not None:
                if field_char == "H":
                    cursor_x = int(round(v))
                elif field_char == "V":
                    cursor_y = int(round(v))
        # All other groups/fields (font selection, page setup, underline,
        # symbol set, PJL UEL, etc.) are intentionally not interpreted --
        # they were still correctly consumed by the generic grammar above.

    def flush_page():
        nonlocal cur_runs
        pages.append(cur_runs)
        cur_runs = []

    while i < n:
        b = data[i]
        if b == 0x1B:  # ESC
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
                    while True:
                        value_str, i = parse_value(i)
                        if i >= n:
                            break  # truncated/malformed; bail safely
                        fb = data[i]
                        i += 1
                        field_char = chr(fb)
                        handle_field(param, group, value_str, field_char)
                        if 0x60 <= fb <= 0x7A:
                            continue  # more fields in this group
                        else:
                            # terminator (0x40-0x5A, '@', or any other
                            # non-lowercase byte) ends the sequence
                            break
                else:
                    # groupless form: single <value><terminator>
                    value_str, i = parse_value(i)
                    if i < n:
                        fb = data[i]
                        i += 1
                        handle_field(param, None, value_str, chr(fb))
            else:
                # two-character escape sequence, e.g. ESC E
                i += 1
                # nothing to do: reset etc. carry no position semantics
        elif b == 0x0C:  # form feed -> page eject
            flush_page()
            cursor_x = None
            cursor_y = None
            i += 1
        elif b in (0x0D, 0x0A):
            i += 1
        elif b < 0x20:
            i += 1  # stray control byte (e.g. 0x1A SUB EOF padding)
        else:
            start = i
            while i < n and data[i] >= 0x20 and data[i] != 0x1B:
                i += 1
            text = bytes(data[start:i]).decode("cp437", "replace")
            if cursor_x is not None and cursor_y is not None:
                cur_runs.append(
                    {"x_decipoints": cursor_x, "y_decipoints": cursor_y, "text": text}
                )
            # else: preamble text (e.g. "@PJL ENTER LANGUAGE=PCL") before
            # any cursor position has been established -- not page content.

    # Final page: keep it unless it's an empty artifact left by the
    # eject-FF that immediately precedes the closing reset/UEL.
    if cur_runs or not pages:
        pages.append(cur_runs)

    return pages


def to_text_grid(runs, x_scale=60):
    """Lay runs out on a simple line/column grid for human diffing.
    x_scale is decipoints-per-character-column (60 ~= 12 cpi)."""
    lines = {}
    for r in runs:
        lines.setdefault(r["y_decipoints"], []).append(r)
    out = []
    for y in sorted(lines):
        row_runs = sorted(lines[y], key=lambda r: r["x_decipoints"])
        buf = []
        col = 0
        for r in row_runs:
            target_col = max(col, round(r["x_decipoints"] / x_scale))
            if target_col > col:
                buf.append(" " * (target_col - col))
                col = target_col
            buf.append(r["text"])
            col += len(r["text"])
        out.append(f"{y:6d} | " + "".join(buf))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pcl_file", help="path to a .pcl/.prn PCL byte stream")
    ap.add_argument(
        "--text",
        action="store_true",
        help="human-readable line-grid layout instead of JSON",
    )
    ap.add_argument(
        "--x-scale",
        type=int,
        default=60,
        help="decipoints per character column for --text (default 60)",
    )
    args = ap.parse_args(argv)

    with open(args.pcl_file, "rb") as f:
        data = f.read()

    pages = parse_pcl(data)

    if args.text:
        for idx, runs in enumerate(pages, start=1):
            print(f"=== page {idx} ({len(runs)} runs) ===")
            for line in to_text_grid(runs, x_scale=args.x_scale):
                print(line)
            print()
    else:
        for idx, runs in enumerate(pages, start=1):
            print(json.dumps({"page": idx, "runs": runs}))


if __name__ == "__main__":
    main()
