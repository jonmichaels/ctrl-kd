"""Planning #270 item 36, Jon's ruling 2026-09-13: "Print controls aren't
supposed to be visible except in Show Invisibles."

A 0x0F user print control carries a SCREEN display string -- WordStar
shows it in the editor where the control sits (LSRBOX.WS labels its rules
`<<Shaded ...>>`, LJ6DTP has 41 of them) -- and sends the raw printer
payload to the paper instead, the block advancing by its own declared HMI
word. The label is an editor artifact, so NO view and NO export may show
it: Printed, the Native layout JSON, Modern, RTF, HTML, plain text and
Markdown all drop it, and only the app's Show Invisibles draws it, from
the ONE place the layout contract still publishes it
(`invisibles['print_controls']`, format version 9).

One test per emitter, by name, so a regression names the surface that
broke. Synthetic fixtures only, per this repo's convention.
"""
import json
import re
import zlib

from ctrlkd import core, emit, layout, pdf

HARD = b'\x0d\x0a'
LABEL = 'EMPTY 3-dot rule'
DECLARED_HMI = 900          # 5 print columns at 180 HMI units each


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _doc():
    """A WS7 document whose body carries one 0x0F print control with a
    screen label and a real printer payload, declaring a 5-column printed
    width (900 HMI units / 180 per 10-CPI column)."""
    shown = LABEL.encode('cp437')
    ctl = ws7_block(0x0F, DECLARED_HMI.to_bytes(2, 'little') + bytes([len(shown)])
                    + shown + b'\x1b*c2370a0003b0P')
    body = (ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
            + b'Before the control ' + ctl + b' after the control' + HARD
            + b'Plain paragraph of ordinary prose padding for detection.' + HARD)
    return core.parse_ws(body)


def _both_ways(fn):
    return [fn('printed'), fn('modern')]


# ------------------------------------------------------------- the exports
def test_print_control_label_never_appears_in_plain_text():
    for out in _both_ways(lambda m: emit.emit_text(_doc(), mode=m)):
        assert LABEL not in out
        assert 'Before the control' in out


def test_print_control_label_never_appears_in_markdown():
    for out in _both_ways(lambda m: emit.emit_markdown(_doc(), mode=m)):
        assert LABEL not in out
        assert 'Before the control' in out


def test_print_control_label_never_appears_in_html():
    for out in _both_ways(lambda m: emit.emit_html(_doc(), mode=m)):
        assert LABEL not in out
        assert 'Before the control' in out


def test_print_control_label_never_appears_in_rtf():
    for out in _both_ways(lambda m: emit.emit_rtf(_doc(), mode=m)):
        assert LABEL not in out
        assert 'Before the control' in out


def _pdf_text(pdf_bytes):
    """Every content stream of a PDF, decompressed -- the label has to be
    looked for in the DRAWN text, not in the raw (Flate-compressed) file,
    where any assertion would pass for the wrong reason."""
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)endstream', pdf_bytes, re.S):
        try:
            out.append(zlib.decompress(m.group(1)).decode('latin-1'))
        except zlib.error:
            out.append(m.group(1).decode('latin-1'))
    return '\n'.join(out)


def test_print_control_label_never_appears_in_either_pdf():
    for mode in ('printed', 'modern'):
        drawn = _pdf_text(pdf.emit_pdf(_doc(), mode))
        assert LABEL not in drawn
        # the surrounding real words ARE drawn, so the assertion above is
        # about the label and not about an unreadable stream
        assert 'Before' in drawn and 'control' in drawn


# -------------------------------------------------- the Native layout JSON
def test_print_control_label_never_appears_in_the_printed_layout_json():
    """The defect this ruling actually found. Every other surface already
    dropped the label; the printed page-lines in the `layout` JSON -- the
    contract the Native view draws from -- published `segments` verbatim,
    label and all. They now publish the control's declared printed WIDTH
    as spaces, the same swap the printed text/HTML paths and the PDF
    writer have always made."""
    doc = json.loads(layout.emit_layout(_doc(), mode='modern'))
    assert LABEL not in json.dumps(doc['printed'])
    assert LABEL not in json.dumps(doc['modern'])
    # the padded segment is still THERE, still tagged, still the right width
    seg = next(sg
               for page in doc['printed']['pages']
               for line in page['lines']
               for sg in line['segments']
               if any(t.startswith('pctl') for t in sg['styles']))
    assert seg['text'] == ' ' * 5
    assert f'pctl{DECLARED_HMI}' in seg['styles']


def test_show_invisibles_is_the_one_place_the_label_survives():
    """...and it has to survive SOMEWHERE, or the ruling's own exception
    ("only Show Invisibles shows them") has nothing to draw. Format
    version 9 publishes it in the invisibles layer, located on the printed
    page-line segment it belongs to."""
    doc = json.loads(layout.emit_layout(_doc(), mode='modern'))
    assert doc['version'] >= 9
    controls = doc['invisibles']['print_controls']
    assert len(controls) == 1
    c = controls[0]
    assert c['label'] == LABEL
    assert c['hmi'] == DECLARED_HMI
    assert c['columns'] == 5
    seg = doc['printed']['pages'][c['page'] - 1]['lines'][c['line']]['segments'][c['segment']]
    assert any(t.startswith('pctl') for t in seg['styles'])


def test_a_document_with_no_print_control_publishes_an_empty_list():
    """Purely additive: a document with no 0x0F control anywhere emits an
    empty list, not a missing key, and nothing else about its JSON moves."""
    doc = core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
                        + b'Ordinary prose with no print control at all.' + HARD)
    out = json.loads(layout.emit_layout(doc, mode='modern'))
    assert out['invisibles']['print_controls'] == []
