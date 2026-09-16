"""Pre-Unicode symbol-font encodings -> real Unicode.

A byte set in the Symbol or ZapfDingbats font is not styled text -- it is a
GLYPH INDEX into that font: 'a' in Symbol means alpha, '!' in Dingbats means
an upper-blade scissors. Unicode absorbed both faces (U+2700..27BF is ITC
Zapf Dingbats by name and order; Symbol's Greek and operators all have
codepoints), so the faithful conversion is transliteration at decode time --
after which the text renders everywhere with NO font requirement at all.
Jon's framing, 2026-08-04: "pre-unicode/emoji... I don't think there's an
equivalent" -- there is, and it's Unicode itself.

Trigger is the font block's own symbol-map bits (10=Math -> Symbol encoding,
11=Symbols -> Dingbats encoding) with the typestyle NAME as fallback.
Consistent with the CP850 oracle finding: there the DRIVER ignored the bits
(body bytes stayed cp437 for text fonts); here the FONT carries the glyphs,
and emulating the font is exactly what a converter is for.

Unmapped bytes pass through unchanged -- pass-through beats a wrong guess.
"""

# Adobe Symbol encoding, the well-established core: Greek per Latin letter
# positions, plus the operators the era actually printed. (Not exhaustive;
# unmapped characters fall through verbatim.)
SYMBOL = {
    'A': 'Α', 'B': 'Β', 'G': 'Γ', 'D': 'Δ', 'E': 'Ε', 'Z': 'Ζ', 'H': 'Η',
    'Q': 'Θ', 'I': 'Ι', 'K': 'Κ', 'L': 'Λ', 'M': 'Μ', 'N': 'Ν', 'X': 'Ξ',
    'O': 'Ο', 'P': 'Π', 'R': 'Ρ', 'S': 'Σ', 'T': 'Τ', 'U': 'Υ', 'F': 'Φ',
    'C': 'Χ', 'Y': 'Ψ', 'W': 'Ω',
    'a': 'α', 'b': 'β', 'g': 'γ', 'd': 'δ', 'e': 'ε', 'z': 'ζ', 'h': 'η',
    'q': 'θ', 'i': 'ι', 'k': 'κ', 'l': 'λ', 'm': 'μ', 'n': 'ν', 'x': 'ξ',
    'o': 'ο', 'p': 'π', 'r': 'ρ', 's': 'σ', 't': 'τ', 'u': 'υ', 'f': 'φ',
    'c': 'χ', 'y': 'ψ', 'w': 'ω',
    'V': 'ς', 'j': 'ϕ', 'v': 'ϖ', 'J': 'ϑ',
    '"': '∀', '$': '∃', "'": '∋', '*': '∗', '-': '−', '@': '≅',
    '~': '∼', '¹': '≠', '£': '≤', '³': '≥', '´': '×', '¸': '÷',
    '¥': '∞', 'Î': '∈', 'Ï': '∉', 'å': '∑', 'Õ': '∏', 'Ö': '√',
    '×': '⋅', '°': '°', '±': '±', '¶': '∂', 'Ñ': '∇', 'ò': '∫',
    '«': '↔', '¬': '←', '­': '↑', '®': '→', '¯': '↓',
    # Adobe Symbol encoding position 0267 octal (0xB7/183) is "periodcentered"
    # -- visually identical to Unicode's own MIDDLE DOT, so self-mapped like
    # the other same-glyph positions above ('°', '±'). Round 2026-09-07 (the
    # pdf.py GRAPHIC_CHARS-in-a-Symbol-run fix): without this a middle dot
    # reaching untransliterate() on a Symbol/math-mapped span (font
    # symbol_map='math') had no code point in SYMBOL_REVERSE and fell to
    # untransliterate's own '?' degradation same as an unmapped glyph would.
    '·': '·',
}

# ZapfDingbats low half: Unicode's U+2700 block was DEFINED in Zapf order,
# so 0x21-0x7E map by formula. The handful of famous cross-block residents
# (card suits, which Unicode already had at U+2660) are explicit.
_DINGBAT_EXCEPTIONS = {
    0xA8: '♣', 0xA9: '♦', 0xAA: '♥', 0xAB: '♠',
}

def _dingbat(ch):
    b = ord(ch)
    if b in _DINGBAT_EXCEPTIONS:
        return _DINGBAT_EXCEPTIONS[b]
    if 0x21 <= b <= 0x7E:
        return chr(0x2700 + (b - 0x20))
    return ch                                   # pass through, never guess

# ---- the way back: Unicode -> the font's own byte codes --------------------
#
# Transliteration is the right answer for text formats, which have no font at
# all. The PDF emitter is the one consumer that CAN show the real glyph: the
# PDF base-14 set includes Symbol and ZapfDingbats themselves, so selecting
# that font and writing the ORIGINAL byte gives the true face with nothing
# embedded. That needs the inverse of the map above.
#
# Round-trip rule, symmetric with `transliterate`: a character the forward map
# never touched (digits, space, punctuation -- all of which sit at their ASCII
# positions in both faces) passes back through as itself. Anything else has no
# code point in the face at all and becomes '?', the same degradation the rest
# of the PDF emitter uses for characters it cannot write.

