"""ctrlkd.writer tests — the native WordStar writer (tasks #20/#21).

Synthetic fixtures are built byte-by-byte here, same discipline as
test_ctrlkd.py (whose helper builders are copied in below rather than
imported — its own guidance). The corpus gauntlet that asserted
byte-identity against Jon's private archive (named files plus a census
floor) was tier 3 and has been relocated out of this public repo entirely
-- see the private test suite in the companion repo, which imports this
module's `rt` helper shape against the installed package from outside it.
"""
import pytest

from ctrlkd import core
from ctrlkd.core import Block, Document, Line, Span
from ctrlkd.writer import emit_ws, WriteError

SOFT = b'\x8d\x0a'
HARD = b'\x0d\x0a'


# -------- helpers copied from test_ctrlkd.py (do not import its privates)

def ws4_word(w):
    """WS4 sets bit 7 on the last character of each word."""
    return w[:-1] + bytes([w[-1] | 0x80])


def ws4_text(s):
    return b' '.join(ws4_word(w.encode()) for w in s.split(' '))


def ws7_block(cmd, content=b''):
    """One WS7 symmetrical sequence: 0x1D, count, type byte, content, the
    matching trailing count, closing 0x1D (count = len(content) + 4)."""
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def ws7_note(cmd, text, number=1, line_count=1, number_format=3, convert_to=0):
    conv_flag = ((number_format & 0x0F) << 4) | (convert_to & 0x0F)
    content = (line_count.to_bytes(2, 'little') + number.to_bytes(2, 'little') +
               bytes([conv_flag]) + text)
    return ws7_block(cmd, content)


def rt(data):
    """The whole contract in one call: emit_ws(parse(x)), to compare with x."""
    return emit_ws(core.parse_ws(data))


# ---------------------------------------------------------------- WS4

def test_ws4_prose_roundtrips_with_flag_bits():
    # bit-7 word flags are masked at decode; Line.fixups restores each one
    data = (ws4_text('hello there friendly world this line wraps along') +
            SOFT + ws4_text('and continues here') + HARD +
            ws4_text('Second paragraph opens now.') + HARD + b'\x1a')
    assert rt(data) == data


def test_ws4_highbit_toggle_roundtrips():
    # a word ending at a style boundary flags the TOGGLE byte (0x93 = ^S|80)
    data = (b'plain \x93under\x93 word' + HARD + b'\x1a')
    assert rt(data) == data


# ---------------------------------------------------------------- WS5+

WS5_SEED = ws7_block(0x0B, b'\x00' * 4)     # end-of-page marker: two 0x1D
                                             # framing bytes make detect()
                                             # read the fixture as ws5+


def test_ws5_prose_and_soft_returns():
    data = (b'This paragraph wraps at the usual column and keeps going' +
            SOFT + b'until the author presses Return.' + HARD + HARD +
            b'Second paragraph.' + HARD + WS5_SEED + b'\x1a')
    assert rt(data) == data


def test_ws5_note_block_reserialized_verbatim():
    note = ws7_note(0x03, b'A footnote body.')
    data = b'Text before' + note + b' and after.' + HARD + b'\x1a'
    doc = core.parse_ws(data)
    assert doc.notes and doc.notes[0].kind == 'footnote'
    assert emit_ws(doc) == data


def test_ws5_tab_block_and_expansion():
    # type 9 tab: 2 columns (360 HMI), hard tab type ' '
    tab = ws7_block(0x09, (360).to_bytes(2, 'little') +
                    (360).to_bytes(2, 'little') + b' \x02')
    data = WS5_SEED + tab + b'indented text' + HARD + b'\x1a'
    assert rt(data) == data


def test_bare_0x09_tab_byte_survives_verbatim():
    """Planning #244 (found 2026-09-08 by the private round-trip census,
    tools/roundtrip_census.py): a bare 0x09 tab byte (as opposed to the
    `.tb`-ruler type-9 tab block the case above covers) must come back
    as the SAME literal byte -- not the modulus-8 spaces Printed-mode PDF
    rendering computes for it (`pdf._expand_bare_tabs_for_printed_layout`,
    planning #244's own layout-time relocation of that expansion, see
    that function's docstring). Baking the expansion into `_decode_spans`
    at PARSE time (the original planning #202/#237 shape) made a computed
    space indistinguishable from one the author actually typed, and this
    exact byte broke round-trip on three real archive documents (sawyer/
    MACROS/HOLYMAC/-HOLYMAC.WS, sawyer/REF/WINDOWS7.WS, sawyer/REF/
    wordstar-file-format.ws) before this fix -- this is the synthetic,
    public-repo regression guard for that gap; the private repo's own
    corpus gauntlet is the real-file coverage."""
    data = WS5_SEED + b'From:\tWordStar' + HARD + b'\x1a'
    assert rt(data) == data


