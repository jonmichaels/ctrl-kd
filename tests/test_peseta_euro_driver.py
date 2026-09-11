"""planning #266: cp437 code 158 is driver-keyed, and the peseta draws.

THE BUG. `pdf._ESC_FALLBACK` carried a blanket '₧' -> '€' entry: EVERY
document carrying cp437 code 158 got a euro on the page, whatever it meant
by it. That was right for exactly one family of documents and wrong for the
rest.

THE RULE (Jon's ruling, 2026-09-11):

    "driver keyed ... So anyone using Sawyer's trick gets the Euro. Any
     other old docs which actually use a Peseta in them, see it as
     intended."

Sawyer's trick is documented in his own -README.WS, section "THE EURO
CURRENCY SYMBOL": WordStar was last updated in 1992, seven years before the
euro was adopted, so he patched three PRINTER DEFINITION FILES -- in this
era a `.PDF` is WordStar's own printer driver, nothing to do with Adobe --
LASERJET.PDF, LJ6DTP.PDF and HP4.PDF, so that PC-8 character 9E (the peseta
slot) selects Roman-8 BA (the euro) on the printer. So:

  * a document naming LASERJET, LJ6DTP or HP4 in its own WS7 header
    driver-name field prints code 158 as a EURO;
  * every other document prints it as the PESETA it really is, drawn as
    vector geometry in the run's own cell (`pdf.SYMBOL_SHAPES`, Jon's
    2026-08-11 cp437 ruling: a cp437 glyph with no encoding slot is drawn
    as geometry) -- never as the '?' the text path used to degrade it to.

Scope: the rule lives in `layout.py`, next to the LJ6DTP character
substitutions it is a sibling of ("driver character substitutions are
content", ruling 2026-08-06 M7), so the semantic flow, the printed
page-lines model and both PDF views agree about what a document's code 158
says. What the RTF/HTML/text emitters do with code 158 is planning #264's
review and is untouched.

Synthetic fixtures throughout for the rule itself (a WSFORMAT type-0 header
block carrying the driver name, exactly as test_lj6dtp_hp_patterns.py and
test_ctrlkd.py's own driver-declaring documents build theirs); the tier-2
(`sawyer`) tests at the bottom pin the real corpus documents on both sides
of the rule.
"""
import re

import pytest

from ctrlkd import core, layout, pdf

HARD = b'\x0d\x0a'
PESETA = b'\x9e'                      # cp437 code 158
EURO_CP1252 = b'\x80'                 # what a euro looks like inside a PDF string


def _ws_block(cmd, content=b''):
    """One WS5+ symmetric sequence: `1D <jump> <cmd> <content> <jump> 1D`."""
    jump = len(content) + 4
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([cmd]) + content + j + b'\x1d'


def _driver_header(name):
    """A WSFORMAT type-0 header block declaring `name` as the printer
    driver -- the leading byte is the record tag core strips (`pLASERJET`),
    and the trailing bytes are the reserved/style-pointer fields."""
    return _ws_block(0x00, b'p' + name + b'\x00\x00\x00\x80')


def _doc(driver, body=b'Costs ' + PESETA + b' 100 today'):
    return core.parse_ws(_driver_header(driver) + body + HARD)


def _headerless_doc(body=b'Costs ' + PESETA + b' 100 today'):
    """A WS5+ document that declares no driver at all -- `printer_driver`
    is absent, which is neither of the three patched names."""
    return core.parse_ws(_ws_block(0x01, b'\x00\x00') + body + HARD)


def _text_strings(pdf_bytes):
    """Every `(...)` literal handed to Tj in the whole file."""
    return re.findall(rb'\((.*?)\) Tj', pdf_bytes, re.S)


# --------------------------------------------------------------- the table

def test_esc_fallback_no_longer_carries_the_blanket_peseta_entry():
    """The bug, named directly: '₧' must not be a lookalike degradation at
    all any more -- the driver decides, and the peseta draws."""
    assert ord('₧') not in pdf._ESC_FALLBACK
    assert '€' not in pdf._ESC_FALLBACK.values()
    # the rest of the table is untouched (str.maketrans keys are ordinals)
    for ch in '∙‼│─═':
        assert ord(ch) in pdf._ESC_FALLBACK


