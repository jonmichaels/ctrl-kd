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

def FOOTER_NUM(mode='printed'):
    """WordStar's automatic number as this mode writes it.

    E10/E10b (Jon 2026-09-17): page furniture takes the body's own face and
    size -- Printed `\\f1` Courier New, Modern `\\f0` (the MODERN_BODY
    face), both at `\\fs24` (Printed's body size; Modern's body less 2pt).
    It was a hardcoded `\\f0\\fs22` in both modes, i.e. Times New Roman 11
    on a Courier page."""
    face = r'\f1' if mode == 'printed' else r'\f0'
    return r'{\footer \pard\plain \qc%s\fs24 {\chpgn }\par}' % face


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
    assert FOOTER_NUM(mode) in emit.emit_rtf(_doc(), mode=mode)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_op_turns_the_number_off(mode):
    assert FOOTER_NUM(mode) not in emit.emit_rtf(_doc(['.op']), mode=mode)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_pg_turns_it_back_on(mode):
    assert FOOTER_NUM(mode) in emit.emit_rtf(_doc(['.op', '.pg']), mode=mode)


def test_the_flag_reaches_the_emitter_at_all():
    """The named defect: `--page-numbers` used to land in `**_options`."""
    assert FOOTER_NUM() not in emit.emit_rtf(_doc(), page_numbers='off')
    assert FOOTER_NUM() in emit.emit_rtf(_doc(['.op']), page_numbers='on')


# ------------------------------------------- the two flags (#264 R7, 2026-09-14)
#
# Jon, ruling on the review round: "Page numbers and headers can be
# different. A header or footer that contains a page number is controlled
# by header flag but a page number on its own is controlled by the page
# number flag. RTF should work the same way."
#
# So `--headers` reaches the running heads and feet -- a `#` the author
# typed inside one goes with its head, because it IS that head's text --
# and `--page-numbers` reaches WordStar's own automatic number and nothing
# else. The first RTF batch had `--headers off` swallow the automatic
# number too; that is what these four rows revert.

@pytest.mark.parametrize('mode', ['printed', 'modern'])
@pytest.mark.parametrize('headers,page_numbers,expected', [
    (True,  'on',  True),
    (True,  'off', False),
    (False, 'on',  True),
    (False, 'off', False),
])
def test_the_four_flag_combinations(mode, headers, page_numbers, expected):
    """The automatic number answers to `--page-numbers` ALONE, in both
    RTF modes, whichever way `--headers` is set."""
    out = emit.emit_rtf(_doc(['.op']), mode=mode, headers=headers,
                        page_numbers=page_numbers)
    assert (FOOTER_NUM(mode) in out) is expected


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_auto_is_the_documents_own_state_under_either_headers_flag(mode):
    """`auto` reads `.pn`/`.pg`/`.op`, and `--headers` does not enter into
    it -- the same answer with heads drawn and with heads suppressed."""
    for headers in (True, False):
        assert FOOTER_NUM(mode) in emit.emit_rtf(_doc(), mode=mode, headers=headers)
        assert FOOTER_NUM(mode) not in emit.emit_rtf(_doc(['.op']), mode=mode,
                                               headers=headers)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_hash_inside_a_head_goes_with_its_head(mode):
    """The other half of the ruling: a `#` the author typed into a real
    `.fo` is that footer's own text, so `--headers off` takes it away --
    and it was never the automatic number, so `--page-numbers` does not
    reach it."""
    doc = _doc(footers={1: 'Page #'})
    on = emit.emit_rtf(doc, mode=mode, headers=True, page_numbers='off')
    assert r'{\chpgn }' in on and 'Page' in on
    off = emit.emit_rtf(doc, mode=mode, headers=False, page_numbers='on')
    assert r'\chpgn' not in off and 'Page' not in off


def test_a_declared_footer_pre_empts_the_automatic_number():
    out = emit.emit_rtf(_doc(footers={1: 'Chapter One'}))
    assert FOOTER_NUM() not in out
    assert r'{\footer ' in out                       # the real footer is there


def test_a_footer_that_renders_nothing_still_pre_empts_it():
    """LJ6DTP.WS's own `.f1` is two 0x0F bytes: declared, invisible, and
    enough to keep WordStar's automatic number off."""
    out = emit.emit_rtf(_doc(footers={1: '\x0f\x0f'}))
    assert FOOTER_NUM() not in out
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
    assert FOOTER_NUM(mode) in emit.emit_rtf(doc, mode=mode)


@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_lj6dtp_keeps_its_own_empty_footer_rule(require_sawyer_doc, mode):
    with open(require_sawyer_doc('LJ6DTP.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert FOOTER_NUM(mode) not in emit.emit_rtf(doc, mode=mode)


@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_real_pn_document_starts_where_it_says(require_sawyer_doc, mode):
    """sawyer/MACROS/HOLYMAC/4MAC1 opens `.pn 22`."""
    with open(require_sawyer_doc('MACROS/HOLYMAC/4MAC1'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert (doc.meta.get('page') or {}).get('pn_start') == 22
    assert r'\pgnstart22' in emit.emit_rtf(doc, mode=mode)


def test_pn_zero_really_starts_at_zero():
    """`.pn 0` is a real command (the archive's macro chapters open with one)
    and means page ZERO, not "unset" -- only an ABSENT `.pn` falls back to 1."""
    assert r'\pgnstart0' in emit.emit_rtf(_doc(pn_start=0))
