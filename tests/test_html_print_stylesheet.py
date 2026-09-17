r"""planning #264 R5 (Jon, 2026-09-14): "Fine. Add it." -- C6, the HTML
print stylesheet: `@page` with the document's own paper size and margins,
`break-after: page` at its own page breaks, `break-inside: avoid` for the
blocks `.cp`/`.cc` asked to hold together.

THIS DOES NOT GIVE HTML PAGES, and that is the point. The 2026-08-17
doctrine stands -- HTML has no pages on screen or anywhere else -- and
nothing here changes what a browser SHOWS. What it changes is what comes
out of a printer when someone hits Print on the page: until now the sheet
was the browser's default paper at the browser's default margins, and the
breaks fell wherever the browser felt like putting them.

PRINTED ONLY. Modern has no pages in any surface, so a Modern HTML export
carries no `@page` and no break rules at all; its `<hr class="pb">`
markers stay the decoration they have always been. (A printstream, and
any document `_printed()` resolves as printed, is printed in BOTH modes --
that is not an exception to this rule, it is the rule.)

ON-SCREEN RENDERING IS UNCHANGED, and this file PROVES it rather than
asserting it: every rule lives inside one `@media print` block appended
last, so the stylesheet above it is byte-for-byte what it was, and no
rule outside that block names the two new classes.

Synthetic fixtures only.
"""
import re

import pytest

from ctrlkd import core, emit

HARD = b'\x0d\x0a'


def _ws7(body, dots=b''):
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


def _css(html):
    return html[html.index('<style>') + len('<style>'):html.index('</style>')]


def _screen_css(html):
    """The stylesheet with the `@media print` block removed -- what a
    browser uses to draw the page."""
    css = _css(html)
    i = css.find('\n@media print{')
    return css if i < 0 else css[:i]


def _print_block(html):
    css = _css(html)
    i = css.find('@media print{')
    return '' if i < 0 else css[i:]


BODY = (b'.cp 3' + HARD + b'A Heading' + HARD + HARD + b'Body one.' + HARD
        + b'.pa' + HARD + b'Page two.' + HARD)


# ------------------------------------------------------------- @page

def test_the_sheet_is_the_documents_own_paper_and_margins():
    """`.pl`'s resolved height and the page model's width; `.mt`/`.mb` at
    6 LPI and `.po` at 10 CPI -- the identical numbers the RTF page setup
    writes as twips."""
    html = emit.emit_html(_ws7(b'Text.' + HARD), mode='printed')
    assert '@page{size:8.5in 11in;margin:0.5in 0.8in 1.33333in 0.8in}' in _print_block(html)


def test_the_documents_own_margins_reach_the_rule():
    doc = _ws7(b'Text.' + HARD, dots=b'.mt 6' + HARD + b'.mb 12' + HARD
               + b'.po 12' + HARD)
    block = _print_block(emit.emit_html(doc, mode='printed'))
    assert re.search(r'@page\{size:8\.5in 11in;margin:1in 1\.2in 2in 1\.2in\}', block)


def test_modern_states_the_paper_and_decides_nothing_else():
    """Planning #264 item 4(c), Jon's own framing of it (the browser check's
    section 3, 2026-09-14): Modern has no pages and this gives it none. What
    it gives is the SHEET -- until now a reader hitting Print on a Modern
    page got the browser's default paper at the browser's default margins,
    which for a document that declares its own is simply wrong information.

    So: `@page`, and nothing that decides where a sheet ENDS. No `hr.pb`
    break, no `.ws-keep`, no `break-after` of any kind. The stylesheet says
    so in its own comment, so a reader of the CSS meets the decision rather
    than an omission."""
    html = emit.emit_html(_ws7(BODY), mode='modern')
    block = _print_block(html)
    assert '@page{size:8.5in 11in;margin:0.5in 0.8in 1.33333in 0.8in}' in block
    assert 'No page breaks, by design' in block
    assert 'break-after' not in block
    assert 'break-inside' not in block
    assert 'hr.pb' not in block
    assert 'ws-keep' not in block
    # and nothing about paper leaks into the SCREEN stylesheet
    assert '@page' not in html[:html.index('@media print')]


