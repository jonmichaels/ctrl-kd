"""A STYLE'S STRIKEOUT RUNS UNTIL A STYLE CLEARS IT (ruling 2026-09-16).

A WS7 paragraph style record carries TWO attribute words: `attrs_on` at byte
91 and `attrs_off` at byte 93. WSFORMAT.TXT states the model exactly:

    Bits set in the first word indicate those attributes are explicitly set
    to the on state.  Bits set in the second word indicate those attributes
    are explicitly set off.  If both corresponding bits are off, then the
    attribute is inherited from the current state.

So a style that turns strikeout on (bit 0x01) starts a run that only ENDS at
a later style whose own `attrs_off` sets the same bit. Both engines used to
reset every attribute at each style switch, which ended the run with the
styled paragraph itself.

Real WS7 settles it. A manuscript in the Sawyer archive selects a heading
style carrying `attrs_on = 0x41` (strikeout | bold) on its title page, and no
other style in that file's library ever sets 0x01 in its `attrs_off` -- not
even the style the manuscript body itself is set in. Its captured LaserJet
print strikes through all 52 pages: WS7 renders strikeout by reprinting a row
of hyphens over the same baseline (a daisy-wheel overstrike the LaserJet
driver kept), and that dash row appears on every page of the capture.

SCOPE, and the question deliberately left open: this is applied to strikeout
ONLY (`core.STICKY_STYLE_ATTRS`). WSFORMAT's inherit sentence is written for
the attribute words as a whole, but in every corpus document that turns bold,
underline or italic on in a style, the next style used sets that same bit in
its own `attrs_off` word -- so an inheriting model and a reset-per-paragraph
model print identical pages and the captures cannot choose between them.
Strikeout is the one bit no corpus style ever clears, which is exactly why
its run is visible. The last test here pins that narrow scope so widening it
is a deliberate act with new evidence behind it, not a drift.

Synthetic fixtures only -- style libraries are built byte by byte below.
"""
import re
import zlib

import pytest

from ctrlkd import core, emit, emit_layout, pdf

HARD = b'\x0d\x0a'

# WSFORMAT's own attribute bits (core.py's `entry['attrs']` decode).
STRIKE, DOUBLE, UNDERLINE, SUB, SUPER, BOLD, ITALIC = (
    0x01, 0x02, 0x08, 0x10, 0x20, 0x40, 0x80)
# The real corpus shape: an `attrs_off` word that clears everything EXCEPT
# strikeout (and the spec's own unlabelled 0x04 bit).
CLEARS_ALL_BUT_STRIKE = 0xFA
CLEARS_EVERYTHING = 0xFB


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def style_record(attrs_on=0, attrs_off=0):
    """A 102-byte style record with every field at its inherit sentinel except
    the two attribute words. Same construction as test_modern_lint.py's own
    `_style_record`, extended with `attrs_off` (bytes 93-94), which is the
    field this behaviour turns on."""
    rec = bytearray(102)
    rec[0:2] = (0xFFFF).to_bytes(2, 'little')          # font word0: inherited
    rec[10:12] = (1800).to_bytes(2, 'little')          # left margin HMI
    rec[12:14] = (0xFFFE).to_bytes(2, 'little')        # right margin: inherited
    rec[14:16] = (0xFFFE).to_bytes(2, 'little')        # para margin: inherited
    rec[18] = rec[19] = 0xFF                           # tab counts: inherited
    for k in range(32):
        rec[20 + 2 * k:22 + 2 * k] = (0xBEEF).to_bytes(2, 'little')
    rec[86] = 0                                        # justification: left
    rec[87] = 1                                        # word wrap on
    rec[88:90] = (0xFFFF).to_bytes(2, 'little')        # line height: inherited
    rec[90] = 0xFF                                     # line spacing: inherited
    rec[91:93] = attrs_on.to_bytes(2, 'little')
    rec[93:95] = attrs_off.to_bytes(2, 'little')
    rec[95] = 0xFF                                     # colour: inherited
    return bytes(rec)


def style_library(entries):
    """`entries` = [(name, record_or_None)]."""
    n = len(entries)
    items, records = b'', b''
    rec_base = 13 + 5 + 33 * n
    for name, rec in entries:
        nm = name.encode('cp437').ljust(24)
        if rec is None:
            items += nm + b'\x00' + bytes(4) + bytes(4)
        else:
            items += nm + b'\x02' + bytes(4) + (rec_base + len(records)).to_bytes(4, 'little')
            records += rec
    head = (b'\x1a\x55' + (1).to_bytes(2, 'little') + b'\x01'
            + n.to_bytes(2, 'little') + (102).to_bytes(2, 'little')
            + (13).to_bytes(4, 'little'))
    return head + bytes([n]) + bytes(4) + items + records


