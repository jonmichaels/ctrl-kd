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
    # No Wingdings here: its glyph MAPPING differs, so a fallback to it
    # would print wrong symbols -- and dingbat runs are transliterated to
    # real Unicode anyway, which any font-stack terminus can render.
    'zapfdingbats':           ['Zapf Dingbats'],
    'zapf dingbats':          ['Zapf Dingbats'],
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
    # Albertus (Monotype, Berthold Wolpe): a glyphic/flared-serif display
    # face -- chiseled, incised strokes, neither a classic serif nor a
    # sans. Not in WSFORMAT.TXT's own 245-entry typestyle catalog at all
    # (verified against the public spec, sfwriter.com/wsformat.txt: zero
    # occurrences) -- WordStar's LaserJet printer drivers (LASERJET.PDF,
    # LJ6DTP.PDF, HP4.PDF, all in the Sawyer archive) instead route their
    # own typestyle 50 ("Aachen (Postscript)" per the canonical table) to
    # the real HP-resident face "Albertus PC ..." -- confirmed by the raw
    # driver bytes (name pairs `Aachen\x00Albertus PC ...\x00`) and by
    # PREVIEW.WS itself, WordStar's own factory demo file, whose caption
    # literally labels that exact font block "Albertus". Herculanum first
    # (closest MAC-native glyphic/incised face); Colonna MT next (the
    # Office-bundled glyphic equivalent, same family as this table's own
    # 'univ. roman' -> Harrington choice); Rockwell as the universal-safe
    # tail (matches 'clarendon'/'aachen' precedent above).
    'albertus':               ['Herculanum', 'Colonna MT', 'Rockwell'],
    # Marigold (Agfa Compugraphic, Arthur Baker, 1989): a calligraphic
    # script face. Also absent from WSFORMAT.TXT's 245-entry catalog --
    # the same LaserJet driver files route typestyle 81 ("ZapfChancery")
    # to the real HP-resident face "Marigold PC ..." (name pair
    # `ZapfChancery\x00Marigold PC ...\x00`), so it takes the same modern
    # alternates already ruled for zapfchancery/coronet.
    'marigold':               ['Apple Chancery', 'Monotype Corsiva', 'Coronet'],
}

_GENERIC_CSS = {'sans': 'sans-serif', 'serif': 'serif',
                'script': 'cursive', 'display': 'fantasy'}

# ---- render targets (Jon's ruling, 2026-08-04 night) -----------------------
# One RTF file cannot serve every importer (Office-private fonts, Cocoa's
# falt-blindness, Docs' web catalog), so the CALLER picks a target:
#   office  Word-first (default): fonts DISTRIBUTED WITH MS OFFICE (Century
#           Gothic etc. are Office-only -- bare Windows has just the web-core
#           set plus Palatino Linotype), resolved by Word AND Google Docs;
#           LibreOffice substitutes them decently via its own tables
#   mac     Cocoa-native names -- TextEdit/Pages/Soft Return.app world
#   google  Docs' own catalog where it has something Office lacks (chancery)
#   linux   the URW base-35 clones (Ghostscript heritage, packaged everywhere
#           as fonts-urw-base35): free metric-compatible copies of EXACTLY
#           this era's set -- URW Gothic IS Avant Garde, URW Bookman IS
#           Bookman, C059 IS New Century Schoolbook, P052 IS Palatino, Z003
#           IS Zapf Chancery, Nimbus Sans/Roman/Mono PS are Helvetica/Times/
#           Courier. The most faithful target of all, and libre.
# Coverage rule: a family with no entry in FONT_ALTS still gets a USEFUL face
# from its font block's own generic-style bits -- never nothing.