SYMBOL_REVERSE = {}
for _code, _uni in SYMBOL.items():
    SYMBOL_REVERSE.setdefault(_uni, _code)          # first key wins; the map
                                                     # has no duplicate glyphs
_DINGBAT_REVERSE = {u: chr(b) for b, u in _DINGBAT_EXCEPTIONS.items()}

def _dingbat_code(ch):
    """Inverse of _dingbat(): the ZapfDingbats byte for a Unicode glyph, or
    None if this face never carried it."""
    if ch in _DINGBAT_REVERSE:
        return _DINGBAT_REVERSE[ch]
    cp = ord(ch)
    if 0x2701 <= cp <= 0x275E:                      # the block _dingbat() emits
        return chr(cp - 0x2700 + 0x20)
    return None

def symbol_fallback_kind(ch):
    """Which base-14 symbol face (if any) carries `ch` in its own byte
    codes: 'math' for the Adobe Symbol encoding, 'symbols' for
    ZapfDingbats (checked in that order -- the two encodings never
    overlap, so order doesn't matter for correctness, only for which
    check runs first). None if neither face has it.

    For a caller deciding whether a character the body face (cp1252)
    cannot carry has ANY substitute face at all -- the same question
    `font_translit_kind` answers from a font block's own declared bits,
    asked instead per character, for prose that carries a handful of
    cp437 Greek/math or Dingbats bytes with no Symbol/Dingbats font
    block in play at all (pdf.py's `_split_symbol_fallback`/
    `_symbol_fallback_split`)."""
    if ch in SYMBOL_REVERSE:
        return 'math'
    if _dingbat_code(ch) is not None:
        return 'symbols'
    return None

def untransliterate(text, kind):
    """Inverse of transliterate: real Unicode -> the bytes to set in the
    Symbol/ZapfDingbats font itself. Unmappable characters -> '?'."""
    if kind not in ('math', 'symbols'):
        return text
    out = []
    for ch in text:
        code = (SYMBOL_REVERSE.get(ch) if kind == 'math' else _dingbat_code(ch))
        if code is None:
            # ASCII rode through the forward map untouched and rides back the
            # same way (both faces keep ASCII punctuation and digits in place).
            code = ch if ' ' <= ch <= '~' else '?'
        out.append(code)
    return ''.join(out)

def transliterate(text, kind):
    """kind: 'math' (Symbol encoding) or 'symbols' (ZapfDingbats)."""
    if kind == 'math':
        return ''.join(SYMBOL.get(c, c) for c in text)
    if kind == 'symbols':
        return ''.join(_dingbat(c) for c in text)
    return text

# Typestyle numbers whose NAME announces a non-text face: the table's own
# word for the glyph repertoire, not a typeface a sentence can be set in.
# 82 (ZapfDingbats) and 192 (Symbol) are matched by name above and never
# reach this set. Numbers, not substrings: 'Pica' contains 'pi' and
# 'Presentations' contains 'ps' -- a substring test on this table is a trap.
NON_TEXT_TYPESTYLES = frozenset({
    33,    # Borders
    68,    # LucidaMath
    143,   # Math-7 (HPLJ)
    144,   # Math-8 (HPLJ)
    166,   # PI
    188,   # Math
    234,   # TD Logos
    244,   # Greek (PS (Universal Greek))
})


def font_translit_kind(font_entry):
    """The transliteration a font run needs, from the typestyle NAME first and
    the block's own symbol-map bits only as the fallback for a face the name
    table cannot resolve. None = ordinary text font."""
    if not font_entry:
        return None
    # NAME first: it is the specific signal. The coarse symbol-map bits can
    # say 'math' for both faces (PS.TST's Dingbats row transliterated to
    # Greek until this ordering).
    name = (font_entry.get('typestyle_name') or '').lower()
    if name.startswith('symbol'):
        return 'math'
    if 'dingbat' in name:
        return 'symbols'
    # A RESOLVED ORDINARY FACE WINS over the character-set bits (ruling
    # 2026-09-16). WordStar's symbol_map bits say which upper-128 (0x80-0xFF)
    # table the EXTENDED characters of a run use; they were never a
    # "replace the alphabet" switch. NOVEL.WS's own 'MS Front Pages' /
    # 'Font: Normal' styles carry typestyle 3 (Courier) with the math bits
    # set, and ten pages of ordinary English prose were being redirected
    # through Adobe Symbol's encoding, so every Latin letter came out as
    # the Greek letter sitting at its keyboard position. Real WS7's
    # LaserJet output prints those pages as plain readable Courier.
    # Characters that genuinely have no home in the body face are still
    # picked up one at a time by the per-character
    # fallback (`char_translit_kind`, pdf.py's `_symbol_fallback_split`),
    # which is what that mechanism was built for.
    #
    # The bits stay the fallback for the case the docstring always claimed:
    # a face the 245-entry name table cannot resolve, and the handful of
    # named faces that are themselves non-text repertoires.
    if name and font_entry.get('typestyle_number') not in NON_TEXT_TYPESTYLES:
        return None
    sm = font_entry.get('symbol_map')
    if sm in ('math', 'symbols'):
        return sm
    return None
