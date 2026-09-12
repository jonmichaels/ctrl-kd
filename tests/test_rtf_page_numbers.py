"""planning #264 item 3 (packet rows A1+A2): page numbers in RTF.

THE DEFECT. A document that declares no header or footer still gets a
centred page number at the foot of every PDF page -- that is what real
WordStar 7 does under a stock install (ws7-prints/v3, the PRISTINE.EXE
recapture). The RTF had no page number anywhere, in either mode, and
`--page-numbers` -- accepted by the command line since 2026-08-25 -- was
swallowed by `emit_rtf`'s own `**_options` and did nothing at all.
`.pn` ("start numbering at 7") was ignored too, so every such document
started at 1.

THE FIX. `emit_rtf` takes `page_numbers` as a named parameter; a document
whose footer is not in use gets a `\\footer` group carrying `\\chpgn` (the
reader's own current-page field), centred -- WordStar's stock position and
what the PDF draws for a document that never sets `.pc`. `.pn`'s start
value becomes `\\pgnstart`.

THE RULE IS THE PDF'S, not a second one: `pdf._pgnum_checkpoints` (seeded
ON -- stock WS7's factory default, reversed 2026-09-07 against the
PRISTINE.EXE capture) decides `auto`, and a DECLARED footer pre-empts the
automatic number (WSFORMAT.WS: "active only when the footers are not in
use"). Declared, not drawn: LJ6DTP.WS's own `.f1` is two 0x0F bytes and
renders nothing visible, and its automatic number still stays off --
exactly what `pdf._close_page` records.

SCOPE. RTF has one section and one footer, so the state is resolved once,
at the document's first block: a document that turns numbering off
half-way through, or re-anchors `.pn` mid-file, needs the section spine
(packet section 3), which is deliberately not built here.
"""
import pytest

from ctrlkd import core, emit

FOOTER_NUM = r'{\footer \pard\plain \qc\f0\fs22 {\chpgn }\par}'


def _doc(dots=(), pn_start=1, footers=None):
    """A one-paragraph document. `dots` are raw dot-command lines recorded as
    (block index, line index, command) triples,
    the way core records them for `pdf._pgnum_checkpoints` to read."""
    doc = core.Document(
        blocks=[core.Block('para', lines=[core.Line(spans=[core.Span('body')])])],
        meta={'variant': 'ws5+', 'page': {'pn_start': pn_start},
              'dot_positions': [(0, 0, d) for d in dots]})
    for lno, txt in (footers or {}).items():
        doc.footers[lno] = txt
        doc.hf_events.append(('F', lno, txt, 0))
    return doc


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_silent_document_gets_a_centred_page_number(mode):
    """Stock WordStar 7 numbers a document that says nothing at all."""
    assert FOOTER_NUM in emit.emit_rtf(_doc(), mode=mode)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_op_turns_the_number_off(mode):
    assert FOOTER_NUM not in emit.emit_rtf(_doc(['.op']), mode=mode)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_pg_turns_it_back_on(mode):
    assert FOOTER_NUM in emit.emit_rtf(_doc(['.op', '.pg']), mode=mode)


def test_the_flag_reaches_the_emitter_at_all():
    """The named defect: `--page-numbers` used to land in `**_options`."""
    assert FOOTER_NUM not in emit.emit_rtf(_doc(), page_numbers='off')
    assert FOOTER_NUM in emit.emit_rtf(_doc(['.op']), page_numbers='on')


def test_headers_off_suppresses_the_number_too():
    """`--headers`' own documented scope is "headers, footers, and page
    numbers in the paged surfaces"."""
    assert FOOTER_NUM not in emit.emit_rtf(_doc(), headers=False,
                                           page_numbers='on')


def test_a_declared_footer_pre_empts_the_automatic_number():
    out = emit.emit_rtf(_doc(footers={1: 'Chapter One'}))
    assert FOOTER_NUM not in out
    assert r'{\footer ' in out                       # the real footer is there


def test_a_footer_that_renders_nothing_still_pre_empts_it():
    """LJ6DTP.WS's own `.f1` is two 0x0F bytes: declared, invisible, and
    enough to keep WordStar's automatic number off."""
    out = emit.emit_rtf(_doc(footers={1: '\x0f\x0f'}))
    assert FOOTER_NUM not in out
    assert r'{\footer ' not in out                   # nothing visible to draw


# ------------------------------------------------------------- `.pn` (A2)

@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_pn_start_value_reaches_pgnstart(mode):
    assert r'\pgnstart7' in emit.emit_rtf(_doc(pn_start=7), mode=mode)


def test_a_document_that_never_set_pn_writes_no_pgnstart():
    assert r'\pgnstart' not in emit.emit_rtf(_doc())


# ---------------------------------------------------- the real corpus (tier 2)

@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_strength_gets_the_number_it_prints(require_sawyer_doc, mode):
    """sawyer/STRENGTH.WS declares no header and no footer -- the packet's
    own A1 example."""
    with open(require_sawyer_doc('STRENGTH.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert FOOTER_NUM in emit.emit_rtf(doc, mode=mode)


@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_lj6dtp_keeps_its_own_empty_footer_rule(require_sawyer_doc, mode):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert FOOTER_NUM not in emit.emit_rtf(doc, mode=mode)


@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_real_pn_document_starts_where_it_says(require_sawyer_doc, mode):
    """sawyer/MACROS/HOLYMAC/4MAC1 opens `.pn 22`."""
    with open(require_sawyer_doc('MACROS/HOLYMAC/4MAC1'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert (doc.meta.get('page') or {}).get('pn_start') == 22
    assert r'\pgnstart22' in emit.emit_rtf(doc, mode=mode)
