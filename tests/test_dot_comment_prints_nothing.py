"""A WordStar COMMENT puts no ink on paper -- and no number standing in for
it either (planning #270, triage round 2026-09-14, item 1).

`..` is WordStar's non-printing comment LINE: MicroPro's own reference gives
it no paper presence at all, and real WS7 agrees -- `sawyer/REF/REFORM.DOT`
carries three `..` lines and its v4 PRISTINE capture has no mark, no digit and
no shift where they sit. The ^ON comment BLOCK is a different construct and is
equally silent on paper (ruling 2026-08-06 M9: "printed ALWAYS silent"), so
both origins are covered by one rule here.

What went wrong before this: the mark survived into the printed LINE and was
only dropped at the drawing step. Under `.pf on` the re-wrap had already
reduced it to characters and fused the three of them into the word "123",
which then printed at the head of REFORM.DOT's next line and shifted it
+16.50pt (1 `extra-word-in-engine`, 1 `line-start-shift`, 7 `exact-drift` on
the pcl tier -- the whole of that document's residual).

The mark is still IR, and still reaches Modern: RTF anchors its `\\*\\annotation`
and HTML its backlink at exactly that position, and Show Invisibles needs
somewhere to draw the comment icon. Only the PRINTED surfaces lose it.
"""
from ctrlkd import core, pdf, emit, layout


HARD = b'\x0d\x0a'
SOFT = b'\x8d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def build(body, dots=b''):
    return core.parse_ws(ws7_block(0x00) + dots + body)


def printed_lines(doc):
    return [''.join(t for t, _ in pl)
            for page in pdf._doc_to_pagelines(doc, True) for pl in page]


THREE_COMMENTS = (b'..one' + HARD + b'..two' + HARD + b'..three' + HARD)


def test_a_dot_comment_line_prints_nothing_at_all():
    doc = build(THREE_COMMENTS + b'Since all "if" commands' + HARD)
    assert len(doc.comments) == 3
    assert printed_lines(doc) == ['Since all "if" commands']


def test_the_printed_line_keeps_no_reference_span_for_a_comment():
    doc = build(THREE_COMMENTS + b'Body' + HARD)
    kept = pdf.pf_rewrapped_lines(doc, doc.blocks[0])[0].spans
    assert [s.text for s in kept] == ['Body']
    assert not any('fnref' in s.styles for s in kept)


def test_three_comment_marks_never_fuse_into_a_printed_word():
    """The REFORM.DOT shape: `.pf on` re-wraps the paragraph the marks were
    deferred onto, and the re-wrap works one character at a time."""
    doc = build(THREE_COMMENTS + b'Since all "if" commands evaluate' + SOFT
                + b'as true during editing' + HARD,
                dots=b'.pf on' + HARD + b'.rm 6.5"' + HARD)
    text = ''.join(printed_lines(doc))
    assert '123' not in text
    assert text.startswith('Since all "if" commands')


def test_a_comment_mark_costs_the_re_wrap_no_width():
    """Three marks are three columns WordStar never spent: with them counted,
    the measure breaks the paragraph one word earlier."""
    body = b'aaaa bbbb cccc dddd eeee ffff gggg hhhh' + SOFT + b'iiii' + HARD
    dots = b'.pf on' + HARD + b'.rm 4.0"' + HARD
    with_comments = printed_lines(build(THREE_COMMENTS + body, dots=dots))
    without = printed_lines(build(body, dots=dots))
    assert with_comments == without


def test_an_on_comment_block_is_equally_silent_on_paper():
    """kind 6 = comment, the ^ON construct -- ruling 2026-08-06."""
    doc = build(b'Body' + ws7_block(0x06, b'\x00' * 8 + b'aside') + b' text'
                + HARD)
    assert [n.kind for n in doc.notes] == ['comment']
    assert printed_lines(doc) == ['Body text']


def test_modern_still_knows_where_the_comment_sat():
    """The anchor is the point of keeping the mark in the IR at all: Modern's
    own flow keeps a zero-width run at the comment's true position (M9)."""
    doc = build(b'Body' + ws7_block(0x06, b'\x00' * 8 + b'aside') + b' text'
                + HARD)
    flow = layout.modern_flow(doc, notes=emit.ALL_NOTE_KINDS)
    runs = [r for item in flow['items'] for r in item.get('runs', [])]
    anchor = [r for r in runs if r.get('note_kind') == 'comment']
    assert len(anchor) == 1
    assert anchor[0]['text'] == ''                     # markless, but placed
    assert [r['text'] for r in runs] == ['Body', '', ' text']


def test_a_real_note_reference_still_prints():
    """The rule is about COMMENTS, not about marks -- a footnote whose own
    mark follows a comment's must still resolve to itself."""
    doc = build(b'..aside' + HARD + b'Body'
                + ws7_block(0x03, b'\x00' * 8 + b'the note') + b' text' + HARD)
    assert [n.kind for n in doc.notes] == ['comment', 'footnote']
    page = printed_lines(doc)
    assert page[0] == 'Body1 text'
