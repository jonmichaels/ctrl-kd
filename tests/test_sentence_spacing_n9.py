"""b33 N9 (Jon's ruling, 2026-08-26, field notes register row): sentence-
spacing export option {keep, single}.

RULED (verbatim): "let's have a default on Modern exports to convert to
single space after a period ending a sentence. Printed (and Native)
should keep documents as is. And then the flag allows you to force the
other option." The field notes name '.' explicitly and don't rule '?'/'!'
in or out; this implementation covers all three real sentence-enders
(the classic typing-class rule) -- see core.SENTENCE_END_CHARS.

The rule is deliberately SIMPLE, no abbreviation detection ("no
cleverness"): a double space after '.', '?', or '!' collapses to one
space regardless of what precedes it (an abbreviation like "e.g." included).
A double space that does NOT follow one of those three characters (after a
comma, or with no punctuation at all) is untouched in EVERY mode -- this
flag has nothing to say about it.

Independent of the flag: Markdown must never emit a line ending in 2+
spaces unless it is the emitter's own deliberate hard-break join (a
verified verse/stanza unit) -- CommonMark reads a coincidental trailing
double space as a break the source never asked for.
"""
from ctrlkd import core, emit, pdf, cli

HARD = b'\x0d\x0a'
SOFT = b'\x8d\x0a'

# WS7 header block (same helper shape as test_flags_toc_inline.py / test_ctrlkd.py)
def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _header():
    return ws7_block(0x00, bytes([0x70]) + bytes(15))


SENTENCE = ('He said hello.  She replied yes!  Then asked why?  '
           "I don't know, honestly.")


def _doc(text=SENTENCE):
    return core.parse_ws(_header() + text.encode() + HARD)


def _single_line(out):
    """The one real content line out of a Text/HTML/RTF/MD rendering,
    stripped -- these fixtures are one short paragraph, one physical
    line, so callers just want its own text back."""
    for l in out.split('\n'):
        if l.strip() and not l.strip().startswith(('<', '{\\', '```')):
            return l.strip()
    return ''


COLLAPSED = ("He said hello. She replied yes! Then asked why? "
            "I don't know, honestly.")
# HTML escapes the apostrophe -- the substring every HTML check uses instead,
# short enough to still prove the collapse happened at every sentence end.
COLLAPSED_NOAPOS = 'He said hello. She replied yes! Then asked why? I'


# --------------------------------------------------------- Modern default

def test_modern_default_converts_to_single_space_text():
    doc = _doc()
    out = emit.emit_text(doc, mode='modern')
    assert '  ' not in out.strip()
    assert COLLAPSED in out


def test_modern_default_converts_to_single_space_markdown():
    doc = _doc()
    out = emit.emit_markdown(doc, mode='modern')
    assert '  ' not in out.strip('\n')
    assert COLLAPSED in out


def test_modern_default_converts_to_single_space_html():
    doc = _doc()
    out = emit.emit_html(doc, mode='modern')
    assert COLLAPSED_NOAPOS in out
    # the body paragraph itself carries no double space (CSS/markup runs
    # of '  ' inside <style> etc. are not what this checks -- just the
    # rendered sentence)
    assert 'hello.  She' not in out


def test_modern_default_converts_to_single_space_rtf():
    doc = _doc()
    out = emit.emit_rtf(doc, mode='modern')
    assert COLLAPSED in out
    assert 'hello.  She' not in out


def test_modern_default_converts_to_single_space_pdf():
    doc = _doc()
    single = pdf.emit_pdf(doc, mode='modern')
    forced_single = pdf.emit_pdf(doc, mode='modern', sentence_spacing='single')
    forced_keep = pdf.emit_pdf(doc, mode='modern', sentence_spacing='keep')
    # auto (the default) must match the explicit 'single' force, and
    # differ from the explicit 'keep' force -- proves the mode-aware
    # default actually resolved to single, not just "did nothing".
    assert single == forced_single
    assert single != forced_keep


# ----------------------------------------------------- Printed/Native default