def test_the_three_patched_drivers_are_sawyers_own_three():
    assert pdf._EURO_PATCHED_DRIVERS == {'LASERJET', 'LJ6DTP', 'HP4'}


def test_driver_match_is_case_insensitive_and_whitespace_tolerant():
    """`core` extracts the header's 9-byte driver-name field as its leading
    upper-case/digit run, so a real document always arrives upper-case --
    the rule is still stated case-insensitively so it cannot depend on that
    one parser detail."""
    class _Doc:
        def __init__(self, name):
            self.meta = {'printer_driver': name}
    for name in ('LASERJET', 'laserjet', ' LJ6DTP ', 'Hp4'):
        assert pdf._peseta_euro_table(_Doc(name)) is not None, name
    for name in ('EPSONFX', 'ACROBAT', 'PRINTER', '', None):
        assert pdf._peseta_euro_table(_Doc(name)) is None, name


# ----------------------------------------------------- the peseta geometry

def test_the_peseta_is_a_drawn_glyph_not_a_fallback_character():
    assert '₧' in pdf.GRAPHIC_CHARS
    assert '₧' in pdf.SYMBOL_SHAPES
    rects = pdf.graphic_cell_rects('₧')
    assert rects
    for x, y, w, h in rects:
        assert w > 0 and h > 0
    ops = pdf.graphic_cell_ops('₧')
    # the P's bowl is a disc, the stems/crossbar/foot are rects, and the
    # two white knockouts are omitted from both public accessors
    assert any(op[0] == 'fill_disc' for op in ops)
    assert any(op[0] == 'fill_rect' for op in ops)
    assert len(ops) == sum(1 for s in pdf.SYMBOL_SHAPES['₧'] if s[0] != 'white')


def test_the_rule_has_one_definition_shared_with_the_layout_model():
    """pdf.py binds layout.py's names rather than restating the three
    driver names a second time -- the LJ6DTP substitutions' own precedent
    ran the other way (duplicated tables) and this is the thing that would
    have to be kept in step."""
    assert pdf._peseta_euro_table is layout.peseta_euro_table
    assert pdf._EURO_PATCHED_DRIVERS is layout.EURO_PATCHED_DRIVERS


@pytest.mark.parametrize('driver,shown', [(b'LASERJET', '\u20ac'),
                                          (b'EPSONFX', '\u20a7')])
def test_the_semantic_flow_carries_the_resolved_character(driver, shown):
    """The model, not just the painted page: a consumer reading
    `layout.modern_flow` (Soft Return.app's native text stack, the `layout`
    JSON) sees the character this document's own driver prints."""
    flow = layout.modern_flow(_doc(driver))
    text = ''.join(r['text'] for it in flow['items']
                   if it['kind'] == 'para' for r in it['runs'])
    assert shown in text
    assert ('\u20a7' if shown == '\u20ac' else '\u20ac') not in text


# --------------------------------------------------------- the euro's width

def test_the_euro_has_a_real_advance_in_every_base14_text_face():
    """`afm.WIDTHS` deliberately left 0x80 at 0 on the reasoning that the
    era's faces had no euro. They carry one, and `afm.INK_TOP` was
    transcribed WITH it, so the two tables disagreed about whether the
    glyph exists -- harmless until planning #266 put euros on a page for
    the first time, at which point a drawn euro advanced NOTHING and
    Modern ran the next word into it ("here \u20ac,then you're", -README.WS
    page 16). The widths are the same URW base-35 AFMs every other number
    in that table came from."""
    from ctrlkd import afm
    for face in ('Times-Roman', 'Times-Bold', 'Times-Italic',
                 'Times-BoldItalic'):
        assert afm.WIDTHS[face][0x80] == 500, face
    for face in ('Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique',
                 'Helvetica-BoldOblique'):
        assert afm.WIDTHS[face][0x80] == 556, face
    for face in ('Courier', 'Courier-Bold', 'Courier-Oblique',
                 'Courier-BoldOblique'):
        assert afm.WIDTHS[face][0x80] == 600, face
    # and the two tables now agree about the glyph existing at all
    for face, widths in afm.WIDTHS.items():
        if face in afm.INK_TOP and widths[0x80]:
            assert afm.INK_TOP[face][0x80] > 0, face


