"""Era font names -> modern equivalents, as FALLBACKS (never replacements).

The WordStar-era names (the PostScript base-35 set, LaserJet cartridge
faces) mostly don't exist under those names on a modern system: a Mac has
Helvetica but not Helvetica Narrow; Windows has Bookman Old Style but not
Bookman. Per the pass-through rule the ORIGINAL name always travels first;
these lists supply what a renderer should try next, ending with what the
font block's own generic-style bits say (sans/serif/script/display).

  RTF   uses the first alternate via {\\*\\falt ...} -- RTF's native
        fallback mechanism, honoured by Word.
  HTML  uses the whole list as a font-family stack.

Keys are the RENDERED family (typestyle name up to its parenthetical),
compared case-insensitively. Extend freely; unlisted names simply fall
through to the generic.
"""

FONT_ALTS = {
    # PostScript base-35 and friends
    'avant garde':            ['Century Gothic', 'ITC Avant Garde Gothic'],
    'bookman':                ['Bookman Old Style'],
    'cntry schlbk':           ['Century Schoolbook', 'New Century Schoolbook'],
    'newcntschlbk':           ['Century Schoolbook', 'New Century Schoolbook'],
    'new century schoolbook': ['Century Schoolbook'],
    'century':                ['Century Schoolbook'],
    'helv':                   ['Helvetica', 'Arial'],
    'helvetica':              ['Arial', 'Helvetica Neue'],
    'helv cond.':             ['Arial Narrow', 'Helvetica Neue Condensed'],
    'helv narrow':            ['Arial Narrow', 'Helvetica Neue Condensed'],
    'helvetica narrow':       ['Arial Narrow', 'Helvetica Neue Condensed'],
    'palatino':               ['Palatino', 'Palatino Linotype', 'Book Antiqua'],
    'tms rmn':                ['Times New Roman', 'Times'],
    'times':                  ['Times New Roman'],
    'zapfchancery':           ['Apple Chancery', 'Monotype Corsiva'],
    'zapf chancery':          ['Apple Chancery', 'Monotype Corsiva'],
    'zapfdingbats':           ['Zapf Dingbats', 'Wingdings'],
    'zapf dingbats':          ['Zapf Dingbats', 'Wingdings'],
    'symbol':                 ['Symbol'],
    'courier':                ['Courier New'],
    'pica':                   ['Courier New'],
    'elite':                  ['Courier New'],
    'lineprinter':            ['Courier New'],
    'letter gothic':          ['Letter Gothic', 'Courier New'],
    'gothic':                 ['Letter Gothic', 'Courier New'],
    'prestige':               ['Prestige Elite', 'Courier New'],
    # common LaserJet/DTP-era scalables seen in the wild
    'univers':                ['Helvetica Neue', 'Arial'],
    'antique olive':          ['Optima', 'Verdana'],
    'cg times':               ['Times New Roman'],
    'cg triumvirate':         ['Arial', 'Helvetica'],
    'garamond':               ['Garamond', 'EB Garamond'],
    'optima':                 ['Optima', 'Candara'],
    'clarendon':              ['Clarendon', 'Rockwell'],
    'aachen':                 ['Rockwell', 'Courier New'],
    'bodoni':                 ['Bodoni 72', 'Bodoni MT', 'Didot'],
    'broadway':               ['Broadway'],
    'univ. roman':            ['University Roman', 'Georgia'],
    'ps sansser qual':        ['Arial', 'Helvetica'],
    'american classic':       ['Century Schoolbook', 'Georgia'],
    'rockwell':               ['Rockwell', 'Courier New'],
    'coronet':                ['Coronet', 'Apple Chancery', 'Monotype Corsiva'],
}

_GENERIC_CSS = {'sans': 'sans-serif', 'serif': 'serif',
                'script': 'cursive', 'display': 'fantasy'}

# ---- render targets (Jon's ruling, 2026-08-04 night) -----------------------
# One RTF file cannot serve every importer (Office-private fonts, Cocoa's
# falt-blindness, Docs' web catalog), so the CALLER picks a target:
#   office  Word-first (default): Microsoft names, resolved by Word AND Docs
#   mac     Cocoa-native names -- TextEdit/Pages/Soft Return.app world
#   google  Docs' own catalog where it has something Office lacks (chancery)
# Coverage rule: a family with no entry in FONT_ALTS still gets a USEFUL face
# from its font block's own generic-style bits -- never nothing.

GENERIC_PRIMARY = {
    'office': {'sans': 'Arial', 'serif': 'Times New Roman',
               'script': 'Monotype Corsiva', 'display': 'Impact'},
    'mac':    {'sans': 'Helvetica', 'serif': 'Georgia',
               'script': 'Apple Chancery', 'display': 'Futura'},
    'google': {'sans': 'Arial', 'serif': 'Times New Roman',
               'script': 'Dancing Script', 'display': 'Impact'},
}

TARGET_OVERRIDES = {
    'office': {},
    # macOS-native stand-ins for the Office-private set: Futura carries the
    # Avant Garde geometry; Iowan Old Style is the closest native to
    # Bookman's warmth; Georgia was DESIGNED as a screen Schoolbook-alike.
    'mac': {
        'avant garde': 'Futura',
        'bookman': 'Iowan Old Style',
        'cntry schlbk': 'Georgia',
        'newcntschlbk': 'Georgia',
        'new century schoolbook': 'Georgia',
        'century': 'Georgia',
        'american classic': 'Iowan Old Style',
        'helv': 'Helvetica',
        'helvetica': 'Helvetica',
        'univers': 'Helvetica Neue',
    },
    # Docs resolves the Microsoft names natively; its one real gap is a
    # chancery script -- Dancing Script is the stock calligraphic answer.
    'google': {
        'zapfchancery': 'Dancing Script',
        'zapf chancery': 'Dancing Script',
        'coronet': 'Dancing Script',
    },
}


def rtf_fonts(family, generic_style=None, target='office'):
    """(primary, falt_or_None) for an RTF fonttbl entry. The primary is the
    target's best AVAILABLE name; the falt is the next-best MODERN name --
    never the era name (Jon: 'no use keeping the ALT font that crazy title'
    -- nothing modern resolves 'PS SansSer Qual'; the verbatim era name
    stays first-class in doc.fonts and the HTML stacks). A family with no
    table entry gets the target's generic primary from the font block's own
    style bits, so EVERY font run lands on a usable face."""
    fam_key = (family or '').lower()
    alts = FONT_ALTS.get(fam_key, [])
    primary = (TARGET_OVERRIDES.get(target, {}).get(fam_key)
               or (alts[0] if alts else None)
               or GENERIC_PRIMARY.get(target, GENERIC_PRIMARY['office'])
                  .get(generic_style or ''))
    if not primary:
        return (family or None), None
    falt = next((a for a in alts if a != primary), None)
    return primary, falt


def font_stack(family, generic_style=None):
    """CSS-style ordered list: original family first, then modern
    alternates, then the generic from the font block's own style bits."""
    stack = [family] if family else []
    for alt in FONT_ALTS.get((family or '').lower(), []):
        if alt not in stack:
            stack.append(alt)
    generic = _GENERIC_CSS.get(generic_style or '')
    if generic:
        stack.append(generic)
    return stack


def rtf_alternate(family):
    """The single best alternate for RTF's {\\*\\falt ...}, or None."""
    alts = FONT_ALTS.get((family or '').lower(), [])
    return alts[0] if alts else None
