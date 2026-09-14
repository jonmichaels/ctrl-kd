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
