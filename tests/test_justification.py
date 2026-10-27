"""Planning #238: `.oj on` full justification in Printed mode.

Root cause (2026-09-08 placement-triage, cause 3): Printed mode had ZERO
handling of `align='justify'` -- `grep -n justification src/ctrlkd/pdf.py`
found one unrelated comment. Rule and captured evidence: the maintainer's
own private research notes -- PRIVATE corpus paths/findings stay out of
this public repo, only the RULE and synthetic fixtures do.

Measured against real WS7 (sawyer/LSRBOX/LSRBOX.WS, sawyer/REF/CTRL-K.H1,
both `ws7-prints/v4`, private corpus):

  1. Every line of a `.oj on` (align='justify') paragraph EXCEPT ITS OWN
     LAST physical line is stretched so its last character lands exactly
     on the block's resolved right margin (`.rm`, in print columns,
     measured from the same `.po` origin as the left edge). The last
     line of the paragraph is left ragged -- confirmed directly (LSRBOX's
     own final line sits short of the margin in the real capture).
  2. The slack is shared the way WS7's own driver does it (WS7 report
     11.7.3, `wordstar-dos/11-print-engine.md`): in dots (1/300 in), every
     run of blanks between the first word and the last takes
     `floor(w * S_rem / W_rem)` of the slack still left, w being that run's
     own width -- so a double blank takes twice a single one's share, the
     remainders fall to the later runs, and a word lands at
     `floor(x_dots * 720 / 300)` decipoints. Leading blanks and the blanks
     before the soft return are not a gap. The six rows measured on earlier
     WS7 captures are reproduced exactly (`test_the_measured_gap_rows`).
  3. The rule runs over the whole line, whatever its spans: a styled word
     mid-sentence, or a proportional face, is spread with each item's own
     width (report 14.15, runs mixj1-mixj4).
  4. WS5+ soft spaces (bare 0xA0) are ignored: the driver spreads the line
     itself (report 14.6).
  5. Modern mode is untouched -- Modern already expresses `align='justify'`
     as a CSS/RTF property rather than literal padding (`test_justify_
     `is_not_faked_with_padding_in_plain_text` in test_ctrlkd.py); no
     reference evidence says Modern should ALSO carry literal justified
     spacing, so nothing there changed (report, don't decide).

Fixed-pitch WS4-shaped fontless documents throughout (no font block --
`_span_pitch` falls back to `pt * 0.6` = 7.2pt/char at the 12pt default,
the same 10-CPI grid the real captures print on), so every width below is
exact arithmetic, not a font-metric approximation.
"""
import re
import zlib

from ctrlkd import core, pdf

HARD = b'\r\n'
SOFT = b'\x8d\n'


def _decoded_streams(pdf_bytes):
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', pdf_bytes, re.S):
        body = m[1]
        try:
            out.append(zlib.decompress(body))
        except zlib.error:
            out.append(body)
    return out


def _word_x(pdf_bytes, word):
    """The Td x immediately preceding `(word) Tj` in ANY decoded content
    stream, or None if the word never appears as its own Tj operand."""
    needle = word.encode()
    pat = re.compile(rb'([\d.]+) [\d.]+ Td \(' + re.escape(needle) + rb'\) Tj')
    for stream in _decoded_streams(pdf_bytes):
        m = pat.search(stream)
        if m:
            return float(m[1])
    return None


def _doc(src, meta_variant='ws4'):
    doc = core.parse_ws(src)
    doc.meta['variant'] = meta_variant
    return doc