GENERIC_PRIMARY = {
    'office': {'sans': 'Arial', 'serif': 'Times New Roman',
               'script': 'Monotype Corsiva', 'display': 'Impact'},
    # mac serif -> Times New Roman (Jon's ruling 2026-08-05): the generic
    # fires for UNKNOWN faces, and the era-honest render is the era's own
    # neutral serif; Georgia now means exactly one thing on mac (NCS).
    'mac':    {'sans': 'Helvetica', 'serif': 'Times New Roman',
               'script': 'Apple Chancery', 'display': 'Futura'},
    # google display -> Poppins: Impact exists in Docs' MENU but the import
    # CONVERTER maps names through an internal table that lacks it (Jon's
    # three import tests, 2026-08-05 -- the Drive previewer renders Impact,
    # conversion turns every declaration form into Arial identically).
    'google': {'sans': 'Arial', 'serif': 'Times New Roman',
               'script': 'Dancing Script', 'display': 'Poppins'},
    'linux':  {'sans': 'DejaVu Sans', 'serif': 'DejaVu Serif',
               'script': 'Z003', 'display': 'DejaVu Sans'},
}

# The sophisticated body: what a document with NO font information at all
# (every WS4 file, fontless WS5+) reads in under Modern. Jon's specimen
# ruling 2026-08-05: "Georgia 14 at 1in margins -- like reading a cozy
# book" -- and one font for ALL targets, because RTF's falt and HTML's
# font stack carry the no-Georgia case natively (the per-target variation
# lives in the FALLBACK). PDF is not here: base-14 by design principle,
# it renders the body as Times at the same size ("the PDF needs to work
# no matter what. Times New Roman 14. It has to be.").
MODERN_BODY_SIZE = 14
MODERN_BODY = {
    'office': ('Georgia', 'Times New Roman'),
    'mac':    ('Georgia', 'Times New Roman'),
    'google': ('Georgia', 'Times New Roman'),
    'linux':  ('Georgia', 'P052'),
}

# ---- the FINAL RULED FONT TABLE (CLI-Defaults-Audit, 2026-08-05) ----------
# Complete per-target (primary, falt) pairs. Every mac cell device-verified
# by Jon (Font Book, locked-flag test); office cells verified against
# Microsoft's published Windows-11 + cloud-fonts lists (11 names are M365
# cloud fonts: menu-visible, auto-fetch, absent from disk -- the target
# means CURRENT CONNECTED WORD); google cells verified by Jon's Docs import
# tests (MS names NEVER survive conversion; Google-catalog names and the
# web core minus Impact do); linux primaries are the URW true clones
# (Ghostscript tier) with every falt a guaranteed-tier name (Liberation
# rides LibreOffice, DejaVu rides fontconfig itself).
#
# A falt of None means the primary is already the safest name available.

def _expand(table):
    """Alias groups -> flat {key: (primary, falt)}."""
    flat = {}
    for keys, pair in table:
        for k in keys.split('|'):
            flat[k] = pair
    return flat

