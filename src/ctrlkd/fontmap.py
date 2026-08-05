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
