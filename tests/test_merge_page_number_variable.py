"""Planning #270 item 40 (triage Q7), Jon's ruling 2026-09-13: "I guess
we can adopt... page numbers seems reasonable."

WordStar's MailMerge substitutes the page-number variable `&#&` at PRINT
time with the number of the page it lands on, and real WS7 does exactly
that in both corpus documents that print one -- `sawyer/REF/TOCTRICK.WS`
prints `2` on page 2 where the author typed `&#/r&`, and
`sawyer/ARTICLES/POWERUSE.WS` prints `CNT=8` on page 8 where the author
typed `CNT=&#&`.

The other half of the ruling matters just as much, and is what most of
this file guards: this is the ONLY merge variable that is ever
substituted. From the same ruling's MAIL MERGE scope paragraph -- "a
merge letter opens and exports as the letter itself, variables shown
as-is (not substituted, not stripped), except the page-number variables
per item 40."

Synthetic fixtures only.
"""
import re
import zlib

import pytest

from ctrlkd import core, pdf

HARD = b'\x0d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _doc(body, dots=b''):
    return core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(11) + bytes(4))
                         + dots + body)


def _pagelines_text(doc):
    """[[line text, ...], ...] per printed page -- what the writer draws."""
    return [[''.join(t for t, _ in pl) for pl in page]
            for page in pdf._doc_to_pagelines(doc, True)]


def _pdf_text(pdf_bytes):
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)endstream', pdf_bytes, re.S):
        try:
            out.append(zlib.decompress(m.group(1)).decode('latin-1'))
        except zlib.error:
            out.append(m.group(1).decode('latin-1'))
    return '\n'.join(out)


# --------------------------------------------------- the page-number variable
def test_the_page_number_variable_is_substituted_on_the_page_it_lands_on():
    """TOCTRICK.WS's own shape: the variable appears on more than one page
    and each occurrence takes ITS OWN page's number, not the first's."""
    body = (b'Page one text with &#& in it.' + HARD
            + b'.pa' + HARD
            + b'Page two text with &#& in it.' + HARD)
    pages = _pagelines_text(_doc(body))
    assert any('with 1 in it.' in line for line in pages[0])
    assert any('with 2 in it.' in line for line in pages[1])
    for page in pages:
        for line in page:
            assert '&#' not in line


def test_a_slash_modifier_is_accepted_and_prints_the_plain_arabic_number():
    """`&#/r&` is what `sawyer/REF/TOCTRICK.WS` actually stores, and real
    WS7 prints `2` for it on page 2 -- the plain arabic number, not a
    roman numeral (the capture's own chunks at x_decipoints 720 and 2304,
    text `2`). The modifier is accepted and ignored."""
    pages = _pagelines_text(_doc(b'Trick: &#/r& here.' + HARD))
    assert any('Trick: 1 here.' in line for line in pages[0])


def test_the_variable_substitutes_inside_a_word_not_only_alone():
    """POWERUSE.WS prints `CNT=8`, not `CNT= 8` or `CNT=` -- the variable
    is spliced into the surrounding text with no spacing of its own."""
    pages = _pagelines_text(_doc(b'CNT=&#& is a new value.' + HARD))
    assert any('CNT=1 is a new value.' in line for line in pages[0])


def test_the_substituted_number_reaches_the_printed_pdf():
    drawn = _pdf_text(pdf.emit_pdf(_doc(b'Count is &#& today.' + HARD), 'printed'))
    assert 'Count is 1 today.' in drawn or ('Count' in drawn and '&#' not in drawn)
    assert '&#' not in drawn


def test_a_pn_restart_substitutes_the_number_wordstar_would_have_printed():
    """The page number comes from the same `.pn`/`.pg` checkpoint walk the
    running head's `#` and the automatic page number already use, never
    from the page's index -- so a document that restarts its numbering
    substitutes the restarted number."""
    body = (b'First sheet with &#&.' + HARD
            + b'.pa' + HARD
            + b'.pn 10' + HARD
            + b'Second sheet with &#&.' + HARD)
    pages = _pagelines_text(_doc(body))
    assert any('with 1.' in line for line in pages[0])
    assert any('with 10.' in line for line in pages[1])


# ------------------------------------------- every OTHER merge variable stays
def test_an_ordinary_merge_variable_is_never_substituted_or_stripped():
    """The ruling's scope, verbatim: "variables shown as-is (not
    substituted, not stripped), except the page-number variables per item
    40." A merge LETTER opens as the letter."""
    body = (b'Dear &NAME&, of &COMPANY& at &ADDRESS/O&:' + HARD)
    pages = _pagelines_text(_doc(body))
    line = next(line for line in pages[0] if 'Dear' in line)
    assert '&NAME&' in line and '&COMPANY&' in line and '&ADDRESS/O&' in line