TARGET_FONTS = {
    'office': _expand([
        ('avant garde',                          ('Century Gothic', 'ITC Avant Garde Gothic')),
        ('bookman',                              ('Bookman Old Style', 'Georgia')),
        ('cntry schlbk|newcntschlbk|new century schoolbook|century',
                                                 ('Century Schoolbook', 'Georgia')),
        ('american classic',                     ('Century Schoolbook', 'Georgia')),
        ('helv|helvetica',                       ('Arial', 'Helvetica Neue')),
        ('helv narrow|helv cond.|helvetica narrow',
                                                 ('Arial Narrow', 'Helvetica Neue Condensed')),
        ('palatino',                             ('Palatino Linotype', 'Palatino')),
        ('tms rmn|times|cg times',               ('Times New Roman', None)),
        # Marigold joins this group (not aliased-in-name, but IN
        # SUBSTITUTION): the LaserJet driver files route ZapfChancery's
        # own typestyle number to the real HP-resident face "Marigold",
        # a calligraphic script -- same category, same modern targets.
        ('zapfchancery|zapf chancery|coronet|marigold',
                                                 ('Monotype Corsiva', 'Apple Chancery')),
        ('zapfdingbats|zapf dingbats',           ('Zapf Dingbats', 'Segoe UI Symbol')),
        ('symbol',                               ('Symbol', None)),
        ('courier|pica|elite|lineprinter',       ('Courier New', None)),
        ('letter gothic|gothic',                 ('Consolas', 'Courier New')),
        ('prestige',                             ('Courier New', None)),
        ('univers',                              ('Arial', 'Helvetica Neue')),
        ('cg triumvirate|ps sansser qual',       ('Arial', 'Helvetica')),
        ('antique olive',                        ('Candara', 'Verdana')),
        ('optima',                               ('Candara', 'Optima')),
        ('garamond',                             ('Garamond', 'EB Garamond')),
        ('clarendon',                            ('Rockwell', 'Clarendon')),
        ('aachen|rockwell',                      ('Rockwell', 'Courier New')),
        ('bodoni',                               ('Bodoni MT', 'Bodoni 72')),
        ('broadway',                             ('Broadway', None)),
        ('univ. roman',                          ('Harrington', 'Georgia')),
        # Colonna MT: an Office-bundled glyphic/incised display face (same
        # decorative Office set as the 'univ. roman' -> Harrington choice
        # just above) -- the closest chiseled-serif match Office ships to
        # Albertus's flared, non-serif/non-sans character.
        ('albertus',                              ('Colonna MT', 'Rockwell')),
    ]),
    'mac': _expand([
        ('avant garde',                          ('Futura', 'Century Gothic')),
        ('bookman',                              ('Cochin', 'Bookman Old Style')),
        ('cntry schlbk|newcntschlbk|new century schoolbook|century',
                                                 ('Georgia', 'Century Schoolbook')),
        ('american classic',                     ('Baskerville', 'Century Schoolbook')),
        ('helv|helvetica',                       ('Helvetica', 'Arial')),
        ('helv narrow|helv cond.|helvetica narrow',
                                                 ('Arial Narrow', 'Helvetica Neue Condensed')),
        ('palatino',                             ('Palatino', 'Palatino Linotype')),
        ('tms rmn|times|cg times',               ('Times New Roman', None)),
        # Marigold joins this group in substitution only (LaserJet driver
        # files route ZapfChancery's typestyle to the real HP-resident
        # face "Marigold", a calligraphic script -- same category).
        ('zapfchancery|zapf chancery|coronet|marigold',
                                                 ('Apple Chancery', 'Monotype Corsiva')),
        ('zapfdingbats|zapf dingbats',           ('Zapf Dingbats', None)),
        ('symbol',                               ('Symbol', None)),
        ('courier|pica|elite|lineprinter',       ('Courier New', None)),
        ('letter gothic|gothic',                 ('Menlo', 'Courier New')),
        ('prestige',                             ('Courier New', None)),
        ('univers',                              ('Helvetica Neue', 'Arial')),
        ('cg triumvirate|ps sansser qual',       ('Helvetica', 'Arial')),
        ('antique olive',                        ('Optima', 'Verdana')),
        ('optima',                               ('Optima', 'Candara')),
        ('garamond',                             ('Hoefler Text', 'Garamond')),
        ('clarendon',                            ('Rockwell', 'Clarendon')),
        ('aachen|rockwell',                      ('Rockwell', 'Courier New')),
        ('bodoni',                               ('Bodoni 72', 'Bodoni MT')),
        ('broadway',                             ('Phosphate Solid', 'Futura')),
        ('univ. roman',                          ('Didot', 'Georgia')),
        # Herculanum: Apple's own bundled glyphic/incised display face
        # (Frutiger, ships standard in macOS's decorative set alongside
        # Papyrus) -- the closest Mac-native chiseled-serif match to
        # Albertus's flared, non-serif/non-sans character.
        ('albertus',                              ('Herculanum', 'Copperplate')),
    ]),
    'google': _expand([
        ('avant garde',                          ('Poppins', 'Century Gothic')),
        ('bookman',                              ('Merriweather', 'Bookman Old Style')),
        ('cntry schlbk|newcntschlbk|new century schoolbook|century',
                                                 ('Georgia', 'Century Schoolbook')),
        ('american classic',                     ('Georgia', 'Century Schoolbook')),
        ('helv|helvetica|univers',               ('Arial', None)),
        ('cg triumvirate|ps sansser qual',       ('Arial', None)),
        ('helv narrow|helv cond.|helvetica narrow',
                                                 ('PT Sans Narrow', 'Arial Narrow')),
        ('palatino',                             ('Lora', 'Palatino Linotype')),
        ('tms rmn|times|cg times',               ('Times New Roman', None)),
        # Marigold joins this group in substitution only (see the office
        # table's own note above) -- same calligraphic-script category.
        ('zapfchancery|zapf chancery|coronet|marigold',
                                                 ('Dancing Script', 'Apple Chancery')),
        ('zapfdingbats|zapf dingbats',           ('Zapf Dingbats', None)),
        ('symbol',                               ('Symbol', None)),
        ('courier|pica|elite|lineprinter|letter gothic|gothic|prestige',
                                                 ('Courier New', None)),
        ('antique olive|optima',                 ('Verdana', None)),
        ('garamond',                             ('EB Garamond', 'Garamond')),
        ('clarendon|aachen|rockwell',            ('Roboto Slab', 'Rockwell')),
        ('bodoni',                               ('Bodoni Moda', 'Bodoni MT')),
        ('broadway',                             ('Poppins', None)),
        ('univ. roman',                          ('Bodoni Moda', None)),
        # Cinzel: a real, widely-used Google Font cut with flared,
        # Roman-inscriptional glyphic serifs -- the closest catalog match
        # to Albertus's chiseled character; Marcellus (also a real Google
        # Font in the same glyphic/inscriptional family) as the second
        # choice.
        ('albertus',                              ('Cinzel', 'Marcellus')),
    ]),
    'linux': _expand([
        ('avant garde',                          ('URW Gothic', 'DejaVu Sans')),
        ('bookman',                              ('URW Bookman', 'DejaVu Serif')),
        ('cntry schlbk|newcntschlbk|new century schoolbook|century',
                                                 ('C059', 'DejaVu Serif')),
        ('american classic',                     ('C059', 'DejaVu Serif')),
        ('helv|helvetica|univers',               ('Nimbus Sans', 'Liberation Sans')),
        ('cg triumvirate|ps sansser qual',       ('Nimbus Sans', 'Liberation Sans')),
        ('helv narrow|helv cond.|helvetica narrow',
                                                 ('Nimbus Sans Narrow', 'DejaVu Sans')),
        ('palatino',                             ('P052', 'DejaVu Serif')),
        ('tms rmn|times|cg times',               ('Nimbus Roman', 'Liberation Serif')),
        # Marigold joins this group in substitution only (see the office
        # table's own note above) -- Z003 IS Zapf Chancery's true URW
        # clone, the most faithful available answer for the whole group.
        ('zapfchancery|zapf chancery|coronet|marigold',
                                                 ('Z003', 'DejaVu Serif')),
        ('zapfdingbats|zapf dingbats',           ('D050000L', 'Zapf Dingbats')),
        ('symbol',                               ('Standard Symbols PS', 'Symbol')),
        ('courier|pica|elite|lineprinter',       ('Nimbus Mono PS', 'Liberation Mono')),
        ('letter gothic|gothic',                 ('DejaVu Sans Mono', 'Nimbus Mono PS')),
        ('prestige',                             ('Nimbus Mono PS', 'Liberation Mono')),
        ('antique olive|optima',                 ('DejaVu Sans', 'Verdana')),
        ('garamond',                             ('P052', 'DejaVu Serif')),
        ('clarendon|aachen|rockwell',            ('DejaVu Serif', 'Rockwell')),
        ('bodoni',                               ('C059', 'DejaVu Serif')),
        ('broadway',                             ('URW Gothic', 'DejaVu Sans')),
        ('univ. roman',                          ('DejaVu Serif', None)),
        # No free glyphic/flared clone of Albertus exists in the
        # guaranteed-packaged set (fonts-urw-base35 covers only the
        # PostScript base-35; URW's own "Lapidar Serif No. 2" Albertus
        # clone is a separate, non-guaranteed URW++ product, unlike
        # Nimbus/URW Gothic/Z003 -- checked against this box's actual
        # `fc-list`/`apt-cache`, not present). Least-wrong per the
        # coverage rule: DejaVu Serif (always present via fontconfig),
        # Rockwell as falt -- same pairing already used for
        # clarendon/aachen above, for the same reason.
        ('albertus',                              ('DejaVu Serif', 'Rockwell')),
    ]),
}


