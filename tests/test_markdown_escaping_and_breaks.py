"""E7 (Jon, 2026-09-17): the three Markdown emitter defects the style-export
audit found, and the boundaries of each fix.

All three were found by `research/2026-09-17_markdown-style-export-audit.md`
and all three affected BOTH engines identically, which is what made them
correctness bugs rather than portability ones. Each is the audit's own
recommended option.

  A. STRIKEOUT RUNS COLLIDED. A bold or italic word inside a strikeout run is
     a separate span, so the emitter closed the strikeout and reopened it with
     nothing in between: `~~~~`. Four tildes are not strikethrough in any
     flavour -- the strikeout was lost AND the tildes became visible text.
     Fixed by merging a run the span split (audit §6.A option 3, the smallest
     change that stops literal `~~` reaching a reader).

  B. `<` AND `&` WERE NOT ESCAPED. A document that literally says `<SP>` or
     `<Enter>` emitted it raw, and every renderer read it as an unknown HTML
     element and showed NOTHING -- the word vanished. `<B>` is worse: a real
     tag, switching bold on with nothing to switch it off. Fixed by escaping
     both (audit §6.B option 1).

  C. HARD-BREAK UNITS EMITTED WHITESPACE-ONLY LINES. A verse/stanza unit
     containing a blank line was joined with the two-trailing-spaces hard
     break, turning the blank line into a line of two spaces. CommonMark reads
     that as a blank line, so the paragraph split anyway -- into pieces whose
     raw text claimed otherwise. Fixed by closing the unit at a blank line
     (audit §6.C option 2), plus dropping the dangling trailing `  ` a unit
     ending in a blank used to leave.

DELIBERATELY UNCHANGED, and tested as such below so a later reader does not
"fix" them by accident:

  * PRINTED-MODE MARKDOWN, and any print-stream/columnar document in either
    mode, is a FENCED CODE BLOCK of the text rendering. Its content is
    literal: escaping `<` inside it would put a backslash on the reader's
    screen, and collapsing its blank lines would destroy the layout that is
    the whole point of a captured page. None of the three fixes may reach it.
  * Paragraph ALIGNMENT and sub/superscript mapping (audit §6.D, §6.E) are
    unruled and untouched.

Synthetic fixtures only.
"""
from ctrlkd import core, emit

HARD = b'\r\n'
MD = emit.get_emitter('markdown')['fn']


def _md(data, mode='modern'):
    return MD(core.parse(data), mode)


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


# The WS5+ seed: without it a short synthetic file classifies as a print
# stream, which renders as a fenced block and exercises none of this.
WS5_SEED = ws7_block(0x0B, b'\x00' * 4)

# WordStar's inline toggles (core.WS_TOGGLES): each byte turns its attribute
# on, and the same byte turns it off again.
BOLD = b'\x02'                        # ^PB
UNDER = b'\x13'                       # ^PS
ITALIC = b'\x19'                      # ^PY
STRIKE = b'\x18'                      # ^PX


# ------------------------------------------------------------------- A

def test_a_style_split_strikeout_run_does_not_emit_four_tildes():
    """The reported shape, exactly: a bold word butted straight against the
    strikeout text around it, no space between. Before the guard this emitted

        ~~alpha~~~~**beta**~~~~gamma~~

    -- the strikeout closing and reopening with nothing in between. Four
    tildes are not strikethrough in any flavour, so the strike was lost and
    the tildes showed up as text."""
    data = (WS5_SEED + STRIKE + b'alpha' + BOLD + b'beta' + BOLD
            + b'gamma' + STRIKE + HARD)
    out = _md(data).strip()
    assert '~~~~' not in out, out
    assert out == '~~alpha**beta**gamma~~', out


def test_the_merged_strikeout_still_marks_every_word():
    """The guard must not lose the run it merges: ONE `~~` pair around the
    whole thing, with the bold still inside it."""
    data = (WS5_SEED + STRIKE + b'alpha' + BOLD + b'beta' + BOLD
            + b'gamma' + STRIKE + HARD)
    out = _md(data)
    assert out.count('~~') == 2, out
    body = out[out.index('~~') + 2:out.rindex('~~')]
    assert 'alpha' in body and 'beta' in body and 'gamma' in body, out


def test_a_cosmetic_split_is_deliberately_left_alone():
    """A SPACE between the spans means the delimiters are not adjacent, so
    there is no collision -- `~~alpha~~ ~~**beta**~~ ~~gamma~~` renders
    correctly as three struck runs. This is the audit's option 3 doing exactly
    what it promised: fix the rendering breakage, leave the cosmetic splits
    alone. Tidying those too (option 1) would re-baseline every Markdown cell
    in both engines and is a separate decision."""
    data = (WS5_SEED + STRIKE + b'alpha ' + BOLD + b'beta' + BOLD
            + b' gamma' + STRIKE + HARD)
    out = _md(data).strip()
    assert out == '~~alpha~~ ~~**beta**~~ ~~gamma~~', out


def test_bold_beside_italic_is_never_merged():
    """The guard compares the delimiter each span actually emitted, never a
    string suffix -- a suffix test cannot tell `**bold**` followed by
    `*italic*` (which ends in `*` and starts with `*`) from two halves of one
    italic run, and merging them would corrupt both."""
    data = WS5_SEED + BOLD + b'bold' + BOLD + ITALIC + b'italic' + ITALIC + HARD
    out = _md(data)
    assert '**bold**' in out, out
    assert '*italic*' in out, out


