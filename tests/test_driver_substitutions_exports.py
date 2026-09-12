"""planning #264 item 1 (B1+B2): the driver's character substitutions and
the driver-keyed euro reach RTF, HTML, Markdown and plain text.

THE DEFECT, measured 2026-09-12 on the real corpus. Jon ruled the LJ6DTP
driver's character substitutions CONTENT on 2026-08-06 (M7: "an em dash is
an em dash in any century") and the cp437-158 euro driver-keyed on
2026-09-11 ("anyone using Sawyer's trick gets the Euro"). Both rules
reached the PDF views and NOTHING else: Printed RTF, Modern RTF, both HTML
modes and the text export of LJ6DTP.WS all kept 7 smiley faces where a ©
belongs, 4 suns where an ellipsis belongs, 11 `«` and 11 `»` where curly
double quotes belong, 4 `≡` where an en dash belongs and the four card
suits where the box corners belong -- zero copyright signs, zero curly
double quotes, zero em dashes in any of the four. -README.WS, which
declares one of Sawyer's three patched drivers, emitted a peseta where the
euro belongs in every one of them.

THE FIX. `layout.driver_substituted` applies both rules ONCE, to the
Document, at each emitter's entry -- so every later pass (paragraph
assembly, structure classification, sentence spacing) sees the characters
the document actually printed.

WHICH TABLE. Deliberately the SEMANTIC flow's own (`layout.LJ_SUBST` +
`layout.LJ_SUBST_UNIVERS`), not `pdf._lj_substitute`'s Printed variant --
see `layout.driver_substituter`'s own comment: every mapping here is one
character for one character, so a facsimile keeps its columns, and the box
corners are the square ones the layout contract (and Soft Return's Modern
view) already carry.

FACE RULES, from the document's own chart and unchanged: only spans in a
PROPORTIONAL face are substituted (a fixed-pitch face was never patched --
which is why LJ6DTP.WS's own chart, typed in Courier, still shows the raw
characters beside their printed forms), and the box corners only in
Univers. The euro is keyed on the driver name alone and applies to every
span.
"""
import pytest

from ctrlkd import core, emit, layout

_UNIVERS = {'proportional': True, 'typestyle_name': 'Univers (also Zurich)'}
_TIMES = {'proportional': True, 'typestyle_name': 'Times New Roman'}
_COURIER = {'proportional': False, 'typestyle_name': 'Courier'}

_FONTS = [_TIMES, _UNIVERS, _COURIER]
# 'font0' = Times (proportional), 'font1' = Univers, 'font2' = Courier
_PROP, _UNI, _FIXED = frozenset({'font0'}), frozenset({'font1'}), frozenset({'font2'})

_SAMPLE = '☻ ☼ «x» ≡ ♥♦♣♠ don\'t _ ₧'
_SUBSTITUTED = '© … “x” – ┌┐└┘ don’t — €'   # LJ6DTP is euro-patched too


def _doc(driver, rows):
    """A Document declaring `driver` as its last-used printer, with one
    block whose lines are `rows` -- each row a list of (text, styles)."""
    blocks = [core.Block('para', lines=[
        core.Line(spans=[core.Span(t, st) for t, st in row]) for row in rows])]
    return core.Document(blocks=blocks, fonts=list(_FONTS),
                         meta={'printer_driver': driver, 'variant': 'ws5+'})


def _exports(doc):
    """{name: text} for every export surface this item covers."""
    return {
        'rtf.printed': emit.emit_rtf(doc, mode='printed'),
        'rtf.modern': emit.emit_rtf(doc, mode='modern'),
        'html.printed': emit.emit_html(doc, mode='printed'),
        'html.modern': emit.emit_html(doc, mode='modern'),
        'text.printed': emit.emit_text(doc, mode='printed'),
        'text.modern': emit.emit_text(doc, mode='modern'),
        'markdown.printed': emit.emit_markdown(doc, mode='printed'),
        'markdown.modern': emit.emit_markdown(doc, mode='modern'),
    }


def _rtf_has(out, ch):
    r"""RTF escapes every non-ASCII character as `\uNNNN?`."""
    return ('\\u%d?' % ord(ch)) in out


def _shows(name, out, ch):
    return _rtf_has(out, ch) if name.startswith('rtf') else ch in out


# ------------------------------------------------ the substitutions arrive

@pytest.mark.parametrize('ch', '©…“”–┌┐└┘—’')
def test_every_export_carries_the_substituted_character(ch):
    """The whole point of the item: all four formats, both modes."""
    out = _exports(_doc('LJ6DTP', [[(_SAMPLE, _UNI)]]))
    for name, text in out.items():
        assert _shows(name, text, ch), '%s lost %r' % (name, ch)


@pytest.mark.parametrize('ch', '☻☼«»≡♥♦♣♠')
def test_no_export_still_shows_the_raw_typed_character(ch):
    out = _exports(_doc('LJ6DTP', [[(_SAMPLE, _UNI)]]))
    for name, text in out.items():
        assert not _shows(name, text, ch), '%s kept raw %r' % (name, ch)


