r"""planning #264 CHECK PLAN, layer 2 (Jon, 2026-09-14): "2 is fine now."
-- structural RTF/HTML checks and a parser round trip, in both engines'
suites.

WHY THIS LAYER EXISTS. Layer 1 is the rules pinned by name and the
cross-engine byte gate: it proves the two engines agree and that each
named rule fires. Neither says the FILE IS WELL FORMED. An RTF with one
unbalanced brace, or a control word no reader knows, or a section opener
the document never asked for, passes every byte comparison in the suite
as long as both engines are wrong in the same way. Layer 3 (a real reader
-- LibreOffice headless, or Jon's own eyes on Word and Pages) is the only
thing that can judge how it LOOKS; this layer is what can be automated
today, and it is about SHAPE.

THREE CHECKS:

  RTF   braces balance (honouring `\{`, `\}` and `\\`); every control
        word comes from a list this file names; and the number of
        `\sect` openers equals the number of section breaks the document
        actually asked for (`emit._rtf_section_breaks`).
  HTML  the body parses under a STRICT parser -- XML, after the void
        elements are self-closed and `&nbsp;` is written as a numeric
        reference. A browser's own parser forgives almost anything; XML
        forgives nothing, which is the point.
  TRIP  the RTF and the HTML are read back to plain text and compared,
        whitespace-normalised, with our own `emit_text`. Two exports of
        one document that disagree about the WORDS have a bug in one of
        them, and no byte comparison between engines can see it.

THE SET. A curated list, named here, chosen to cover every construct the
#264 rounds touched: columns, a column break, a head that changes,
keep-with-next, footnotes, styles, a printstream, a mailmerge letter, and
a picture-bearing document. Not the whole corpus -- this is a shape check
run on every suite invocation, not a release battery (memory
`testing-proportional-to-change`).
"""
import html as _html
import re
import xml.etree.ElementTree as ET

import pytest

from ctrlkd import core, emit

CURATED = (
    'REF/WINGDING.CHT',       # `.co5` columns, five of them
    'MICKEE/MICKEE.WS',       # columns on and off, `.cb`, a head change
    'MACROS/HOLYMAC/1-3MAC',  # a head redefined mid-document, `.cp`
    'OLDTIMES.WS',            # `.cp`, a running head, notes
    'LJ6DTP.WS',              # a driver document: substitutions, print controls
    'REF/WSFORMAT.WS',        # long, heavily dot-commanded reference prose
    'STRENGTH.WS',            # space-centred lines, no head or foot at all
    'RTF-RJS/NOVEL.WS',       # styles, `.tc` entries, merge variables
    'REF/TOCTRICK.WS',        # the merge page-number variable
    'VERSIONS.TXT',           # a printstream
)


# ------------------------------------------------------------------ RTF

def rtf_brace_depth_errors(rtf):
    """Every place the brace nesting goes wrong, as (offset, reason)."""
    errors, depth, i = [], 0, 0
    while i < len(rtf):
        ch = rtf[i]
        if ch == '\\' and i + 1 < len(rtf):
            i += 2                                  # an escape, whatever it is
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                errors.append((i, 'a closing brace with nothing open'))
                depth = 0
        i += 1
    if depth:
        errors.append((len(rtf), f'{depth} group(s) never closed'))
    return errors


# Every control word either engine writes. A word NOT on this list is not
# necessarily wrong -- it is UNREVIEWED, which is the thing this check is
# for: a typo (`\keepnn`) and a real new feature look identical to a byte
# comparison, and only one of them should be added here.
RTF_CONTROL_WORDS = frozenset("""
rtf ansi deff fonttbl f falt colortbl red green blue stylesheet s
paperw paperh margl margr margt margb facingp margmirror headery footery
pgnstart landscape cols colsx sect sectd column page par line tab titlepg
header headerl headerr headerf footer footerl footerr footerf chpgn
pard plain qc qr ql qj fs cf chcbpat highlight b i ul ulnone strike super sub nosupersub
fi li ri sl slmult sb sa keep keepn up dn
chftn footnote ftnalt chatn annotation atnid atnauthor
u uc bkmkstart bkmkend field fldinst fldrslt pict pngblip jpegblip
picw pich picwgoal pichgoal emfblip wmetafile
info title author creatim yr mo dy
""".split())

_RTF_WORD = re.compile(r'\\([a-zA-Z]+)(-?\d+)?')


def rtf_control_words(rtf):
    """Every control word in `rtf`, in order.

    A SCAN, not `finditer`: `\\\\`, `\\{` and `\\}` are ESCAPES, and a
    document whose text contains a DOS path (`C:\\WS\\PrintFilePrinter`,
    which LJ6DTP.WS really does) escapes each backslash, so a naive
    regex reads `\\WS` as a control word called `WS`. Found by this very
    check on its first run."""
    out, i, n = [], 0, len(rtf)
    while i < n:
        if rtf[i] != '\\':
            i += 1
            continue
        m = _RTF_WORD.match(rtf, i)
        if m:
            out.append(m.group(1))
            i = m.end()
            continue
        i += 2                                      # an escaped character
    return out