# ------------------------------------------------------------------- B

def test_angle_brackets_in_the_source_survive():
    """`<SP>` used to vanish entirely: every renderer read it as an unknown
    HTML element and showed nothing."""
    out = _md(WS5_SEED + b'Press <SP> then <Enter>.' + HARD)
    assert '\\<SP>' in out and '\\<Enter>' in out, out


def test_a_source_b_tag_does_not_switch_bold_on():
    """`<B>` is a REAL tag -- unescaped it turned bold on for the rest of the
    document with nothing to turn it off."""
    out = _md(WS5_SEED + b'Type <B> to continue.' + HARD)
    assert '\\<B>' in out, out


def test_ampersands_are_escaped():
    out = _md(WS5_SEED + b'Smith & Sons &amp; Co.' + HARD)
    assert '\\&' in out and '&amp;' not in out.replace('\\&amp;', ''), out


def test_the_emitters_own_tags_are_never_escaped():
    """`<u>`/`<sub>`/`<sup>` are wrapped around text the escaper has already
    returned, so they must come through intact -- escaping them would put a
    backslash on the reader's screen and lose the underline."""
    out = _md(WS5_SEED + b'plain ' + UNDER + b'under' + UNDER + b' plain' + HARD)
    assert '<u>under</u>' in out, out
    assert '\\<u>' not in out, out


def test_a_note_definition_escapes_the_same_characters_as_body_text():
    """A note's raw text bypasses the span path, and escaped only the
    backslash until E7 -- so `<-Repeated` in a real TAGS annotation still
    vanished after every span had been fixed. One escape definition, two
    readers."""
    from ctrlkd.emit import _md_escape
    assert _md_escape('<-Repeated & <B>') == '\\<-Repeated \\& \\<B>'


# ------------------------------------------------------------------- C

def _verse(*lines):
    r"""A hand-positioned (`.aw off`) block: never reflowed, so its lines keep
    their own breaks and take the two-trailing-spaces hard-break join.

    A blank line INSIDE such a block is the real shape -- a blank line between
    two ordinary paragraphs ends the block instead, and never reaches the
    join. The corpus documents that carry this are mail-merge label templates
    (`DEFAULT/OPTIONS/HP-LAB3.LST` and its siblings) whose body opens with a
    blank line after their dot-command preamble.
    """
    return WS5_SEED + b'.aw off' + HARD + HARD.join(lines) + HARD


def test_a_blank_line_inside_a_hard_break_unit_starts_a_new_paragraph():
    """Before the fix this emitted a first line of nothing but the two
    hard-break spaces:

        '  \nalpha  \nbeta\n'

    CommonMark reads a whitespace-only line as blank, so the paragraph split
    anyway -- into pieces whose raw text claimed a break that could not
    happen. The rendering is unchanged; the file now agrees with it."""
    out = _md(_verse(b'', b'alpha', b'beta'))
    assert not any(l and not l.strip() for l in out.split('\n')), repr(out)
    assert out.strip() == 'alpha  \nbeta', repr(out)


def test_no_line_is_ever_only_whitespace():
    out = _md(_verse(b'', b'alpha', b'beta', b'', b'gamma'))
    for line in out.split('\n'):
        assert line == '' or line.strip(), repr(line)


def test_a_unit_ending_in_a_blank_leaves_no_dangling_hard_break():
    """Inert -- nothing follows it to break onto -- but non-conforming, and it
    made the raw text claim a break that could not happen."""
    out = _md(_verse(b'', b'alpha', b'beta', b''))
    assert not out.rstrip('\n').endswith('  '), repr(out)
    lines = out.split('\n')
    for i, line in enumerate(lines[:-1]):
        if line.endswith('  '):
            assert lines[i + 1].strip(), repr(out)


def test_a_real_hard_break_between_two_content_lines_survives():
    """The fix must not take the feature away: two verses with nothing between
    them still get the two-trailing-spaces break."""
    out = _md(_verse(b'', b'first verse', b'second verse'))
    assert '  \n' in out, repr(out)


# --------------------------------------------- the fenced body is untouched

_FENCE_DOC = b'Plain text with <SP> in it.' + HARD + HARD + b'After a blank.' + HARD


def test_a_print_stream_renders_fenced_and_is_left_literal():
    """A print stream (and every Printed-mode Markdown body) is a FENCED CODE
    BLOCK of the text rendering. Inside a fence Markdown has no syntax at all,
    so escaping `<` would put a visible backslash on the reader's screen and
    collapsing blank lines would destroy the captured page's layout. None of
    the three fixes may reach it."""
    doc = core.parse(_FENCE_DOC)
    assert doc.meta.get('variant') == 'printstream'
    out = MD(doc, 'modern')
    assert out.lstrip().startswith('```'), out
    assert '<SP>' in out and '\\<SP>' not in out, out


def test_printed_mode_markdown_is_the_fenced_body_for_a_ws_document_too():
    """Same rule from the other direction: a real WS document asked for in
    Printed mode also renders fenced, and is equally literal."""
    out = MD(core.parse(WS5_SEED + b'Press <SP> now.' + HARD), 'printed')
    assert out.lstrip().startswith('```'), out
    assert '\\<' not in out, out