def test_justified_line_reaches_the_resolved_right_margin():
    """`.po 0"` / `.lm 0` / `.rm 20` (144pt) -- "AA BB CC" is 8 chars (57.6pt)
    natural, 2 single-blank gaps, needing 86.4pt of slack split evenly
    (43.2pt/gap, `base` below): AA@0, BB@AA(14.4)+gap(7.2+43.2)=64.8,
    CC@BB_end(64.8+14.4)+gap(7.2+43.2)=129.6, ending at 129.6+14.4=144.0 --
    the one confirmed-solid part of the rule (every justified line in the
    corpus lands its last character exactly on the margin); the per-gap
    SPLIT that gets it there is this pass's own documented approximation
    (see this module's docstring, rule 2), not a WS7 byte-for-byte match."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD)
    b = doc.blocks[0]
    assert b.align == 'justify'
    assert len(b.lines) == 2
    out = pdf.emit_pdf(doc, mode='printed')
    x_aa = _word_x(out, 'AA')
    x_bb = _word_x(out, 'BB')
    x_cc = _word_x(out, 'CC')
    assert x_aa == 0.0
    base = (144.0 - 8 * 7.2) / 2       # 43.2pt of slack per elastic gap
    x_bb_expected = 2 * 7.2 + (7.2 + base)
    x_cc_expected = x_bb_expected + 2 * 7.2 + (7.2 + base)
    assert x_bb == round(x_bb_expected, 1)
    assert x_cc == round(x_cc_expected, 1)
    # The confirmed-solid part of the rule: CC's own right edge lands
    # exactly on the margin, not just "somewhere further right".
    assert x_cc + 2 * 7.2 == 144.0


def test_last_line_of_justified_paragraph_is_not_stretched():
    """WS7 never justifies a paragraph's own trailing line (measured
    directly against LSRBOX.WS's real capture) -- "DD." here is the
    second (last) physical line of the SAME block and must render at its
    natural, un-stretched position."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    assert _word_x(out, 'DD.') == 0.0


def test_a_double_blank_takes_twice_a_single_blanks_share():
    """`AA BB  CC` at `.rm 20`: 330 dots of slack over a 30-dot and a 60-dot
    run of blanks -- floor(30*330/90) = 110 dots, then the rest (220) to the
    double blank. WS7 report 11.7.3 (a typed double blank DOES stretch)."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB  CC' + SOFT + b'DD.' + HARD)
    b = doc.blocks[0]
    assert b.lines[0].text() == 'AA BB  CC'
    out = pdf.emit_pdf(doc, mode='printed')
    # AA ends at 60 dots; BB starts 30 + 110 dots later, CC 60 + 220 after BB ends
    assert _word_x(out, 'AA') == 0.0
    assert _word_x(out, 'BB') == (60 + 30 + 110) * 12 // 5 / 10
    assert _word_x(out, 'CC') == (200 + 60 + 60 + 220) * 12 // 5 / 10
    assert _word_x(out, 'CC') + 2 * 7.2 == 144.0


def test_the_blank_before_the_soft_return_is_not_a_gap():
    """WS7 report 11.7.3: trailing blanks are not items. `AA BB CC ` + soft
    return gives the same line as without the trailing blank."""
    plain = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
                b'AA BB CC' + SOFT + b'DD.' + HARD)
    trailing = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
                   b'AA BB CC ' + SOFT + b'DD.' + HARD)
    a = pdf._doc_to_pagelines(plain, True)[0][0].justify_word_x
    b = pdf._doc_to_pagelines(trailing, True)[0][0].justify_word_x
    assert [p[:2] for p in a] == [p[:2] for p in b[:5]]
    assert b[5][0] == ' '                      # the blank is still a piece
    assert b[4][1] + b[4][2] == 144.0         # and CC still ends on the margin


def test_leading_blanks_are_not_a_gap():
    """A paragraph's indent is not stretched (report 11.7.3): AA, BB, CC share
    the slack in their two gaps only."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'  AA BB CC' + SOFT + b'DD.' + HARD)
    pieces = pdf._doc_to_pagelines(doc, True)[0][0].justify_word_x
    assert pieces[0][:2] == ('  ', 0.0)
    assert pieces[1][1] == 14.4                      # AA right after the indent
    assert round(pieces[-1][1] + pieces[-1][2], 1) == 144.0