def test_ws5_wrapped_extended_chars_and_bare_high_byte():
    # a real é as the wrapped triple, a chart glyph, a wrapped PRINTABLE
    # (ASCIITAB style), and a bare extended byte -- four different escape
    # economies, each of which must come back in its own original form
    data = (WS5_SEED + b'caf\x1b\x82\x1c glyph \x1b\x01\x1c' + HARD +
            b'wrapped \x1bA\x1c bare \xe1' + HARD + b'\x1a')
    assert rt(data) == data


def test_toggle_at_line_end_stays_before_break():
    # WordStar writes the toggle BEFORE the separator; the style lands on
    # the next line's spans. 40+ archive files diverged on exactly this.
    data = (WS5_SEED + b'next line is bold\x02' + HARD +
            b'bold on\x02 then off' + HARD + b'\x1a')
    assert rt(data) == data


def test_doublestrike_and_net_zero_toggle_pair():
    # ^D toggles the same 'b' tag as ^B (fixup restores the byte), and a
    # <14 14> on/off pair leaves no span behind at all
    data = (WS5_SEED + b'\x04double\x04 and \x14\x14 nothing' + HARD + b'\x1a')
    assert rt(data) == data


def test_toggle_order_is_preserved_against_canonical_diff():
    # the writer's span diff emits sorted removals-then-additions; the
    # file's own order <19 02> (italic-off after bold-on interleaved) must
    # come back via the cluster fixup
    data = (WS5_SEED + b'\x19ital\x02\x19bold\x02' + HARD + b'\x1a')
    assert rt(data) == data


def test_binding_space_soft_hyphens_and_dropped_controls():
    data = (WS5_SEED + b'bind\x0fhere soft\x1fhyphen in\x1eactive' + HARD +
            b'phantom \x08 rubout \x00 fix' + HARD + b'\x1a')
    assert rt(data) == data


def test_soft_space_a0_comes_back():
    data = WS5_SEED + b'five \xa0year mission' + SOFT + b'ends.' + HARD + b'\x1a'
    assert rt(data) == data


# ------------------------------------------------------------ dot commands

def test_dot_lines_verbatim_including_mailmerge():
    # mailmerge lines are PRESERVED bytes, never interpreted (permanent
    # ruling); trailing spaces and mixed case survive the rstrip/mask the
    # IR's own dot_commands view applies
    data = (b'.op\r\n'
            b'.AV "Name", 30  \r\n'
            b'.df DATA.LST\r\n'
            b'.rv name, street \r\n'
            b'Dear &name&,' + HARD + b'.pa\r\n'
            b'Page two.' + HARD + WS5_SEED + b'\x1a')
    assert rt(data) == data


def test_dot_lines_between_paragraphs_keep_position():
    data = (b'First paragraph.' + HARD + HARD +
            b'.lm 8\r\n'
            b'.rm 65\r\n'
            b'Indented paragraph.' + HARD + WS5_SEED + b'\x1a')
    assert rt(data) == data


def test_header_footer_comment_dot_lines():
    data = (b'.he Running head with #  \r\n'
            b'.. a comment the printer never sees\r\n'
            b'.ig another comment form\r\n'
            b'Body text here.' + HARD + WS5_SEED + b'\x1a')
    assert rt(data) == data


# ------------------------------------------------------- breaks and pages

def test_formfeed_pagebreak_byte_survives():
    data = (WS5_SEED + b'Page one.' + HARD + b'\x0c' + b'Page two.' + HARD +
            b'\x1a')
    assert rt(data) == data


def test_dot_command_after_flagged_form_feed_roundtrips():
    """Planning #246 round-trip companion to test_dot_command_after_a_flagged_
    form_feed_is_not_printed_as_text (test_ctrlkd.py): same byte shape (an
    End-of-page block's overprint-CR break, a bare 0x0D, a flagged form feed
    0x8C, then a dot command with no space), now checked for exact reassembly.

    The FF byte and the dot line's own bytes both land in the round-trip
    ledger at that point (a pagebreak Block plus a separate dot-line entry) --
    only the pagebreak's own event owns the flagged byte (patched back from
    0x0C to 0x8C by the file-level offset-based `flagged_at` un-translate);
    the dot line's own ledger entry must NOT also carry it, or the byte
    doubles on write. (The Swift port had exactly this bug: its dot-command
    ledger entry read the pre-mutation `physical.text` instead of the locally
    peeled `raw`, so the flagged form feed was serialized twice -- once from
    the pagebreak event, once folded into the dot line. Fixed alongside this
    test, ParseWS.swift.)
    """
    end_of_page = ws7_block(0x0B, b'\x00' * 28)
    data = (ws7_block(0x00) +
            b'Set a paragraph margin to print in' + SOFT +
            b'paragraph style.' + HARD +
            b'.cc 19' + end_of_page +
            b'\x0d' + b'\x8c' + b'.pm1' + HARD +
            b'Hanging Indentation' + HARD + b'\x1a')
    assert rt(data) == data


