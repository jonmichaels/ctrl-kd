"""Five rulings, 2026-08-24 (WordStar-Feature-Decision-Register.md rows for
2026-08-23/2026-08-24):

  1. Collision-triggered continuous renumbering for footnotes/endnotes in
     TXT, MD, HTML (the three page-less formats) -- ONLY when WordStar's own
     per-page-reset numbers actually collide within a kind. Printed, Modern
     PDF, and RTF must never renumber.
  2. Modern PDF note ENTRY labels drop the brackets: `1.` (footnote),
     `i.` (endnote) -- no brackets, no superscript on the entry.
  3. TXT note markers: `[N]` footnotes, `(N)` endnotes, inline and in the
     entry -- same wrapper both places.
  4. Note TAGS (WSFORMAT.TXT high-bit-on-high-bit case): a footnote/endnote
     can carry a user MARK instead of a number. Display it, never renumber
     it. NO ARCHIVE SPECIMEN CARRIES ONE -- synthetic fixtures only.
  5. Note FORMAT TYPES (conversion-flag high nybble): 0 symbols, 1 upper,
     2 lower, 3 numeric. `Note.number_format` was parsed but never read.
     NO ARCHIVE SPECIMEN USES ANYTHING BUT 3 -- synthetic fixtures only.
"""
import re

from ctrlkd import core, emit
from ctrlkd.emit import _format_note_number, _alpha_label, _note_symbol

HARD = b'\x0d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def ws7_note(cmd, text, number=1, line_count=1, number_format=3, convert_to=0):
    conv_flag = ((number_format & 0x0F) << 4) | (convert_to & 0x0F)
    content = (line_count.to_bytes(2, 'little') + number.to_bytes(2, 'little') +
               bytes([conv_flag]) + text)
    return ws7_block(cmd, content)


def ws7_note_tagged(cmd, text, tag_text, line_count=1, junk_conv_flag=0x00):
    """A footnote/endnote carrying a user MARK (ruling item 4): the SAME
    high-bit-nested-sequence shape `ws7_note_with_tag` (test_ctrlkd.py)
    already exercises for a plain NUMBER override, but with the INNER
    block's OWN tag word ALSO high-bit-set -- WSFORMAT.TXT's rule applied
    one level deeper, since "currently only one level of this recursion is
    used" leaves no third level. The tag text sits at the same byte
    offset (5) an annotation's tag already comes from."""
    inner_content = b'\x00\x00' + b'\x00\x80' + bytes([junk_conv_flag]) + tag_text
    inner = ws7_block(cmd, inner_content)
    split = len(text) // 2
    outer_text = text[:split] + inner + text[split:]
    content = (line_count.to_bytes(2, 'little') + b'\x00\x80' +
               bytes([junk_conv_flag]) + outer_text)
    return ws7_block(cmd, content)


def _td_words(pdf_bytes):
    """Every Tj show-text operand in a PDF content stream, in order."""
    return re.findall(rb'\(((?:\\.|[^)\\])*)\)\s*Tj', pdf_bytes)


# =========================== item 4: note tags ==============================

def test_footnote_tag_is_captured_and_has_no_number():
    data = ws7_note_tagged(0x03, b'A marked footnote.', b'STAR')
    doc = core.parse_ws(data)
    note = doc.notes[0]
    assert note.kind == 'footnote'
    assert note.tag == 'STAR'
    assert note.number is None
    assert note.text == 'A marked footnote.'
    assert note.number_format == 0 and note.convert_to == 0   # spec: unused with a tag


def test_endnote_tag_is_captured_and_has_no_number():
    data = ws7_note_tagged(0x04, b'A marked endnote.', b'DAGGER')
    doc = core.parse_ws(data)
    note = doc.notes[0]
    assert note.kind == 'endnote'
    assert note.tag == 'DAGGER'
    assert note.number is None