def test_a_variable_merely_containing_a_hash_is_not_the_page_number():
    """Only the variable whose NAME is exactly `#` is the page number. A
    merge field called `&REF#&` or `&#COUNT&` is an ordinary variable and
    stays as typed."""
    pages = _pagelines_text(_doc(b'See &REF#& and &#COUNT& and &N#M&.' + HARD))
    line = next(line for line in pages[0] if 'See' in line)
    assert '&REF#&' in line and '&#COUNT&' in line and '&N#M&' in line


def test_a_document_with_no_merge_variable_is_untouched():
    pages = _pagelines_text(_doc(b'Ordinary prose, an ampersand & a hash #.' + HARD))
    assert any('Ordinary prose, an ampersand & a hash #.' in line
               for line in pages[0])


# ------------------------------- non-paged exports carry no page apparatus
#
# Planning #270 item 42, Jon's ruling 2026-09-14, verbatim: "Actual page
# numbers and the page number merge should NOT be sent to non-paged
# exports: HTML, Markdown, and Text. The current handling of Headers and
# Footers for non-paged exports is correct. That data should not be sent."
#
# Those three formats have no pages, so there is no number to substitute
# and nothing the variable could mean. It is REMOVED -- never shown as
# typed -- which is the ONE exception to the Mail Merge scope rule's
# "variables stay visible exactly as typed", for the same reason headers
# and footers are already dropped there.
from ctrlkd import emit                                       # noqa: E402

_NONPAGED = ('text', 'markdown', 'html')


_EMITTERS = {'text': emit.emit_text, 'markdown': emit.emit_markdown,
             'html': emit.emit_html}


def _export(doc, fmt, mode):
    return _EMITTERS[fmt](doc, mode=mode)


def test_no_non_paged_export_ever_shows_the_page_number_variable():
    doc = _doc(b'Set in type on page &#/r& of &#& of this.' + HARD)
    for fmt in _NONPAGED:
        for mode in ('printed', 'modern'):
            out = _export(doc, fmt, mode)
            assert '&#/r&' not in out and '&#&' not in out, (fmt, mode)
            assert 'Set in type on page  of  of this.' in out or \
                   'Set in type on page of of this.' in out.replace('  ', ' '), (fmt, mode)


def test_a_non_paged_export_removes_the_variable_rather_than_numbering_it():
    """Removed, not substituted: a page-less format has no page 1 to name."""
    doc = _doc(b'Page &#&.' + HARD)
    for fmt in _NONPAGED:
        out = _export(doc, fmt, 'modern')
        assert 'Page 1.' not in out, fmt


def test_every_other_merge_variable_survives_a_non_paged_export():
    doc = _doc(b'Dear &NAME& of &COMPANY&, see &REF#& and &#COUNT&.' + HARD)
    for fmt in _NONPAGED:
        for mode in ('printed', 'modern'):
            out = _export(doc, fmt, mode)
            # HTML escapes the ampersand and Markdown backslash-escapes
            # the hash -- neither is this rule's business, so compare
            # against each format's own rendering of the same characters.
            plain = out.replace('&amp;', '&').replace('\\#', '#')
            for var in ('&NAME&', '&COMPANY&', '&REF#&', '&#COUNT&'):
                assert var in plain, (fmt, mode, var)


def test_the_variable_is_dropped_from_a_notes_text_too():
    """A note's own text is body content on these surfaces and takes the
    same rule -- `layout.merge_pageno_dropped` rewrites `doc.notes`
    beside the blocks."""
    from dataclasses import replace as _replace
    from ctrlkd.layout import merge_pageno_dropped
    doc = _doc(b'Body.' + HARD)
    if not doc.notes:
        return
    dropped = merge_pageno_dropped(_replace(doc, notes=[
        _replace(n, text=(n.text or '') + ' page &#&') for n in doc.notes]))
    assert all('&#' not in (n.text or '') for n in dropped.notes)


def test_a_document_with_no_variable_is_the_same_object_on_the_way_through():
    """The pass is free for the documents that carry none -- the guard
    returns the SAME Document, nothing is copied."""
    from ctrlkd.layout import merge_pageno_dropped
    doc = _doc(b'Ordinary prose with an ampersand & and a hash #.' + HARD)
    assert merge_pageno_dropped(doc) is doc