def test_a_euro_and_its_comma_do_not_collide_under_modern():
    """The visible defect, as a rule: the word after a euro starts a
    full space clear of it."""
    from ctrlkd.afm import string_width_pt
    doc = _doc(b'LASERJET', b'Here ' + PESETA + b', then more words follow.')
    out = pdf.emit_pdf(doc, mode='modern')
    xs = {}
    for m in re.finditer(rb'([-\d.]+) ([-\d.]+) Td \((.*?)\) Tj', out, re.S):
        xs[m.group(3)] = float(m.group(1))
    assert b'\x80,' in xs and b'then' in xs
    gap = xs[b'then'] - xs[b'\x80,']
    assert gap > string_width_pt('\u20ac,', 'Times-Roman', pdf.MODERN_BODY_PT)


# -------------------------------------------------- patched drivers: euro

@pytest.mark.parametrize('driver', [b'LASERJET', b'LJ6DTP', b'HP4'])
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_patched_driver_prints_the_euro(driver, mode):
    doc = _doc(driver)
    assert doc.meta['printer_driver'] == driver.decode()
    out = pdf.emit_pdf(doc, mode=mode)
    assert any(EURO_CP1252 in s for s in _text_strings(out)), (
        f'{driver!r}/{mode}: no euro reached the content stream')


@pytest.mark.parametrize('driver', [b'LASERJET', b'LJ6DTP', b'HP4'])
def test_a_patched_driver_draws_no_peseta_geometry(driver):
    """The euro is a real cp1252 character on every base-14 face, so it is
    ordinary TEXT -- the vector path must not also fire for it."""
    doc = _doc(driver)
    plain = pdf.emit_pdf(_doc(driver, b'Costs 100 today'), mode='printed')
    out = pdf.emit_pdf(doc, mode='printed')
    assert out.count(b' re f') == plain.count(b' re f')


# ------------------------------------------------ other drivers: peseta

@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_an_unpatched_driver_draws_the_peseta(mode):
    doc = _doc(b'EPSONFX')
    assert doc.meta['printer_driver'] == 'EPSONFX'
    out = pdf.emit_pdf(doc, mode=mode)
    assert not any(EURO_CP1252 in s for s in _text_strings(out)), (
        f'{mode}: a euro reached a document no patched driver printed')
    # the Pt ligature: one Bezier disc (the P's bowl) plus filled rects
    plain = pdf.emit_pdf(_doc(b'EPSONFX', b'Costs 100 today'), mode=mode)
    assert out.count(b' re f') > plain.count(b' re f')
    assert out.count(b' c\n') > plain.count(b' c\n')


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_document_with_no_driver_at_all_draws_the_peseta(mode):
    doc = _headerless_doc()
    assert doc.meta.get('printer_driver') is None
    out = pdf.emit_pdf(doc, mode=mode)
    assert not any(EURO_CP1252 in s for s in _text_strings(out))
    assert b' re f' in out


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_the_peseta_never_degrades_to_a_question_mark(mode):
    """The defect the vector path exists to close: before this, a
    non-patched document's code 158 had no cp1252 slot and no glyph, so it
    reached the page as a literal '?'."""
    doc = _doc(b'EPSONFX')
    out = pdf.emit_pdf(doc, mode=mode)
    assert not any(b'?' in s for s in _text_strings(out)), (
        f'{mode}: a "?" reached the content stream')


# ------------------------------------------------------- running heads/feet

def _doc_with_running_head(driver, hf_text=b'Report ' + PESETA + b' Draft #'):
    """A synthetic document naming `driver` (or no driver at all, when
    `driver` is None) whose `.h1`/`.f1` running head AND foot both carry
    `hf_text` -- the running-head/foot counterpart of `_doc`'s own body
    fixture. The WSFORMAT type-0 driver block and the plain `.h1`/`.f1`
    dot commands compose exactly as `test_lj6dtp_heading_face.py`'s own
    `_doc_with_header_font` (driver block) and `test_ctrlkd.py`'s own
    `test_head_foot_lines_land_on_the_model_matching_the_writer` (plain
    `.h1`/`.f1`, no WSFORMAT block needed for text alone) already show."""
    header = _driver_header(driver) if driver else _ws_block(0x01, b'\x00\x00')
    body = (b'.h1 ' + hf_text + HARD + b'.f1 ' + hf_text + HARD +
            b'Body text, plain and ordinary and long enough to be real.' + HARD)
    return core.parse_ws(header + body)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