def test_tagged_footnote_displays_tag_and_is_immune_to_collision_renumbering():
    # Two PLAIN footnotes stored as 0 (a real collision, per a private specimen) plus
    # one TAGGED footnote in between. The plain pair must renumber
    # continuously; the tagged one must show its mark, untouched, in every
    # format, and must not itself trigger or absorb any renumbering.
    data = (ws7_block(0x00) + b'one' + ws7_note(0x03, b'Plain one.', number=0) +
            b' two' + ws7_note_tagged(0x03, b'Marked one.', b'STAR') +
            b' three' + ws7_note(0x03, b'Plain two.', number=0) +
            b' end.' + HARD)
    doc = core.parse_ws(data)
    t = emit.emit_text(doc, mode='modern')
    assert '[1] Plain one.' in t
    assert '[STAR] Marked one.' in t
    assert '[2] Plain two.' in t
    md = emit.emit_markdown(doc, mode='modern')
    assert '[^1]: Plain one.' in md and '[^2]: Plain two.' in md
    h = emit.emit_html(doc, mode='modern')
    assert 'id="fn1"' in h and 'id="fn2"' in h and 'id="fnSTAR"' in h


def test_rtf_tagged_footnote_uses_custom_mark_not_chftn():
    data = (ws7_block(0x00) +
            b'Prose padding so the detector reads this as a document, plainly.'
            + HARD + b'A marked reference' +
            ws7_note_tagged(0x03, b'A marked footnote.', b'STAR') +
            b' continues after.' + HARD)
    doc = core.parse_ws(data)
    r = emit.emit_rtf(doc, mode='modern')
    assert r'{\super STAR}' in r
    assert r.count(r'\chftn') == 0     # never auto-numbered once tagged


# ====================== item 5: note format types ===========================

def test_symbol_cycle_matches_the_classical_sequence_and_doubles_past_six():
    assert [_note_symbol(i) for i in range(1, 7)] == list('*†‡§‖¶')
    assert _note_symbol(7) == '**'
    assert _note_symbol(13) == '***'


def test_alpha_label_is_bijective_base_26():
    assert _alpha_label(1, upper=False) == 'a'
    assert _alpha_label(26, upper=False) == 'z'
    assert _alpha_label(27, upper=False) == 'aa'
    assert _alpha_label(1, upper=True) == 'A'


def test_number_format_is_NOT_honoured_ground_truth_says_arabic():
    """WordStar's format spec documents a conversion-flag high nybble (0
    symbols / 1 upper / 2 lower / 3 numeric) and we briefly honoured it.

    REAL WORDSTAR 7 DISPROVED THAT. `DISPLAY.WS` -- WordStar's own tutorial
    file in the archive -- carries a footnote at number_format=2 and an endnote
    at number_format=1. Printed through real WS7 under DOSBox-X it puts `1.`
    and `(1)` on the page: plain arabic, exactly like every other document.
    Capture: ws7-prints/v1/DISPLAY.pcl.

    So the label is ALWAYS arabic. The field stays parsed -- preserve-what-you-
    find governs the IR -- and is simply not consulted for display.
    """
    for fmt in (0, 1, 2, 3, 9):
        assert _format_note_number(1, fmt) == '1'
        assert _format_note_number(7, fmt) == '7'

def test_a_nonnumeric_format_code_still_renders_arabic_everywhere():
    """The same ground truth, end to end: a note carrying a non-numeric format
    code renders arabic in the actual output, not a symbol or a letter."""
    data = (ws7_block(0x00) + b'ref' +
            ws7_note(0x03, b'Symbol note.', number=0, number_format=0) +
            b' end.' + HARD)
    doc = core.parse_ws(data)
    t = emit.emit_text(doc, mode='modern')
    assert '[1] Symbol note.' in t
    assert '[*]' not in t and '[A]' not in t and '[a]' not in t

def test_modern_endnote_with_a_format_code_still_romanizes_normally():
    # A non-numeric format code must not disturb Modern's lower-roman endnote
    # labels: the code is ignored, the label stays arabic underneath, and
    # layout.py's endnote_label() romanizes it exactly as it would any other.
    # (Before ground truth, this test asserted `A.` -- WordStar itself prints
    # arabic for such a note, so `i.` is correct here.)
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) + b'ref' +
            ws7_note(0x04, b'Alpha endnote.', number=0, number_format=1) +
            b' end.' + HARD)
    doc = core.parse_ws(data)
    pdf = emit_pdf(doc, mode='modern')
    words = _td_words(pdf)
    assert b'i.' in words
    assert b'A.' not in words


# ============ item 1: collision-triggered pageless renumbering ==============