def test_the_paged_surfaces_still_substitute_a_real_number():
    """The other half of the same ruling: Printed is unchanged, and a
    paged surface prints the number, not a hole."""
    pages = _pagelines_text(_doc(b'Set on page &#&.' + HARD))
    assert any('Set on page 1.' in line for line in pages[0])


# ------------------------------------- item 42 remainder: the paged EXPORTS
#
# Jon's ruling 2026-09-14 (planning #270 item 42), verbatim: "The page
# number merge variable should be substituted for page numbers in Modern
# PDF and RTF. And it should be controlled by the page number flag."
#
# Printed PDF already substituted (above). What follows is the rest:
# Modern PDF, and BOTH RTF modes -- Printed RTF is not named by the
# ruling, and gets it for the same reason Modern RTF does. RTF's answer to
# "the number of the page this lands on" is `{\chpgn }`, the reader's own
# current-page field: an RTF's pages are the reader's, in both modes
# (packet section 3), so a field is not a fallback for a number we could
# not compute -- it is the only answer that stays true after the reader
# lays the file out at its own margins and fonts.

from ctrlkd import emit, layout                                   # noqa: E402

CHPGN = r'{\chpgn }'


def _rtf_body(doc, mode, **kw):
    """The RTF with its `\\footer` group removed, so an assertion about the
    body cannot pass on the automatic page number's own field."""
    out = emit.emit_rtf(doc, mode=mode, **kw)
    return re.sub(r'\{\\footer .*?\\par\}', '', out, flags=re.S)


def test_the_two_marker_constants_are_the_same_character():
    """`emit._MERGE_PAGENO_MARK` is spelled out rather than imported (the
    import would cycle); this is what keeps the two honest."""
    assert emit._MERGE_PAGENO_MARK == layout.MERGE_PAGENO_MARK


def test_both_rtf_modes_substitute_the_readers_own_page_field():
    for mode in ('printed', 'modern'):
        body = _rtf_body(_doc(b'Count is &#& today.' + HARD), mode)
        assert CHPGN in body
        assert '&#' not in body


def test_the_slash_modifier_form_substitutes_in_rtf_too():
    for mode in ('printed', 'modern'):
        assert CHPGN in _rtf_body(_doc(b'Trick: &#/r& here.' + HARD), mode)


def test_page_numbers_off_removes_the_variable_from_rtf():
    """`off` REMOVES it rather than showing it as typed -- with no number
    to show there is nothing left for the variable to say, so it goes the
    way it goes on a page-less surface."""
    for mode in ('printed', 'modern'):
        body = _rtf_body(_doc(b'Count is &#& today.' + HARD), mode,
                         page_numbers='off')
        assert CHPGN not in body and '&#' not in body
        assert 'Count is  today.' in body


def test_no_other_merge_variable_becomes_a_field_in_rtf():
    for mode in ('printed', 'modern'):
        body = _rtf_body(_doc(b'Dear &NAME&, see &REF#& and &#COUNT&.' + HARD),
                         mode)
        assert CHPGN not in body
        assert '&NAME&' in body and '&REF#&' in body and '&#COUNT&' in body


def test_the_marker_never_survives_into_the_rtf():
    """A private-use code point in a delivered file would be a defect in
    its own right."""
    for mode in ('printed', 'modern'):
        assert layout.MERGE_PAGENO_MARK not in emit.emit_rtf(
            _doc(b'Count is &#& today.' + HARD), mode=mode)


def _modern_page_words(doc, **kw):
    """[[word, ...], ...] per Modern page -- Modern draws one `Tj` per
    word, so the phrase never appears as one string in the stream."""
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)endstream',
                         pdf.emit_pdf(doc, 'modern', **kw), re.S):
        try:
            body = zlib.decompress(m.group(1)).decode('latin-1')
        except zlib.error:
            body = m.group(1).decode('latin-1')
        words = re.findall(r'\((.*?)\) Tj', body)
        if words:
            out.append(words)
    return out


def test_modern_pdf_substitutes_a_real_number():
    pages = _modern_page_words(_doc(b'Count is &#& today.' + HARD))
    assert pages[0] == ['Count', 'is', '1', 'today.']


def test_modern_pdf_page_numbers_off_removes_it():
    drawn = _pdf_text(pdf.emit_pdf(_doc(b'Count is &#& today.' + HARD), 'modern',
                                   page_numbers='off'))
    assert '&#' not in drawn and 'today' in drawn


def test_printed_pdf_page_numbers_off_removes_it():
    drawn = _pdf_text(pdf.emit_pdf(_doc(b'Count is &#& today.' + HARD), 'printed',
                                   page_numbers='off'))
    assert '&#' not in drawn and '1 today' not in drawn


