"""Round 20 item 6 (slate items 5/11, engine half): what the Modern
layout JSON (layout.py's modern_flow / emit_layout) carries for sr's own
AnnotatedLayout (Sources/CtrlKD/AnnotatedLayout.swift) to build Show
Invisibles from, in Modern view. The VIEW rendering is a later wave
(explicitly out of scope this round) -- this round only ensures the DATA
survives into the layout emission.

INVESTIGATION FINDINGS (2026-08-18):
  - Header/footer declarations ('hf' items, `{kind, which, line, text}`)
    were ALREADY present inline in modern_flow's own item stream, anchored
    at the correct block position -- nothing to fix, documented here so
    it doesn't get "discovered" as a gap a second time.
  - `.tc`/`.ix`/tab-ruler state ('tabs' items) likewise already present.
  - Page-break ORIGIN ('.pa' dot command vs a literal form-feed byte) was
    a genuine, verifiable gap: core.py's Block object already carries
    `origin` ('ff' for a real 0x0C byte, None for `.pa`/DOT_PAGEBREAK),
    but modern_flow's own `{'kind': 'break'}` item dropped it -- Native
    (doc.blocks itself) always had the answer, Modern's JSON view didn't.
    FIXED: `{'kind': 'break', 'origin': ...}`, using the EXACT wire
    string sr's own AnnotatedLayout.swift already produces from its
    parallel Swift IR (`block.origin == .ff ? "\\u{0C}" : ".pa"`) -- so
    the two engines' layout JSON stays parity-testable as data (this
    module's own standing contract), not just internally self-consistent.
  - The comment-position gap this docstring used to flag as KNOWN,
    NOT-YET-FIXED was CLOSED in round 22 (C5): a kept comment under the
    default 'word' note-ref scheme now emits a ZERO-WIDTH anchor run
    ({'text': '', 'styles': [...], 'ref': ni}) at its true inline
    position -- the same spot the RTF export anchors \\*\\annotation at
    -- so Show Invisibles has a position to draw the comment icon at
    while the mark itself stays markless (Word's bubble convention).
    pdf.py's `_modern_streams` (the shared-consumer risk the round-20
    note worried about) skips empty ref runs explicitly, so Modern PDF
    bytes are untouched. Tests below pin the anchor's position against
    the RTF export's own anchor for the same fixture.
"""
from ctrlkd import core, emit
from ctrlkd.layout import modern_flow


def _ws_block(cmd, content, jump=None):
    if jump is None:
        jump = len(content) + 4
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([cmd]) + content + j + b'\x1d'


def test_dot_command_pagebreak_carries_the_dot_origin():
    data = b'Page one text.\r\n.pa\r\nPage two text.\r\n'
    doc = core.parse_ws(data)
    flow = modern_flow(doc)
    breaks = [it for it in flow['items'] if it['kind'] == 'break']
    assert breaks, 'no break item produced'
    assert breaks[0]['origin'] == '.pa'


def test_literal_formfeed_pagebreak_carries_the_formfeed_origin():
    # WS4's bit-7-toggle path (era='ws4', literal 0x0C in the byte
    # stream) is a real, distinct source from a WS5+ `.pa` dot command --
    # core.py already tags it (Block(..., origin='ff')); confirm the
    # JSON layer now reports it distinctly too.
    data = b'Page one.\x0cPage two.\r\n'
    doc = core.parse_ws(data)
    flow = modern_flow(doc)
    breaks = [it for it in flow['items'] if it['kind'] == 'break']
    assert breaks, 'no break item produced'
    assert breaks[0]['origin'] == '\x0c'


def test_pagebreak_origin_is_the_only_new_key_added():
    # a strict addition -- confirm no other break-item shape changed.
    data = b'Text.\r\n.pa\r\nMore.\r\n'
    doc = core.parse_ws(data)
    flow = modern_flow(doc)
    breaks = [it for it in flow['items'] if it['kind'] == 'break']
    assert set(breaks[0]) == {'kind', 'origin'}


def _ws_note(cmd, text, number=0):
    """A WS7 note block (0x03..0x06), matching test_ctrlkd's ws7_note:
    line count 1, embedded number, conversion flag 0x30."""
    content = ((1).to_bytes(2, 'little') + number.to_bytes(2, 'little') +
               bytes([0x30]) + text)
    return _ws_block(cmd, content)


def _comment_doc():
    """A comment (type 0x06) anchored between 'Alpha' and 'beta' -- the
    round-18 export fixture shape: the anchor's true inline position is
    mid-sentence, not at line or document end."""
    data = (_ws_block(0x00, b'') + b'Alpha ' +
            _ws_note(0x06, b'A margin comment.') + b'beta gamma.\r\n')
    return core.parse_ws(data)