def select(slot):
    """One 0x11 paragraph-style-select block for `slot` of this file's pool."""
    return ws7_block(0x11, (0x0200 | slot).to_bytes(2, 'little')
                     + (0x0201).to_bytes(2, 'little')
                     + (0x0300).to_bytes(2, 'little')
                     + (0x0201).to_bytes(2, 'little'))


def build(entries, body):
    header = ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
    doc_body = header + body
    base = ((len(doc_body) + 127) // 128) * 128
    data = bytearray(doc_body.ljust(base, b'\x1a')) + style_library(entries)
    data[4 + 12:4 + 16] = base.to_bytes(4, 'little')
    return core.parse_ws(bytes(data))


# ------------------------------------------------------------- the fixtures

PLAIN_TEXT = b'Plain paragraph before any styled one at all.'
STRUCK_TEXT = b'The styled heading that turns strikeout on.'
AFTER_TEXT = b'The following paragraph, whose own style never clears it.'
CLEARED_TEXT = b'The paragraph whose style does clear it again.'

LIBRARY = [
    ('Plain', style_record(attrs_on=0, attrs_off=CLEARS_ALL_BUT_STRIKE)),
    ('Struck', style_record(attrs_on=STRIKE | BOLD,
                            attrs_off=CLEARS_ALL_BUT_STRIKE & ~BOLD)),
    ('Clears', style_record(attrs_on=0, attrs_off=CLEARS_EVERYTHING)),
]
SLOT_PLAIN, SLOT_STRUCK, SLOT_CLEARS = 0, 1, 2


def run_doc():
    """Plain -> Struck -> Plain (inherits) -> Clears (ends the run)."""
    return build(LIBRARY,
                 select(SLOT_PLAIN) + PLAIN_TEXT + HARD + HARD +
                 select(SLOT_STRUCK) + STRUCK_TEXT + HARD + HARD +
                 select(SLOT_PLAIN) + AFTER_TEXT + HARD + HARD +
                 select(SLOT_CLEARS) + CLEARED_TEXT + HARD)


def block_for(doc, text):
    wanted = text.decode('cp437')
    for b in doc.blocks:
        joined = ''.join(sp.text for ln in b.lines for sp in ln.spans)
        if wanted[:20] in joined:
            return b
    raise AssertionError(f'no block carrying {wanted[:20]!r}')


def decoded_streams(pdf_bytes):
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', pdf_bytes, re.S):
        try:
            out.append(zlib.decompress(m[1]))
        except zlib.error:
            out.append(m[1])
    return b'\n'.join(out)


# --------------------------------------------------------------- the model

def test_the_run_starts_continues_and_ends_on_the_blocks_themselves():
    doc = run_doc()
    assert 'strike' not in block_for(doc, PLAIN_TEXT).style_attrs, \
        'strikeout before the style that turns it on'
    assert 'strike' in block_for(doc, STRUCK_TEXT).style_attrs, \
        'the style that turns strikeout on did not'
    assert 'strike' in block_for(doc, AFTER_TEXT).style_attrs, \
        'the run stopped at the styled paragraph instead of continuing'
    assert 'strike' not in block_for(doc, CLEARED_TEXT).style_attrs, \
        'a style setting 0x01 in attrs_off did not end the run'


def test_an_unresolvable_style_handle_inherits_rather_than_resets():
    """A 0x03xx editing-temp handle declares neither attribute word, so every
    attribute inherits -- the same sentence of the spec, applied to the case
    where there is no record to read."""
    body = (select(SLOT_STRUCK) + STRUCK_TEXT + HARD + HARD +
            ws7_block(0x11, (0x0301).to_bytes(2, 'little') * 4) +
            AFTER_TEXT + HARD)
    doc = build(LIBRARY, body)
    assert 'strike' in block_for(doc, AFTER_TEXT).style_attrs


# ------------------------------------------- one rule, every output format

def fmt_outputs(doc, mode):
    return {
        'text': emit.emit_text(doc, mode),
        'markdown': emit.emit_markdown(doc, mode),
        'html': emit.emit_html(doc, mode),
        'rtf': emit.emit_rtf(doc, mode),
        'layout': emit_layout(doc, mode),
    }


def rtf_group_for(body, needle):
    """The `{...}` character-run group that carries `needle` -- RTF's own
    scope for a run's attributes, so the assertion reads exactly one run."""
    end = body.index(needle)
    start = body.rindex('{', 0, end)
    return body[start:body.index('}', end) + 1]


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_rtf_marks_the_inherited_paragraph_struck(mode):
    out = fmt_outputs(run_doc(), mode)['rtf']
    body = out.decode('cp1252', 'replace') if isinstance(out, bytes) else out
    assert '\\strike' in rtf_group_for(body, 'never clears'), \
        f'{mode}: the inherited paragraph carries no \\strike'
    assert '\\strike' not in rtf_group_for(body, 'does clear it again'), \
        f'{mode}: the run did not end at the clearing style'


def html_tag_for(body, needle):
    """The opening tag of the element carrying `needle`."""
    end = body.index(needle)
    start = body.rindex('<', 0, end)
    return body[start:body.index('>', start) + 1]


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_html_marks_the_inherited_paragraph_struck(mode):
    out = fmt_outputs(run_doc(), mode)['html']
    body = out.decode('utf-8') if isinstance(out, bytes) else out
    # HTML's paragraph attributes ride a CSS class keyed to the STYLE SLOT, so
    # an attribute inherited from an EARLIER style needs its own class
    # (`emit._INHERITED_ATTR_CSS`) -- the slot's own rule cannot carry it.
    assert '.ws-inherit-strike { text-decoration:line-through }' in body, \
        f'{mode}: no CSS rule for the inherited run'
    assert 'ws-inherit-strike' in html_tag_for(body, 'never clears'), \
        f'{mode}: the inherited paragraph is not marked struck'
    assert 'ws-inherit-strike' not in html_tag_for(body, 'does clear it again'), \
        f'{mode}: the run did not end at the clearing style'


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_layout_json_carries_the_inherited_run(mode):
    out = fmt_outputs(run_doc(), mode)['layout']
    body = out.decode('utf-8') if isinstance(out, bytes) else out
    assert body.count('"strike"') >= 2, \
        f'{mode}: fewer struck runs than the styled paragraph plus the one it runs into'


def test_markdown_modern_marks_the_inherited_paragraph_struck():
    """Modern Markdown carries character attributes; PRINTED Markdown is a
    verbatim monospace page inside a fence and has no inline markers at all,
    in either behaviour -- there is nothing for this rule to change there."""
    out = fmt_outputs(run_doc(), 'modern')['markdown']
    body = out.decode('utf-8') if isinstance(out, bytes) else out
    line = next(l for l in body.splitlines() if 'never clears' in l)
    assert line.strip().startswith('~~'), f'no strikethrough markers: {line!r}'


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_pdf_draws_a_rule_over_the_inherited_paragraph(mode):
    """Strikeout in PDF is a stroked rule over the run (`pdf.py`'s own
    `... m ... l S`). More rules are drawn when the run continues than when
    the very next style ends it."""
    running = decoded_streams(pdf.emit_pdf(run_doc(), mode=mode))
    ended = build(LIBRARY,
                  select(SLOT_STRUCK) + STRUCK_TEXT + HARD + HARD +
                  select(SLOT_CLEARS) + AFTER_TEXT + HARD)
    ended_ops = decoded_streams(pdf.emit_pdf(ended, mode=mode))
    assert running.count(b' l S') > ended_ops.count(b' l S'), \
        f'{mode}: the continuing run drew no more rules than the cleared one'


def test_text_output_is_unaffected_and_still_carries_the_words():
    """Plain text has no representation for strikeout in either behaviour --
    named here so the format is not silently missing from the list above."""
    out = fmt_outputs(run_doc(), 'printed')['text']
    body = out.decode('utf-8') if isinstance(out, bytes) else out
    for sample in (PLAIN_TEXT, STRUCK_TEXT, AFTER_TEXT, CLEARED_TEXT):
        assert sample.decode('cp437')[:20] in body


# ------------------------------------------------------------ the scope pin

def test_only_strikeout_is_sticky():
    """The narrow scope, pinned. Bold here is turned on by one style and never
    cleared by the next one's `attrs_off`, and it still must NOT carry: no WS7
    capture in the corpus can show whether real WordStar would carry it, so
    the rule is not extended to bold, underline or italic on a guess. Widening
    `core.STICKY_STYLE_ATTRS` means finding a capture that settles it."""
    assert core.STICKY_STYLE_ATTRS == ((0x01, 'strike'),)
    library = [
        ('Bold', style_record(attrs_on=BOLD, attrs_off=0)),
        ('Next', style_record(attrs_on=0, attrs_off=0)),
    ]
    doc = build(library,
                select(0) + STRUCK_TEXT + HARD + HARD +
                select(1) + AFTER_TEXT + HARD)
    assert 'b' in block_for(doc, STRUCK_TEXT).style_attrs
    assert 'b' not in block_for(doc, AFTER_TEXT).style_attrs, \
        'bold carried past its own paragraph -- the scope was widened silently'
