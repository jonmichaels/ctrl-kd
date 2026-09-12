"""planning #264 item 2 (packet row A10): no trailing blank RTF page.

THE DEFECT. Every document ending in `.pa` got an extra, permanently blank
page in both RTF modes -- the emitter wrote `\\page` for the document's own
last block and then closed the file, so a reader opens a page with nothing
on it. The PDF has not done that since planning #228: real WS7 only opens
the page after a forced break when at least one more real line of content
was typed after it before EOF (research/2026-09-08_trailing-pa-rule.md,
eleven harness probes).

THE FIX. RTF reads the SAME already-parsed fact the PDF reads --
`doc.meta['pa_eof_blank_after']`, set by core only when the document's own
last block really is a forced pagebreak. No second rule, no second
detector.

Both real ends of the rule are pinned below: sawyer/STRENGTH.WS (False --
a bare trailing `.pa`, nothing after it) and sawyer/REF/PAGESIZE.WS (True
-- the one corpus document that actually saved a blank paragraph after
its own trailing `.pa`, and whose real WS7 print really does carry a
sixth, footer-only page).
"""
import pytest

from ctrlkd import core, emit


def _doc(pa_eof_blank_after, trailing_break=True):
    blocks = [core.Block('para', lines=[core.Line(spans=[core.Span('body')])])]
    if trailing_break:
        blocks.append(core.Block('pagebreak'))
    meta = {'variant': 'ws5+'}
    if pa_eof_blank_after is not None:
        meta['pa_eof_blank_after'] = pa_eof_blank_after
    return core.Document(blocks=blocks, meta=meta)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_bare_trailing_pa_opens_no_rtf_page(mode):
    assert r'\page' not in emit.emit_rtf(_doc(False), mode=mode)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_trailing_pa_with_a_saved_blank_paragraph_still_opens_one(mode):
    assert r'\page' in emit.emit_rtf(_doc(True), mode=mode)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_pagebreak_that_is_not_the_last_block_is_untouched(mode):
    """Only the DOCUMENT'S OWN LAST block is in question -- an ordinary
    mid-document `.pa` breaks the page exactly as before."""
    doc = _doc(False, trailing_break=False)
    doc.blocks.append(core.Block('pagebreak'))
    doc.blocks.append(core.Block('para', lines=[core.Line(spans=[core.Span('after')])]))
    out = emit.emit_rtf(doc, mode=mode)
    assert out.count(r'\page') == 1


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_document_that_never_ends_in_pa_is_unchanged(mode):
    """`pa_eof_blank_after` is absent for the overwhelming majority of
    documents (core only computes it when the last block IS a pagebreak),
    and absence must not start suppressing anything."""
    out = emit.emit_rtf(_doc(None, trailing_break=False), mode=mode)
    assert r'\page' not in out


# ---------------------------------------------------- the real corpus (tier 2)

@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_strength_has_no_trailing_page(require_sawyer_doc, mode):
    with open(require_sawyer_doc('STRENGTH.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert doc.meta.get('pa_eof_blank_after') is False
    assert not emit.emit_rtf(doc, mode=mode).rstrip().rstrip('}').rstrip().endswith(r'\page')


@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_pagesize_keeps_the_page_wordstar_really_opened(require_sawyer_doc, mode):
    with open(require_sawyer_doc('REF/PAGESIZE.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert doc.meta.get('pa_eof_blank_after') is True
    assert emit.emit_rtf(doc, mode=mode).rstrip().rstrip('}').rstrip().endswith(r'\page')