@pytest.mark.parametrize('driver', [b'LASERJET', b'LJ6DTP', b'HP4'])
def test_a_patched_drivers_running_head_and_foot_print_the_euro(driver, mode):
    """THE LATENT GAP this fix closes: `_running_ops` already bound
    `_peseta_euro_table` (same commit as the body rule) with a comment
    saying it applies to running heads/feet, but `_hf_line_ops` never
    consumed it -- a running head/foot carrying cp437 code 158 kept
    showing '?' even on a patched-driver document, the exact defect the
    driver rule exists to close for body text. Modern's own running-head/
    foot renderer, `_modern_hf_ops` (called from `_modern_streams`),
    carried the identical latent gap (planning #266 follow-up 2) -- found
    porting to the sr engine (Sources/CtrlKD/PDFWriter.swift `runningOps`,
    commit 00b85ae, and Sources/CtrlKD/PDFModernLayout.swift
    `modernHFOps`) -- byte-identical across the corpus either way, since
    no document's own running head carries code 158."""
    doc = _doc_with_running_head(driver)
    assert doc.meta['printer_driver'] == driver.decode()
    out = pdf.emit_pdf(doc, mode=mode)
    if mode == 'printed':
        # `_hf_line_ops` keeps a whole header/footer line as one `Tj`
        # string, so the euro lands inside the same string as 'Report'.
        strings = [s for s in _text_strings(out) if b'Report' in s]
        assert strings, f'{driver!r}/{mode}: the running head/foot text never reached the page'
        assert all(EURO_CP1252 in s for s in strings), (
            f'{driver!r}/{mode}: no euro reached the running head/foot -- {strings!r}')
    else:
        # `_modern_hf_ops` tokenises a line word-by-word (`_modern_line_
        # ops`'s one-op-per-word rule), so the converted euro is its own
        # standalone `Tj` string, never merged with 'Report'/'Draft'. The
        # fixture's body carries no peseta/euro of its own, so any euro
        # reaching the page at all must be this running head/foot's.
        assert any(EURO_CP1252 in s for s in _text_strings(out)), (
            f'{driver!r}/{mode}: no euro reached the running head/foot')


@pytest.mark.parametrize('mode', ['printed', 'modern'])
@pytest.mark.parametrize('driver', [b'EPSONFX', None])
def test_an_unpatched_drivers_running_head_and_foot_keep_the_peseta_unconverted(driver, mode):
    """The twin: a document naming no patched driver (or no driver at
    all) sees its running head/foot's own code 158 exactly as before this
    fix -- unchanged, not regressed, by the driver rule now reaching here,
    under either mode.

    The two modes were ALREADY different here, before this fix and after
    it alike: `_hf_line_ops` (printed) has no vector-drawing path of its
    own, so an unconverted peseta degrades through `_esc`'s cp1252
    'replace' fallback to a literal '?', same as every other character
    `_ESC_FALLBACK` does not cover. `_modern_hf_ops` (modern) calls the
    SAME `_modern_line_ops` body text draws through, and that function's
    graphic-character branch does not know or care that its caller is a
    running line -- so an unconverted peseta there draws as the vector
    geometry `pdf.SYMBOL_SHAPES` defines, exactly as it would in a
    paragraph. Neither behavior moved when the euro table was wired in;
    this test pins both."""
    doc = _doc_with_running_head(driver)
    plain = _doc_with_running_head(driver, hf_text=b'Report Draft #')
    if driver:
        assert doc.meta['printer_driver'] == driver.decode()
    else:
        assert doc.meta.get('printer_driver') is None
    out = pdf.emit_pdf(doc, mode=mode)
    assert not any(EURO_CP1252 in s for s in _text_strings(out)), (
        f'{driver!r}/{mode}: a euro reached a running head/foot no patched driver printed')
    if mode == 'printed':
        strings = [s for s in _text_strings(out) if b'Report' in s]
        assert strings, f'{driver!r}/{mode}: the running head/foot text never reached the page'
        assert all(b'?' in s for s in strings), (
            f'{driver!r}/{mode}: expected the pre-existing "?" degradation, got {strings!r}')
    else:
        # the vector twin of the body-level `test_an_unpatched_driver_
        # draws_the_peseta`: a peseta-bearing running head/foot draws
        # strictly more vector geometry than the same fixture with the
        # peseta simply removed, and no literal '?' reaches the page.
        out_plain = pdf.emit_pdf(plain, mode=mode)
        assert out.count(b' re f') > out_plain.count(b' re f')
        assert out.count(b' c\n') > out_plain.count(b' c\n')
        assert not any(b'?' in s for s in _text_strings(out)), (
            f'{driver!r}/{mode}: a "?" reached a running head/foot with its own vector path')