def test_the_measured_gap_rows():
    """The six rows measured on earlier WS7 captures (report 11.7.3): per-gap
    stretch in decipoints for a slack of N/1800 in over G single gaps."""
    measured = [
        (180, 8, [7, 7, 10, 9, 10, 9, 10, 10]),
        (180, 9, [7, 7, 7, 7, 8, 7, 9, 10, 10]),
        (125, 5, [9, 10, 9, 10, 12]),
        (225, 5, [16, 17, 19, 20, 19]),
        (225, 8, [9, 10, 12, 12, 12, 12, 12, 12]),
        (225, 9, [9, 10, 9, 10, 10, 9, 10, 12, 12]),
    ]
    for slack, gaps, want in measured:
        kinds, widths = [], []
        for i in range(gaps + 1):
            kinds.append('w')
            widths.append(21.6)
            if i < gaps:
                kinds.append('s')
                widths.append(7.2)
        right = sum(widths) + slack / 25
        xs = pdf._justify_x_printed(kinds, widths, 0.0, right)[0::2]
        natural = [i * 120 * 12 // 5 for i in range(gaps + 1)]
        extra = [x - n for x, n in zip(xs, natural)]
        assert [b - a for a, b in zip(extra, extra[1:])] == want


def test_blanks_share_by_their_own_width():
    """A narrow blank gets a proportionally smaller share (report 14.15,
    run mixj4): widths 30 and 15 dots, 45 dots of slack -> 30 and 15."""
    xs = pdf._justify_x_printed(['w', 's', 'w', 's', 'w'],
                                [24.0, 7.2, 24.0, 3.6, 24.0], 0.0,
                                24 * 3 + 7.2 + 3.6 + 45 * 0.24)
    # word 0 is 100 dots wide, then the 30-dot blank takes its 30, the
    # 15-dot blank its 15 (S_rem and W_rem both fall to 15 by then)
    assert xs == [0, 240, 384, 624, 696]


def test_a_line_that_is_slightly_too_long_is_squeezed():
    """Negative slack (report 11.7.3): the same loop with the sign reversed,
    the amount capped at half the total width of the blanks. Two 100pt words
    and a 7.2pt blank (30 dots) end 60/1800 in (10 dots) past the margin: the
    blank gives up 10 dots, the second word moves 10 dots left."""
    xs = pdf._justify_x_printed(['w', 's', 'w'], [100.0, 7.2, 100.0], 0.0,
                                204.96)
    assert xs == [0, 417 * 12 // 5, (417 + 30 - 10) * 12 // 5]


def test_a_line_too_long_to_squeeze_is_left_alone():
    """Past the cap WS7's own wrap could not have produced the line: the
    margin is not this line's, so it keeps its natural widths."""
    assert pdf._justify_x_printed(['w', 's', 'w'], [100.0, 7.2, 100.0], 0.0,
                                  150.0) is None


def test_soft_spaces_are_ignored_by_the_driver():
    """WS5+ soft spaces (0xA0 after a typed blank, report 11.7.3/14.6) are
    not part of the gap: `AA`, one typed blank + three soft ones, `BB`."""
    data = (b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
            b'AA \xa0\xa0\xa0BB CC \x8d\nDD.\r\n')
    doc = core.parse(data, variant='ws5+')
    pieces = pdf._doc_to_pagelines(doc, True)[0][0].justify_word_x
    assert [p[0] for p in pieces] == ['AA', '    ', 'BB', ' ', 'CC', ' ']
    # two equal one-blank gaps: 144 - 8*7.2 = 86.4pt = 360 dots -> 180 each
    assert pieces[2][1] == (60 + 30 + 180) * 12 // 5 / 10
    assert round(pieces[4][1] + pieces[4][2], 1) == 144.0


def test_a_hard_return_line_in_a_justified_block_stays_ragged_in_ws5():
    """Report 11.7.1: only a line that ends in a soft return is spread. In a
    WS5+ block, a hard-returned line that is not the block's last is ragged."""
    data = (b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
            b'AA BB CC\r\nDD EE FF\x8d\nGG.\r\n')
    doc = core.parse(data, variant='ws5+')
    lines = pdf._doc_to_pagelines(doc, True)[0]
    assert [getattr(l, 'justify_word_x', None) is not None
            for l in lines if hasattr(l, 'justify_right_x')][:2] == [False, True]


def test_oj_off_is_unaffected():
    """The default (no `.oj on` anywhere) must render byte-identically to
    before this feature existed: one whole-line Tj (`justify_eligible`
    never fires, so the line is never split into per-word pieces), the
    line's own single, exact, un-stretched text."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD)
    assert doc.blocks[0].align == 'left'
    out = pdf.emit_pdf(doc, mode='printed')
    assert _word_x(out, 'AA BB CC') == 0.0
    assert _word_x(out, 'BB') is None     # never its OWN Tj -- not split


def test_oj_on_then_off_mid_document_only_justifies_the_on_block():
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD +
              b'.oj off\r\nEE FF GG' + SOFT + b'HH.' + HARD)
    assert [b.align for b in doc.blocks] == ['justify', 'left']
    out = pdf.emit_pdf(doc, mode='printed')
    x_bb = _word_x(out, 'BB')                 # justified block -- split, stretched
    assert x_bb is not None and x_bb > 2 * 7.2 + 7.2
    assert _word_x(out, 'EE FF GG') == 0.0     # .oj off block -- one whole-line Tj
    assert _word_x(out, 'FF') is None          # never split into pieces


def test_styled_mixed_line_is_justified_across_its_spans():
    """A line with a bold word mid-sentence resolves to several spans; the
    slack is shared over the whole line anyway (report 14.15): `AA BB CC`
    at `.rm 40` -- two equal gaps of 480 dots (115.2pt) each."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 40\r\n.oj on\r\n'
              b'AA \x02BB\x02 CC' + SOFT + b'DD.' + HARD)
    b = doc.blocks[0]
    assert b.align == 'justify'
    assert len(b.lines[0].spans) > 1
    out = pdf.emit_pdf(doc, mode='printed')
    assert _word_x(out, 'BB') == 136.8
    assert _word_x(out, 'CC') == 273.6


def test_justify_word_x_lands_on_the_pageline_model():
    """planning #251(b): the per-word/gap Bresenham split is no longer a
    writer-only decision -- `_doc_to_pagelines` (and therefore `layout`
    JSON) now carries it too, `PageLine.justify_word_x = [(piece, x_pt,
    width_pt), ...]`, the exact values `_line_ops_printed` draws from.
    Same fixture and arithmetic as
    `test_justified_line_reaches_the_resolved_right_margin` above, checked
    one level lower: on the model, not the content stream."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD)
    pieces = pdf._doc_to_pagelines(doc, True)[0][0].justify_word_x
    assert pieces is not None
    texts = [p[0] for p in pieces]
    assert texts == ['AA', ' ', 'BB', ' ', 'CC']
    base = (144.0 - 8 * 7.2) / 2
    (t_aa, x_aa, w_aa), (t_g1, x_g1, w_g1), (t_bb, x_bb, w_bb), \
        (t_g2, x_g2, w_g2), (t_cc, x_cc, w_cc) = pieces
    assert x_aa == 0.0 and round(w_aa, 1) == 2 * 7.2
    assert round(x_bb, 1) == round(2 * 7.2 + (7.2 + base), 1)
    assert round(x_cc, 1) == round(x_bb + w_bb + (7.2 + base), 1)
    assert round(x_cc + w_cc, 1) == 144.0    # lands exactly on the margin

    # The last (unjustified) line of the SAME block carries no opinion --
    # `.oj on` never stretches a paragraph's own trailing line (rule 1),
    # so `_attach_justify_word_x_printed` never even attempts one: its own
    # `justify_right_x` is already None (`_doc_to_pagelines`'s own gate).
    dd_line = pdf._doc_to_pagelines(doc, True)[0][1]
    assert dd_line.justify_right_x is None
    assert dd_line.justify_word_x is None

    # The same answer, one level up, through the public `layout` JSON.
    from ctrlkd import layout as _layout
    import json
    out = json.loads(_layout.emit_layout(doc))
    assert out['version'] == 13
    jline = out['printed']['pages'][0]['lines'][0]
    assert [p['text'] for p in jline['justify_word_x']] == ['AA', ' ', 'BB', ' ', 'CC']
    assert jline['justify_word_x'][2]['x'] == round(x_bb, 1)
    assert 'justify_word_x' not in out['printed']['pages'][0]['lines'][1]


def test_justify_word_x_tiles_a_styled_mixed_line():
    """planning #251(b): the model's pieces cover the whole line across its
    spans -- their texts concatenate to the line's text, so a consumer can
    map them onto its own spans by offset."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 40\r\n.oj on\r\n'
              b'AA \x02BB\x02 CC' + SOFT + b'DD.' + HARD)
    line = pdf._doc_to_pagelines(doc, True)[0][0]
    assert line.justify_right_x is not None
    assert ''.join(p[0] for p in line.justify_word_x) == 'AA BB CC'
    assert [p[1] for p in line.justify_word_x if p[0].strip()] == [0.0, 136.8, 273.6]