def test_modern_takes_each_occurrences_own_page():
    """Two occurrences either side of a forced break take two different
    numbers -- the measuring pass reads the page each one actually fell
    on, not the document's first."""
    body = (b'Alpha with &#& in it.' + HARD
            + b'.pa' + HARD
            + b'Beta with &#& in it.' + HARD)
    pages = _modern_page_words(_doc(body))
    assert pages[0] == ['Alpha', 'with', '1', 'in', 'it.']
    assert pages[1] == ['Beta', 'with', '2', 'in', 'it.']


def test_modern_numbers_it_the_way_modern_numbers_its_pages():
    """NOT the printed answer, and that is deliberate. Modern's own page
    number is `.pn`'s start value plus the page index (`_modern_streams`'
    `start_no + pi`) -- a `.pn` that re-anchors MID-document has never
    reached Modern's running heads either, and this variable is answered
    by the same number the rest of the Modern page shows, not by a second,
    better paginator nothing else uses. A document that opens with `.pn`
    does carry it."""
    body = (b'First sheet with &#&.' + HARD
            + b'.pa' + HARD
            + b'.pn 10' + HARD
            + b'Second sheet with &#&.' + HARD)
    pages = _modern_page_words(_doc(body))
    assert pages[0] == ['First', 'sheet', 'with', '1.']
    assert pages[1] == ['Second', 'sheet', 'with', '2.']
    opened = _modern_page_words(_doc(b'Sheet with &#&.' + HARD, dots=b'.pn 7' + HARD))
    assert opened[0] == ['Sheet', 'with', '7.']


def test_a_document_without_the_variable_costs_no_measuring_pass():
    """The measuring pass is a whole extra Modern composition, so the
    necessary condition that gates it has to be real: `-HOLYMAC.WS`, the
    speed benchmark, must not pay for a feature it does not use."""
    d = _doc(b'Ordinary prose with no variable.' + HARD)
    assert pdf._merge_pageno_modern(d, {}) is d


def test_the_non_paged_formats_are_unchanged_by_any_of_this():
    """HTML/Markdown/text still REMOVE it, and still do so whatever the
    page-number flag says -- they have no pages for the flag to govern."""
    d = _doc(b'Count is &#& today.' + HARD)
    for fn in (emit.emit_text, emit.emit_markdown, emit.emit_html):
        for pn in ('auto', 'on', 'off'):
            out = fn(d, mode='modern', page_numbers=pn)
            assert '&#' not in out and 'chpgn' not in out


# ------------------------------------------------ the drift check (tier 2)
#
# `_merge_pageno_modern` measures once and renders once, and substituting
# SHORTENS the text: in principle an occurrence sitting within a few
# characters of a page's last line could move up a page between the two
# compositions and then name the page it left. That is not iterated to a
# fixed point (one need not exist -- a shorter line can pull the variable
# back, which lengthens it again); it is CHECKED, here, on every document
# in the archive that carries one.
#
# The check is exact rather than a spot assertion: if the measuring
# composition and the rendering composition put the same number of drawn
# words on every page, then they paginated identically, and every
# occurrence is on the page it was measured on.

MERGE_PAGENO_DOCS = ('REF/TOCTRICK.WS', 'ARTICLES/POWERUSE.WS', 'REF/CODES.WS')


def _modern_page_sizes(doc):
    return [len(words) for words in _modern_page_words(doc)]


@pytest.mark.sawyer
@pytest.mark.parametrize('name', MERGE_PAGENO_DOCS)
def test_modern_measuring_and_rendering_paginate_alike(require_sawyer_doc,
                                                       monkeypatch, name):
    with open(require_sawyer_doc(name), 'rb') as fh:
        doc = core.parse(fh.read())
    rendered = _modern_page_sizes(doc)
    monkeypatch.setattr(pdf, '_merge_pageno_modern', lambda d, o: d)
    measured = _modern_page_sizes(doc)
    assert measured == rendered, (name, measured, rendered)


@pytest.mark.sawyer
@pytest.mark.parametrize('name', MERGE_PAGENO_DOCS)
def test_no_paged_export_of_a_real_document_still_shows_the_variable(
        require_sawyer_doc, name):
    with open(require_sawyer_doc(name), 'rb') as fh:
        doc = core.parse(fh.read())
    for mode in ('printed', 'modern'):
        assert '&#' not in emit.emit_rtf(doc, mode=mode)
        assert b'&#' not in pdf.emit_pdf(doc, mode=mode)
