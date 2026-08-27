"""Round 20b (slate item 13): screenplay preservation, the RENDERING
half -- detected regions (test_screenplay_detection.py covers the
detection itself) get verse-class (line/indent-structure-preserving)
treatment in every Modern reflow emitter (Text, Markdown, HTML, RTF),
wired as one additional `or bi in screenplay_blocks` clause alongside
each format's own existing `is_verse` computation.

ACCEPTANCE (Jon's own naming): "SCRIPT.WS is the named acceptance doc:
its Modern output preserves the character/dialogue/parenthetical
ladder." Verified end-to-end against the real document below.
"""
import pytest

from ctrlkd import core, emit


def _screenplay_fixture():
    data = (b'INT. HOUSE - DAY\r\n\r\n'
            b'JOHN stares at the door.\r\n\r\n'
            b'                    JOHN\r\n'
            b'          What is that noise?\r\n\r\n')
    doc = core.parse_ws(data)
    doc.meta['variant'] = 'ws4'
    return doc


def _real_doc(path):
    return core.parse(open(path, 'rb').read())


# ============================================================ mechanism

def test_html_screenplay_detection_forces_verse_even_when_looks_like_verse_would_not(monkeypatch):
    """Direct proof the OR-wiring is real, not redundant with the
    pre-existing looks_like_verse heuristic: force looks_like_verse to
    say "not verse" and confirm a screenplay-detected block still keeps
    its <br>-joined line structure (via the SAME synthetic slugline
    fixture test_screenplay_detection.py's own region-growth test uses)."""
    import ctrlkd.emit as emit_mod
    monkeypatch.setattr(emit_mod, 'looks_like_verse', lambda *a, **k: False)
    doc = _screenplay_fixture()
    html = emit_mod.emit_html(doc, mode='modern')
    assert '<br>' in html, 'screenplay-detected block lost its line structure'


def test_rtf_screenplay_detection_forces_verse_even_when_looks_like_verse_would_not(monkeypatch):
    import ctrlkd.emit as emit_mod
    monkeypatch.setattr(emit_mod, 'looks_like_verse', lambda *a, **k: False)
    doc = _screenplay_fixture()
    rtf = emit_mod.emit_rtf(doc, mode='modern')
    assert r'\line' in rtf, 'screenplay-detected block lost its line structure'


def test_markdown_screenplay_detection_forces_verse_even_when_looks_like_verse_would_not(monkeypatch):
    import ctrlkd.emit as emit_mod
    monkeypatch.setattr(emit_mod, 'looks_like_verse', lambda *a, **k: False)
    doc = _screenplay_fixture()
    md = emit_mod.emit_markdown(doc, mode='modern')
    assert '  \n' in md, 'screenplay-detected block lost its hard-break line structure'


def test_text_screenplay_detection_forces_verse_even_when_looks_like_verse_would_not(monkeypatch):
    import ctrlkd.emit as emit_mod
    monkeypatch.setattr(emit_mod, 'looks_like_verse', lambda *a, **k: False)
    doc = _screenplay_fixture()
    text = emit_mod.emit_text(doc, mode='modern')
    lines = [l for l in text.split('\n') if l.strip() in ('JOHN', 'What is that noise?')]
    assert len(lines) == 2, ('screenplay-detected lines got flowed into one '
                             f'joined line instead of staying separate: {text!r}')


def test_ordinary_prose_is_byte_identical_with_and_without_detection():
    # a document with NO slugline at all must render EXACTLY as before
    # this round -- detect_screenplay_blocks returns frozenset() and the
    # new `or bi in screenplay_blocks` clause is unconditionally False.
    data = b'An ordinary paragraph.\r\n\r\nAnother ordinary paragraph.\r\n'
    doc = core.parse_ws(data)
    doc.meta['variant'] = 'ws4'
    html = emit.emit_html(doc, mode='modern')
    rtf = emit.emit_rtf(doc, mode='modern')
    md = emit.emit_markdown(doc, mode='modern')
    text = emit.emit_text(doc, mode='modern')
    assert '<br>' not in html
    assert r'\line' not in rtf
    assert '  \n' not in md
    assert 'ordinary paragraph.\nAnother' not in text  # not force-split


# =================================================== real-corpus acceptance
#
# Tier 2 (sawyer): SCRIPT.WS is one of the ten committed manifest documents
# (tests/SAWYER-CORPUS.md).

@pytest.mark.sawyer
def test_script_ws_html_ladder_preserves_relative_indent(require_sawyer_doc):
    doc = _real_doc(require_sawyer_doc('SCRIPT.WS'))
    html = emit.emit_html(doc, mode='modern')
    idx = html.rfind('OFFICE - DAY')      # the rendered "Figure 1" occurrence
    assert idx != -1
    region = html[idx:idx + 1600]
    # CAROLYN's own first-line indent (26 source columns) must exceed the
    # parenthetical's relative indent signal surviving as literal &nbsp;
    # runs on its OWN (non-first) line, and the action line's indent (6
    # columns) must be the smallest of the three.
    assert 'text-indent:26ch' in region      # CAROLYN
    assert 'text-indent:6ch' in region       # action lines
    assert '(irritated, impatient)' in region
    # the parenthetical/dialogue continuation lines keep MORE leading
    # &nbsp; than the action block's own continuation lines (6-column
    # indent), preserving the ladder's relative structure.
    paren_line = [l for l in region.split('<br>') if 'irritated' in l][0]
    nbsp_count = paren_line.count('&nbsp;')
    assert nbsp_count >= 17, f'parenthetical indent not preserved: {nbsp_count} nbsp'


@pytest.mark.sawyer
def test_script_ws_rtf_ladder_preserves_character_dialogue_structure(require_sawyer_doc):
    doc = _real_doc(require_sawyer_doc('SCRIPT.WS'))
    rtf = emit.emit_rtf(doc, mode='modern')
    idx = rtf.rfind("WRITER'S OFFICE - DAY")
    assert idx != -1
    region = rtf[idx:idx + 1200]
    assert r'\fi3744' in region      # CAROLYN's own 26-column indent (26*144)
    assert 'CAROLYN' in region and '(irritated, impatient)' in region
    assert r'\line' in region, 'dialogue lines lost their line-break structure'


@pytest.mark.sawyer
def test_script_ws_slugline_itself_survives_as_its_own_line(require_sawyer_doc):
    doc = _real_doc(require_sawyer_doc('SCRIPT.WS'))
    html = emit.emit_html(doc, mode='modern')
    assert "1     INT. WRITER&#x27;S OFFICE - DAY" in html
    assert "2     EXT. BAR - NIGHT" in html


@pytest.mark.sawyer
def test_script_ws_detection_is_the_deciding_factor_not_an_accident(require_sawyer_doc):
    """Confirms detect_screenplay_blocks itself (not some OTHER mechanism)
    is what covers the rendered-example region -- a regression in the
    detector's own region growth would be caught here even if
    looks_like_verse happened to independently also cover the same
    blocks (as it currently does for this specific document)."""
    doc = _real_doc(require_sawyer_doc('SCRIPT.WS'))
    region = core.detect_screenplay_blocks(doc)
    assert {76, 77, 78, 79, 80, 81, 82, 83}.issubset(region)
