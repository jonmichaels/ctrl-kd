"""QUIRKS: named, individually switchable departures from a literal reading.

Jon's ruling, 2026-09-16: "Our engine needs to be faithful. We can't be
arbitrarily cleaning up 'mistakes' since there are plenty of reasons that
someone might want things a certain way. However, this is a mistake. ... So is
there a way we can go into a 'quirks' mode to fix this? Maybe a new flag and
specific cases can be added to it. We already have a way for users to extend
ctrl-kd with new outputs. Maybe something similar can exist."

So: a registry shaped exactly like the emitter registry (`ctrlkd.quirks`), a
`--quirk NAME` / `--no-quirk NAME` / `--quirks off|auto|all` flag surface, and
a report in the layout JSON so a reader can be OFFERED a known quirk without
having to already know it exists.

TWO CLASSES, and this file pins the difference:

  auto     the document's own bytes point at it -- its WS7 header names the
           printer driver it was last printed through, and three of those
           drivers were patched so certain characters PRINT as something else.
           On by default (that IS what the paper showed), switchable off.
  opt-in   a human judged it from context, with nothing in the file to say so.
           Off by default. Today there is exactly one: the stray style-library
           strikeout bit (register entry 2026-09-16, "Style-library strikeout
           runs until a style clears it" -- the faithful default keeps the
           strike; this quirk is how a reader gets the document without it).

THE ONE THING THIS QUIRK MUST NOT DO is take away a cross-out somebody meant.
`detect` is what guarantees that: it fires only when NO span anywhere in the
document carries a strikeout the typist toggled inline (WordStar's `^PX`,
byte 0x18). `PRINT.TST` -- WordStar's own feature-demo file, which types real
inline `^PX` strikeout under the stock LASERJET driver -- is the corpus's
contrast case and is pinned at the bottom.

Synthetic fixtures for the mechanism; the tier-2 (`sawyer`) tests at the end
pin the seven real archive documents the bit was actually found in.
"""
import json
import re
import zlib

import pytest

from ctrlkd import core, emit, emit_layout, pdf, quirks
from ctrlkd.quirks import AUTO, OPT_IN, Quirk, UnknownQuirk

HARD = b'\x0d\x0a'
STRIKE, BOLD = 0x01, 0x40
CLEARS_ALL_BUT_STRIKE = 0xFA
PESETA = b'\x9e'                       # cp437 code 158


# ------------------------------------------------------------ the fixtures
#
# Same byte-level construction as test_style_strikeout_runs_until_cleared.py's
# (a 102-byte style record, a paragraph-style library, a 0x11 select block)
# and test_peseta_euro_driver.py's (a WSFORMAT type-0 header block naming a
# driver). Kept local rather than imported: a test fixture that two test files
# share silently becomes a contract neither of them states.

def ws_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def driver_header(name):
    """A type-0 header block declaring `name` as the last-used printer driver
    (the leading byte is the record tag `core` strips)."""
    return ws_block(0x00, b'p' + name + b'\x00\x00\x00\x80')


def style_record(attrs_on=0, attrs_off=0):
    rec = bytearray(102)
    rec[0:2] = (0xFFFF).to_bytes(2, 'little')
    rec[10:12] = (1800).to_bytes(2, 'little')
    rec[12:14] = (0xFFFE).to_bytes(2, 'little')
    rec[14:16] = (0xFFFE).to_bytes(2, 'little')
    rec[18] = rec[19] = 0xFF
    for k in range(32):
        rec[20 + 2 * k:22 + 2 * k] = (0xBEEF).to_bytes(2, 'little')
    rec[86] = 0
    rec[87] = 1
    rec[88:90] = (0xFFFF).to_bytes(2, 'little')
    rec[90] = 0xFF
    rec[91:93] = attrs_on.to_bytes(2, 'little')
    rec[93:95] = attrs_off.to_bytes(2, 'little')
    rec[95] = 0xFF
    return bytes(rec)


def style_library(entries):
    n = len(entries)
    items, records = b'', b''
    rec_base = 13 + 5 + 33 * n
    for name, rec in entries:
        nm = name.encode('cp437').ljust(24)
        items += nm + b'\x02' + bytes(4) + (rec_base + len(records)).to_bytes(4, 'little')
        records += rec
    head = (b'\x1a\x55' + (1).to_bytes(2, 'little') + b'\x01'
            + n.to_bytes(2, 'little') + (102).to_bytes(2, 'little')
            + (13).to_bytes(4, 'little'))
    return head + bytes([n]) + bytes(4) + items + records