def test_word_scheme_comment_emits_zero_width_anchor_at_inline_position():
    # Round 22 (C5): the default 'word' scheme used to drop a comment's
    # inline position entirely (no run at all). It must now carry a
    # markless zero-width anchor run at the true position: between the
    # 'Alpha ' run and the 'beta gamma.' run.
    doc = _comment_doc()
    flow = modern_flow(doc, notes=emit.ALL_NOTE_KINDS, note_refs='word')
    paras = [it for it in flow['items'] if it['kind'] == 'para'
             and any('ref' in r for r in it['runs'])]
    assert paras, 'no para item carries the comment anchor'
    runs = paras[0]['runs']
    i_ref = next(i for i, r in enumerate(runs) if 'ref' in r)
    assert runs[i_ref]['text'] == ''                  # markless: zero-width
    assert flow['notes'][runs[i_ref]['ref']]['kind'] == 'comment'
    i_alpha = next(i for i, r in enumerate(runs) if 'Alpha' in r['text'])
    i_beta = next(i for i, r in enumerate(runs) if 'beta' in r['text'])
    assert i_alpha < i_ref < i_beta


def test_comment_anchor_position_matches_rtf_export_anchor():
    # The layout stream's anchor and the RTF export's \*\annotation must
    # sit between the SAME two words for the same fixture -- the round-18
    # export anchoring is the reference the layout stream now matches.
    doc = _comment_doc()
    rtf = emit.emit_rtf(doc, mode='modern', notes=emit.ALL_NOTE_KINDS,
                        note_refs='word')
    assert rtf.index('Alpha') < rtf.index(r'\*\annotation') < rtf.index('beta')
    flow = modern_flow(doc, notes=emit.ALL_NOTE_KINDS, note_refs='word')
    para = next(it for it in flow['items'] if it['kind'] == 'para'
                and any('ref' in r for r in it['runs']))
    order = []
    for r in para['runs']:
        if 'ref' in r:
            order.append('anchor')
        elif 'Alpha' in r['text']:
            order.append('Alpha')
        elif 'beta' in r['text']:
            order.append('beta')
    assert order == ['Alpha', 'anchor', 'beta']


def test_prefixed_scheme_comment_mark_is_unchanged():
    # the 'prefixed' scheme already carried the visible c-mark at the
    # inline position -- confirm the round-22 change didn't touch it.
    doc = _comment_doc()
    flow = modern_flow(doc, notes=emit.ALL_NOTE_KINDS, note_refs='prefixed')
    para = next(it for it in flow['items'] if it['kind'] == 'para'
                and any('ref' in r for r in it['runs']))
    ref_run = next(r for r in para['runs'] if 'ref' in r)
    assert ref_run['text'] == 'c1'


def test_default_note_kinds_still_exclude_comments_entirely():
    # flag semantics unchanged: comments are opt-in (DEFAULT_NOTE_KINDS
    # excludes them) -- the default flow carries no anchor and no note row.
    doc = _comment_doc()
    flow = modern_flow(doc)
    assert not any('ref' in r for it in flow['items']
                   if it['kind'] == 'para' for r in it['runs'])
    assert all(row['kind'] != 'comment' for row in flow['notes'])


def test_word_scheme_comment_anchor_adds_no_ink_to_modern_pdf():
    # pdf._modern_flow skips empty ref runs: the anchor must not surface
    # as any visible mark in Modern PDF (no 'c1' text), while the opted-in
    # comment text still renders in the end-notes section as before.
    from ctrlkd import pdf
    doc = _comment_doc()
    out = pdf.emit_pdf(doc, mode='modern', notes=emit.ALL_NOTE_KINDS,
                       note_refs='word')
    assert b'(c1)' not in out
    assert b'margin' in out          # end-matter note text still renders


def test_header_declaration_already_rides_inline_in_modern_items():
    # documents the pre-existing, already-correct behavior -- guards
    # against a future change silently dropping it, matching this
    # investigation's own finding that 'hf' items needed no fix.
    data = b'.h1 My Header\r\nBody text.\r\n'
    doc = core.parse_ws(data)
    flow = modern_flow(doc)
    hf_items = [it for it in flow['items'] if it['kind'] == 'hf']
    assert hf_items, 'header declaration missing from Modern item stream'
    assert hf_items[0]['which'] == 'H'
    assert 'My Header' in hf_items[0]['text']