def test_the_substituter_is_the_semantic_flows_own_table():
    """One definition, shared -- never a fourth copy of the chart."""
    subst = layout.driver_substituter(_doc('LJ6DTP', []))
    assert subst(_SAMPLE, _UNI) == _SUBSTITUTED
    assert '♥♦♣♠'.translate(layout.LJ_SUBST_UNIVERS) == '┌┐└┘'


# ------------------------------------------------------------- face rules

def test_a_fixed_pitch_face_is_never_substituted():
    """LJ6DTP.WS's own substitution CHART is typed in Courier: it shows the
    raw character beside its printed form, and must keep doing so."""
    out = _exports(_doc('LJ6DTP', [[(_SAMPLE, _FIXED)]]))
    for name, text in out.items():
        assert _shows(name, text, '☻'), '%s substituted a fixed-pitch run' % name
        assert not _shows(name, text, '©'), '%s substituted a fixed-pitch run' % name


def test_box_corners_are_univers_only():
    out = _exports(_doc('LJ6DTP', [[(_SAMPLE, _PROP)]]))
    for name, text in out.items():
        assert _shows(name, text, '©'), '%s: Times run not substituted' % name
        assert _shows(name, text, '♥'), '%s: corners outside Univers' % name
        assert not _shows(name, text, '┌'), '%s: corners outside Univers' % name


def test_another_driver_substitutes_nothing():
    out = _exports(_doc('EPSONFX', [[(_SAMPLE, _UNI)]]))
    for name, text in out.items():
        assert _shows(name, text, '☻'), '%s substituted a non-LJ6DTP doc' % name
        assert not _shows(name, text, '©'), '%s substituted a non-LJ6DTP doc' % name


# ------------------------------------------------------- the euro (B2/#266)

@pytest.mark.parametrize('driver', ['LASERJET', 'LJ6DTP', 'HP4'])
def test_a_patched_driver_prints_the_euro_in_every_export(driver):
    out = _exports(_doc(driver, [[('Costs ₧ 100', _FIXED)]]))
    for name, text in out.items():
        assert _shows(name, text, '€'), '%s kept the peseta' % name
        assert not _shows(name, text, '₧'), '%s kept the peseta' % name


def test_an_unpatched_driver_keeps_the_peseta_in_every_export():
    """Jon's ruling: "Any other old docs which actually use a Peseta in
    them, see it as intended.\""""
    out = _exports(_doc('EPSONFX', [[('Costs ₧ 100', _FIXED)]]))
    for name, text in out.items():
        assert _shows(name, text, '₧'), '%s lost the peseta' % name
        assert not _shows(name, text, '€'), '%s invented a euro' % name


def test_the_euro_applies_to_a_fixed_pitch_run_too():
    """The euro is keyed on the DRIVER, never on the face -- unlike the
    LJ6DTP character chart above."""
    subst = layout.driver_substituter(_doc('HP4', []))
    assert subst('₧', _FIXED) == '€'


# --------------------------------------------------------------- hygiene

def test_the_document_handed_in_is_never_mutated():
    """One `convert()` call hands the SAME Document to several emitters."""
    doc = _doc('LJ6DTP', [[(_SAMPLE, _UNI)]])
    _exports(doc)
    assert doc.blocks[0].lines[0].spans[0].text == _SAMPLE


def test_a_document_with_no_patched_driver_is_not_copied_at_all():
    doc = _doc('EPSONFX', [[('plain text', _PROP)]])
    assert layout.driver_substituted(doc) is doc


def test_a_picture_placeholder_keeps_its_own_file_name():
    """`_` -> em dash would rewrite a real file name: a `pix<N>`/`pcl<N>`/
    `pctl<N>` span's text is a MARKER, not prose, and is exempt."""
    subst = layout.driver_substituter(_doc('LJ6DTP', []))
    assert layout._subst_exempt(frozenset({'pix3', 'font0'}))
    assert layout._subst_exempt(frozenset({'fnref'}))
    assert not layout._subst_exempt(frozenset({'font0', 'b'}))
    assert subst('MY_FIG.PIX', _PROP) == 'MY—FIG.PIX'    # only if NOT exempt


# ---------------------------------------------------- the real corpus (tier 2)

@pytest.mark.sawyer
def test_lj6dtp_exports_carry_the_substitutions(require_sawyer_doc):
    """The measured example in the review packet: LJ6DTP.WS's non-PDF
    exports carried 7 ☻ / 4 ☼ / 11 « / 11 » / 4 ≡ and zero © / “ / — .
    The 2 of each that survive are the chart's own Courier specimens."""
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    for name, out in _exports(doc).items():
        for ch in '©“”—…–':
            assert _shows(name, out, ch), '%s: no %r' % (name, ch)


@pytest.mark.sawyer
def test_readme_exports_carry_the_euro(require_sawyer_doc):
    """-README.WS declares one of Sawyer's three patched drivers, so its
    own "THE EURO CURRENCY SYMBOL" section means a euro."""
    with open(require_sawyer_doc('-README.WS (root)'), 'rb') as fh:
        doc = core.parse_ws(fh.read())
    for name, out in _exports(doc).items():
        assert _shows(name, out, '€'), '%s: no euro' % name
        assert not _shows(name, out, '₧'), '%s: still a peseta' % name
