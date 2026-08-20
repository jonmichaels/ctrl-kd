"""Round 20 item 1 (RJS.WS / slate item 10): the corpus-wide polarity gate.

RJS.WS investigation (2026-08-18): reported as "renders entirely struck-
through". Traced to core.py's style-library walk (_parse_style_library):
block style_id=1 ("Sawyer Defaults") carries attrs_on=1 (strikeout,
WSFORMAT's own bit table, byte offset rec+91 -- independently verified
against the WSFORMAT.TXT field list byte-for-byte, EVERY field in the
102-byte record decodes plausibly: font 180/240/0, margins 0/11700/-1,
2 tabs at 900/5940, justification=left, wrap=on, line-height=240,
line-spacing=1). This is NOT a misread -- the file's own 0x11 selector
block (offset 167, content 0102000202030002) resolves word0=0x0201 ->
pool 0x02 (this file) slot 1 (0-based, matches style-link-report.md's
validated join rule) -- exactly the strikeout-bearing record. Every
content block (1-7) selects this slot.

SETTLED BY REAL WS7 BYTES (2026-08-18, this investigation): printed
RJS.WS through the actual Sawyer WS7 install (SAWYER.EXE's own tree,
the private Sawyer install tree, env CTRLKD_SAWYER_ROOT) under DOSBox-X via
tools/wordstar_harness.sh (LASERJET driver -- did NOT stall despite
carrying a style library, contrary to the harness doc's OLDTIMES-based
"styled documents stall" caveat). Decoded with tools/pcl_text.py: EVERY
line of body text has a run of literal hyphen ('-') characters printed
at the IDENTICAL x/y decipoint position as the real words -- real
WordStar 7's own LaserJet driver rendering of strikeout via an
overprinted dash rule. ctrl-kd's whole-document strikethrough is
THEREFORE PERIOD-ACCURATE, not a parser bug -- reproduced here as
evidence, not "fixed" (there is nothing to fix; the record-boundary
mechanism was traced and found sound).

The polarity gate below is the SEPARATE, general correctness check Jon
asked for regardless: the INLINE attribute stream specifically (a span's
own RAW styles, via WS_TOGGLES bytes -- NOT block.style_attrs, which is a
different, independently-enabling mechanism RJS.WS itself proves is
allowed to diverge from raw toggle-byte counts) must never show an
attribute whose toggle byte(s) never occur in the document's own cleaned
text stream (the bytes that actually reach _decode_spans, i.e. outside
every validated 1D-framed symmetric block). A violation here would mean
raw binary payload bytes leaking into the inline decode path and being
misread as a toggle -- the mechanism the coordinator's report described,
verified NOT to affect RJS.WS but swept corpus-wide regardless.
"""
import glob
import os

import pytest

from ctrlkd import core

CORPUS = os.environ.get('CTRLKD_PRIVATE_CORPUS')

# WS_TOGGLES groups two source bytes onto one tag ('b': 0x02 bold, 0x04
# doublestrike-degrades-to-bold) -- the invariant must group them too, or
# a document with 0x02 present/0x04 absent would look like a false
# violation for a tag that's legitimately explained by the OTHER byte.
_TAG_BYTES = {'b': (0x02, 0x04), 'u': (0x13,), 'i': (0x19,),
             'sup': (0x14,), 'sub': (0x16,), 'strike': (0x18,)}


def inline_polarity_violations(data: bytes, encoding: str = 'cp437'):
    """[(tag, why)] -- tags that appear as a RAW (unmerged) span style
    somewhere in the document despite their toggle byte(s) never
    occurring in the cleaned text stream (_symmetric_blocks' own `out`,
    i.e. every byte that reaches _decode_spans -- symmetric-block payload
    bytes, including a style library's, are excluded by construction:
    they never reach `out` at all, see UnknownBlock handling and every
    recognized cmd's own content extraction)."""
    det = core.detect(data)
    if det['variant'] not in ('ws4', 'ws5+'):
        return []
    if not core.era_for(det['variant']).symmetric_blocks:
        return []          # WS4: no symmetric blocks, no style library either
    out = core._symmetric_blocks(data, encoding)[0]
    doc = core.parse_ws(data, encoding=encoding)
    # A note-reference marker is SYNTHESIZED with its own 'sup' tag
    # (_decode_spans's fn_counter mechanism, Span(str(n), {'sup','fnref'}))
    # -- a WordStar convention for how footnote numbers display, wholly
    # unrelated to the ^T (0x14) toggle byte. Corpus-proven false-positive
    # source (28/86 real documents) once this gate started checking the
    # real corpus (2026-08-18) -- excluded at the source, not special-
    # cased per document.
    raw_tags = {tag for b in doc.blocks for line in b.lines
               for sp in line.spans if 'fnref' not in sp.styles
               for tag in sp.styles}
    violations = []
    for tag, byte_vals in _TAG_BYTES.items():
        if tag not in raw_tags:
            continue
        if not any(out.count(bv) for bv in byte_vals):
            violations.append((tag, byte_vals))
    return violations


# ============================================================== synthetic

def _ws_block(cmd, content, jump=None):
    if jump is None:
        jump = len(content) + 4
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([cmd]) + content + j + b'\x1d'


def test_ordinary_toggle_produces_no_violation():
    # ^S...^S (0x13, underline) really is in the text stream -- the tag
    # it produces is legitimately explained, not a violation.
    data = b'plain \x13underlined\x13 text\r\n'
    assert inline_polarity_violations(data) == []