def rtf_unknown_control_words(rtf):
    return sorted({w for w in rtf_control_words(rtf)
                   if w not in RTF_CONTROL_WORDS})


def rtf_section_count(rtf):
    return len(re.findall(r'\\sect\\sectd', rtf))


# --------------------------------------------------------- RTF -> text

_RTF_DESTINATIONS = ('fonttbl', 'colortbl', 'stylesheet', 'info',
                     'header', 'headerl', 'headerr', 'headerf',
                     'footer', 'footerl', 'footerr', 'footerf',
                     'footnote', 'annotation', 'atnid', 'atnauthor',
                     'pict', 'field')


def rtf_to_text(rtf):
    """A small RTF text extractor -- enough to read our own output back.

    Skips the destination groups whose content is not body text (the font
    and colour tables, the stylesheet, the running heads and feet, note
    destinations, pictures), unescapes `\\uN?` and `\\'hh`, turns `\\par`,
    `\\line`, `\\page` and `\\column` into newlines, and drops every other
    control word. Deliberately small: a full RTF reader would hide the
    very defects this is here to find."""
    out, i, n = [], 0, len(rtf)
    skip_to_depth = None
    depth = 0
    while i < n:
        ch = rtf[i]
        if ch == '{':
            depth += 1
            i += 1
            # A group is skipped when it OPENS a destination, or when it
            # opens `{\*` (RTF's own ignore-if-unknown marker). Only ever
            # set when nothing is already being skipped: a nested
            # `{\*\falt ...}` inside the font table used to OVERWRITE the
            # table's own depth and then clear it on its own closing brace,
            # which leaked `;Courier New;` into the extracted text. Found by
            # this check on its first run.
            if skip_to_depth is None:
                m = re.match(r'\\([a-zA-Z]+)', rtf[i:])
                if rtf[i:i + 2] == r'\*' or (m and m.group(1) in _RTF_DESTINATIONS):
                    skip_to_depth = depth
            continue
        if ch == '}':
            if skip_to_depth is not None and depth == skip_to_depth:
                skip_to_depth = None
            depth -= 1
            i += 1
            continue
        if ch == '\\':
            m = _RTF_WORD.match(rtf, i)
            if m:
                word, arg = m.group(1), m.group(2)
                i = m.end()
                if i < n and rtf[i] == ' ':
                    i += 1
                if skip_to_depth is not None:
                    continue
                if word in ('par', 'line', 'page', 'column'):
                    out.append('\n')
                elif word == 'tab':
                    out.append('\t')
                elif word == 'u' and arg is not None:
                    out.append(chr(int(arg) % 65536))
                    if i < n and rtf[i] == '?':      # the ANSI fallback
                        i += 1
                continue
            nxt = rtf[i + 1:i + 2]
            i += 2
            if skip_to_depth is None and nxt in ('\\', '{', '}'):
                out.append(nxt)
            continue
        if skip_to_depth is None and ch not in '\r\n':
            out.append(ch)
        i += 1
    return ''.join(out)


# -------------------------------------------------------- HTML strict

_VOID = re.compile(r'<(br|hr|img|meta|link|input)\b([^>]*?)/?>')


def html_body_xml_errors(html):
    """The body, parsed as XML. A browser forgives almost anything; XML
    forgives nothing, and an unclosed or mis-nested tag is exactly the
    class of defect a byte comparison cannot see."""
    body = html[html.index('<body>') + len('<body>'):html.rindex('</body>')]
    body = _VOID.sub(lambda m: f'<{m.group(1)}{m.group(2)}/>', body)
    body = body.replace('&nbsp;', '&#160;')
    try:
        ET.fromstring('<root>' + body + '</root>')
    except ET.ParseError as exc:
        return [str(exc)]
    return []


_TAG = re.compile(r'<[^>]+>')


def html_to_text(html):
    body = html[html.index('<body>') + len('<body>'):html.rindex('</body>')]
    body = re.sub(r'<(br|hr)\b[^>]*>', '\n', body)
    # BLOCK BOUNDARIES ON BOTH TAGS, opening and closing. A nested list --
    # `<dd>76702,747<dl><dt>GEnie:</dt>...` on MICKEE.WS, where the ladder
    # really does step in -- opens its sublist INSIDE the `<dd>` with no
    # closing tag between, so closing tags alone ran two rows' words
    # together. Found by this check on its first run; the markup is right
    # and the reader was not.
    body = re.sub(r'</?(p|div|h[1-6]|ul|ol|li|dl|dt|dd|blockquote|section|pre)\b[^>]*>',
                  '\n', body)
    body = _TAG.sub('', body)
    # `html.unescape`, not a hand table: the emitter writes `&#x27;` for an
    # apostrophe (Python's own `html.escape(quote=True)`), and a five-entry
    # table missed it on every document in the set. Found by this check on
    # its first run.
    return _html.unescape(body.replace('&nbsp;', ' '))