def test_no_collision_leaves_stored_numbers_untouched():
    # Simulates a `.F#`-consecutive document: two footnotes with DIFFERENT
    # stored numbers already display distinctly and must NOT be forced into
    # 1, 2 -- collision is the only trigger.
    data = (ws7_block(0x00) + b'one' + ws7_note(0x03, b'First.', number=0) +
            b' two' + ws7_note(0x03, b'Second.', number=5) + b' end.' + HARD)
    doc = core.parse_ws(data)
    t = emit.emit_text(doc, mode='modern')
    assert '[1] First.' in t and '[6] Second.' in t


def test_collision_renumbers_txt_md_html_but_not_printed_modern_pdf_rtf():
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) + b'one' + ws7_note(0x03, b'First.', number=0) +
            b' two' + ws7_note(0x03, b'Second.', number=0) + b' end.' + HARD)
    doc = core.parse_ws(data)

    t = emit.emit_text(doc, mode='modern')
    assert '[1] First.' in t and '[2] Second.' in t

    md = emit.emit_markdown(doc, mode='modern')
    assert '[^1]: First.' in md and '[^2]: Second.' in md

    h = emit.emit_html(doc, mode='modern')
    assert h.count('id="fn1"') == 1 and h.count('id="fn2"') == 1
    assert h.count('id="fnref1"') == 1 and h.count('id="fnref2"') == 1

    pp = emit_pdf(doc, mode='printed')
    ptexts = b' '.join(_td_words(pp))
    assert b'First.' in ptexts and b'Second.' in ptexts
    assert b'2.' not in ptexts                # WS7's own number: both "1."

    pm = emit_pdf(doc, mode='modern')
    mtexts = b' '.join(_td_words(pm))
    assert b'First.' in mtexts and b'Second.' in mtexts
    assert b'2.' not in mtexts                # unrenumbered here too

    r = emit.emit_rtf(doc, mode='modern')
    # unstarred (ruling 2026-08-26): a `\footnote` destination, no `\*`
    assert r.count(r'\footnote') == 2 and r.count(r'\chftn') >= 2
    assert r'\*\footnote' not in r


# ================ item 2: Modern PDF entry labels, no brackets ==============

def test_modern_pdf_footnote_and_endnote_entries_drop_brackets():
    from ctrlkd.pdf import emit_pdf
    data = (ws7_block(0x00) + b'ref one' + ws7_note(0x03, b'Foot body.', number=0) +
            b' ref two' + ws7_note(0x04, b'End body.', number=0) + b' end.' + HARD)
    doc = core.parse_ws(data)
    words = _td_words(emit_pdf(doc, mode='modern'))
    assert b'1.' in words                      # footnote entry: arabic + period
    assert b'i.' in words                      # endnote entry: lower-roman + period
    assert b'[1]' not in words and b'[i]' not in words


def test_modern_pdf_annotation_entry_keeps_brackets_unaffected_by_ruling():
    # The ruling named only footnote/endnote appearance; an annotation's
    # tag-based entry must stay exactly as it was.
    from ctrlkd.pdf import emit_pdf
    import test_ctrlkd as _tc
    data = (ws7_block(0x00) + b'ref' +
            _tc.ws7_annotation_with_tag(dot_lines=[b'.. aside'],
                                        text=b'Anno body.', tag_text=b'AC1') +
            b' end.' + HARD)
    doc = core.parse_ws(data)
    words = _td_words(emit_pdf(doc, mode='modern'))
    assert b'[AC1]' in words


# ==================== item 3: TXT [N] footnote, (N) endnote =================

def test_txt_footnote_bracket_endnote_paren_inline_and_entry():
    data = (ws7_block(0x00) + b'foot here' + ws7_note(0x03, b'Foot body.', number=0) +
            b' end here' + ws7_note(0x04, b'End body.', number=0) + b' done.' + HARD)
    doc = core.parse_ws(data)
    t = emit.emit_text(doc, mode='modern')
    assert 'foot here[1] end here(1) done.' in t
    assert 'Footnotes:\n[1] Foot body.' in t
    assert 'Endnotes:\n(1) End body.' in t


# ===================== the real specimen (private corpus) ========================
#
# Jon's own LYING.WS-derived test document (two footnotes and two endnotes,
# exercising the same collision-renumbering rules above against a real
# WS7 specimen rather than synthetic bytes) was tier 3 (private) and has
# been relocated out of this public repo entirely -- see the private test
# suite in the companion repo, which runs the same assertions against this
# engine from outside it.