def test_a_tab_span_leaves_the_line_unspread():
    """A tab record resets the justified region (report 11.7.3); until that
    is modelled a line with one is drawn at its natural widths."""
    segs = [('AA', frozenset(), 'Courier', 12.0, None, False),
            ('  ', frozenset({'tabhmi900', 'tableader32'}), 'Courier', 12.0,
             None, False),
            ('BB CC', frozenset(), 'Courier', 12.0, None, False)]
    assert pdf._justify_line_printed(segs, 0.0, 144.0, None, False,
                                     frozenset()) is None


# ------------------ notes-paginator scope gap (planning #238, cause 1) ------

def _ws7_footnote_block(text):
    """A minimal WS7 footnote block (type 0x03) -- same shape as
    test_pictures.py's own helper of the same name, duplicated here rather
    than imported (this module has no other cross-file test dependency and
    the shape is tiny): line count 1, number 0, conversion flag 0x30
    (number_format=3, convert_to=0)."""
    content = ((1).to_bytes(2, 'little') + (0).to_bytes(2, 'little') +
              bytes([0x30]) + text)
    jump = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + jump + bytes([0x03]) + content + jump + b'\x1d'


def test_justification_still_applies_when_the_document_has_a_real_footnote():
    """Planning #238 scope gap: a document carrying a REAL footnote/
    endnote/annotation anywhere routes its ENTIRE Printed body through
    `_paginate_printed_notes` -> `_body_stream_printed`
    (`_has_placeable_notes`, gating `_doc_to_pagelines`) instead of that
    function's own plain per-block loop -- a SEPARATE PageLine-building
    walk that, before this fix, never set `justify_right_x` at all, so
    `.oj on` silently stopped stretching ANY line in such a document, not
    just a line that itself carries the footnote reference. Two-line `.oj
    on` block here carries no note reference of its own; the real
    footnote sits in a second, unrelated paragraph purely to route the
    whole document through the notes paginator and prove the FIRST
    paragraph is still justified once it does."""
    doc = _doc(b'.po 0"\r\n.lm 0\r\n.rm 20\r\n.oj on\r\n'
              b'AA BB CC' + SOFT + b'DD.' + HARD +
              b'\r\nElsewhere.' + _ws7_footnote_block(b'A note.') + HARD)
    assert doc.notes and doc.notes[0].kind == 'footnote'
    from ctrlkd import pdf as pdfmod
    assert pdfmod._has_placeable_notes(doc), \
        'fixture must route through _paginate_printed_notes'
    b = doc.blocks[0]
    assert b.align == 'justify'
    out = pdf.emit_pdf(doc, mode='printed')
    x_aa = _word_x(out, 'AA')
    x_bb = _word_x(out, 'BB')
    x_cc = _word_x(out, 'CC')
    assert x_aa == 0.0
    base = (144.0 - 8 * 7.2) / 2       # same arithmetic as the plain-path
                                        # test above -- identical rule, only
                                        # the pagination path differs
    x_bb_expected = 2 * 7.2 + (7.2 + base)
    x_cc_expected = x_bb_expected + 2 * 7.2 + (7.2 + base)
    assert x_bb == round(x_bb_expected, 1)
    assert x_cc == round(x_cc_expected, 1)
    assert x_cc + 2 * 7.2 == 144.0
    # The paragraph's own last line stays ragged here too (rule 1) --
    # unaffected by which pagination path built it.
    assert _word_x(out, 'DD.') == 0.0