# ------------------------------------------------------------- tier 2

@pytest.mark.sawyer
def test_readme_ws_prints_the_euro_where_it_always_did(require_sawyer_doc):
    """-README.WS is the document the euro trick was written FOR: it names
    LASERJET, and its own worked example ("If you see the euro character
    right here ₧") inserts code 158 to prove the patched driver renders it.

    The Printed page is BYTE-IDENTICAL to what it was before planning #266
    -- the recorded op below is the one from the answer key this change was
    made against -- because a patched-driver document was already getting
    the euro, just for the wrong reason.

    Tier 2 (sawyer): one of the committed manifest documents
    (tests/SAWYER-CORPUS.md).
    """
    path = require_sawyer_doc('-README.WS (root)')
    doc = core.parse(open(path, 'rb').read())
    assert doc.meta['printer_driver'] == 'LASERJET'
    out = pdf.emit_pdf(doc, mode='printed')
    assert (b"BT /F1 12 Tf 0 Ts 57.6 564.0 Td (If you see the euro character"
            b" right here \x80, then you're all set ) Tj ET") in out


@pytest.mark.sawyer
def test_display_ws_chart_entry_follows_its_own_driver(require_sawyer_doc):
    """DISPLAY.WS is a bare cp437 code-to-glyph reference chart ("158
    <glyph>") with no euro prose anywhere in it -- it used to be recorded
    as this rule's KNOWN LIMIT, resolved the same way as -README's own
    worked example for no reason of its own. Under the driver rule it is
    not a special case at all: it names LASERJET in its own header, so it
    is a patched-driver document and its chart entry shows the euro that
    driver actually put on paper.

    Tier 2 (sawyer): one of the committed manifest documents.
    """
    path = require_sawyer_doc('DISPLAY.WS')
    doc = core.parse(open(path, 'rb').read())
    assert doc.meta['printer_driver'] == 'LASERJET'
    out = pdf.emit_pdf(doc, mode='printed')
    row = [s for s in _text_strings(out) if b'158' in s and b'142' in s]
    assert row, 'DISPLAY.WS no longer carries its 142/158/174 chart row'
    assert all(EURO_CP1252 in s for s in row)


@pytest.mark.sawyer
@pytest.mark.parametrize('name,driver', [('REF/ASCIITAB.WS', 'PRINTER'),
                                         ('PSPRINT.TST', None)])
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_unpatched_corpus_documents_get_the_peseta(require_sawyer_doc,
                                                   name, driver, mode):
    """The other half of the rule on real documents: ASCIITAB.WS declares
    PRINTER (a driver Sawyer never patched) and PSPRINT.TST declares no
    driver at all, and both carry code 158. Each now draws a peseta
    instead of borrowing -README's euro.

    Tier 2 (sawyer): committed manifest documents.
    """
    path = require_sawyer_doc(name)
    doc = core.parse(open(path, 'rb').read())
    assert doc.meta.get('printer_driver') == driver
    body = ''.join(sp.text for b in doc.blocks for line in b.lines
                   for sp in line.spans)
    assert '₧' in body, f'{name} no longer carries cp437 code 158'
    out = pdf.emit_pdf(doc, mode=mode)
    assert not any(EURO_CP1252 in s for s in _text_strings(out)), (
        f'{name}/{mode}: a euro reached a document no patched driver printed')