def select(slot):
    return ws_block(0x11, (0x0200 | slot).to_bytes(2, 'little')
                    + (0x0201).to_bytes(2, 'little')
                    + (0x0300).to_bytes(2, 'little')
                    + (0x0201).to_bytes(2, 'little'))


def build(entries, body, header=None):
    doc_body = (header or ws_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))) + body
    base = ((len(doc_body) + 127) // 128) * 128
    data = bytearray(doc_body.ljust(base, b'\x1a')) + style_library(entries)
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    return core.parse_ws(bytes(data))


LIBRARY = [
    ('Editing Defaults', style_record(attrs_on=STRIKE | BOLD,
                                      attrs_off=CLEARS_ALL_BUT_STRIKE & ~BOLD)),
]
STRUCK_TEXT = b'A heading whose style turns strikeout on.'
AFTER_TEXT = b'The paragraph that inherits the run, because nothing clears it.'


def stray_strike_doc():
    """A style turns strikeout on; the writing never types a cross-out."""
    return build(LIBRARY, select(0) + STRUCK_TEXT + HARD + HARD
                 + AFTER_TEXT + HARD)


def typed_strike_doc():
    """The SAME style-declared strike, but the writer ALSO typed a real
    inline cross-out (`^PX`, byte 0x18) -- the case that must be left
    completely alone even with the quirk on."""
    return build(LIBRARY, select(0) + STRUCK_TEXT + HARD + HARD
                 + b'Struck on purpose: \x18deleted words\x18 and on we go.'
                 + HARD)


def plain_doc():
    """No style strike, no driver -- trips nothing at all."""
    return build([('Plain', style_record())],
                 select(0) + b'Nothing here trips any quirk.' + HARD)


def decoded_streams(pdf_bytes):
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', pdf_bytes, re.S):
        try:
            out.append(zlib.decompress(m[1]))
        except zlib.error:
            out.append(m[1])
    return b'\n'.join(out)


def block_for(doc, text):
    wanted = text.decode('cp437')
    for b in doc.blocks:
        if wanted[:20] in ''.join(sp.text for ln in b.lines for sp in ln.spans):
            return b
    raise AssertionError(f'no block carrying {wanted[:20]!r}')


# ------------------------------------------------------- registry mechanics

def test_every_registered_quirk_states_all_five_things():
    """A quirk with no plain-language description, or no class, or no detect,
    cannot be offered to a reader at all -- an app draws a checkbox from
    exactly these fields."""
    for q in (quirks.get_quirk(n) for n in quirks.quirk_names()):
        assert re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', q.name), q.name
        assert q.quirk_class in (AUTO, OPT_IN), q.name
        # Jon's wording, 2026-09-16: a description is a short LABEL for a
        # checkbox, not a sentence -- capitalised, no closing period. The
        # strings themselves are Jon's, verbatim; this only pins their shape.
        assert q.description and q.description[0].isupper() \
            and not q.description.endswith('.'), q.name
        assert callable(q.detect) and callable(q.apply), q.name


def test_descriptions_carry_no_codenames():
    """Plain-language reporting: the description is shown to a user as-is, so
    it may not lean on this project's own internal vocabulary."""
    banned = ('register', 'planning #', 'IR', 'attrs_on', '0x01', 'quirk',
              'emitter', 'span', 'cp437')
    for q in (quirks.get_quirk(n) for n in quirks.quirk_names()):
        low = q.description.lower()
        for word in banned:
            assert word.lower() not in low, (q.name, word)


def test_registering_the_same_name_replaces_it():
    """Matches `emitter()`'s own documented plain-assignment behaviour."""
    before = quirks.get_quirk('sawyer-strikeout')
    try:
        quirks.register(Quirk(name='sawyer-strikeout',
                              description='Replaced.', quirk_class=OPT_IN,
                              detect=lambda doc: None, apply=lambda doc: doc))
        assert quirks.get_quirk('sawyer-strikeout').description == 'Replaced.'
        assert quirks.quirk_names().count('sawyer-strikeout') == 1
    finally:
        quirks.register(before)


def test_a_name_this_build_does_not_know_is_an_error_not_a_shrug():
    with pytest.raises(UnknownQuirk) as e:
        quirks.apply_quirks(plain_doc(), enable=['no-such-quirk'])
    assert 'no-such-quirk' in str(e.value)
    assert 'sawyer-strikeout' in str(e.value)     # says what IS available


def test_naming_a_quirk_this_document_does_not_trip_is_a_no_op():
    """A caller (an app's own settings list) holds one standing set of quirks
    and hands it to every document; a document that trips none of them must
    convert exactly as it would with no flags at all."""
    plain = emit.emit_rtf(quirks.apply_quirks(plain_doc()), 'modern')
    asked = emit.emit_rtf(quirks.apply_quirks(
        plain_doc(), enable=['sawyer-strikeout', 'euro-swap']), 'modern')
    assert plain == asked


def test_a_caller_that_never_mentions_quirks_gets_the_defaults():
    """The compatibility promise: every emitter still works on a bare parsed
    document, and resolves the same decision `apply_quirks` would."""
    doc = stray_strike_doc()
    assert quirks.enabled(doc, 'sawyer-strikeout') is False
    assert emit.emit_rtf(doc, 'modern') == emit.emit_rtf(
        quirks.apply_quirks(doc), 'modern')


# ------------------------------------------ what each class does by default

def test_auto_quirks_are_on_and_opt_in_ones_are_off():
    doc = core.parse_ws(driver_header(b'LJ6DTP') + b'text' + HARD)
    applicable = dict(quirks.applicable(doc))
    assert set(applicable) == {'euro-swap', 'smart-punctuation',
                               'box-corners', 'colors-as-gray',
                               'fill-patterns'}
    _, applied = quirks.report(quirks.apply_quirks(doc))
    assert applied == sorted(applied, key=quirks.quirk_names().index)
    assert set(applied) == set(applicable)

    struck = quirks.apply_quirks(stray_strike_doc())
    assert quirks.report(struck) == (['sawyer-strikeout'], [])


def test_every_auto_quirk_states_the_documents_own_evidence_as_its_reason():
    doc = core.parse_ws(driver_header(b'LJ6DTP') + b'text' + HARD)
    for name, reason in quirks.applicable(doc):
        assert 'LJ6DTP' in reason and reason.startswith('last printed on'), name


def test_quirks_off_turns_off_even_the_automatic_ones():
    """`--quirks off` is the most literal reading of the bytes this converter
    can give: the peseta stays a peseta even on a patched-driver document."""
    src = driver_header(b'LASERJET') + b'Costs ' + PESETA + b' 100.' + HARD
    on = emit.emit_text(quirks.apply_quirks(core.parse_ws(src)), 'modern')
    off = emit.emit_text(quirks.apply_quirks(core.parse_ws(src), mode='off'), 'modern')
    assert '€' in on and '₧' not in on
    assert '₧' in off and '€' not in off


def test_quirks_all_turns_on_the_opt_in_one_too():
    doc = quirks.apply_quirks(stray_strike_doc(), mode='all')
    assert quirks.report(doc)[1] == ['sawyer-strikeout']


@pytest.mark.parametrize('name', ['euro-swap', 'smart-punctuation',
                                  'box-corners', 'colors-as-gray',
                                  'fill-patterns'])
def test_no_quirk_switches_one_automatic_quirk_off_and_leaves_its_siblings(name):
    doc = core.parse_ws(driver_header(b'LJ6DTP') + b'text' + HARD)
    _, applied = quirks.report(quirks.apply_quirks(doc, disable=[name]))
    assert name not in applied
    assert len(applied) == 4


def test_switching_the_euro_off_shows_the_peseta_the_bytes_actually_carry():
    src = driver_header(b'LASERJET') + b'Costs ' + PESETA + b' 100.' + HARD
    off = emit.emit_text(
        quirks.apply_quirks(core.parse_ws(src), disable=['euro-swap']),
        'modern')
    assert '₧' in off and '€' not in off


def test_the_two_lj6dtp_character_families_switch_independently():
    """The driver prints `_` as an em dash and the card suits as box corners.
    Those are two separate quirks, so each has to be able to go without the
    other -- which is why `pdf._lj_substitute` takes them as two flags rather
    than one "is this the LJ6DTP driver" gate."""
    univers = {'proportional': True, 'typestyle_name': 'Univers (also Zurich)'}
    segs = [('a_b \u2665', frozenset(), 'times', 12.0, univers)]

    def sub(**kw):
        return pdf._lj_substitute(segs, True, **kw)[0][0]

    # The PRINTED table's corners are the Unicode ARC glyphs (`pdf.ARC_CORNERS`,
    # register C7 -- real WS7 draws a quarter-circle join, not a square one);
    # the semantic flow's own table uses the plain box corners instead.
    assert sub(typography=True, corners=True) == 'a\u2014b \u256d'
    assert sub(typography=True, corners=False) == 'a\u2014b \u2665'
    assert sub(typography=False, corners=True) == 'a_b \u256d'
    assert sub(typography=False, corners=False) == 'a_b \u2665'


def test_the_semantic_substitution_pass_disappears_when_both_are_off():
    """`layout.driver_substituter` returns None -- no pass, nothing copied --
    once nothing is left for it to do."""
    from ctrlkd import layout
    src = driver_header(b'LJ6DTP') + b'a_b' + HARD
    doc = core.parse_ws(src)
    assert layout.driver_substituter(quirks.apply_quirks(doc)) is not None
    all_off = quirks.apply_quirks(doc, disable=['smart-punctuation',
                                                'box-corners',
                                                'euro-swap'])
    assert layout.driver_substituter(all_off) is None


# ---------------------------------------- the stray style-strikeout quirk

def test_it_applies_when_a_style_strikes_and_the_writer_never_did():
    reasons = dict(quirks.applicable(stray_strike_doc()))
    assert 'sawyer-strikeout' in reasons
    assert "'Editing Defaults'" in reasons['sawyer-strikeout']


def test_it_does_not_apply_when_the_writer_typed_a_real_cross_out():
    """The case this quirk must never touch. A document that types `^PX` has
    made a deliberate cross-out; the style's own bit can no longer be read as
    an accident, so the quirk is not offered at all."""
    assert 'sawyer-strikeout' not in dict(quirks.applicable(typed_strike_doc()))


def test_applying_it_drops_the_strike_and_keeps_every_other_attribute():
    doc = quirks.apply_quirks(stray_strike_doc(), enable=['sawyer-strikeout'])
    for text in (STRUCK_TEXT, AFTER_TEXT):
        assert 'strike' not in block_for(doc, text).style_attrs
    assert 'b' in block_for(doc, STRUCK_TEXT).style_attrs, \
        'the style declared bold as well and the quirk took it away'


def test_applying_it_never_mutates_the_document_it_was_given():
    """One `convert()` hands the same Document to several emitters."""
    original = stray_strike_doc()
    quirks.apply_quirks(original, enable=['sawyer-strikeout'])
    assert 'strike' in block_for(original, STRUCK_TEXT).style_attrs


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_the_strike_disappears_from_every_format_that_can_show_one(mode):
    faithful = stray_strike_doc()
    quirked = quirks.apply_quirks(faithful, enable=['sawyer-strikeout'])

    rtf = emit.emit_rtf(quirked, mode)
    rtf = rtf.decode('cp1252', 'replace') if isinstance(rtf, bytes) else rtf
    assert '\\strike' not in rtf

    html = emit.emit_html(quirked, mode)
    assert 'line-through' not in html

    md = emit.emit_markdown(quirked, 'modern')
    assert '~~' not in md

    on = decoded_streams(pdf.emit_pdf(faithful, mode=mode))
    off = decoded_streams(pdf.emit_pdf(quirked, mode=mode))
    assert off.count(b' l S') < on.count(b' l S'), \
        'the PDF still strokes as many rules as the faithful render'


def test_plain_text_is_unaffected_and_still_carries_the_words():
    """Named rather than left out: plain text has no way to show a strikeout
    in either direction, so this quirk changes nothing there."""
    quirked = quirks.apply_quirks(stray_strike_doc(),
                                  enable=['sawyer-strikeout'])
    body = emit.emit_text(quirked, 'printed')
    for sample in (STRUCK_TEXT, AFTER_TEXT):
        assert sample.decode('cp437')[:20] in body


def test_a_document_that_types_its_own_cross_out_is_untouched_even_when_asked():
    """`--quirk sawyer-strikeout` on a document `detect` did not flag is
    a no-op, not an override."""
    doc = typed_strike_doc()
    asked = quirks.apply_quirks(doc, enable=['sawyer-strikeout'])
    assert emit.emit_rtf(asked, 'modern') == emit.emit_rtf(doc, 'modern')


# ------------------------------------------------ the layout JSON's report

def test_a_document_that_trips_nothing_says_nothing():
    """Omitted, not empty -- the same convention every other additive layout
    field uses, so a document with no quirk available emits byte-identical
    JSON to version 11."""
    out = json.loads(emit_layout(quirks.apply_quirks(plain_doc()), 'modern'))
    assert out['version'] == 13
    assert 'quirks_applicable' not in out and 'quirks_applied' not in out


def test_applicable_is_reported_even_on_a_plain_faithful_run():
    """The whole point: a reader must be able to be OFFERED the quirk without
    having had to turn it on to find out it exists."""
    out = json.loads(emit_layout(quirks.apply_quirks(stray_strike_doc()), 'modern'))
    assert out['quirks_applicable'] == ['sawyer-strikeout']
    assert out['quirks_applied'] == []


def test_applied_names_the_subset_actually_in_force():
    doc = quirks.apply_quirks(stray_strike_doc(), enable=['sawyer-strikeout'])
    out = json.loads(emit_layout(doc, 'modern'))
    assert out['quirks_applicable'] == ['sawyer-strikeout']
    assert out['quirks_applied'] == ['sawyer-strikeout']


def test_an_automatic_quirk_reports_itself_as_applied():
    doc = quirks.apply_quirks(core.parse_ws(driver_header(b'LJ6DTP') + b'x' + HARD))
    out = json.loads(emit_layout(doc, 'printed'))
    assert out['quirks_applied'] == out['quirks_applicable']
    assert 'smart-punctuation' in out['quirks_applied']


# ------------------------------------------------------------- the listing

def test_the_listing_without_a_document_is_the_build_s_own_catalogue():
    rows = quirks.list_quirks()
    assert [r['name'] for r in rows] == quirks.quirk_names()
    assert all(set(r) == {'name', 'description', 'class'} for r in rows)


def test_the_listing_with_a_document_says_applicable_why_and_on():
    rows = {r['name']: r for r in quirks.list_quirks(stray_strike_doc())}
    stray = rows['sawyer-strikeout']
    assert stray['applicable'] is True and stray['enabled'] is False
    assert stray['reason']
    assert rows['euro-swap']['applicable'] is False
    assert rows['euro-swap']['reason'] is None


# ------------------------------------------------------------------- CLI

def test_cli_lists_quirks_as_json(capsys):
    from ctrlkd import cli
    assert cli.main(['--list-quirks']) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r['name'] for r in rows] == quirks.quirk_names()


