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
  - KNOWN, NOT-YET-FIXED gap (documented, not silently dropped): a
    WordStar comment's INLINE reference position is lost entirely in
    modern_flow's 'word' note-ref scheme (no run, no marker at all,
    unlike Native's own PageLine which keeps the real fnref span in
    place even where nothing renders) -- Show Invisibles would have no
    position to draw a comment icon at in Modern view under the default
    scheme. Left out of this round: fixing it means adding a new
    zero-width run KIND to the shared `runs` list pdf.py's
    `_modern_streams` also consumes, and verifying that consumer's own
    width/measurement math tolerates it needs more care than this
    round's remaining budget allows to do safely. Flagged for the
    prerequisite of wave 4's VIEW work, not silently left unmentioned.
"""
from ctrlkd import core
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