# --------------------------------------------------------- page breaks

def test_a_page_break_becomes_a_real_one_in_print():
    block = _print_block(emit.emit_html(_ws7(BODY), mode='printed'))
    assert 'hr.pb{break-after:page;border:none;margin:0;height:0}' in block


def test_the_dashed_rule_is_still_the_screens_own_marker():
    """The `<hr class="pb">` element and its SCREEN rule are untouched --
    the print rule only stops it drawing on paper, where a dashed line
    across the foot of every sheet is not what it was ever for."""
    html = emit.emit_html(_ws7(BODY), mode='printed')
    assert '<hr class="pb">' in html
    assert 'hr.pb{border:none;border-top:1px dashed #bbb;margin:2rem 0}' in _screen_css(html)


def test_a_document_with_no_break_gets_no_break_rule():
    block = _print_block(emit.emit_html(_ws7(b'Text.' + HARD), mode='printed'))
    assert '@page' in block and 'hr.pb' not in block


# --------------------------------------------------------------- keeps

def test_the_cp_run_is_marked_and_kept():
    html = emit.emit_html(_ws7(BODY), mode='printed')
    assert 'ws-keep' in html
    block = _print_block(html)
    assert '.ws-keep{break-inside:avoid}' in block
    assert '.ws-keepn{break-after:avoid}' in block


def test_the_classes_name_exactly_the_blocks_r2_names():
    """Read from R2's OWN plan, so the RTF and the printed HTML cannot
    disagree about which paragraphs a `.cp` holds."""
    doc = _ws7(BODY)
    plan = emit._rtf_keep_plan(doc)
    html = emit.emit_html(doc, mode='printed')
    paras = re.findall(r'<p class="([^"]*)"', html)
    assert sum('ws-keep' in c for c in paras) == len(plan)
    assert sum('ws-keepn' in c for c in paras) == sum(1 for v in plan.values() if v[1])


def test_modern_never_carries_the_keep_classes():
    assert 'ws-keep' not in emit.emit_html(_ws7(BODY), mode='modern')


def test_a_document_with_no_cp_gets_no_keep_rules():
    block = _print_block(emit.emit_html(_ws7(b'Text.' + HARD + b'.pa' + HARD
                                             + b'More.' + HARD), mode='printed'))
    assert 'ws-keep' not in block


# ---------------------------------------------- the screen is untouched

@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_the_screen_stylesheet_is_byte_identical_to_the_base(mode):
    """The proof the ruling asked for: strip `@media print` and what is
    left is exactly the stylesheet that was there before -- so nothing a
    browser renders can have moved.

    E9 H4 (2026-09-17) added ONE thing to the screen side, and only in
    Modern: the reading measure (`emit._MODERN_MEASURE_CSS`). Printed's
    screen stylesheet is still the base, byte for byte, which is the half
    of this claim the print round actually made."""
    html = emit.emit_html(_ws7(BODY), mode=mode)
    base = emit._CSS + ('' if mode == 'printed' else emit._MODERN_MEASURE_CSS)
    assert _screen_css(html) == base


def test_no_screen_rule_ever_names_the_new_classes():
    """A class a screen rule matched would be a rendering change smuggled
    in as markup."""
    for mode in ('printed', 'modern'):
        screen = _screen_css(emit.emit_html(_ws7(BODY), mode=mode))
        assert 'ws-keep' not in screen and '@page' not in screen
        assert 'break-after' not in screen and 'break-inside' not in screen


def test_the_print_block_is_the_last_thing_in_the_stylesheet():
    css = _css(emit.emit_html(_ws7(BODY), mode='printed'))
    assert css.rstrip().endswith('}')
    assert css.count('@media print{') == 1
    assert css.index('@media print{') > css.rindex('hr.pb{border:none')