def test_printed_default_preserves_double_space_text():
    doc = _doc()
    out = emit.emit_text(doc, mode='printed')
    assert 'hello.  She replied yes!  Then asked why?  I' in out


def test_printed_default_preserves_double_space_markdown():
    doc = _doc()
    out = emit.emit_markdown(doc, mode='printed')
    assert 'hello.  She replied yes!  Then asked why?  I' in out


def test_printed_default_preserves_double_space_html():
    doc = _doc()
    out = emit.emit_html(doc, mode='printed')
    assert 'hello.  She replied yes!  Then asked why?  I' in out


def test_printed_default_preserves_double_space_rtf():
    doc = _doc()
    out = emit.emit_rtf(doc, mode='printed')
    assert 'hello.  She replied yes!  Then asked why?  I' in out


def test_printed_default_preserves_double_space_pdf():
    doc = _doc()
    auto = pdf.emit_pdf(doc, mode='printed')
    forced_keep = pdf.emit_pdf(doc, mode='printed', sentence_spacing='keep')
    forced_single = pdf.emit_pdf(doc, mode='printed', sentence_spacing='single')
    assert auto == forced_keep
    assert auto != forced_single


# ------------------------------------------------------------- flag overrides

def test_flag_forces_keep_on_modern():
    doc = _doc()
    out = emit.emit_text(doc, mode='modern', sentence_spacing='keep')
    assert 'hello.  She replied yes!  Then asked why?  I' in out


def test_flag_forces_single_on_printed():
    doc = _doc()
    for fn in (emit.emit_text, emit.emit_markdown, emit.emit_rtf):
        out = fn(doc, mode='printed', sentence_spacing='single')
        assert COLLAPSED in out, fn.__name__
    html_out = emit.emit_html(doc, mode='printed', sentence_spacing='single')
    assert COLLAPSED_NOAPOS in html_out


def test_flag_forces_single_on_printed_pdf():
    doc = _doc()
    keep = pdf.emit_pdf(doc, mode='printed', sentence_spacing='keep')
    single = pdf.emit_pdf(doc, mode='printed', sentence_spacing='single')
    assert keep != single


def test_flag_forces_keep_on_modern_pdf():
    doc = _doc()
    default_single = pdf.emit_pdf(doc, mode='modern')
    forced_keep = pdf.emit_pdf(doc, mode='modern', sentence_spacing='keep')
    assert default_single != forced_keep


# --------------------------------------------------------------- CLI wiring

def _run_cli(tmp_path, data, *args):
    src = tmp_path / 'SAMPLE.WS'
    src.write_bytes(data)
    out = tmp_path / 'out.txt'
    rc = cli.main([str(src), '-t', 'text', '-o', str(out), *args])
    return rc, (out.read_text() if out.exists() else '')


def test_cli_sentence_spacing_flag_forces_keep_on_modern_default(tmp_path):
    rc, text = _run_cli(tmp_path, _header() + SENTENCE.encode() + HARD,
                        '--sentence-spacing', 'keep')
    assert rc == 0
    assert 'hello.  She replied yes!  Then asked why?  I' in text


def test_cli_sentence_spacing_defaults_to_auto(tmp_path):
    # bare CLI call, mode defaults to modern -> single
    rc, text = _run_cli(tmp_path, _header() + SENTENCE.encode() + HARD)
    assert rc == 0
    assert COLLAPSED in text


# ---------------------------------------------- not sentence-ending spacing

def test_double_space_after_comma_is_never_touched():
    """The flag has nothing to say about a double space that does not
    follow '.', '?', or '!' -- comma included -- in EITHER mode."""
    doc = _doc('A list: apples,  oranges, and pears.')
    for mode in ('modern', 'printed'):
        for ss in ('keep', 'single'):
            out = emit.emit_text(doc, mode=mode, sentence_spacing=ss)
            assert 'apples,  oranges' in out


def test_bare_double_space_with_no_punctuation_is_never_touched():
    doc = _doc('Two words  apart with no punctuation before the gap.')
    for mode in ('modern', 'printed'):
        for ss in ('keep', 'single'):
            out = emit.emit_text(doc, mode=mode, sentence_spacing=ss)
            assert 'words  apart' in out


