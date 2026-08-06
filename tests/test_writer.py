"""ctrlkd.writer tests — the native WordStar writer and its gauntlet
(tasks #20/#21).

Synthetic fixtures are built byte-by-byte here, same discipline as
test_ctrlkd.py (whose helper builders are copied in below rather than
imported — its own guidance). The corpus gauntlet at the bottom runs only
when the private archive is present and asserts byte-identity on named,
verified files plus a census floor a regression will trip.
"""
import os
import glob

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


# --------------------------------------------------------- corpus gauntlet

# The private archive (never enters this repo). One path constant; every
# corpus test skips when it is absent.
ARCHIVE = '<PRIVATE-SAWYER-ROOT>/'

# Files VERIFIED byte-identical on 2026-08-06 -- a deliberate spread:
# WS4-flagged prose, style libraries, notes, Symbol/Dingbats runs, pctl
# rule-drawing, mailmerge, wrapped control charts, a 526 KB macro doc.
GAUNTLET_FILES = [
    'WS/OLDTIMES.WS',            # the review benchmark: notes, styles
    'WS/LJ6DTP.WS',              # 41 print controls, colour, fonts
    'WS/RTF-RJS/NOVEL.WS',       # style library + Symbol-font passages
    'WS/REF/WSFORMAT.WS',        # the spec describing its own format
    'WS/REF/ASCIITAB.WS',        # every control code wrapped as a chart
    'WS/REF/BOOKLET.WS',         # A0 soft spaces, flagged form feeds
    'WS/REF/PP.WS',              # trailing wrapped-control triples
    'WS/REF/CODES.WS',           # overprint ^H composition
    'WS/PRINTERS/fontcrib.ws',   # mid-line Symbol/Dingbats via styles
    'WS/WS-CON/SAMPLE.WS',       # ^D doublestrike, interleaved toggles
    'WS/LSRBOX/LSRBOXES.MRG',    # mailmerge + wrapped NULs
    'WS/MACROS/HOLYMAC/-HOLYMAC.WS',   # 526 KB, net-zero toggle pairs
]

needs_archive = pytest.mark.skipif(not os.path.isdir(ARCHIVE),
                                   reason='private corpus not present')


@needs_archive
@pytest.mark.parametrize('rel', GAUNTLET_FILES)
def test_gauntlet_named_file_byte_identical(rel):
    path = os.path.join(ARCHIVE, rel)
    if not os.path.exists(path):
        pytest.skip(f'{rel} not in this copy of the archive')
    with open(path, 'rb') as fh:
        data = fh.read()
    assert rt(data) == data


@needs_archive
def test_gauntlet_ws_cohort_census_floor():
    """Every .WS document in the archive, with a floor a regression trips.

    83 of 83 were byte-identical when this was written (2026-08-06). The
    floor is set at 83 so a writer/parser regression fails loudly; if the
    archive itself grows a new pathological file, the failure message says
    which file so the census (tools/roundtrip_census.py) can rule on it.
    """
    files = sorted(glob.glob(os.path.join(ARCHIVE, '**', '*.[Ww][Ss]'),
                             recursive=True))
    ok, bad = 0, []
    total = 0
    for path in files:
        with open(path, 'rb') as fh:
            data = fh.read()
        if not data or core.detect(data)['variant'] not in ('ws4', 'ws5+'):
            continue
        total += 1
        if rt(data) == data:
            ok += 1
        else:
            bad.append(os.path.relpath(path, ARCHIVE))
    assert total >= 80, f'archive shrank? only {total} .WS documents seen'
    assert ok >= 83 and not bad, (
        f'{ok} of {total} identical; diverged: {bad[:10]}')