def test_cli_rejects_an_unknown_quirk_name(tmp_path):
    from ctrlkd import cli
    p = tmp_path / 'x.WS'
    p.write_bytes(b'plain text\r\n')
    with pytest.raises(SystemExit) as e:
        cli.main(['--quirk', 'nope', '-t', 'text', '-o', str(tmp_path / 'o.txt'),
                  str(p)])
    assert e.value.code == 2


def test_cli_quirk_flag_reaches_the_conversion(tmp_path):
    from ctrlkd import cli
    src = tmp_path / 'struck.WS'
    doc_bytes = None
    # rebuild the same synthetic document as bytes on disk
    body = select(0) + STRUCK_TEXT + HARD + HARD + AFTER_TEXT + HARD
    header = ws_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
    doc_body = header + body
    base = ((len(doc_body) + 127) // 128) * 128
    data = bytearray(doc_body.ljust(base, b'\x1a')) + style_library(LIBRARY)
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    doc_bytes = bytes(data)
    src.write_bytes(doc_bytes)

    faithful, quirked = tmp_path / 'a.rtf', tmp_path / 'b.rtf'
    assert cli.main(['-t', 'rtf', '-o', str(faithful), str(src)]) == 0
    assert cli.main(['--quirk', 'sawyer-strikeout', '-t', 'rtf',
                     '-o', str(quirked), str(src)]) == 0
    assert '\\strike' in faithful.read_text(encoding='cp1252', errors='replace')
    assert '\\strike' not in quirked.read_text(encoding='cp1252', errors='replace')


# --------------------------------------------- tier 2: the real documents
#
# The seven archive files the stray bit was actually found in (the corpus-wide
# sweep in research 2026-09-16_ws7-style-strikeout-bit.md §2a: 319 WordStar-
# shaped files checked BY BYTES, not by extension; nine style records across
# these seven files carry `attrs_on & 0x01` and not one of them is ever
# cleared by a later style's own attrs_off word).

STRAY_STRIKE_DOCS = [
    'RTF-RJS/NOVEL.WS',        # the manuscript: style 'H3', strike + bold
    'RTF-RJS/MARKUP.WS',       # style 'Word-wrap off'
    'REF/SCREEN.WS',           # style 'WordStar Defaults'
    'RJS.WS',                  # style 'Sawyer Defaults'
    'REF/BOOKLET.RJS',         # style 'Editing Defaults'
    'REF/-HOW-TO.RJS',         # the same 'Editing Defaults' record, reused
    'REF/-LASERJE.FNT',        # style 'Sizes'
]


@pytest.mark.sawyer
@pytest.mark.parametrize('name', STRAY_STRIKE_DOCS)
def test_the_seven_archive_documents_offer_the_quirk(require_sawyer_doc, name):
    doc = core.parse(open(require_sawyer_doc(name), 'rb').read())
    reasons = dict(quirks.applicable(doc))
    assert 'sawyer-strikeout' in reasons, name
    assert 'never types a cross-out' in reasons['sawyer-strikeout']


@pytest.mark.sawyer
@pytest.mark.parametrize('name', STRAY_STRIKE_DOCS)
def test_turning_it_on_removes_the_strike_from_those_documents(require_sawyer_doc, name):
    faithful = core.parse(open(require_sawyer_doc(name), 'rb').read())
    quirked = quirks.apply_quirks(faithful, enable=['sawyer-strikeout'])
    on = emit.emit_html(faithful, 'modern')
    off = emit.emit_html(quirked, 'modern')
    assert 'line-through' in on, f'{name}: nothing struck in the faithful render'
    assert 'line-through' not in off, f'{name}: still struck with the quirk on'


@pytest.mark.sawyer
def test_print_tst_types_a_real_cross_out_and_is_never_offered_the_quirk(
        require_sawyer_doc):
    """The calibration case. `PRINT.TST` is WordStar's own feature-demo file:
    it types genuine inline `^PX` strikeout under the stock LASERJET driver,
    with no style library involved. A quirk that "removes accidental
    strikeout" must leave it completely alone -- and it is not even offered,
    because the typed cross-out is the evidence that the document means it."""
    doc = core.parse(open(require_sawyer_doc('PRINT.TST'), 'rb').read())
    assert any('strike' in sp.styles
               for b in doc.blocks for ln in b.lines for sp in ln.spans), \
        'PRINT.TST no longer parses an inline cross-out -- the contrast case is gone'
    assert 'sawyer-strikeout' not in dict(quirks.applicable(doc))


@pytest.mark.sawyer
def test_lj6dtp_ws_offers_the_five_driver_quirks_and_no_others(require_sawyer_doc):
    doc = core.parse(open(require_sawyer_doc('LJ6DTP.WS'), 'rb').read())
    names = [n for n, _ in quirks.applicable(doc)]
    assert names == ['euro-swap', 'smart-punctuation',
                     'box-corners', 'colors-as-gray',
                     'fill-patterns']
    assert quirks.report(quirks.apply_quirks(doc))[1] == names


@pytest.mark.sawyer
@pytest.mark.parametrize('name,disable,gone', [
    ('LJ6DTP.WS', 'smart-punctuation', '\u2014'),      # em dash
    ('LJ6DTP.WS', 'box-corners', '\u250c'),     # box corner
    ('DISPLAY.WS', 'euro-swap', '\u20ac'),      # euro sign
])
def test_switching_an_automatic_quirk_off_changes_a_real_document(
        require_sawyer_doc, name, disable, gone):
    """One document each, per quirk: with the swap off, the character the
    driver printed is no longer in the output."""
    doc = core.parse(open(require_sawyer_doc(name), 'rb').read())
    on = emit.emit_text(quirks.apply_quirks(doc), 'modern')
    off = emit.emit_text(quirks.apply_quirks(doc, disable=[disable]), 'modern')
    assert gone in on, f'{name}: the faithful default never printed it either'
    assert gone not in off, f'{name}: still there with {disable} switched off'


@pytest.mark.sawyer
@pytest.mark.parametrize('disable,marker', [
    ('colors-as-gray', b'/ExtGState'),
    ('fill-patterns', b'/PatternType 1'),
])
def test_switching_a_colour_quirk_off_changes_the_printed_pdf(
        require_sawyer_doc, disable, marker):
    """The two colour quirks live in the PDF writer, not in the text flow --
    proved on the one archive document that declares the LJ6DTP driver."""
    doc = core.parse(open(require_sawyer_doc('LJ6DTP.WS'), 'rb').read())
    on = pdf.emit_pdf(quirks.apply_quirks(doc), mode='printed')
    off = pdf.emit_pdf(quirks.apply_quirks(doc, disable=[disable]), mode='printed')
    assert marker in on
    assert marker not in off


# ------------------------------------------------ the 4.4.0 names (aliases)
#
# Jon's ruling 2026-09-17: a quirk's identifier is shipped text like any other --
# a reader types it, `--list-quirks` prints it, the layout JSON publishes it --
# so all six were renamed into plain English. The names that shipped in 4.4.0
# are still ACCEPTED AS INPUT and never PRODUCED, because an app released before
# the rename has them written into every user's stored per-document overrides.

RETIRED_NAMES = {
    'driver-euro-sign': 'euro-swap',
    'lj6dtp-typography': 'smart-punctuation',
    'lj6dtp-box-corners': 'box-corners',
    'lj6dtp-colour-as-gray': 'colors-as-gray',
    'lj6dtp-fill-patterns': 'fill-patterns',
    'stray-style-strikeout': 'sawyer-strikeout',
}


@pytest.mark.parametrize('old,new', sorted(RETIRED_NAMES.items()))
def test_every_retired_name_still_selects_its_quirk(old, new):
    """Each 4.4.0 name resolves to the quirk that replaced it, rather than
    raising UnknownQuirk at a reader who upgraded."""
    assert quirks.canonical_name(old) == new
    assert quirks.get_quirk(old).name == new


def test_the_alias_table_covers_exactly_the_names_that_shipped():
    """A rename table, not a junk drawer: every entry maps to a name this build
    really registers, and every registered name is reachable."""
    assert set(quirks.quirk_names()) == set(RETIRED_NAMES.values())
    for new in RETIRED_NAMES.values():
        assert quirks.get_quirk(new).name == new


def test_a_name_that_was_never_a_quirk_is_still_an_error():
    """An actual typo still raises, which is the whole point of UnknownQuirk."""
    assert quirks.canonical_name('lj6dtp-colour-as-grey') == 'lj6dtp-colour-as-grey'
    with pytest.raises(quirks.UnknownQuirk):
        quirks.get_quirk('lj6dtp-colour-as-grey')


def test_no_retired_name_is_ever_produced(require_sawyer_doc):
    """ONE DIRECTION. Naming old names on the way in must not put them back into
    anything this engine writes -- the decision, the report, the listing and the
    layout JSON say the new names only, so the two spellings can never both
    appear in one output."""
    doc = core.parse(open(require_sawyer_doc('LJ6DTP.WS'), 'rb').read())
    doc = quirks.apply_quirks(doc, enable=list(RETIRED_NAMES))
    applic, applied = quirks.report(doc)
    assert 'colors-as-gray' in applied and 'smart-punctuation' in applied
    produced = set(applic) | set(applied) | {r['name'] for r in quirks.list_quirks(doc)}
    assert produced.isdisjoint(RETIRED_NAMES)
    out = json.loads(emit_layout(doc))
    assert set(out['quirks_applicable']).isdisjoint(RETIRED_NAMES)
    assert set(out['quirks_applied']).isdisjoint(RETIRED_NAMES)


def test_a_retired_name_turns_its_quirk_off_too(require_sawyer_doc):
    """`--no-quirk` takes an alias by the same route -- `resolve` maps both
    lists, not just the enable one."""
    doc = core.parse(open(require_sawyer_doc('LJ6DTP.WS'), 'rb').read())
    doc = quirks.apply_quirks(doc, disable=['lj6dtp-colour-as-gray'])
    assert 'colors-as-gray' not in quirks.report(doc)[1]