def test_blank_lines_including_trailing_run_and_ctrlz_tail():
    # the trailing blank run is consumed by lines_pass without ever being
    # yielded (raw_extras['eof_tail'] carries it); the ^Z padding after the
    # EOF byte is the file tail, verbatim
    data = (b'Text body line one here to make this look like prose ok' +
            SOFT + b'and its continuation.' + HARD + HARD + HARD +
            WS5_SEED + b'\x1a\x1a\x1a\x00')
    assert rt(data) == data


def test_whitespace_only_line_single_break():
    # a spaces-only physical line parses to a content Line plus a phantom
    # blank that owns the separator; the writer merges them back to ONE line
    data = WS5_SEED + b'Above.' + HARD + b'   ' + HARD + b'Below.' + HARD + b'\x1a'
    assert rt(data) == data


def test_overprint_bare_cr():
    data = WS5_SEED + b'BASE LINE\rOVERPRINT' + HARD + b'\x1a'
    assert rt(data) == data


def test_rr_ruler_image_overprint_terminator_roundtrips():
    """Planning #249 companion to test_rr_bare_ruler_image_overprint_
    terminator_adds_no_blank_line (test_ctrlkd.py): the swallowed overprint-continuation
    entry is folded into the ruler's own round-trip ledger (`_rt_dots`, same
    tally anchor) rather than dropped -- its bytes (here, just the bare
    entry's own CRLF; the entry's text is empty) must still come back."""
    data = (WS5_SEED +
            b'Line ending before the rulers.' + HARD + HARD +
            b'.rr\rL----P----R' + b'\x0d' + HARD +
            b'.rr\rL----R' + HARD +
            HARD +
            b'Line after the rulers.' + HARD + b'\x1a')
    assert rt(data) == data


# ------------------------------------------------------------ the contract

def test_editor_mutation_survives_a_save():
    # the reason the writer serializes from the IR: mutate a span, save,
    # and the mutation is in the bytes (guarded fixups degrade, never
    # corrupt). This is the anti-"keep a copy of the input" test.
    data = (WS5_SEED + b'The quick brown fox.' + HARD + b'\x1a')
    doc = core.parse_ws(data)
    line = doc.blocks[0].lines[0]
    line.spans[0] = Span(line.spans[0].text.replace('quick', 'sneaky'),
                         line.spans[0].styles)
    out = emit_ws(doc)
    assert b'sneaky' in out and b'quick' not in out
    assert out.endswith(HARD + b'\x1a')
    # and the mutated file still parses to the mutated text
    assert 'sneaky brown fox' in core.parse_ws(out).blocks[0].lines[0].text()


def test_synthetic_document_writes_canonical_bytes():
    # no ledger at all: flags drive the breaks, output ends like a WordStar
    # file, and it parses back to the same text
    doc = Document(meta={'era': 'ws5+'})
    doc.blocks = [Block('para', lines=[
        Line([Span('Hello '), Span('bold', frozenset({'b'}))]),
        Line([Span('second line')]),
    ])]
    out = emit_ws(doc)
    # the span diff closes bold at the next span boundary -- the head of
    # line two -- because a ledger-less doc has no tog_end to say otherwise
    assert out == b'Hello \x02bold\r\n\x02second line\r\n\x1a'


def test_printstream_refused_with_reason():
    doc = core.parse(b'Line one of printed page\r\nLine two\r\nLine three\r\n')
    with pytest.raises(WriteError):
        emit_ws(doc)


def test_shift_jis_document_refused():
    # 0x17 shift blocks rewrite the cleaned stream after the fact -- the
    # one parse transform whose offsets cannot be replayed. Refusal, not
    # corruption.
    data = (WS5_SEED + b'Enough plain prose here for detection to call the '
            b'fixture a document. ' + ws7_block(0x17, b'\x01') +
            b'\x93\x8a\x96\x7b' + ws7_block(0x17, b'\x00') + b' after' +
            HARD + b'\x1a')
    doc = core.parse_ws(data)
    assert doc.roundtrip['unsupported'] == 'shift-jis'
    with pytest.raises(WriteError):
        emit_ws(doc)