def rtf_fonts(family, generic_style=None, target='office', proportional=None):
    """(primary, falt_or_None) for an RTF fonttbl entry, from the FINAL
    RULED FONT TABLE. A family with no table entry gets the target's
    generic primary from the font block's own style bits (a primary that
    RESOLVES beats a period name Cocoa/Docs cannot -- the verbatim era
    name stays first-class in doc.fonts and the HTML stacks), falling all
    the way back to the family's own name when even the bits are absent.

    `proportional=False` (round 9, Jon's ruling, tier-1 evidence) is
    DECISIVE and short-circuits all of the above: WSFORMAT's generic
    Non-PostScript typestyles (typestyle_name "NPS SansSer Qual"/"NPS
    Serif Qual" and friends) have no real installable face, genuine or
    fallback -- their OWN table lookups miss, and the generic-style-bits
    fallback would promote them to Arial/Times New Roman, a real
    proportional face this record's own bit says it is NOT. Routed
    through the SAME per-target 'courier' table entry every genuine mono
    family already resolves through (single source for the target's mono
    face -- Courier New for office/mac/google, the URW clone for linux),
    never a family-name or falt garnish: there is no honest mono-flavored
    alternate for a generic NLQ category, so none is invented."""
    if proportional is False:
        return TARGET_FONTS.get(target, TARGET_FONTS['office'])['courier']
    fam_key = (family or '').lower()
    pair = TARGET_FONTS.get(target, TARGET_FONTS['office']).get(fam_key)
    if pair:
        return pair
    alts = FONT_ALTS.get(fam_key, [])
    primary = ((alts[0] if alts else None)
               or GENERIC_PRIMARY.get(target, GENERIC_PRIMARY['office'])
                  .get(generic_style or ''))
    if not primary:
        return (family or None), None
    falt = next((a for a in alts if a != primary), None)
    return primary, falt


def font_stack(family, generic_style=None, proportional=None):
    """CSS-style ordered list: original family first, then modern
    alternates, then the generic from the font block's own style bits.

    `proportional=False` (round 9) keeps the verbatim family name as
    harmless first-choice garnish (a browser just skips an unresolvable
    name) but TERMINATES the stack at the CSS generic `monospace` instead
    of whatever `generic_style`'s sans/serif/script/display bits would
    otherwise pick -- the same "never promote to a proportional face"
    rule as `rtf_fonts`, honoured for HTML's own fallback mechanism."""
    stack = [family] if family else []
    for alt in FONT_ALTS.get((family or '').lower(), []):
        if alt not in stack:
            stack.append(alt)
    if proportional is False:
        stack.append('monospace')
        return stack
    generic = _GENERIC_CSS.get(generic_style or '')
    if generic:
        stack.append(generic)
    return stack


def rtf_alternate(family):
    """The single best alternate for RTF's {\\*\\falt ...}, or None."""
    alts = FONT_ALTS.get((family or '').lower(), [])
    return alts[0] if alts else None
