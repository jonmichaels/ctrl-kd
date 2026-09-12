"""planning #264 items 2 and 4 (packet row A10): no trailing break that the
document never earned -- in RTF, HTML, text and Markdown.

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

ITEM 4 (2026-09-12) gives the other three emitters that same reading. Each
was still marking the break the document never earned, as the LAST thing
in the file, separating the document from nothing: HTML a `<hr class="pb">`
rule, printed text a form feed (Modern text, a row of dashes), Markdown a
`---`. `emit._trailing_pa_skip_index` is now the one place the fact is
read; RTF calls it too, in place of the inline copy item 2 left behind.

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


# ------------------------------- item 4: the same fact, in the other emitters

@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_html_draws_no_trailing_rule_for_a_bare_trailing_pa(mode):
    assert '<hr class="pb">' not in emit.emit_html(_doc(False), mode=mode)


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_html_keeps_the_rule_when_the_document_earned_the_page(mode):
    assert '<hr class="pb">' in emit.emit_html(_doc(True), mode=mode)


def test_printed_text_emits_no_trailing_form_feed():
    assert '\f' not in emit.emit_text(_doc(False), mode='printed')
    assert '\f' in emit.emit_text(_doc(True), mode='printed')


def test_modern_text_emits_no_trailing_dashed_separator():
    """Modern's marker is decorative rather than a page, but it is the same
    fact deciding it -- and a separator to nothing is no better than a
    blank page."""
    assert '-' * 20 not in emit.emit_text(_doc(False), mode='modern')
    assert '-' * 20 in emit.emit_text(_doc(True), mode='modern')


def test_modern_markdown_emits_no_trailing_rule():
    out = emit.emit_markdown(_doc(False), mode='modern')
    assert not out.rstrip().endswith('---')
    assert emit.emit_markdown(_doc(True), mode='modern').rstrip().endswith('---')


def test_printed_markdown_emits_no_trailing_form_feed():
    """Printed Markdown is a fenced facsimile built from the text
    renderer's own lines, so its marker is the form feed, not a `---`."""
    assert '\f' not in emit.emit_markdown(_doc(False), mode='printed')
    assert '\f' in emit.emit_markdown(_doc(True), mode='printed')


@pytest.mark.parametrize('fmt', ['html', 'text', 'markdown', 'rtf'])
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_mid_document_pa_is_untouched_in_every_emitter(fmt, mode):
    """Only the DOCUMENT'S OWN LAST block is ever in question."""
    doc = _doc(False, trailing_break=False)
    doc.blocks.append(core.Block('pagebreak'))
    doc.blocks.append(core.Block('para', lines=[core.Line(spans=[core.Span('after')])]))
    out = getattr(emit, 'emit_' + fmt)(doc, mode=mode)
    if fmt == 'html':
        marker = '<hr class="pb">'
    elif fmt == 'rtf':
        marker = r'\page'
    elif mode == 'printed':
        marker = '\f'                  # text and printed Markdown's facsimile
    elif fmt == 'text':
        marker = '-' * 20
    else:
        marker = '---'                 # Modern Markdown
    assert marker in out


# --------------------------------------------------- the real corpus (tier 2)

@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_strength_drops_its_trailing_marker_in_every_emitter(require_sawyer_doc, mode):
    """STRENGTH.WS is the worked example on this side too: a bare trailing
    `.pa` with nothing saved after it."""
    with open(require_sawyer_doc('STRENGTH.WS'), 'rb') as fh:
        doc = core.parse(fh.read())
    assert doc.meta.get('pa_eof_blank_after') is False
    assert '<hr class="pb">' not in emit.emit_html(doc, mode=mode)
    assert '\f' not in emit.emit_text(doc, mode=mode)
    assert '\f' not in emit.emit_markdown(doc, mode=mode)
    assert not emit.emit_markdown(doc, mode=mode).rstrip().endswith('---')