def test_abbreviation_double_space_collapses_same_as_a_real_sentence_end():
    """Jon's ruling: a simple two-spaces-after-period rule, no cleverness
    -- 'e.g.  ' is not special-cased and collapses exactly like a genuine
    sentence end."""
    doc = _doc('See the guide, e.g.  the appendix, for details.')
    out = emit.emit_text(doc, mode='modern')          # auto -> single
    assert 'e.g. the appendix' in out
    assert 'e.g.  the' not in out
    kept = emit.emit_text(doc, mode='printed')          # auto -> keep
    assert 'e.g.  the appendix' in kept


# ----------------------------------------------------------- notes text too

def test_footnote_text_also_gets_sentence_spacing():
    def ws7_note(cmd, text, number=1):
        content = ((1).to_bytes(2, 'little') + number.to_bytes(2, 'little')
                  + bytes([0x30]) + text)
        return ws7_block(cmd, content)
    data = (_header() + b'Body' + ws7_note(0x03, b'A note.  With two spaces.')
           + b' text.' + HARD)
    doc = core.parse_ws(data)
    single = emit.emit_text(doc, mode='modern')
    assert 'note. With two spaces.' in single
    kept = emit.emit_text(doc, mode='printed')
    assert 'note.  With two spaces.' in kept


# --------------------------------------------------------------- MD guard

def test_md_guard_strips_trailing_double_space_even_in_keep_mode():
    """The exact hazard the field notes named: a sentence joint landing at
    a reflowed line's own END. 'keep' does not collapse the double space
    mid-line, but MUST NOT let a source line's own trailing double space
    survive as an unintended CommonMark hard break."""
    doc = _doc('First sentence.  Second ends here.  ')
    out = emit.emit_markdown(doc, mode='modern', sentence_spacing='keep')
    lines = [l for l in out.split('\n') if l.strip()]
    assert not any(l.endswith('  ') for l in lines), lines
    # the INTERIOR double space (not at line end) is untouched by 'keep'
    assert 'sentence.  Second' in out


def test_md_guard_holds_under_single_too():
    doc = _doc('First sentence.  Second ends here.  ')
    out = emit.emit_markdown(doc, mode='modern', sentence_spacing='single')
    lines = [l for l in out.split('\n') if l.strip()]
    assert not any(l.endswith('  ') for l in lines), lines
    assert 'sentence. Second' in out


def test_md_guard_never_fires_in_printed_fenced_facsimile():
    """Inside a fenced code block trailing spaces are inert (no CommonMark
    construct reads inside one) -- sentence-spacing itself still applies
    there (inherited from emit_text's own printed facsimile)."""
    doc = _doc('First sentence.  Second ends here.  ')
    out = emit.emit_markdown(doc, mode='printed')      # auto -> keep
    assert '```' in out
    assert 'sentence.  Second ends here.' in out


def test_md_guard_does_not_break_a_real_verse_hard_break():
    """A verified verse/stanza unit's own deliberate '  \\n' join (Jon's
    2026-08-17 hard-break ruling) must survive untouched -- the guard
    only ever removes a coincidence baked into a LINE's own text, never
    the join the emitter adds on purpose."""
    poem = (b'     Line one ends.  --' + SOFT
           + b'     Line two ends!  --' + HARD)
    doc = core.parse_ws(poem)
    doc.meta['variant'] = 'ws4'
    for ss in ('keep', 'single'):
        out = emit.emit_markdown(doc, mode='modern', sentence_spacing=ss)
        assert '  \n' in out, (ss, out)
        lines = out.split('\n')
        # exactly one blank-trailing join (the intentional one) -- no
        # OTHER line ends in 2+ spaces
        trailing = [l for l in lines if l.endswith('  ')]
        assert len(trailing) == 1, (ss, lines)
    single_out = emit.emit_markdown(doc, mode='modern', sentence_spacing='single')
    assert 'Line one ends. --' in single_out.replace('  \n', '\n')
    keep_out = emit.emit_markdown(doc, mode='modern', sentence_spacing='keep')
    assert 'Line two ends!  --' in keep_out