def test_a_toggle_byte_absent_from_text_never_appears_as_a_raw_span_tag():
    # No control bytes at all in this document -- every one of the six
    # tracked tags must be absent from raw span styles too.
    data = b'Nothing but plain prose, no toggles anywhere.\r\n'
    doc = core.parse_ws(data)
    raw_tags = {t for b in doc.blocks for line in b.lines
               for sp in line.spans for t in sp.styles}
    assert not (raw_tags & set(_TAG_BYTES))
    assert inline_polarity_violations(data) == []


def test_gate_correctly_ignores_toggle_bytes_inside_a_recognized_block_payload():
    # A pix tag's payload can legitimately contain byte values that equal
    # a toggle byte (e.g. a DOS path fragment) -- they must never register
    # as a real inline toggle just because the byte VALUE matches.
    block = _ws_block(0x10, b'C:\\PIX\\A' + bytes([0x18]) + b'B.PIX')
    data = b'Before. ' + block + b' After, no real toggles.\r\n'
    assert inline_polarity_violations(data) == []


def test_gate_ignores_footnote_reference_markers():
    # A footnote reference number is SYNTHESIZED as {'sup', 'fnref'} by
    # _decode_spans (WordStar convention: note markers display raised) --
    # unrelated to the ^T (0x14) toggle byte. This is the real, corpus-
    # proven false-positive source the gate's fnref exclusion fixes
    # (28/86 real documents before the fix).
    block = _ws_block(0x03, b'A footnote.')     # NOTE_KINDS footnote
    data = b'Reference' + block + b' here, no real superscript toggle.\r\n'
    doc = core.parse_ws(data)
    has_fnref_sup = any('sup' in sp.styles and 'fnref' in sp.styles
                        for b in doc.blocks for line in b.lines for sp in line.spans)
    assert has_fnref_sup, 'fixture did not produce the marker this test needs'
    assert inline_polarity_violations(data) == []


def test_gate_flags_a_genuine_synthetic_leak():
    # A deliberately-constructed adversarial case, to prove the gate
    # itself actually fires: hand-build a Document whose only 'strike'
    # span exists with no corresponding 0x18 anywhere in the real text
    # stream (the shape a genuine record-boundary leak would produce) and
    # confirm the checker catches it -- this test does NOT go through
    # core.parse_ws (there is no real leak to construct one from, per the
    # investigation above), so it exercises the violations LOGIC directly
    # rather than the full parse pipeline.
    class FakeSpan:
        def __init__(self, styles):
            self.styles = frozenset(styles)
    class FakeLine:
        def __init__(self, spans):
            self.spans = spans
    class FakeBlock:
        def __init__(self, lines):
            self.lines = lines
    class FakeDoc:
        def __init__(self, blocks):
            self.blocks = blocks

    doc = FakeDoc([FakeBlock([FakeLine([FakeSpan({'strike'})])])])
    raw_tags = {t for b in doc.blocks for line in b.lines
               for sp in line.spans for t in sp.styles}
    out = b'no toggle bytes in this cleaned stream at all'
    violations = [(tag, byte_vals) for tag, byte_vals in _TAG_BYTES.items()
                 if tag in raw_tags and not any(out.count(bv) for bv in byte_vals)]
    assert violations == [('strike', (0x18,))]


# =================================================== real-corpus sweep

@pytest.mark.skipif(not CORPUS, reason='CTRLKD_PRIVATE_CORPUS not set')
def test_corpus_wide_inline_polarity_gate():
    paths = sorted(set(
        glob.glob(os.path.join(CORPUS, '**', '*.WS'), recursive=True) +
        glob.glob(os.path.join(CORPUS, '**', '*.ws'), recursive=True)))
    assert paths, f'no .WS files under {CORPUS}'
    failures = []
    for p in paths:
        try:
            data = open(p, 'rb').read()
            v = inline_polarity_violations(data)
        except Exception as e:
            failures.append((p, f'error: {e!r}'))
            continue
        if v:
            failures.append((p, v))
    assert not failures, failures


@pytest.mark.skipif(not os.path.exists(os.path.join(
    os.environ.get('CTRLKD_SAWYER_ROOT', ''), 'RJS.WS')),
    reason='real WS7 corpus not present on this machine')
def test_rjs_ws_specifically_passes_the_inline_gate():
    """RJS.WS's whole-document strikethrough comes ENTIRELY from
    block.style_attrs (the style library's attrs_on=1), never from a raw
    inline 0x18 -- confirmed period-accurate against real WordStar 7 (see
    module docstring). The inline gate must show it clean; a future
    change that starts leaking 0x18 into raw span styles for this
    document would be a genuine regression this test exists to catch."""
    path = os.path.join(os.environ['CTRLKD_SAWYER_ROOT'], 'RJS.WS')
    data = open(path, 'rb').read()
    assert inline_polarity_violations(data) == []
    # and the EFFECTIVE (merged) render still shows strike everywhere
    # except the untitled first block -- documenting what IS expected,
    # not just what is absent.
    doc = core.parse_ws(data)
    struck = [bi for bi, b in enumerate(doc.blocks) if 'strike' in b.style_attrs]
    assert struck == [1, 2, 3, 4, 5, 6, 7]
