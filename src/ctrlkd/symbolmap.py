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

def transliterate(text, kind):
    """kind: 'math' (Symbol encoding) or 'symbols' (ZapfDingbats)."""
    if kind == 'math':
        return ''.join(SYMBOL.get(c, c) for c in text)
    if kind == 'symbols':
        return ''.join(_dingbat(c) for c in text)
    return text

def font_translit_kind(font_entry):
    """The transliteration a font run needs, from the block's own symbol-map
    bits first, typestyle name as fallback. None = ordinary text font."""
    if not font_entry:
        return None
    # NAME first: it is the specific signal. The coarse symbol-map bits can
    # say 'math' for both faces (PS.TST's Dingbats row transliterated to
    # Greek until this ordering); bits remain the fallback for unnamed fonts.
    name = (font_entry.get('typestyle_name') or '').lower()
    if name.startswith('symbol'):
        return 'math'
    if 'dingbat' in name:
        return 'symbols'
    sm = font_entry.get('symbol_map')
    if sm in ('math', 'symbols'):
        return sm
    return None