_PAGE_MARK = re.compile(r'^-{20}$|^\x0c$', re.M)


def _bullet_markers(doc):
    """The glyphs this document's own classifier calls bullet markers.

    Modern HTML renders a bullet row as a real `<ul><li>`, where the
    marker is the LIST's, drawn by CSS -- so the typed glyph correctly
    does not appear in the markup, while Modern text and Modern RTF keep
    it. A format difference, not a defect in any of them, and the round
    trip has to know it. Read from `layout.classify_rows`' own verdicts,
    never from a hardcoded glyph list, so a marker the classifier
    discovers tomorrow is forgiven here too. Found by this check on its
    first run, on STRENGTH.WS."""
    out = set()
    for rows in emit._classify_modern_blocks(doc).values():
        for _line, structure in rows:
            if structure and structure.get('marker'):
                out.add(structure['marker'])
    return out


def words(text, markers=()):
    """The word sequence, whitespace-normalised -- what a round trip can
    honestly compare. Line breaks, indent columns and paragraph gaps are
    each format's own business; the WORDS are the document.

    The PAGE-BREAK MARK is dropped first, and it is the one thing this
    has to forgive: each format writes the same fact its own way -- a form
    feed in printed text, a twenty-dash rule in Modern text, `<hr
    class="pb">` in HTML, `\\page` in RTF -- and only the text one is made
    of characters a word split can see. Found by this check on its first
    run, and it is a real difference between the formats rather than a
    defect in any of them.

    `markers` does the same for a BULLET glyph HTML's own `<li>` consumed
    -- see `_bullet_markers`."""
    marks = set(markers)
    return [w for w in _PAGE_MARK.sub('', text).split() if w not in marks]


# ------------------------------------------------------------- the rows

@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_synthetic_rtf_is_structurally_sound(mode):
    doc = _synthetic()
    rtf = emit.emit_rtf(doc, mode=mode)
    assert rtf_brace_depth_errors(rtf) == []
    assert rtf_unknown_control_words(rtf) == []
    assert rtf_section_count(rtf) == len(emit._rtf_section_breaks(doc))


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_synthetic_html_parses_strictly(mode):
    assert html_body_xml_errors(emit.emit_html(_synthetic(), mode=mode)) == []


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_synthetic_exports_agree_about_the_words(mode):
    doc = _synthetic()
    marks = _bullet_markers(doc)
    text = words(emit.emit_text(doc, mode=mode), marks)
    assert words(rtf_to_text(emit.emit_rtf(doc, mode=mode)), marks) == text
    assert words(html_to_text(emit.emit_html(doc, mode=mode)), marks) == text


HARD = b'\x0d\x0a'


def _synthetic():
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    body = (b'.he First Head' + HARD
            + b'Opening paragraph of the document.' + HARD
            + b'.cp 3' + HARD + b'A Kept Heading' + HARD + HARD
            + b'Body under the heading.' + HARD
            + b'.co 2, 5' + HARD + b'Columnar text here.' + HARD
            + b'.cb' + HARD + b'Second column text.' + HARD
            + b'.co 1' + HARD + b'Back to one column.' + HARD
            + b'.pa' + HARD + b'.he Second Head' + HARD
            + b'After the head changed.' + HARD)
    return core.parse_ws(head + body)


@pytest.mark.sawyer
@pytest.mark.parametrize('name', CURATED)
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_curated_rtf_is_structurally_sound(require_sawyer_doc, name, mode):
    with open(require_sawyer_doc(name), 'rb') as fh:
        doc = core.parse(fh.read())
    rtf = emit.emit_rtf(doc, mode=mode)
    assert rtf_brace_depth_errors(rtf) == [], name
    assert rtf_unknown_control_words(rtf) == [], name
    assert rtf_section_count(rtf) == len(emit._rtf_section_breaks(doc)), name


@pytest.mark.sawyer
@pytest.mark.parametrize('name', CURATED)
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_curated_html_parses_strictly(require_sawyer_doc, name, mode):
    with open(require_sawyer_doc(name), 'rb') as fh:
        doc = core.parse(fh.read())
    assert html_body_xml_errors(emit.emit_html(doc, mode=mode)) == [], name


@pytest.mark.sawyer
@pytest.mark.parametrize('name', CURATED)
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_curated_exports_agree_about_the_words(require_sawyer_doc, name, mode):
    """THE ROUND TRIP. Read the RTF and the HTML back to plain text and
    compare, whitespace-normalised, with our own text export. Two exports
    of one document that disagree about the WORDS have a bug in one of
    them, and no byte comparison between engines can see it."""
    with open(require_sawyer_doc(name), 'rb') as fh:
        doc = core.parse(fh.read())
    marks = _bullet_markers(doc)
    text = words(emit.emit_text(doc, mode=mode), marks)
    assert words(rtf_to_text(emit.emit_rtf(doc, mode=mode)), marks) == text, (name, 'rtf')
    assert words(html_to_text(emit.emit_html(doc, mode=mode)), marks) == text, (name, 'html')
