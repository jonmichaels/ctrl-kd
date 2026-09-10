"""ctrl-kd PDF emitter — the page as it would have printed.

Hand-written PDF 1.4, zero dependencies: the base-14 Courier family needs no font
embedding and its fixed metrics make layout exact. That fits the tool's soul — a
WordStar document rendered as the typescript it was, on Letter pages:

  printed mode   line-for-line, form feeds / .pa / WordStar's own page breaks
                 honored — a facsimile of the 1990 printout, in the fonts and
                 sizes the document's own font blocks chose (base-14: Times,
                 Helvetica, Courier, Symbol, ZapfDingbats — still nothing
                 embedded, still zero dependencies), ON THE DOCUMENT'S OWN
                 LAYOUT GRID: each line advances by the `.lh` in force where it
                 appears, and each span starts at the x WordStar's own
                 per-character HMI advance puts it at (see _line_ops_printed)
  modern mode    reflowed paragraphs wrapped to the text column, headings bold,
                 footnotes at the end — still typewriter-set, still Courier

Styles: bold/italic map to the family's variants, underline is drawn,
superscript is raised and reduced. Non-Latin-1 characters degrade to '?'.
"""
import math as _math
import re as _re
import zlib as _zlib
from . import pix as _pixdecode
from .core import merged_lines as _merged_lines, Span as _Span, \
    trailing_blank_lines as _trailing_blank_lines, \
    effective_span_styles as _effective_span_styles, \
    detect_screenplay_blocks as _detect_screenplay_blocks, \
    sentence_spacing_texts as _sentence_spacing_texts, \
    resolve_sentence_spacing as _resolve_sentence_spacing, \
    line_numbering_checkpoints as _line_numbering_checkpoints, \
    line_numbering_at as _line_numbering_at, \
    _SCREENPLAY_SLUGLINE_RE, DEFAULT_LH_48, TAB_HMI_PER_COL as _TAB_HMI_PER_COL
from .emit import emitter, _printed, _annotated_notes, _ref_pairs, \
    _font_family, hf_runs as _hf_runs
from . import layout as _layout
from .symbolmap import font_translit_kind, untransliterate, SYMBOL_REVERSE, \
    symbol_fallback_kind
from .afm import string_width_pt as _natural_width_pt

PAGE_W, PAGE_H = 612, 792            # US Letter, points
MARGIN = 72                          # 1 inch
SIZE, LEAD = 12, 12                  # 10 CPI pica x 6 LPI — the dot-matrix standard;
                                     # a 65-col WordStar line is exactly 6.5in
TOP_MODERN, TOP_PRINTED = 72, 36     # printed: default when a stream has no geometry
                                     # meta (its margin blanks travel in-band); WS docs
                                     # get an .mt-derived top from _printed_top()
LINES_MODERN = (PAGE_H - 2 * 72) // LEAD                 # 54
# `.l#` line-numbering gutter (planning #247): right edge of the printed
# label, ABSOLUTE from the true page edge (x=0) -- WordStar column 4, 0.4in
# -- never relative to the document's own `.po`/left margin. Measured
# against real WS7 (ws7-prints/v4/sawyer__PRINT_EXT_TST.pcl, dosbox-x): the
# document's `.po .8"` (column 8, 57.6pt) puts body text at x=576 decipoints
# while a single-digit label sits at x=216..288 decipoints and a two-digit
# one at x=144..288 -- the SAME right edge (288 decipoints = 28.8pt) either
# way, confirming right-alignment to a fixed column, not a `.po`-relative
# one. WSFORMAT.TXT's own internal-format section (the 0Ch "Page offset"
# printer-driver record) calls this field an "Absolute HMI spot for line
# number", which is the same reading. One oracle value only (both real
# `.l#` occurrences in the Sawyer archive share the same `.po .8"`) -- a
# document with a narrower `.po` than this could in principle overlap its
# own body text; not observed, not guarded against.
LINE_NO_RIGHT_PT = 28.8
# Printed capacity is per-document: _printed_cap() -- WordStar's own model
# (.pl - .mt - .mb at the .lh line height; 55 for WordStar's defaults). The
# old hardcoded (PAGE_H - 2*36)//LEAD = 60 was a naive Letter computation
# that matched no WordStar the manual describes.
MAX_COLS = int((PAGE_W - 2 * MARGIN) / (SIZE * 0.6))     # 65 — WordStar's own margin

# Period-authentic footnote layout (Printed mode only -- WordStar Professional
# 5 manual, pp. 138-139, and the WSCHANGE factory-defaults table, WS7 manual):
FOOTNOTE_SEPARATOR = '-' * 20     # "Footnotes are separated from the text by a
                                  # line of 20 dashes." -- a fixed count, not
                                  # the text measure.
CONTINUATION_TEXT = '...Continued...'   # WSCHANGE factory default (footnote
                                        # continuation text)
FOOTNOTE_FLOOR = 3               # "A minimum of three lines of regular text
                                  # are printed on a page regardless of the
                                  # size of the footnote area" (except the
                                  # last page of the document)

def _landscape_page(page):
    """A copy of the page dict with height_in/pw_in SWAPPED -- `.pr or=l`
    (round 17, RULINGS-LEDGER row 2, register C18, Paged-surface doctrine
    point 2: "honor .pr or=l landscape in all paged surfaces"). Swapping
    at this single source lets every existing height_in/pw_in consumer
    (pagination capacity, top margin, the MediaBox itself) cascade
    correctly with no per-site change -- a landscape page is genuinely
    SHORTER top-to-bottom (fewer text lines fit) as well as wider, exactly
    what real landscape printing does. `.mt`/`.mb`/`.po`-derived margins
    are left untouched -- still top/bottom/left relative to the text, same
    as WordStar's own driver-level rotation never re-interpreted them."""
    eff = dict(page)
    eff['height_in'], eff['pw_in'] = (
        float(page.get('pw_in', 8.5)), float(page.get('height_in', 11.0)))
    return eff


def _resolved_page_height(doc, printed):
    """Page height in points for THIS document. Printed mode honours the
    file's own .pl-derived geometry (core.py's doc.meta['page']['height_in']
    -- file geometry wins for page size, best-effort). Modern mode does NOT:
    it deliberately reflows to fill its own fixed page rather than preserve
    the original measure (Printed is the faithfulness mode; Modern's whole
    point is a page that's simply pleasant to read), so it always renders at
    the fixed US Letter height regardless of what the file declares."""
    if not printed:
        return PAGE_H
    height_in = doc.meta.get('page', {}).get('height_in', 11.0)
    if height_in == 0:
        # `.pl 0` = page breaks off (bug 12284; see core._text_lines_per_page).
        # The text model already never breaks; the PDF page box itself falls
        # back to Letter -- a truly unbounded page is not expressible in PDF.
        return PAGE_H
    return max(LEAD * (FOOTNOTE_FLOOR + 1), round(height_in * 72))

def _printed_cap(doc):
    """Lines of vertical room on a printed page for THIS document -- the
    cap used both for plain pagination and as the footnote layout's page
    budget (see _paginate_printed_notes).

    WS documents carry doc.meta['page'] and get WordStar's own vertical
    model (core._text_lines_per_page: .pl - .mt - .mb at the .lh line
    height -- 55 for WordStar's defaults, NOT the 60 a naive 1in-margin
    computation gives).

    PRINT STREAMS GET THE SAME MODEL. Corrected 2026-08-03 (Jon's ruling:
    "printstreams need to follow WordStar standards, not our falsely invented
    ones"). This used to hand a print stream the FULL page height -- 66 lines
    on Letter -- justified by the claim that "their margin blanks travel
    in-band". That claim was checked against raw bytes and is FALSE for real
    print-to-disk output: such a stream carries no form feeds, and no top
    margin after its first page. It is not a stack of whole physical pages; it
    is a run of printed lines. Paginating it at 66 invented a page size
    WordStar does not document and no evidence supports.

    So a stream with no page metadata now falls back to WordStar's documented
    defaults, the same as a document that declares none: .pl 66 - .mt 3 - .mb 8
    = 55 lines. That is what WordStar 4 itself produces when run (its live
    output shows 11-line inter-page gaps = .mb 8 + .mt 3, on a 66-line pitch),
    and it makes the three renderings of one document -- the WS4 source, its
    print stream, and the live program -- finally agree.

    KNOWN LIMIT, recorded rather than papered over: a print stream that DOES
    carry its margins in band (WordStar 4's live output does) will now get
    margin on top of margin. Distinguishing the two cases needs evidence we do
    not have, and inventing a detector is exactly what this change undoes.

    SECOND KNOWN LIMIT, added with stateful `.lh` (2026-08-05). Capacity is
    computed at the DOCUMENT-DEFAULT line height -- core._text_lines_per_page
    on meta['page']['lh_48'], the file's first `.lh`. A document that changes
    leading mid-page therefore paginates at a fixed lines-per-page while its
    lines advance at their own leads, so a page of tightly-led text ends
    early and a page of banners can run long. Whether WordStar RECOMPUTED
    lines-per-page as `.lh` changed is UNMEASURED -- register open question
    #15 -- and the honest options (recompute per line, or accumulate points
    until the text height is used up) are different answers to a question no
    manual page settles. Guessing here would silently repaginate every
    multi-`.lh` document on an assumption; leaving capacity where the
    evidence is keeps the change to what was ruled: leads, not pagination."""
    page = doc.meta.get('page')
    if page is not None:
        return max(FOOTNOTE_FLOOR + 1, page.get('text_lines', 55))
    from .core import (DEFAULT_PL_LINES, DEFAULT_MT_LINES, DEFAULT_MB_LINES,
                       DEFAULT_LH_48, _text_lines_per_page)
    return max(FOOTNOTE_FLOOR + 1,
               _text_lines_per_page(DEFAULT_PL_LINES, DEFAULT_MT_LINES,
                                    DEFAULT_MB_LINES, DEFAULT_LH_48))


def _printed_cap_for(doc, mt_lines, mb_lines, pl_lines=None):
    """`_printed_cap`, but for an EXPLICIT (mt, mb) pair instead of the
    document's global first-occurrence values -- Finding 3
    (b26-print-fidelity-2)'s per-page capacity; see `_mt_mb_checkpoints`.

    `pl_lines` (register b31-dot-command-sweep, `_pl_checkpoints`): `.pl`
    is STATEFUL exactly like `.mt`/`.mb` -- measured against real WS7
    (PL_PROBE, dosbox-x): a document holding `.mt`/`.mb` fixed and setting
    `.pl 20` then `.pl 40` mid-document printed 18 lines on page 1 (cap =
    20-1-1) and 38 on page 2 (cap = 40-1-1) -- the SECOND value, not the
    first, governs the page that follows it. None means "no page-specific
    override", i.e. use the document's own global first-occurrence `.pl`
    (every document that never repeats `.pl` mid-document).
    `doc.meta['page']['text_lines']` is a value CACHED at parse time from
    the document's global mt/mb (core.py's own `_text_lines_per_page`
    call) -- calling that same function directly here, rather than
    reading the cache, is what makes a page whose (mt, mb) MATCHES the
    global pair come out byte-identical (same formula, same inputs) while
    a page that changes them gets its own true capacity.

    NEVER BELOW the document's own global capacity (b26-mtmb-general,
    LJ6DTP.WS): a mid-document margin change may LOOSEN a page (more
    room than the document's own declared default) but WS7 does not let
    one TIGHTEN it. Reconciled from two real WS7 captures whose mid-
    document `.mt`/`.mb` changes point opposite directions:
      SCRIPT.WS block 64 (`.mt1`/`.mb0`, Figure 1's own tiny margins):
        local cap 65 > global cap 53 (pl 66 - mt 7 - mb 6, its own `.MT
        7`/`.MB 6`) -- HONORED. WS7 fits the whole figure on one page
        (measured: SCRIPT.pcl page count 11, matching only when this
        local cap is used).
      LJ6DTP.WS block 12 (`.mt1"`/`.mb1"`, right after the SAME kind of
        `.pa`-then-margin-restate SCRIPT's own figures use): local cap
        46 (pl 66 - mt 6.0 - mb 6.0) < global cap 48 (pl 66 - mt 6.6 -
        mb 3.0, its own `.mt 1.1"`/`.mb .5"`) -- NOT honored. WS7's
        "Proportional Spacing Tables" section (measured: LJ6DTP.pcl,
        page 7 of 8) prints on ONE page; using the tighter local cap
        splits it across two, one page too many (9 engine vs WS7's 8).
    Both obey `cap = max(local, global)` with no exception -- the ONE
    rule shape that fits both real captures pointing opposite ways.
    Applying the SAME clamp per-field (e.g. only to `.mb`, treating
    `.mt` differently) was considered and rejected: LJ6DTP's own `.mt`
    change (6.6 -> 6.0, negligible) can't discriminate between "mb never
    applies mid-document" and "mb is clamped" from this evidence alone,
    but "mb never applies" independently FAILS SCRIPT (whose `.mb0` must
    be honored) while the whole-cap max does not -- so the max is the
    narrower, non-file-specific reading of what's actually measured."""
    page = doc.meta.get('page')
    from .core import DEFAULT_PL_LINES, DEFAULT_LH_48, _text_lines_per_page
    pl = pl_lines if pl_lines is not None else (page or {}).get('pl_lines', DEFAULT_PL_LINES)
    lh = (page or {}).get('lh_48', DEFAULT_LH_48)
    local = max(FOOTNOTE_FLOOR + 1,
               _text_lines_per_page(pl, mt_lines, mb_lines, lh))
    return max(local, _printed_cap(doc))


def _mt_mb_checkpoints(doc):
    """[(block_index, mt_lines, mb_lines), ...] in ascending block order --
    the .mt/.mb pair IN FORCE from that block onward, at BLOCK granularity
    (the coarsest anchor doc.meta['dot_positions'] gives -- core.py's own
    per-dot-command position record, (block_index, line_index, cmd), the
    same mechanism Soft Return.app's Show Invisibles and this file's own
    `_toc_page_numbers` already read). Mirrors how `.lh` already tracks
    per-LINE state (Line.lead_48/`_style_lead_pt`) -- one level coarser,
    because .mt/.mb only take visible effect at the next page start, never
    mid-line.

    The FIRST checkpoint (block 0) is the document's own global
    mt_lines/mb_lines (core.py's "first occurrence wins" page dict) -- a
    document that never touches .mt/.mb again after its own opening
    geometry gets exactly ONE checkpoint, so every page's lookup returns
    the SAME pair the document-global functions already gave it: no
    behaviour change for any document but the ones this exists for.

    Finding 3 (b26-print-fidelity-2): SCRIPT.WS changes both mid-document,
    around its embedded worked-example figures -- measured (ARTICLES/
    SCRIPT.WS's own dot-command bytes, via doc.meta['dot_positions']):
    block 64 sets `.mt1`/`.mb0` (Figure 1's near-zero margins), block 75
    sets `.mt1"`/`.mb1"` (Figure 2's own, different margins)."""
    page = doc.meta.get('page') or {}
    from .core import DEFAULT_MT_LINES, DEFAULT_MB_LINES, _resolve_lines_arg
    mt = page.get('mt_lines', DEFAULT_MT_LINES)
    mb = page.get('mb_lines', DEFAULT_MB_LINES)
    checkpoints = [(0, mt, mb)]
    for bi, _li, cmd in doc.meta.get('dot_positions', ()):
        m = _MT_MB_CMD_RE.match(cmd)
        if not m:
            continue
        name, value, unit = m.group(1).upper(), float(m.group(2)), m.group(3)
        resolved = _resolve_lines_arg(value, unit.encode() if unit else None)
        if name == 'MT':
            mt = resolved
        else:
            mb = resolved
        if (mt, mb) != checkpoints[-1][1:]:
            checkpoints.append((bi, mt, mb))
    return checkpoints


_MT_MB_CMD_RE = _re.compile(r'^\.(MT|MB)\s*([0-9.]+)\s*("|[A-Za-z]{1,2})?',
                            _re.IGNORECASE)


def _mt_mb_at(checkpoints, bi):
    """(mt_lines, mb_lines) in force at block index `bi`, per `checkpoints`
    (ascending, from `_mt_mb_checkpoints`) -- the LAST checkpoint at or
    before `bi`."""
    mt, mb = checkpoints[0][1], checkpoints[0][2]
    for cp_bi, cp_mt, cp_mb in checkpoints:
        if cp_bi > bi:
            break
        mt, mb = cp_mt, cp_mb
    return mt, mb


def _pl_checkpoints(doc):
    """[(block_index, pl_lines), ...] in ascending block order -- the `.pl`
    IN FORCE from that block onward. Mirrors `_mt_mb_checkpoints` exactly
    (same mechanism, same `dot_positions` anchor, same "block 0 is the
    document's own global first-occurrence value" contract) -- kept as its
    OWN function/list rather than folded into `_mt_mb_checkpoints` because
    `.pl` was found and fixed separately (register b31-dot-command-sweep),
    on its own oracle evidence, months after the mt/mb mechanism shipped;
    see that function's docstring for why the shape is what it is.

    Real WS7 evidence (PL_PROBE, dosbox-x, 2026-08-25): a document that
    holds `.mt`/`.mb` fixed at 1 line each and sets `.pl 20` then, after
    exactly one page's worth of body, `.pl 40`, printed 18 lines on page 1
    (cap = pl 20 - mt 1 - mb 1) and 38 on page 2 (cap = pl 40 - mt 1 - mb
    1) -- the page AFTER the second `.pl` uses ITS value, not the
    document's first. Before this, `_parse_page_dot`'s "first occurrence
    wins" was the ONLY reading anywhere in the pipeline: every page of
    such a document got the page-1 capacity forever.

    Seeded at WordStar's own HARDCODED default (`DEFAULT_PL_LINES`), never
    at `doc.meta['page']['pl_lines']` (core.py's first-occurrence reading)
    -- those are the SAME number for a document that declares `.pl` right
    at its own start (the overwhelming common case, and every document
    `_mt_mb_checkpoints` was built against), but NOT for one whose only
    `.pl` sits mid-document with nothing before it: core.py's "first
    occurrence wins" would read THAT single occurrence as the document's
    global default and hand it back for block 0 too, retroactively
    applying the mid-document value to pages that printed before the
    command was ever reached. Caught building `_hm_fm_checkpoints`
    (below) against HMFM_PROBE, whose only `.hm`/`.fm` are mid-document --
    fixed here too since `.pl` shares the exact same construction."""
    from .core import DEFAULT_PL_LINES, _resolve_lines_arg
    checkpoints = [(0, DEFAULT_PL_LINES)]
    for bi, _li, cmd in doc.meta.get('dot_positions', ()):
        m = _PL_CMD_RE.match(cmd)
        if not m:
            continue
        value, unit = float(m.group(2)), m.group(3)
        resolved = _resolve_lines_arg(value, unit.encode() if unit else None)
        if resolved != checkpoints[-1][1]:
            checkpoints.append((bi, resolved))
    return checkpoints


_PL_CMD_RE = _re.compile(r'^\.(PL)\s*([0-9.]+)\s*("|[A-Za-z]{1,2})?',
                         _re.IGNORECASE)


def _pl_at(checkpoints, bi):
    """`pl_lines` in force at block index `bi`, per `checkpoints` (ascending,
    from `_pl_checkpoints`) -- the LAST checkpoint at or before `bi`."""
    pl = checkpoints[0][1]
    for cp_bi, cp_pl in checkpoints:
        if cp_bi > bi:
            break
        pl = cp_pl
    return pl


def _hm_fm_checkpoints(doc):
    """[(block_index, hm_lines, fm_lines), ...] in ascending block order --
    the `.hm`/`.fm` pair IN FORCE from that block onward. Mirrors
    `_mt_mb_checkpoints` exactly (same `dot_positions` anchor, same
    "block 0 is the document's own global first-occurrence pair"
    contract) -- kept as its own pair/function rather than folded into
    `_mt_mb_checkpoints` because `.hm`/`.fm` were found and fixed
    together, sharing one dot-command regex, months after the mt/mb
    mechanism shipped (mirrors `_pl_checkpoints`'s own docstring, which
    gives the identical reason for staying separate). `_running_ops`'s
    own `head_base` no longer gates `hm`'s participation on `mt_source`
    at all (mechanism W, PCL-DIVERGENCE-TRIAGE.md) -- it reads whatever
    `hm_lines` this checkpoint pair resolves to for the page unconditionally.

    Real WS7 evidence (HMFM_PROBE, dosbox-x, register b31-dot-command-
    sweep): a document that never touches `.mt` (stays at the factory
    default throughout) but sets `.hm 6`/`.fm 6` mid-document (factory
    default is `.hm 2`/`.fm 2`) printed its header/footer at TWO
    different PCL rows -- 35.7pt/75.6pt on the pages before the change,
    12.0pt/80.4pt on the pages after it -- even though `.mt` itself never
    moved. Before this, `_running_ops`/`_printed_top` read `hm_lines`/
    `fm_lines` from `doc.meta['page']` alone (`_parse_page_dot`'s "first
    occurrence wins" reading, and the ONLY reading anywhere in the
    pipeline): every page of such a document rendered its header/footer
    at the SAME row forever, using whichever `.hm`/`.fm` happened to be
    the document's first (or, if `.hm`/`.fm` never appeared before the
    mid-document one, that later value -- applied from the very first
    page, which is equally wrong the other direction).

    Seeded at WordStar's own hardcoded defaults (`DEFAULT_HM_LINES`/
    `DEFAULT_FM_LINES`), NOT `doc.meta['page']['hm_lines']`/`fm_lines`
    (core.py's first-occurrence reading) -- HMFM_PROBE is exactly the
    degenerate case that distinguishes them: its `.hm`/`.fm` appear only
    ONCE, mid-document, so "first occurrence wins" reads that single
    occurrence as the document's global default and would otherwise hand
    it back for block 0 too, retroactively applying the mid-document
    value to the pages that printed before the command was ever reached.
    See `_pl_checkpoints`'s docstring -- same fix, same reason."""
    from .core import DEFAULT_HM_LINES, DEFAULT_FM_LINES, _resolve_lines_arg
    hm, fm = DEFAULT_HM_LINES, DEFAULT_FM_LINES
    checkpoints = [(0, hm, fm)]
    for bi, _li, cmd in doc.meta.get('dot_positions', ()):
        m = _HM_FM_CMD_RE.match(cmd)
        if not m:
            continue
        name, value, unit = m.group(1).upper(), float(m.group(2)), m.group(3)
        resolved = _resolve_lines_arg(value, unit.encode() if unit else None)
        if name == 'HM':
            hm = resolved
        else:
            fm = resolved
        if (hm, fm) != checkpoints[-1][1:]:
            checkpoints.append((bi, hm, fm))
    return checkpoints


_HM_FM_CMD_RE = _re.compile(r'^\.(HM|FM)\s*([0-9.]+)\s*("|[A-Za-z]{1,2})?',
                            _re.IGNORECASE)


def _hm_fm_at(checkpoints, bi):
    """(hm_lines, fm_lines) in force at block index `bi`, per `checkpoints`
    (ascending, from `_hm_fm_checkpoints`) -- the LAST checkpoint at or
    before `bi`."""
    hm, fm = checkpoints[0][1], checkpoints[0][2]
    for cp_bi, cp_hm, cp_fm in checkpoints:
        if cp_bi > bi:
            break
        hm, fm = cp_hm, cp_fm
    return hm, fm


def _po_checkpoints(doc):
    """[(block_index, po_cols), ...] in ascending block order -- the `.po`
    (page offset) IN FORCE from that block onward. Mirrors `_pl_checkpoints`
    exactly (same `dot_positions` anchor, same "block 0 is the document's
    own global first-occurrence value" contract, same reason for seeding at
    WordStar's hardcoded default rather than `doc.meta['page']['po_cols']`
    -- see `_pl_checkpoints`'s docstring).

    Body text already carries a mid-document `.po` change correctly:
    core.py stamps `Line.po_cols` on every physical line (state carried
    forward exactly like `.lh`), and `_page_stream` overrides its own
    `left` per line whenever a line's `po_cols` differs from the document
    default (`_resolve_left_pt(line.po_cols, ...)`). `_running_ops`
    (the header/footer row) had NO equivalent -- it always rendered at the
    document's global `left`, regardless of which page it was on.

    SCRIPT.WS (sawyer archive) is the oracle: its own worked-example
    figures reset `.po` to `.5"` (5 columns, `.po.5"`/`.po .5"`) around
    block 64 and again around block 75/84, alongside the `.mt`/`.hm`
    changes `_mt_mb_checkpoints`/`_hm_fm_checkpoints` already track for
    the SAME figures. WS7's own capture (`ws7-prints/v1/SCRIPT.pcl`)
    prints the running head "PROFILES MONTH '88 SCRIPT.001..." on the
    figure pages starting at x=36.0pt (column 5, the figure's own local
    `.po .5"`) -- this engine, reading only the document's global `.po`
    default (8 columns, 57.6pt), rendered it 21.6pt (3 columns) too far
    right. Confirmed genuine LaserJet PCL (PJL `ENTER LANGUAGE=PCL`,
    `ESC(s...T` font selection), not a different driver family's own
    margin convention -- see `tools/PCL-DIVERGENCE-TRIAGE.md`."""
    from .core import DEFAULT_PO_COLS, _resolve_cols_arg
    checkpoints = [(0, DEFAULT_PO_COLS)]
    for bi, _li, cmd in doc.meta.get('dot_positions', ()):
        m = _PO_CMD_RE.match(cmd)
        if not m:
            continue
        value, unit = float(m.group(1)), m.group(2)
        resolved = _resolve_cols_arg(value, unit.encode() if unit else None)
        if resolved != checkpoints[-1][1]:
            checkpoints.append((bi, resolved))
    return checkpoints


_PO_CMD_RE = _re.compile(r'^\.PO\s*([0-9.]+)\s*("|[A-Za-z]{1,2})?',
                         _re.IGNORECASE)


def _po_at(checkpoints, bi):
    """`po_cols` in force at block index `bi`, per `checkpoints` (ascending,
    from `_po_checkpoints`) -- the LAST checkpoint at or before `bi`."""
    po = checkpoints[0][1]
    for cp_bi, cp_po in checkpoints:
        if cp_bi > bi:
            break
        po = cp_po
    return po


_POE_CMD_RE = _re.compile(r'^\.POE\b', _re.IGNORECASE)
_POO_CMD_RE = _re.compile(r'^\.POO\b', _re.IGNORECASE)


def _poe_poo_checkpoints(doc, pattern):
    """[(block_index, po_cols), ...] the `.poe`/`.poo` (page 231: even/odd
    page-offset) override IN FORCE from that block onward, per `pattern`
    (`_POE_CMD_RE`/`_POO_CMD_RE`) -- EMPTY if the document never uses that
    command (unlike `_po_checkpoints`, no block-0 seed: WordStar has no
    hardcoded default for a parity-specific offset, "never set" genuinely
    means "no override," resolved by falling back to whichever of `.po`/
    the other parity governs instead -- see `_left_for_parity`).

    Uses `core._dot_num_match` (WordStar 4.0+'s own dot-command math,
    WSFORMAT.TXT) rather than `_PO_CMD_RE`'s plain-decimal pattern: the one
    real corpus document that depends on this (sawyer/REF/-HOW-TO.RJS)
    writes both as arithmetic (`.poe 0.50-0.20"`, `.poo
    0.50+4.50+1.00-0.20"`), never a bare number."""
    from .core import _dot_num_match, _resolve_cols_arg
    checkpoints = []
    for bi, _li, cmd in doc.meta.get('dot_positions', ()):
        m = pattern.match(cmd)
        if not m:
            continue
        num = _dot_num_match(cmd[m.end():].encode('latin-1', 'replace'))
        if not num or not num.group(1):
            continue
        resolved = _resolve_cols_arg(float(num.group(1)), num.group(2))
        if resolved is None:
            continue
        if not checkpoints or resolved != checkpoints[-1][1]:
            checkpoints.append((bi, resolved))
    return checkpoints


def _left_for_parity(po, poe, poo, is_even):
    """The resolved `po_cols` for a page of the given parity (planning
    #231): its OWN parity override if one is in force (`poe`/`poo`, each
    already `_po_at`-resolved or None -- see `_poe_poo_checkpoints`), else
    whatever plain `.po` governs. Brief's own rule: "odd pages use .poo
    (or .po), even pages .poe (or .po)."""
    if is_even:
        return poe if poe is not None else po
    return poo if poo is not None else po


def _pn_checkpoints(doc):
    """[(block_index, pn_value), ...] in ascending block order -- a `.pn`
    RE-ANCHORS the automatic page-number sequence starting on the page it
    appears on (WSFORMAT: ".PN ... Sets the starting page number"), it
    does not merely set the document's own opening number once. Measured
    on WordStar 4, 2026-08-03 (`_PAGE_DOT_KEYS`'s own comment): a single
    `.pn 7` numbers the pages 7, 8, 9 -- that finding never tested a
    SECOND `.pn` later in the same document, which is what `.pn` shares
    with every other command register b31-dot-command-sweep found: real
    WS7 (PN_PROBE, dosbox-x) printed page 1 as "10", page 2 as "11" (a
    `.pn 10` up front, incrementing normally), then page 3 as "500" and
    page 4 as "501" once a mid-document `.pn 500` was reached -- the
    SECOND value re-anchors the count from the page it lands on, exactly
    like the first. Before this, `pn_start` (core.py's "first occurrence
    wins" reading of `.pn`) was read ONCE, globally: every page after the
    first got `pn_start + page_index`, so a document with two `.pn`
    commands numbered every page after the change wrong.

    Seeded at 1 (WordStar's own hardcoded starting number), same reason
    `_pl_checkpoints`/`_hm_fm_checkpoints` seed at the hardcoded default
    rather than `doc.meta['page']['pn_start']` -- see their docstrings."""
    from .core import _resolve_lines_arg
    checkpoints = [(0, 1)]
    for bi, _li, cmd in doc.meta.get('dot_positions', ()):
        m = _PN_CMD_RE.match(cmd)
        if not m:
            continue
        try:
            value = int(float(m.group(1)))
        except (TypeError, ValueError):
            continue
        if value != checkpoints[-1][1]:
            checkpoints.append((bi, value))
    return checkpoints


_PN_CMD_RE = _re.compile(r'^\.PN\s*([0-9.]+)', _re.IGNORECASE)


def _resolve_page_numbers(pn_checkpoints, pages):
    """[page_number, ...], one per `pages` (ascending, from
    `_doc_to_pagelines`) -- walks the pages in order, re-anchoring to a
    `.pn` checkpoint's own value on whichever page its block index first
    lands on (WordStar's own "sets the number of the page it appears on"),
    otherwise continuing the previous page's number by one. A page with
    no `.bi`-carrying line at all (should not happen for real content,
    but a synthetic/degenerate page is handled rather than crashed on)
    just continues the count.

    A checkpoint is consumed (matched to a page) at most once, by the
    FIRST page whose own block range reaches it -- `applied_bi` tracks
    the highest checkpoint block index already used, so a checkpoint
    sitting mid-page is applied to THAT page (not the next one) and never
    re-applied to a later page that also happens to satisfy `cp_bi <=
    page_max_bi`."""
    numbers = []
    current = None
    applied_bi = -1
    for pg in pages:
        bis = [bi for bi in (getattr(ln, 'bi', None) for ln in pg) if bi is not None]
        page_max_bi = max(bis) if bis else None
        candidate = None
        if page_max_bi is not None:
            for cp_bi, cp_val in pn_checkpoints:
                if applied_bi < cp_bi <= page_max_bi:
                    candidate = (cp_bi, cp_val)     # last match in range wins
        if candidate is not None:
            applied_bi, current = candidate
        elif current is None:
            current = pn_checkpoints[0][1]
        else:
            current += 1
        numbers.append(current)
    return numbers


# no `\b` after the 2-letter code (matches `_PN_CMD_RE`'s own shape,
# immediately below in this same module): a real WS7 file overwhelmingly
# writes `.pn0`/`.pn22`/`.hm3` with NO space before the argument, and `\b`
# between two WORD characters (a letter then a digit) never matches --
# `_parse_page_dot`'s own `_PAGE_DOT_KEYS` regex has the identical shape
# for exactly this reason. Caught on real corpus content (HOLYMAC.WS's own
# `.pn0`/`.pn1`/`.pn22`/... chapter restarts, all silently missed by a
# first `\b`-bearing draft of this pattern).
_PGNUM_ON_RE = _re.compile(r'^\.(PN|PG)', _re.IGNORECASE)
_PGNUM_OFF_RE = _re.compile(r'^\.OP', _re.IGNORECASE)


def _pgnum_checkpoints(doc):
    """[(block_index, enabled), ...] ascending -- whether WordStar's
    AUTOMATIC page number (the one `.pc` positions; WSFORMAT.WS's own text:
    ".PC ... active only when the footers are not in use and page numbering
    is turned on") is ON from that block onward. Mirrors `_pn_checkpoints`'s
    shape exactly (same `dot_positions` anchor, "last checkpoint at or
    before this block wins" contract, via `_pgnum_at` below).

    Seeded ON -- WordStar 7's stock factory default state (WSCHANGE ships
    the automatic page number ON, centered at the bottom margin, unless
    `.op` turns it off). REVERSED 2026-09-07 (ws7-prints/v3, the
    PRISTINE.EXE recapture, finding #2 -- v3/README.md): every one of
    BOXES/SAWYER/VERSIONS/-README plus several private-corpus documents, none of which
    touch `.pn`/`.pg`/`.op`/`.pc`, prints a bottom-of-page "1"/"2"/"3"...
    under a genuinely stock (PRISTINE.EXE) install, confirmed at the raw
    PCL byte level -- and the engine's OWN existing `.po`/`.pc`-derived x
    position (`_auto_pageno_x_pt`) already lands EXACTLY on that number's
    measured position (291.6pt for `.po` 8, the stock default) once
    `auto_page_number` is forced True, so only this toggle's default was
    wrong, not its geometry.

    Previously seeded OFF, MEASURED (dosbox-x, E3 item 2, register b31,
    2026-08-25) against the harness tree's Sawyer-install `WS.EXE` --
    Robert J. Sawyer's own WSCHANGE-customized install, per the SAME
    contamination `.po` column 7 vs 8 (mechanism S, `aac4b38`/`350270b`)
    already traced to that install and reverted for: Sawyer's WSCHANGE
    profile turned the automatic number OFF by default, stock WS7 does
    not. BARE_PROBE/PC_PROBE's "no number at all" result was real for
    THAT install, just not for stock WordStar 7.

    `.pn` (ANY occurrence -- WSFORMAT: "sets the starting page number";
    real WS7 measured this as "yes, number the pages": PN_ONLY_PROBE, a
    bare `.pn 5` with no header/footer/`.pg` at all, printed a
    bottom-of-page "5"/"6"/"7") and `.pg` (WSFORMAT's own documented
    re-enable after `.op`) both turn it ON (a no-op against this new
    default, since it is already ON); `.op` turns it OFF -- unaffected by
    this change, still the only way a document reaches "no number".
    OPPG_PROBE (`.op`, ~1 page, then a mid-document `.pg`, ~2 more pages,
    no `.pn` anywhere) confirmed the toggle is genuinely stateful
    mid-document -- page 1 (under `.op`): no number; pages 2-3 (after
    `.pg`): "2"/"3", the ordinary physical page count.

    This is the engine for `--page-numbers auto` (the default): the
    document's own dot commands decide, byte-identical to every existing
    capture/oracle for the overwhelming majority of documents that never
    touch any of these four commands (they now get the stock automatic
    number instead of none). `--page-numbers on`/`off` bypass this
    entirely (see `_emit_pdf_inner`'s own call site)."""
    checkpoints = [(0, True)]
    for bi, _li, cmd in doc.meta.get('dot_positions', ()):
        if _PGNUM_ON_RE.match(cmd):
            value = True
        elif _PGNUM_OFF_RE.match(cmd):
            value = False
        else:
            continue
        if value != checkpoints[-1][1]:
            checkpoints.append((bi, value))
    return checkpoints


def _pgnum_at(checkpoints, bi):
    """Whether the automatic page number is ON at block index `bi`, per
    `checkpoints` (ascending, from `_pgnum_checkpoints`) -- the LAST
    checkpoint at or before `bi`, mirroring `_pl_at`/`_hm_fm_at`."""
    on = checkpoints[0][1]
    for cp_bi, cp_on in checkpoints:
        if cp_bi > bi:
            break
        on = cp_on
    return on


# Measured (dosbox-x, E3 item 2, register b31, 2026-08-25): the automatic
# page number's LEFT edge sits at column `(po_cols + pc_col - 1)` in the
# SAME 10-CPI frame `.po`/`.lm`/`.rm`/`.pm` share (`_PDF_PT_PER_COL`),
# regardless of how many digits the number itself has (PN998_PC10_PROBE: a
# 3-digit "998"/"999" landed at the IDENTICAL x as the 1-digit "5"/"6" case
# at the same `.pc`/`.po` pair -- LEFT-anchored, not right-anchored or
# centred on the string itself). Confirmed relative to `.po`, not absolute
# from the page edge: PO_PC_PN_PROBE (`.po 20`, `.pc 10`, x=2088pt/10) and
# PN_PC10_PROBE (`.po` at this install's own factory-configured 7.0, `.pc
# 10`, x=1152pt/10) both fit the SAME formula exactly once `.po` is added
# in; a plain `N * 7.2pt` (ignoring `.po`) does not.
#
# `.pc 0` (WSFORMAT.WS's own text: "If the column specified is 0, then the
# page number is centered between the margins in effect") and `.pc` NEVER
# DECLARED AT ALL produced the IDENTICAL position in every probe (PC0_
# PROBE vs PN_ONLY_PROBE/PO_PN_NODEFAULT_PROBE) -- "unset" and "0" are the
# SAME internal state. But the manual's own "centered between the margins"
# claim does NOT hold in this install/driver as measured: PC0_RM40_PROBE
# (`.rm 40`, `.pc 0`) landed at the IDENTICAL x as PC0_PROBE (`.rm` at this
# install's own default, `.pc 0`) -- no dependency on `.rm` at all, twice
# confirmed (RM_PN_PROBE, no `.pc` either, also unaffected by `.rm 40`).
# Measured bytes beat manual prose (`_printed_left`'s own precedent, same
# doctrine): the "0/unset" case resolves to this FIXED measured column
# instead of a dynamically computed lm/rm midpoint. Fit from two
# independent `.po` values (7.0 exactly, 20.0 exactly) with zero decipoint
# residual either way -- not a guess, and not (yet) traced to a WSCHANGE
# factory constant, so it may be THIS install's own customisation the same
# way its `.po` 7.0 (vs the manual's 8.0) is; flagged, not hidden.
_AUTO_PAGENO_DEFAULT_COL = 33.5


def _auto_pageno_x_pt(doc):
    """Left edge (points) of the automatic page number's text, from `.po`/
    `.pc` -- see `_AUTO_PAGENO_DEFAULT_COL`'s docstring for the formula's
    own measurement. `pc_col` 0 or unset (`page.get('pc_col')` is None or
    falsy either way -- both measured identical) uses the fixed default;
    an explicit non-zero `.pc N` overrides it."""
    page = doc.meta.get('page') or {}
    po = page.get('po_cols', 8.0)
    pc = page.get('pc_col') or _AUTO_PAGENO_DEFAULT_COL
    return (po + pc - 1) * _PDF_PT_PER_COL


def _printed_top(doc):
    """Top-of-text offset in points for printed mode: the bottom edge of
    WS7's reserved TOP-MARGIN zone (`.mt`, lines at 6 LPI -> 12pt each;
    the default `.mt 3` = 36pt). Print streams keep the fixed 36pt --
    their own top-margin blanks are in the data (minus the machine-margin
    strip in _doc_to_pagelines). Clamped inside the page so garbage `.mt`
    from a misdetected binary degrades to an ugly page, never an absurd
    coordinate space.

    Mechanism U (PCL-DIVERGENCE-TRIAGE.md, `ws7-prints/v3` PRISTINE.EXE
    round): `.hm` is NEVER added on top of `.mt`, matching the WS7
    manual's own dot-command reference, already quoted in this module for
    the symmetric `.mb`/`.fm` case (`core._text_lines_per_page`'s
    docstring: "the header is printed WITHIN this margin"). This function
    used to add `.hm` (2 lines, 24pt) whenever `.mt` was left at its
    document default -- see the "INCLUDES `.hm`" history below, all of it
    measured ONLY against `ws7-prints/v1`/`v2`, both captured through
    Robert J. Sawyer's own WSCHANGE-customized `WS.EXE` (the SAME install
    mechanisms S and T already found responsible for the `.po` and
    auto-leading contaminations). A `PRISTINE.EXE` (factory, no WSCHANGE)
    recapture of 4 default-`.mt` documents settles it: every one measures
    its first real content line at EXACTLY `.mt` alone (36pt) + that
    line's own entering lead, a clean, zero-residual fit --

    | Doc | First line | `ws7-prints/v1` (Sawyer) | `ws7-prints/v3` (pristine) | v1-v3 delta |
    |---|---|---:|---:|---:|
    | OCAPTAIN | "O CAPTAIN! MY CAPTAIN!" (12pt) | 71.7pt | 48.0pt | 23.7pt |
    | BOXES | box-drawing top rule (12pt) | 71.7pt | 48.0pt | 23.7pt |
    | SAWYER | "===...===" rule (12pt) | -- | 48.0pt | -- |
    | LYING | "On the Decay..." title (16pt, `.pm` style, `mt_source` default) | 78.9pt | 52.0pt | 26.9pt |
    | WARPRAYR | "The War Prayer" title (16pt, style, `mt_source` default) | -- | 52.0pt | -- |

    36 (`.mt` alone) + 12 (OCAPTAIN/BOXES/SAWYER's own 12pt entering lead)
    = 48.0pt, exactly; 36 + 16 (LYING/WARPRAYR's 16pt Title style, at
    `AUTO_LEAD_FACTOR` 1.0 -- mechanism T) = 52.0pt, exactly -- zero
    residual across every family this corpus has (fixed-pitch default
    lead, and a styled title), on both a `mt_source == 'default'` document
    (all 5 above) and PREVIEW's own explicit-`.mt` case (unaffected by
    this change either way, see below). `ws7-prints/v1`'s uniform ~24-27pt
    EXTRA gap on the SAME 5 documents (measured directly against the SAME
    real files, not a different corpus) is Sawyer's own `.hm`-adds-to-`.mt`
    customization, not stock WS7's -- the pattern is invisible in this
    module's own `pcl` tier verdicts because it is a UNIFORM per-page
    offset (identical for every line on the page, title included), which
    the tier's own per-page median-dy calibration silently absorbs as
    "the page's own consistent calibration" -- the exact masking mechanism
    S's own docstring already named for `.po`, now confirmed on the
    vertical axis too. See `document_frame_offset_pt`'s own docstring in
    `tools/pcl_tolerance.py` for the analogous absolute (unmasked) check
    on the horizontal axis; no vertical equivalent exists yet as of this
    fix (recorded, not built, out of this round's scope).

    ---- history below, superseded by the above ----

    INCLUDES `.hm` (round 26 wave 3, fidelity_gate.py Unit B). Measured
    2026-08-20 against real WS7 PCL captures (ws7-prints/v1): every
    default-geometry Courier document's first baseline sits at PCL
    y=71.7pt (OCAPTAIN/TWAINLET/SAWYER/VERSIONS/BOXES + the private WS4 trio, all
    IQR=0.0 across the matched corpus) -- NOT the 48pt (.mt 3 * 12 + 12pt
    baseline-within-line) this function used to return before the +size
    term was folded in at the call site. (.mt 3 + .hm 2) * 12 = 60pt,
    +12pt for the first line's own baseline-within-line (see _page_stream)
    = 72pt, a 0.3pt residual against the measured 71.7pt -- decipoint
    (1/720in) rounding in the WS7 driver's own arithmetic, not a modelling
    gap. This entire measurement, per mechanism U above, was of Sawyer's
    own install, not stock.

    NO LONGER SPECIAL-CASED FOR HEADERED DOCUMENTS (round 26, fidelity_gate.py
    Finding A -- reversing the headerless scoping above). The prior version of
    this function returned `.mt` ALONE (36pt) whenever `doc.headers` or
    `doc.footers` was non-empty, reasoning from a WS4 measurement
    (`_running_ops`'s docstring, `test_head_foot_land_where_wordstar_puts_them`)
    that a header's `.hm` gap sits INSIDE `.mt`, not additional to it. Mechanism
    U now confirms that WS4 finding was right about STOCK WS7 all along --
    `.hm` is always within `.mt`, headered document or not -- and -README's
    own body-vs-header split (used at the time to argue the opposite) was
    itself measuring the Sawyer-install `.hm` contamination on the BODY side
    while its header (`_running_ops`, a separate computation) happened to
    stay correct.

    PREVIEW.WS is unaffected by this change either way: it declares its
    OWN `.mt` explicitly (`mt_source == 'file'`, 4.98 lines -- a
    WSFORMAT-style non-integer .mt, likely typed as a decimal inch value),
    and both its `ws7-prints/v1` and `v3` captures already match `.mt`
    ALONE (round(4.98*12)=60, +12+12 for this headerless document's own
    two leading blank lines at `AUTO_LEAD_FACTOR` 1.0 = 84pt vs the `v3`
    measured 83.7pt, 0.3pt residual -- the same decipoint-rounding gap
    every other oracle here shows)."""
    page = doc.meta.get('page')
    if page is None:
        return TOP_PRINTED
    page_h = _resolved_page_height(doc, True)
    mt = page.get('mt_lines', 3.0)
    return max(0, min(round(mt * 12), page_h - LEAD))


def _printed_notes_reserve_pt(doc):
    """Bottom-of-page reserve for `_paginate_printed_notes`'s FOOTNOTE
    area (never the endnote continuation -- see that function's own
    docstring: endnotes are never queued here, `_endnote_pages` appends
    them afterward and inherits this area's position for free by
    continuing its sequential flow), in points -- Finding 2
    (b26-print-fidelity-2). The area used to be flow-appended right after
    the body (whatever y the body happened to end at), correct only when
    the body already fills the page (LYING.WS, every page) -- on a short
    page (-SCREEN.WS, a 1-page doc whose body ends mid-page) that put the
    area mid-page, colliding with the WORDSTAR.PIX image; real WS7 prints
    it at the physical bottom.

    Originally measured against TWO WS7 captures (ws7-prints/v1), both at
    every page-geometry default (.mb 8 lines): -SCREEN.pcl's footnote line
    "1. Footnote" at y=708pt (dash rule at 684pt) and LYING.pcl's "1.Did
    not take the prize." also at y=708pt (dash rule also 684pt -- LYING's
    page is full, so its flow-appended position and this anchor coincide,
    per `_paginate_printed_notes`'s own docstring). Both landed on
    84pt = (.mb - 1) * 12 = 7 lines, alongside a (since-fixed) 3-line
    header model (`_area_size`/`_render_area`) that inserted an extra
    leading blank neither real capture ever printed.

    Mechanism U (PCL-DIVERGENCE-TRIAGE.md, `ws7-prints/v3` PRISTINE.EXE
    round, same install already found responsible for the `.po`/leading/
    top-margin contaminations -- mechanisms S, T, and this function's own
    sibling `_printed_top`). With the header-count fix landed (2 lines:
    rule then blank, not 3), re-deriving BOTH real captures from scratch:

    -SCREEN (`ws7-prints/v1`, Sawyer): rule at V=6840 (684.0pt), footnote
    text at V=7080 (708.0pt) -- a genuinely SHORT page (last real body
    content at V=4341, nowhere near either), so this anchor's own reserve
    governs directly. Solving with the 2-line header: reserve = 96.0pt =
    `.mb * 12` EXACTLY (8 lines, no adjustment at all) -- zero residual.
    The old `-1` was compensating for the wrong (3-line) header model, not
    a real per-install customization; Sawyer's own real anchor, once the
    header count is corrected, needs no fudge whatsoever.

    LYING (`ws7-prints/v3`, pristine): rule at V=6600 (660.0pt), footnote
    text at V=6840 (684.0pt) -- a FULL page, so this document's own
    natural (un-anchored) flow is what actually places it: once
    `_printed_top`'s own fix lands, the body's last real content line
    lands at y=648.0pt (matching pristine exactly on its own). The code's
    own `body_y` (`_notes_top + body_len * default_lead`, the position of
    the NEXT line after the body, not the last body line itself) is
    648 + 12 = 660.0pt -- that, not 648, is what the override compares
    against (`override = target_first - body_y`).

    2026-09-07 correction (planning #202 residuals round, `-SCREEN`
    recapture): the prior text here compared `target_first` against
    `natural_y` (648, the body's last content line) instead of the code's
    actual `body_y` (660, one line further down) -- a 12pt/one-line error
    in the DERIVATION, not in the code's own `override` arithmetic, but it
    produced a reserve requirement (`>= 120`) that was 12pt too large. The
    `-SCREEN` v3 capture used to look like it corroborated this because
    `ws7-prints/v3/-SCREEN.pcl` was silently TRUNCATED at the embedded
    Inset picture (fixed by corpus commit 2be7569, 2026-09-06): its lower
    half -- the entire footnote/endnote block -- was missing from the
    capture, not absent from stock WS7's real output. The claim below this
    docstring used to carried ("its own footnote/endnote block is entirely
    ABSENT under `ws7-prints/v3`") is FALSE and is corrected here: stock
    WS7 prints the footnote and endnote block on this document exactly
    like every other install. The recaptured, complete `-SCREEN.pcl`
    measures: dash rule at V=6600 (660.0pt), footnote line ("1." then,
    tab-separated, "Footnote") at V=6840 (684.0pt), endnote line ("(1)"
    then "Endnote") at V=7080 (708.0pt), page-number footer at V=7320
    (732.0pt, unaffected by this reserve -- already matched before and
    after this fix). `-SCREEN`'s body ends at V=4341 (434.1pt, nowhere
    near the anchor), so -- exactly like the v1/Sawyer case above -- its
    own short page makes the anchor govern DIRECTLY, and now for the first
    time gives a genuine second, INDEPENDENT stock data point (previously
    only LYING's full-page, anchor-need-not-engage case existed): solving
    `792 - reserve - (area_len-1)*12 = 660` with `area_len=3` (rule,
    blank, text) gives `reserve = 108.0pt` = `(.mb + 1) * 12` (9 lines),
    not `(.mb + 2) * 12` (120pt, the prior, now-refuted value).

    Re-checked against LYING with `reserve = 108`: `override = target_first
    - body_y = (792 - 108 - 24) - 660 = 0`, and the code's own gate is
    `if override > 0`, so `0` still does NOT engage the anchor -- LYING's
    already-correct pure-sequential-flow position (684.0pt, matching
    pristine with zero residual) is completely undisturbed. So `108` is
    not a compromise between two installs' needs; it is the exact value
    both real stock captures independently agree on: -SCREEN governs it
    directly (short page), LYING is consistent with it as a boundary case
    (full page, override lands at exactly 0 rather than needing to stay
    strictly negative).

    CONFIRMED under stock, n=2 (`-SCREEN` direct + `LYING` boundary-
    consistent), superseding the prior n=1 JUDGMENT CALL: `108pt` =
    `(.mb + 1) * 12`, not `(.mb + DEFAULT_HM_LINES) * 12`. The `.hm`-
    symmetry reading that motivated `+2` doesn't hold; the footnote area's
    real cushion above the physical bottom margin is one line, not
    `DEFAULT_HM_LINES` lines -- `_printed_top`'s own `.hm` finding (top of
    page) and this reserve (bottom of page) are NOT mirror images after
    all, contra the earlier note here."""
    page = doc.meta.get('page')
    if page is None:
        return 108.0                   # print streams: no .mb to read;
                                        # the measured default constant
    mb = page.get('mb_lines', 8.0)
    return max(0.0, (mb + 1) * 12.0)

def _lead_pt(lh_48):
    """One `.lh` value (1/48in units) as points: a point is 1/72in, so
    lh * 1.5. None/non-positive -> None, meaning "no answer here, use the
    document's default"."""
    if not lh_48 or lh_48 <= 0:
        return None
    return lh_48 * 1.5


# Mechanism T (PCL-DIVERGENCE-TRIAGE.md, ws7-prints/v3 round): the factor
# `_style_lead_pt`'s "auto" (vmi==-2) branch, its too-small-explicit-vmi
# fallback, and `_font_lead_pt`'s WS5+ font-block formula all multiply a
# governing font size by, for STOCK WordStar 7's single-spacing leading.
#
# Every prior measurement of this factor (1.2, "19.2pt on a 16pt style",
# etc. -- see this module's git history and test_style_leading.py before
# this fix) was taken from `ws7-prints/v1`/`v2`, both captured through
# Robert J. Sawyer's own WSCHANGE-customized `WS.EXE` -- the SAME install
# mechanism S already found responsible for the `.po` contamination
# (column 7 vs the manual's/stock's column 8). WSCHANGE's own settings
# chart (`Installing and Customizing (WordStar 7)`, the "Changing WordStar
# Settings in WSCHANGE" appendix) lists this exact feature by name, twice
# (once under the alphabetical chart, once under its own "Leading" cluster
# alongside "Leading (line height)" BCJ/240):
#
#     Automatic leading, 120% of text size        BCL     OFF
#
# i.e. "120% of text size" (1.2x) is a WSCHANGE-toggleable setting whose
# FACTORY DEFAULT IS OFF. Confirmed directly against a `PRISTINE.EXE`
# (factory, no WSCHANGE) recapture of the same 4 documents whose leading
# this module already modelled from Sawyer's install (`ws7-prints/v3`,
# captured 2026-09-06/07): every baseline gap driven by this formula
# scales by EXACTLY 1/1.2 under pristine, with zero exceptions --
#   LYING.pcl   Title(16pt)->Author gap:   19.2pt (v1, Sawyer) -> 16.0pt (v3, pristine)
#   WARPRAYR.pcl Title(16pt)->Author gap:  19.2pt (v1)         -> 16.0pt (v3)
#   -SCREEN.pcl body (12pt, font-block, no style) gaps: 14.4pt (v1) -> 12.0pt (v3)
#   PREVIEW.pcl  every font_lead_pt-governed gap: v3 == v1 / 1.2 exactly
#     (14.4->12.0, 86.4->72.0, 57.6->48.0, 100.8->84.0)
# Every OTHER transition this module measured against v1 (explicit vmi
# that already fits its own font, `.lh`-governed lines, blank lines' own
# RAW lead) is IDENTICAL between v1 and v3 -- confirming the factor above
# is the ONLY thing that moved between the two installs; nothing else in
# this leading model is Sawyer-specific.
#
# So: 1.0 (plain single-spacing, no auto-leading padding) is STOCK
# WordStar 7's real behaviour; 1.2 was Sawyer's own personalization,
# exactly like `.po` column 7 and page-numbering-off before it. The
# engine models stock -- see this repo's own standing ruling. A document
# that explicitly wants the 120%-padded look would need to say so via its
# own dot commands/style vmi (an explicit vmi is UNCHANGED by this
# constant either way); nothing in the corpus does.
AUTO_LEAD_FACTOR = 1.0

# `_font_lead_pt`'s governing-size ceiling (planning #233, ERROR.WS, 2026-09-09):
# a WS5+ FONT-BLOCK document's oversized DECORATIVE title-card sizes (72pt/
# 42pt) do NOT carry the auto-lead scaling the way PREVIEW.WS's 24pt font
# blocks do (the mechanism-T oracle above, still the largest size with real
# WS7 evidence of scaling). Measured directly against `sawyer/FONTS/PS/
# ERROR.WS`'s real WS7 capture (`tools/pcl_text.py` on `ws7-prints/v4/
# sawyer__FONTS__PS__ERROR_EXT_WS.pcl`, ground truth -- a real LaserJet PCL5
# capture, gpcl6-rendered PNG confirms the visual): "ERROR!" (72pt) to "Must
# Sterilize!" (42pt) is a clean 5-line-feed run (`\r\n` x5 in the source
# bytes) covering exactly 60.0pt -- 12.0pt/line-feed, the document's own flat
# `.lh` default (`lh_48=8.0`), NOT 72.0pt/line as the ungated governing-size
# formula computes. "Must Sterilize!" (42pt) to "No new WORDSTAR.PS produced"
# (20pt) is a 10-line-feed run covering exactly 120.0pt -- again 12.0pt/line,
# not 42.0pt. Both gaps decompose to ONE clean constant with zero residual;
# there is no partial/mixed scaling anywhere in either run. PREVIEW.WS's own
# three 24pt transitions (Times->Univers, Univers->Aachen, Aachen->Courier),
# by contrast, are clean 2-line-feed runs at exactly 24.0pt/line-feed each
# (`ws7-prints/v3/PREVIEW.pcl`) -- governing-size scaling IS real, just not
# above whatever ceiling separates 24pt (scales) from 42pt (doesn't). No
# corpus document exercises this un-`.lh`'d auto-lead path at an intermediate
# size (every other big-font document found -- LJ6DTP.WS, PRINTER.PS,
# fontcrib.ws, WINGDING.CHT, SYMBOL.CHT -- sets its own explicit `.lh` around
# its decorative text, which routes around this formula entirely per its own
# guard below). Rather than guess a number between the two measured points,
# the ceiling is set at the largest size real WS7 evidence actually confirms
# scales, 24.0pt: at or under it, a proportional font's own declared size
# governs (unchanged behaviour); over it, it degrades to the SAME "reset the
# carried state, fall back to the document default" treatment a fixed-pitch
# font already gets (see `_font_lead_pt`'s own docstring) -- an oversized
# decorative font's own line, and every blank line after it, prints at the
# plain document-default lead, not its own huge size.
FONT_LEAD_CAP_PT = 24.0


def _style_lead_pt(block, doc, raw=False):
    """The baseline-to-baseline leading a WS7 paragraph STYLE dictates for
    every physical line in `block` (core.Block.line_height_vmi/style_font_pt,
    set from the style record's own font/line-height fields -- core.py's
    style-selection parse). None when no style governs this block, or the
    style set no line height of its own: the caller falls back to the
    pre-existing `.lh`/document-default leading UNCHANGED, so a WS4 or
    otherwise styleless document never shifts.

    vmi == -2 ("auto" -- the ONLY value seen on every style in the measured
    oracle, LYING.WS/LYING.pcl): real WS7 leading is 1.2 x the style's own
    font size, not the document's fixed default -- measured 2026-08-20 from
    PCL decipoint baseline gaps: Title/Author (16pt style) 192 decipoints
    (19.2pt) apart, Body (12pt) 144 decipoints (14.4pt) apart, and a blank
    line between a 16pt block and the next 12pt block contributing its OWN
    19.2pt of the two lines' combined 336-decipoint (33.6pt) gap -- a blank
    line advances at ITS block's leading, which `style_font_pt` already
    gives it (block-level, not read off the line's own spans, precisely
    because a blank line carries no spans/font tag of its own -- see
    core.Block.style_font_pt's docstring). Falls back to the document's own
    printed SIZE (_printed_size) if the style declared no font of its own
    (an all-zero/recordless font triple).

    UPDATE 2026-09-07 (mechanism T, PCL-DIVERGENCE-TRIAGE.md): the "1.2 x"
    figure above, and every specific point value in this docstring derived
    from it (19.2, 14.4, 33.6, ...), was measured against `ws7-prints/v1`,
    captured through Robert J. Sawyer's own WSCHANGE-customized `WS.EXE` --
    the SAME install mechanism S already found responsible for contaminating
    `.po`. A `PRISTINE.EXE` (factory, no WSCHANGE) recapture of the SAME
    documents (`ws7-prints/v3`) shows every one of these gaps at exactly
    1/1.2 of the number above (Title/Author 19.2pt -> 16.0pt, Body-to-Body
    14.4pt -> 12.0pt, the blank-line-spanning 33.6pt -> 28.0pt) -- stock
    WordStar 7's real auto-leading factor is 1.0, not 1.2; see
    `AUTO_LEAD_FACTOR`'s own docstring for the manual citation ("Automatic
    leading, 120% of text size", WSCHANGE path BCL, factory default OFF)
    and the full v1-vs-v3 evidence table. Left the rest of this docstring's
    OLD (Sawyer-measured) numbers as written below -- they are still an
    accurate record of what was measured and when -- rather than editing
    every instance; only the LIVE factor (`AUTO_LEAD_FACTOR`) changed.

    vmi > 0: an EXPLICIT count, in the same 1/1440in VMI unit WSFORMAT.WS
    documents for a font's own height word ("Font height in VMIs
    (1/1440ths)") -- so vmi/20.0 is points, the identical conversion
    _font_entry already applies to a font's height word. Evidenced from the
    format spec's own text, not guessed.

    UPDATE 2026-08-20 (round 26 wave 3, fidelity_gate.py Unit A): a WS7
    oracle for a vmi>0 style now DOES exist -- WARPRAYR.pcl (ws7-prints/v1),
    which this docstring previously (wrongly) said was never printed on
    real WS7. WARPRAYR carries vmi=240 on both its byline (16pt) and its
    entire body (12pt). The vmi/20.0=12pt formula below is CONFIRMED, not
    contradicted, for the body: WARPRAYR.pcl's own baseline_gaps_pt run
    12.0pt for ~20 consecutive body-paragraph lines, exactly vmi/20 at
    12pt font, with zero drift. The ONE anomaly is the byline's OWN
    baseline, 19.2pt below the title's (78.9 -> 98.1), not the 12pt
    vmi/20 (or the document default, also 12pt) predicts.

    An EARLIER version of this comment special-cased vmi==240 to behave
    like -2/auto everywhere (reasoning from the byline anomaly alone,
    plus 240 being suspiciously identical to WSCHANGE's own "VMI units
    for line height" factory default, Installing and Customizing p.2-47,
    DBA2A -- sic, DBA2H). That over-generalised: applied to the BODY it
    made every body line 14.4pt instead of the CONFIRMED 12pt, which does
    get WARPRAYR to the WS7 page count (3) but at the cost of a much
    larger positional residual within the page (median jumped from
    ~2.5pt to 24pt) -- fitting the one number the task asked for by
    breaking twenty it didn't. Reverted, and a margin-COLLAPSING
    hypothesis (the byline's OWN entry gap borrows the outgoing title
    block's larger lead, CSS-style) was reported instead of acted on --
    correctly: it isn't margin collapsing.

    FIX B (b26-print-fidelity-2), the evidence-backed resolution: the
    byline's vmi (240 = 12pt) is simply too SMALL for its own 16pt font
    -- 12pt leading on 16pt type overlaps ascender-to-descender, so WS7
    falls back to the SAME auto formula (1.2 x the style's own size,
    19.2pt) an unset vmi already gets. The body's vmi=240 on its OWN
    12pt font is the negative case that PROVES this doesn't regress:
    240/20 = 12.0 >= 12.0, no fallback, the already-CONFIRMED 12.0pt
    stands untouched. Cross-checked against every OTHER styled document
    in the corpus before landing: LYING's four styles are all vmi=-2/auto
    (never reach this branch); OCAPTAIN/TWAINLET carry no paragraph
    styles at all.

    RESOLVED by Fix C's full block-transition inventory (below, and
    `_entering_lead_pt`): this docstring's own UPDATE section originally
    read the byline's 19.2pt as a property of the WHOLE Author block (so
    this fallback was applied uniformly, per block, to every line). That
    was ALSO wrong, just less visibly -- Author's own trailing BLANK line
    (the one line inside it besides the byline itself) measures its OWN
    space at 12.0pt, the UNFALLEN-BACK vmi/20, not 19.2pt. The fallback
    protects against a REAL line's ascender/descender clipping into the
    line above -- a blank line has no glyphs to clip, so it never needs
    it: `raw=True` (every BLANK line, and the value a block hands to
    `_entering_lead_pt` as the NEXT block's "outgoing" reference) always
    returns the unfallen-back vmi/20, regardless of position in the
    block. `raw=False` (the default, every REAL line, first or not --
    every EXISTING call site before Fix C only ever rendered a block's
    OWN first line through this function, so this is the identical
    behaviour there) keeps the fallback.

    Document-level guard: if the file EVER used a real `.lh` dot command
    (doc.meta['page']['lh_source'] == 'file' -- core.py's own file-vs-default
    tag), a style's own leading is NOT applied at all, even where a line's
    own `.lh` state happens to equal the document default and so normalises
    to None (core.py's Line.lead_48 normalisation pass, ~line 3960) --
    indistinguishable, at the per-line level, from a line that never saw
    `.lh` in the first place. No corpus evidence exists for how real WS7
    arbitrates a style's vmi against an ACTIVE `.lh`, so this stays
    conservative: an `.lh`-bearing document's leading is left exactly as
    the pre-existing mechanism computed it, unconditionally."""
    vmi = getattr(block, 'line_height_vmi', None)
    if vmi is None:
        return None
    if doc.meta.get('page', {}).get('lh_source') == 'file':
        return None
    if vmi == -2:
        size = getattr(block, 'style_font_pt', None)
        if not size:
            size = _printed_size(doc)
        return size * AUTO_LEAD_FACTOR
    if vmi > 0:
        # Finding B (b26-print-fidelity-2): an explicit vmi too SMALL for
        # the style's own font falls back to the SAME auto formula
        # (AUTO_LEAD_FACTOR x the style's own size) an unset vmi already
        # gets -- WARPRAYR's Author style (vmi=240=12pt on a 16pt font;
        # 12pt lead on 16pt type would overlap ascender-to-descender)
        # measures 16.0pt (stock, AUTO_LEAD_FACTOR x 16 -- see that
        # constant's own docstring for the v1-Sawyer-vs-v3-pristine
        # measurement this factor is now taken from) for its byline's OWN
        # entry gap. The Body style's vmi=240 on its OWN 12pt font is the
        # negative case PROVING vmi/20 remains correct when it fits
        # (240/20 = 12.0 >= 12.0, no fallback) -- the already-CONFIRMED
        # 12.0pt body leading (~20 consecutive lines, zero drift), unmoved
        # by this fix.
        #
        # `raw` (Fix C, b26-print-fidelity-2): the fallback above protects
        # a REAL line's ascender/descender from clipping into the line
        # above -- a BLANK line has no glyphs to clip, so it never needs
        # it. `raw=True` skips the fallback and returns the unfallen-back
        # vmi/20 always -- see `_entering_lead_pt`, which is the ONLY
        # caller that ever passes `raw=True` (for the block being LEFT,
        # never the one being entered), and the direct blank-line call
        # site in `_doc_to_pagelines`. `raw=False` (the default) is every
        # EXISTING call site's own behaviour, unchanged.
        size = getattr(block, 'style_font_pt', None)
        pt = vmi / 20.0
        if not raw and size and pt < size:
            return size * AUTO_LEAD_FACTOR
        return pt
    return None


def _entering_lead_pt(block, doc, prev_block):
    """A block's own FIRST REAL (non-blank) physical line's lead:
    `_style_lead_pt`'s font-relative fallback (Finding B), floored
    against the block being ENTERED's own natural minimum -- Fix C
    (b26-print-fidelity-2, WARPRAYR.WS). An EXPLICIT (vmi>0) style's
    first line never sits CLOSER to the preceding content than that
    content's own RAW lead was -- i.e. entering an explicitly, tightly-
    leaded block never crowds whatever was above it.

    UPDATE 2026-09-07 (mechanism T): the inventory and cross-check below
    are re-stated at STOCK WS7's real `AUTO_LEAD_FACTOR` (1.0, not the
    1.2 the WARPRAYR.pcl/LYING.pcl oracle behind them was originally
    measured at -- see `AUTO_LEAD_FACTOR`'s own docstring). The two
    transitions that route entirely through RAW/fitting values (never
    through the `size * AUTO_LEAD_FACTOR` fallback line) are IDENTICAL
    between Sawyer's install and stock -- confirmed directly against both
    `ws7-prints/v1` and `ws7-prints/v3` captures of the same document.

    Full block-transition inventory (WARPRAYR.pcl, WS7 frame, blank-line
    + entering-line combined gaps -- a blank line carries no glyph, so
    only the PAIR is independently measurable; stock/v3 numbers, 1.2x/v1
    Sawyer numbers alongside where they differ):
        Author(fallback,16.0; was 19.2) -> Body(vmi 240=12, fits)   24.0 = 12.0 + 12.0 (UNCHANGED -- all-raw/fitting)
        Body(vmi 240=12)    -> Quote(auto,12.0; was 14.4)  x2       24.0 = 12.0 + 12.0 (was 26.4 = 12.0 + 14.4)
        Quote(auto,12.0; was 14.4)    -> Body(vmi 240=12)  x2       24.0 = 12.0 + 12.0 (was 28.8 = 14.4 + 14.4)
    Only the Quote -> Body pairs need MORE than `_style_lead_pt` alone
    gives (Body's own 12.0 entering gap) -- WS7 floors Body's own
    entering gap at Quote's own 12.0 instead (a no-op at stock's factor,
    since Quote's own and Body's own both land on 12.0 already; the
    floor's EXISTENCE is still proven by the Sawyer/v1 numbers, where
    12.0 < 14.4 and the floor visibly engages). Author -> Body does NOT
    need this floor once Finding B's fallback is correctly scoped to
    REAL lines only (`raw=True` for Author's OWN blank line, above):
    Author's raw/exported lead is 12.0 (not its fallback value, whatever
    the live factor makes that), so Body's own entering gap (12.0) is
    ALREADY >= it, no floor needed -- matching the measured 24.0 exactly
    with no special case, at either factor.

    Cross-checked against LYING.WS, which is entirely auto styles (no
    vmi>0 block exists there to test the floor itself) but DOES cover
    the discriminating case this floor must NOT fire for: Author(auto,
    16.0; was 19.2) -> Subtitle(auto,12.0; was 14.4) measures 28.0 (was
    33.6) = 16.0 + 12.0 -- Subtitle's OWN entering gap, NOT floored up to
    Author's outgoing 16.0 (which would give 32.0, wrong).

    UPDATE 2026-09-08 (#236, INTERVU.WS/WORDSTAR.WS title blocks): the
    ABOVE cross-check and the "auto never needs the floor" conclusion it
    supported only ever exercised a transition with a BLANK line between
    the two blocks (Author's own trailing blank separates it from
    Subtitle) -- the blank line already provides real separation, at ITS
    OWN (outgoing) block's lead, before Subtitle's first real line is
    even reached, so no extra floor is needed there. INTERVU.WS's title
    block is the discriminating case that reading never covered: three
    single-line AUTO-style paragraphs stacked with NO blank line between
    them at all (H1 "Why I Still Use WordStar:" directly followed by H2
    "An Interview...", no intervening blank). Measured directly against
    WS7's own capture: H1(18pt)->H2(16pt) advances 18.0pt (H1's OWN
    outgoing size, not H2's entering 16.0), and H2->H3(14pt) advances
    16.0pt (H2's own outgoing size) -- the identical floor this function
    already applies for an explicit vmi, engaging for auto too, but ONLY
    when the line above is REAL (no blank line already did the job).
    The floor therefore applies whenever the block being ENTERED has an
    EXPLICIT vmi (unconditionally, as before), OR an auto (-2) vmi AND
    the previous block's own LAST line still carries real content (no
    blank line intervening) -- a genuinely auto style needs no
    protection when a blank line already separated it from what came
    before, but does need it butted directly against another real line,
    for the same ascender/descender-clipping reason Finding B's own
    fallback exists.

    NOT independently confirmed: a SECOND real (non-blank) line inside a
    too-small-vmi style also getting the fallback rather than the raw
    value -- no such line exists in the corpus (WARPRAYR's Author block
    has exactly one real line). Reasoned from the SAME clipping rationale
    Finding B's own fallback rests on (a real line's ascender/descender
    doesn't stop clipping just because it isn't the block's first), not
    from a second measurement."""
    own = _style_lead_pt(block, doc, raw=False)
    vmi = getattr(block, 'line_height_vmi', None)
    if own is None or prev_block is None:
        return own
    explicit = vmi is not None and vmi > 0
    auto_adjacent = (vmi == -2 and prev_block.lines
                     and prev_block.lines[-1].spans)
    if not (explicit or auto_adjacent):
        return own
    prev_raw = _style_lead_pt(prev_block, doc, raw=True)
    if prev_raw is None:
        return own
    return max(own, prev_raw)


def _font_lead_pt(line, fonts, base_size, state):
    """This physical line's own baseline-to-baseline lead in points, for a
    WS5+ FONT-BLOCK document with no paragraph style governing the line
    (`_style_lead_pt` returns None for every line here -- PREVIEW.WS, the
    oracle behind this rule, carries no styles at all).

    CALLER'S GATE, not this function's: only consulted (own_lead is still
    None otherwise) when `doc.fonts` contains at least one PROPORTIONAL
    entry -- a document-WIDE mode switch, not a per-line one. -README.WS
    is the negative oracle for this: it carries exactly one font-block
    record, a 12pt FIXED-PITCH Courier entry (likely the installation's
    own default-face declaration, not an author's deliberate `.fp`
    insertion), and its WS7 capture prints flat 12pt leading throughout
    (baseline_gaps_pt: 12.0 between consecutive body lines) -- NOT the
    14.4 (1.2x12) this function would compute if consulted for every one
    of its Courier-tagged lines. PREVIEW.WS's own 12pt sections (its
    3-line Courier intro, BEFORE any font tag has even appeared in the
    stream) measure 14.4 despite being just as fontless-looking at that
    exact point -- the only document-level difference is that PREVIEW
    contains real proportional font blocks (Times/Univers/Aachen)
    elsewhere and -README never does. So a document with no proportional
    font block anywhere -- SAWYER, VERSIONS, TWAINLET, OCAPTAIN, every
    fontless doc in the corpus, AND -README's single-fixed-font case --
    must stay on the byte-identical 12pt grid throughout, full stop.

    `state` is a 1-element list, `[current_governing_pt_or_None]`, owned
    and threaded by the CALLER across every physical line of the document
    in source order (mirrors `pending_sa`'s cross-block carry): a blank
    line (no font tag of its own) inherits whatever `state[0]` already
    holds, exactly as a real printer's VMI-select state would survive an
    empty line with no command bytes to change it.

    RULE (measured 2026-08-20 against PREVIEW.WS/PREVIEW.pcl,
    fidelity_gate.py Finding B -- every gap on the page decomposes to
    0.3pt residual under it, THEN re-measured 2026-09-07 against the same
    document's `ws7-prints/v3` PRISTINE.EXE recapture, which shows the
    identical shape at exactly 1/1.2 of every v1 number -- see
    `AUTO_LEAD_FACTOR`'s own docstring, the SAME WSCHANGE "Automatic
    leading, 120% of text size" setting Sawyer's install had ON):
    AUTO_LEAD_FACTOR x the largest PROPORTIONAL font size
    (doc.fonts[n]['proportional'] True) active anywhere on the line,
    carried forward through blank lines. A FIXED-PITCH font block
    (Courier, any declared point size) NEVER raises the governing size
    above the document default and, as the LAST font tag active on a
    line, RESETS the carried state -- WS5+ Courier font blocks change
    PITCH (historically elite/pica variants of the one typewriter face),
    not real vertical measure, so a 20pt Courier block's own line and
    every blank line after it print at the plain AUTO_LEAD_FACTOR x 12 =
    12.0pt (stock) default, not AUTO_LEAD_FACTOR x 20. Confirmed on
    PREVIEW's OWN 12pt intro (no font tag at all yet -- 12.0pt gaps,
    14.4pt under Sawyer's install) and its trailing Courier-20pt block (6
    blank continuation lines, all 12.0pt, not 20.0pt) alike -- both land
    on the SAME formula via `state`, not a special case. A line whose OWN
    leading spaces still carry the OUTGOING tag before a mid-line font
    change (WordStar's own encoding: the change lands after the
    characters it precedes, not at line start) takes the LARGER of every
    proportional size found on the line, matching a real printer sizing
    the line to its tallest glyph.

    NOT APPLIED when the document ever used a real `.lh` (guarded by the
    same `lh_source == 'file'` check `_style_lead_pt` uses) -- no corpus
    evidence exists for how real WS7 arbitrates a font block's own size
    against an ACTIVE `.lh`, so that combination is left to the
    pre-existing `.lh`-based mechanism, unconditionally, same doctrine as
    `_style_lead_pt`'s own guard.

    CEILING (planning #233, `FONT_LEAD_CAP_PT` -- see its own docstring for
    the full ERROR.WS/PREVIEW.WS evidence): a proportional font block whose
    OWN declared size exceeds `FONT_LEAD_CAP_PT` never governs -- it is
    treated exactly like a FIXED-PITCH block for this function's purposes
    (does not raise `prop_sizes_here`, RESETS the carried `state` the same
    way a Courier tag does). A 72pt or 42pt decorative title-card font's own
    line, and every blank line after it, therefore prints at the plain
    document-default lead, matching real WS7 -- only sizes at or under the
    cap (the largest real WS7 evidence confirms scales, 24pt) get the
    governing-size treatment described above.

    ORDERING, and the VIRGIN/ESTABLISHED distinction in `state`, both
    planning #233 (second half of the same evidence -- ERROR.WS's residual
    8.0pt after the ceiling alone): a line's OWN font tag governs the
    ENTERING advance of the line AFTER it, generally never its own --
    WordStar's byte encoding puts a font-change record right before the
    text it applies to, AFTER that text's own leading `\\r\\n`, so the
    vertical move that PLACES a line usually happens before that line's own
    tag has even been read. ERROR.WS's "No new WORDSTAR.PS produced" proves
    this directly: it carries its own 20pt Triumvirate tag (within the
    ceiling), but its real entering advance is the SAME flat 12.0pt as the
    nine purely-blank lines before it, not 20.0pt -- because `state` was
    already ESTABLISHED at the document default by "Must Sterilize!"'s
    42pt tag exceeding the ceiling immediately before this run, and an
    established `state` always wins over a line's own tag.

    But `state` starting VIRGIN (nothing has ever governed -- the very
    first proportional tag in the whole document) is different, and
    PREVIEW.WS's own Times-Roman heading (its FIRST proportional tag) is
    the oracle that tells the two apart: `core.parse_ws` gives this
    engine only 4 blank `Line` records between the document's plain-12pt
    intro and the Times heading, one fewer than the capture's real 6-line-
    feed gap (720 decipoints/72.0pt) -- ctrl-kd's own parse folds a `.oc
    off` dot-command's line into the record that follows it, a parse-level
    detail invisible to WS7's own byte-for-byte vertical motion. Crediting
    the Times heading's OWN 24pt tag to ITS OWN entering advance (4 blank x
    12 + 1 x 24 = 72) reproduces the real 72.0pt exactly; forcing it through
    `state` (still None, "fall back to base" once VIRGIN state is read
    literally as "no size") would under-shoot by exactly one line (60, not
    72) -- the residual this distinction fixes. Once ANY tag has been
    seen, real or reset, `state` becomes ESTABLISHED (see below) and every
    later line, including one with its own in-range tag (Univers/Aachen in
    PREVIEW, "No new..." in ERROR.WS), is governed by `state` alone.

    So: `state[0]` is `None` ONLY before the first font tag of the whole
    document; every reset (`FONT_LEAD_CAP_PT` exceeded, or a fixed-pitch
    tag) sets it to `base_size` itself -- an ESTABLISHED real number, not
    `None` -- specifically so a LATER in-range tag can never again fall
    back to governing its own line the way a virgin `None` would. The scan
    below still folds every proportional size found ON a line into what
    `state` becomes for the NEXT line (still `max()` of them, for a mid-
    line font change's padding -- see the paragraph above); only which
    value THIS line's own return uses -- `state` if already established,
    else this line's own scan -- is new."""
    if not fonts:
        return None
    prop_sizes_here = []
    last_tag_proportional = None
    for s in line.spans:
        tag = next((t for t in s.styles
                    if t.startswith('font') and t[4:].isdigit()), None)
        if tag is None:
            continue
        fidx = int(tag[4:])
        if 0 <= fidx < len(fonts):
            entry = fonts[fidx]
            pts = entry.get('points') or 0.0
            if entry.get('proportional') and pts <= FONT_LEAD_CAP_PT:
                prop_sizes_here.append(pts)
                last_tag_proportional = True
            else:
                last_tag_proportional = False
    if state[0] is not None:
        governing = state[0]
    else:
        governing = max(prop_sizes_here) if prop_sizes_here else None
    if last_tag_proportional is False:
        state[0] = base_size
    elif prop_sizes_here:
        state[0] = max(prop_sizes_here)
    return (governing if governing else base_size) * AUTO_LEAD_FACTOR


def _printed_lead(doc):
    """The DOCUMENT-DEFAULT baseline-to-baseline distance in points for
    printed mode, from the file's first `.lh`. Default .lh 8 IS the 12pt lead
    this emitter always used. Print streams (no 'page' meta) keep the fixed
    LEAD.

    Only the default: `.lh` is stateful and a line that was set at a different
    leading carries its own (core.Line.lead_48 -> PageLine.lead), which
    _page_stream honours per line. This is what a line WITHOUT one falls back
    to, and what page CAPACITY is still computed at (see _printed_cap)."""
    page = doc.meta.get('page')
    if page is None:
        return LEAD
    return _lead_pt(page.get('lh_48', 8.0)) or LEAD


def resolved_printed_leads_48(doc):
    """{id(block): lead_48} for every printed content block ('para' kind,
    headings included -- `condpage`/`pagebreak` sentinels carry no lines
    and are skipped), giving RTF's own per-paragraph `\\sl` (round 6's
    `_rtf_block_lead_48`, before this fix) the SAME resolved leading this
    module's own PDF page-building already uses per PHYSICAL line
    (`_doc_to_pagelines`'s printed branch: `.lh` override, else a
    paragraph STYLE's own `line_height_vmi`-derived leading via
    `_style_lead_pt`/`_entering_lead_pt`, else a WS5+ font-block's own
    proportional size via `_font_lead_pt`, else the document default).
    Ruling 2026-08-26 (register row, b33 field notes N2): Printed/Native
    RTF previously emitted ONE flat `\\sl` for the whole document --
    LYING.WS/WARPRAYR.WS and a private specimen's 16pt Title/Author paragraphs (WS7
    style vmi -2/auto, real leading 1.2x16=19.2pt) were squeezed onto the
    document's plain 12pt body lead, clipping in Word/TextEdit. This ports
    the READ side of that same per-line algorithm to block granularity --
    RTF's `\\sl` is a PARAGRAPH property with no per-line control word, so
    a block collapses to its own FIRST REAL (non-blank) physical line's
    resolved value, exactly the "ceiling of what RTF can express per
    paragraph" round 6's own `_rtf_block_lead_48` docstring already named
    (a `.lh` change strictly mid-paragraph was already out of scope
    there, unchanged here). `font_lead_state` is still threaded across
    EVERY physical line of the WHOLE document in source order, blank
    lines and non-first real lines included, even though only one
    resolved value per block is kept -- an inline font-block change
    inside a later line must still update the carried state exactly as
    `_doc_to_pagelines` computes it, or a LATER block's own first line
    would resolve against a stale governing size. No existing PDF
    consumer of `_lead_pt`/`_style_lead_pt`/`_entering_lead_pt`/
    `_font_lead_pt` is touched -- this only calls them, read-only, in the
    same per-line order and under the same gates they already use.

    `DEFAULT_LH_48` (used below) needed importing at true module scope
    (this file's other consumers of the same name -- `_doc_to_pagelines`/
    `_body_stream_printed` -- reference it too, but bare, with no import
    anywhere in either function's own body): a PRE-EXISTING NameError,
    unrelated to this fix, that this function's own first corpus sweep
    exposed (-HOW-TO.RJS/BOOKLET.RJS, a style+notes combination neither
    existing function's own test coverage had hit). Fixed at the import
    line above rather than routed around, since leaving it broken would
    make Printed RTF newly crash on documents where Printed PDF already
    did -- and the fix also repairs Printed PDF's own long-standing crash
    on those same two documents, a straight improvement, not a side
    effect this function relies on."""
    font_lead_state = [None]
    font_lead_ok = (any(f.get('proportional') for f in doc.fonts)
                    and doc.meta.get('page', {}).get('lh_source') != 'file')
    font_lead_base = _printed_size(doc) if font_lead_ok else None
    default_lead_pt = _printed_lead(doc)
    out = {}
    for bi, b in enumerate(doc.blocks):
        if b.kind in ('pagebreak', 'condpage'):
            continue
        prev_para_block = next((doc.blocks[k] for k in range(bi - 1, -1, -1)
                                if doc.blocks[k].kind == 'para'), None)
        first_line_of_block = True
        resolved_pt = None
        for line in b.lines:
            is_blank = not any(sp.text.strip() for sp in line.spans)
            own_lead = _lead_pt(line.lead_48)
            if is_blank:
                style_lead = _style_lead_pt(b, doc, raw=True)
            elif first_line_of_block:
                style_lead = _entering_lead_pt(b, doc, prev_para_block)
            else:
                style_lead = _style_lead_pt(b, doc)
            if not is_blank:
                first_line_of_block = False
            if style_lead is not None and (
                    line.lead_48 is None or line.lead_48 == DEFAULT_LH_48):
                own_lead = style_lead
            if own_lead is None and font_lead_ok:
                own_lead = _font_lead_pt(line, doc.fonts, font_lead_base,
                                         font_lead_state)
            if resolved_pt is None and not is_blank:
                resolved_pt = own_lead if own_lead is not None else default_lead_pt
        if resolved_pt is None:
            # every line in this block is blank (a pure spacer block) --
            # no REAL line ever set resolved_pt above. Fall back to the
            # block's own first line, raw (no entering-floor: there is no
            # real glyph here to protect from clipping into whatever came
            # before), same `raw=True` doctrine as a blank line mid-block.
            if b.lines:
                line = b.lines[0]
                own_lead = _lead_pt(line.lead_48)
                style_lead = _style_lead_pt(b, doc, raw=True)
                if style_lead is not None and (
                        line.lead_48 is None or line.lead_48 == DEFAULT_LH_48):
                    own_lead = style_lead
                if own_lead is None and font_lead_ok:
                    own_lead = _font_lead_pt(line, doc.fonts, font_lead_base,
                                             font_lead_state)
                resolved_pt = own_lead if own_lead is not None else default_lead_pt
            else:
                resolved_pt = default_lead_pt
        out[id(b)] = resolved_pt / 1.5      # points -> 1/48in, inverse of _lead_pt
    return out


def _printed_roll_pt(doc):
    """The DOCUMENT-DEFAULT `.sr` sub/superscript roll for printed mode, in
    points -- the fallback `_page_stream` uses for a PageLine that carries
    no `.roll` of its own (see PageLine's docstring), same role `left`'s
    document-default parameter plays for `.po`.

    Originally ONE document-wide value read regardless of position (round
    17, RULINGS-LEDGER row 3, register C22) -- "not stateful per-line like
    `.lh`", on the belief that mid-document `.sr` re-selects had no evidence
    behind per-position tracking. Register b32-N10 (private specimen) found that
    belief wrong: a superscript that is a line's LAST span rendered at the
    wrong position whenever a LATER `.sr` appeared anywhere else in the same
    document, because every span in the document -- including ones that
    printed before the `.sr` line was ever reached -- shared this one
    document-wide reading. `.sr` IS stateful, the same disease the b31 E3
    sweep found for `.pl`/`.hm`/`.fm`/`.pn`; the real per-line answer now
    lives on `core.Line.roll_48` -> `PageLine.roll`, resolved in
    `_doc_to_pagelines` and consumed in `_page_stream`. This function's own
    reading (`doc.meta['formatting']['sub_super_roll_48']`, the document's
    LAST `.sr` occurrence, unchanged) now serves only as the pre-first-`.sr`
    fallback and for PageLines this emitter MAKES rather than reads (TOC
    lines and the like, which never carry a superscript anyway). Default 3
    (WSFORMAT's own stated `.sr` default, 3/48in) whenever the file never
    sets it, converted the same way every other 1/48in value is (round 6:
    1/48in = 1.5pt)."""
    roll_48 = doc.meta.get('formatting', {}).get('sub_super_roll_48', 3.0)
    return roll_48 * 1.5


_PDF_PT_PER_COL = 7.2   # print columns at 10 CPI: 72pt/in / 10 col/in = 7.2pt/col
                        # -- the SAME unit .lm/.rm/.pm/.po all share, and the
                        # exact value MAX_COLS itself already derives from
                        # (SIZE * 0.6 == 7.2 at the default SIZE=12).


def _printed_pm_fi_pt(block):
    """First-line indent in points from `.pm` -- mirrors `_rtf_pm_fi_twips`
    (round 6, RULINGS-LEDGER row 5/7), relative to li=0: Printed PDF has no
    per-block `.lm`/`.rm` margin of its own (that gap is Printed RTF's own
    ledger row 8, a SEPARATE item this one doesn't reach), so the baseline
    this indent sits against is the document's own left edge -- the same
    li=0 an unstyled/WS4 Printed RTF paragraph already gets from the SAME
    round 6 code. None when the block never set `.pm`.

    TYPED-INDENT OFFSET (PCL tier, WARPRAYR.WS): `.pm`'s column is where a
    paragraph's first line auto-indents to when WordStar STARTS it under
    that margin -- it is not an amount added on top of whatever the
    author already typed there by hand. WARPRAYR's two Quote-styled
    blocks (`para_margin` 5, from the style record, not a literal `.pm`)
    open each stanza with 10 literal leading spaces the author typed --
    real WS7 (ws7-prints/v1/WARPRAYR.pcl/.measurements.json, page 1 y=448.5
    and page 2 y=326.1/369.6/513.3/556.5) prints those lines at exactly
    left-edge + 10 typed columns (e.g. 50.4 + 72.0 = 122.4pt) -- the
    style's own 5-column indent contributes NOTHING once the typed text
    already reaches column 10. Modelled as `max(0, pm_cols -
    already_typed_cols)`: a typed indent SHORTER than `.pm`'s column
    still gets topped up to it (the pre-existing, already-tested case --
    test_pm_shifts_printed_pdf_first_line_start_x types no indent at all
    and gets the full column); one that already reaches or passes it
    adds nothing further (the newly-measured WARPRAYR case). Blank
    leading lines are skipped -- this reads the block's first REAL
    (non-blank) line, the same line `_doc_to_pagelines`'s own
    `first_line_of_block` gate ultimately applies `fi` to."""
    if block.para_margin is None:
        return None
    typed_cols = 0
    first_real = next((ln for ln in block.lines if any(s.text.strip() for s in ln.spans)), None)
    if first_real is not None:
        text = ''.join(s.text for s in first_real.spans)
        typed_cols = len(text) - len(text.lstrip(' '))
    return max(0.0, (block.para_margin - typed_cols) * _PDF_PT_PER_COL)


def _printed_doc_spacing_pt(doc):
    """(sb, sa) in points from WordTsar's own `.psa`/`.psb` extensions --
    mirrors `_rtf_doc_spacing_twips` (round 6) exactly, converted to points
    via the document's own DEFAULT leading (the same quantity PageLine.lead
    already carries) instead of twips. (None, None) when neither command
    was ever seen."""
    sb_lines = doc.meta.get('space_before_lines')
    sa_lines = doc.meta.get('space_after_lines')
    if sb_lines is None and sa_lines is None:
        return None, None
    lead_pt = _printed_lead(doc)
    sb = sb_lines * lead_pt if sb_lines is not None else None
    sa = sa_lines * lead_pt if sa_lines is not None else None
    return sb, sa


def _printed_size(doc):
    """Type size in points for printed mode, from .cw: character width in
    1/120in units, and Courier advances 0.6em, so a pitch of cw/120in per
    character IS a (cw*72/120)/0.6 = cw*1.0 point font. The default .cw 12
    (10 CPI pica) IS the 12pt this emitter always used; .cw 10 is 12 CPI
    elite at 10pt. Rounded to whole points (the Tf operator is written as
    an integer, as it always has been), floored at 1. Print streams keep
    the fixed SIZE."""
    page = doc.meta.get('page')
    if page is None:
        return SIZE
    cw = page.get('cw_120', 12.0)
    return max(1, round(cw)) if cw > 0 else SIZE

def _resolve_left_pt(po_cols: float, size: float) -> float:
    """`.po` print columns -> left edge in points, clamped inside the page --
    the conversion `_printed_left` (document default) and the per-line
    override (core.Line.po_cols, stateful like `.lh`; register b31) both
    need, factored out so a line that never overrides `.po` resolves
    IDENTICALLY to the document default it would otherwise have inherited."""
    left = po_cols * _PDF_PT_PER_COL
    return max(0.0, min(left, PAGE_W - size * 0.6))


def _printed_left(doc, size):
    """Left edge of text in points for printed mode, from .po: "the number
    of print columns from the left edge of the paper to the left margin of
    text. The current setting of character width (.CW) determines the
    actual amount of indentation" -- but real WS7 output contradicts
    that clause: PCL captures keep .po at a FIXED 7.2pt/column at BOTH
    10cpi and 12cpi (dx experiment 2026-08-20: ESC&aH = 576dp for .po 8
    at either pitch), matching _PDF_PT_PER_COL exactly as .lm/.rm/.pm
    already do. Measured bytes beat manual prose. The default .po 8 (the WS7
    manual's ".8 inch" at 10 CPI) lands at 57.6pt -- NOT the old fixed 72pt
    MARGIN, which was this emitter's guess, not WordStar's. Print streams
    keep MARGIN: their offset spaces, where a driver emitted them, are
    in-band. Clamped inside the page for garbage .po from misdetected
    binaries.

    This is the DOCUMENT DEFAULT -- the first `.po` in the file, exactly
    like `_printed_lead`'s document default. A line whose own `.po` differs
    (core.Line.po_cols, register b31 -- LJ6DTP.WS moves .po to 2.5" for its
    page-4 checkerboard) overrides this at render time in `_page_stream`,
    the same `.lh`-stateful shape PageLine.lead already carries. It also
    cannot carry a per-page `.poe`/`.poo` (planning #231) -- that's resolved
    per-line by `PageLine.parity_left`/`left`, not here.

    Twin: Swift's public `PrintedPageMetrics.left` (CtrlKD/PrintedGeometry.swift)
    is this same document-default-only value, exposed to Soft Return.app -- its
    doc comment carries the identical .poe/.poo caveat and points callers at
    `PageLine.left` for anything page-specific."""
    page = doc.meta.get('page')
    if page is None:
        return float(MARGIN)
    return _resolve_left_pt(page.get('po_cols', 8.0), size)

FONTS = {(False, False): 'F1', (True, False): 'F2',
         (False, True): 'F3', (True, True): 'F4'}
FONT_NAMES = {'F1': 'Courier', 'F2': 'Courier-Bold',
              'F3': 'Courier-Oblique', 'F4': 'Courier-BoldOblique'}

# ---------------------------------------------------------- the base-14 fonts
#
# Jon's ruling, 2026-08-04: a PRINTED-mode PDF of a WS5+ document renders
# WordStar's exact line breaks (it always has) PLUS the fonts the document
# chose -- through the PDF base-14 built-ins, so still zero dependencies and
# still nothing embedded. MODERN mode is unchanged: Courier-only typewriter
# setting, deliberately. WS4 and print streams carry no font blocks at all, so
# they stay Courier automatically -- there is nothing to look up.
#
# The base-14 set is what every PDF viewer must provide: Times x4, Helvetica
# x4, Courier x4, Symbol, ZapfDingbats. A WordStar typestyle is mapped to one
# of those five families by a strict three-way split -- serif, sans, mono --
# plus the two symbol faces (Jon's amendment: "every face we can't truly
# represent resolves by serif/sans/mono, no special flavoring"). Univers
# becomes Helvetica, Garamond becomes Times, Pica becomes Courier. The era
# name itself is never lost: it stays verbatim in doc.fonts and rides into the
# RTF/HTML exports, which CAN name a real face.
BASE14 = {
    'Courier':      ('Courier', 'Courier-Bold',
                     'Courier-Oblique', 'Courier-BoldOblique'),
    'Times':        ('Times-Roman', 'Times-Bold',
                     'Times-Italic', 'Times-BoldItalic'),
    'Helvetica':    ('Helvetica', 'Helvetica-Bold',
                     'Helvetica-Oblique', 'Helvetica-BoldOblique'),
    # neither symbol face has variants in the base-14 set: bold/italic on a
    # Symbol run has no face to go to, so the roman is used for all four.
    'Symbol':       ('Symbol',) * 4,
    'ZapfDingbats': ('ZapfDingbats',) * 4,
}

# Fixed-pitch era faces, matched on the typestyle NAME. This test must run
# BEFORE the generic-style bits, and the archive says why: the spec's own font
# block for `Courier` declares generic_style 'serif' (a slab serif, which is
# honest typography), and 48 of the 121 font blocks in the Sawyer corpus are
# exactly that. Reading the bits first would have set every Courier run in
# Times -- the one substitution a typescript facsimile must never make.
MONO_FAMILIES = ('courier', 'pica', 'elite', 'lineprinter')

# WordStar measures horizontal advance in HMIs -- 1/1800 inch -- and every
# font block in a WS5+ file carries the per-character width it laid the
# document out on. A PDF point is 1/72 inch, so 1800 HMI = 72 pt and the
# conversion is a division by 25. (The old per-family ADVANCE guesses --
# Times 0.5, Helvetica 0.55 -- are gone: afm.py carries the real per-glyph
# tables now, so nothing here has to approximate a width.)
HMI_PER_POINT = 1800.0 / 72.0                 # = 25

# Tz (horizontal scaling, percent) clamp. A span is scaled to land exactly on
# WordStar's grid; a ratio outside this range does not mean the author wanted
# glyphs at a quarter width, it means the file's HMI and the substituted
# face's metrics disagree -- a typestyle we can only approximate, a font block
# from a printer whose pitch had nothing to do with the base-14. Stretching to
# obey it would produce unreadable text in the name of fidelity, so outside
# the clamp the span keeps its natural advance and the grid loses that one
# argument. 40/250 is wide enough to cover every real substitution in the
# reference corpus (the worst honest case there is ~0.85) and narrow enough
# that a genuinely absurd ratio is caught.
TZ_MIN, TZ_MAX = 40.0, 250.0
TZ_DEFAULT = 100.0                            # PDF's own initial text state

# Face-constant Tz: one horizontal scale per (face, HMI pitch, size), chosen
# so the face's AVERAGE character lands on the document's grid. Per-SPAN
# scaling (the earlier model) forced every span to end exactly on the grid,
# which crushed any short span whose glyphs are wider than average -- a lone
# (c) squeezed to 70% is "not a circle" (Jon, 2026-08-05) -- and let a PDF
# viewer's substitute metrics accumulate error over a whole span before the
# next absolutely-placed span collided with it. A constant per-face scale
# keeps every glyph's true proportions (the driver printed real widths; the
# patched PS tables made WordStar's arithmetic use them too) while words are
# re-anchored to the grid at every space run (see _line_ops_printed).
_TZ_REF = 'abcdefghijklmnopqrstuvwxyz '
_FACE_TZ_CACHE = {}

def _face_tz(basefont, pitch, pt):
    key = (basefont, pitch, pt)
    tz = _FACE_TZ_CACHE.get(key)
    if tz is None:
        avg = _natural_width_pt(_TZ_REF, basefont, pt) / len(_TZ_REF)
        tz = round(pitch / avg * 100.0, 2) if avg > 0 else TZ_DEFAULT
        tz = min(TZ_MAX, max(TZ_MIN, tz))
        _FACE_TZ_CACHE[key] = tz
    return tz

# LJ6DTP's colour palette as PDF fill grays (`g`: 0 black, 1 white). The
# indices are DRIVER-DEFINED -- this table was recovered from the LJ6DTP
# printer description file's own string table and confirmed against the
# document's sample rows (deep-read 2026-08-05): 1-7 are 85/75/50/25/15/5/2%
# ink, 15 is White, the knockout. Index 8 is ambiguous in the source and
# left black. Applied ONLY when the document declares driver LJ6DTP; any
# other driver's indices stay opaque, unrendered.
#
# 1-7 stay FLAT gray rather than real halftone dot screens (Jon's page-5
# defect report, C3, asked for a deliberate call here, not just for 9-14):
# real WS7 puts an actual halftone screen on PAPER, but this table's whole
# job is a SCREEN-reading facsimile, and the seven densities are already
# what the defect was about for 9-14 and NOT about for these -- a flat
# 15%/25%/.../98% gray is already visually DISTINCT row to row at the
# swatch's own size (confirmed against ws7-prints/gpcl6-renders/LJ6DTP-p5.png,
# 2026-08-23), which is exactly the property the HP patterns below were
# missing. A real dot screen would also risk moire against a PDF viewer's
# own rasterizer at arbitrary zoom, for a page whose readable point is "seven
# distinguishable densities" -- which flat gray already delivers.
_COLOUR_GRAY_LJ6DTP = {
    1: 0.15, 2: 0.25, 3: 0.50, 4: 0.75, 5: 0.85, 6: 0.95, 7: 0.98,
    15: 1.0,
}

# HP1-HP6 (colour indices 9-14, confirmed by walking LJ6DTP.WS's own
# colour-change records against its page-5 sample rows: colour9 sits on the
# "HP1" line, colour10 on "HP2", ... colour14 on "HP6" -- deep-read
# 2026-08-23) as real PDF tiling patterns (`/PatternType 1 /PaintType 1`:
# colored, painted with plain black strokes against the transparent cell,
# which reveals white paper between strokes exactly like the driver's own
# fill patterns do). Each entry is (cell width, cell height, content-stream
# ops) in PATTERN SPACE; no /Matrix is set, so pattern space ties to the
# PAGE's default coordinate system (PDF's own rule for an omitted Matrix),
# not to wherever a given glyph's CTM happens to sit -- fine here, every
# swatch is its own isolated fill. Direction and relative density are what
# the reference page distinguishes (horizontal / vertical / two diagonals /
# two crosshatch weaves); exact PCL dot pitch is not reproduced.
_LJ6DTP_HP_PATTERNS = {
    9:  (300, 4, b'1 w 0 0.5 m 300 0.5 l S'),                # HP1 horizontal
    10: (3, 300, b'1 w 1.5 0 m 1.5 300 l S'),                # HP2 vertical
    11: (6, 6, b'0.8 w 0 0 m 6 6 l S'),                      # HP3 diagonal /
    12: (6, 6, b'0.8 w 0 6 m 6 0 l S'),                      # HP4 diagonal \
    13: (6, 6, b'0.8 w 0 3 m 6 3 l S 3 0 m 3 6 l S'),        # HP5 crosshatch +
    14: (4, 4, b'0.7 w 0 0 m 4 4 l S 0 4 m 4 0 l S'),        # HP6 dense X
}

# LJ6DTP's character substitutions -- the driver patches PC-8 slots so that
# typing `_` PRINTS an em dash, `«»` print curly doubles, ☻ prints ©, and so
# on (the whole point of the hack: proper typography out of a 1992 WordStar).
# The map is the document's own chart, recovered and confirmed in the
# deep-read. Face rules from the same chart: fixed-pitch faces (Courier,
# Letter Gothic, LinePrinter) are NOT patched, and the rounded box corners
# exist in Univers only (drawn here as square corners via the vector path --
# the shape is approximated, the position is exact).
_LJ_SUBST = str.maketrans({'☻': '©', '☼': '…', "'": '’', '_': '—',
                           '`': '‘', '«': '“', '»': '”', '≡': '–'})
# Register C7: these four map to the ARC_CORNERS glyphs (rounded join), NOT
# to plain ┌┐└┘ -- see ARC_CORNERS's own comment for why a distinct
# character set matters here.
_LJ_SUBST_UNIVERS = str.maketrans({'♥': '╭', '♦': '╮', '♣': '╰', '♠': '╯'})


def _lj_substitute(segs, kerning=True):
    """Apply the LJ6DTP print-time substitutions to one line's spans.

    `kerning` is core.Line.kerning -- the `.KR` state in force where the
    line sat (default True, WordStar's own default). Two of the substituted
    pairs are only SINGLE curly quotes (backtick -> single open '‘', typed
    apostrophe -> single close '’'): doubling them ("``"/"''") is how the
    document fakes a proper curly DOUBLE quote without the DeskTop symbol
    set actually carrying one -- its own prose: "we've also added these two
    pairs to the PDF kerning tables" so the pair prints TUCKED TOGETHER,
    reading as one double-quote glyph, only when kerning is on (register
    C7). Page 2 demonstrates exactly this: the identical characters typed
    once under `.kr off` and once under `.kr on`, immediately above each
    other, specifically so the difference shows. Kerning off is genuinely
    just the two single quotes at their ordinary advance (loose) -- no
    change from plain substitution. Rather than compute an arbitrary
    sub-glyph kern amount, collapsing the kerned pair to the real double
    curly quote character reproduces the same look the tucked pair makes on
    paper (measured against LJ6DTP-p2.png)."""
    out = []
    for text, styles, family, size_here, entry in segs:
        if entry is not None and entry.get('proportional'):
            text = text.translate(_LJ_SUBST)
            if kerning:
                text = text.replace('‘‘', '“').replace(
                    '’’', '”')
            if (entry.get('typestyle_name') or '').startswith('Univers'):
                text = text.translate(_LJ_SUBST_UNIVERS)
        out.append((text, styles, family, size_here, entry))
    return out

# ------------------------------------------------- cp437 graphics as vectors
#
# Latin-1 has none of cp437's line-drawing repertoire, so the text path
# degrades every box/shade/block glyph to '?'. But these glyphs ARE geometry:
# a full block is a filled cell, a shade is a lighter fill, and each
# box-drawing character is up to four half-arms (up/down/left/right), single
# or double, meeting at the cell's center. Drawing them as rectangles is not
# an approximation of the printed page -- it is what the printer's own glyphs
# put on paper, minus the dot pitch. Only spans WITH a font block take this
# path (a fontless byte is never changed -- same rule as every other printed
# exception).
#
# Arms per glyph: (up, down, left, right); 0 none, 1 single, 2 double.
BOX_ARMS = {
    '─': (0, 0, 1, 1), '│': (1, 1, 0, 0), '┌': (0, 1, 0, 1), '┐': (0, 1, 1, 0),
    '└': (1, 0, 0, 1), '┘': (1, 0, 1, 0), '├': (1, 1, 0, 1), '┤': (1, 1, 1, 0),
    '┬': (0, 1, 1, 1), '┴': (1, 0, 1, 1), '┼': (1, 1, 1, 1),
    '═': (0, 0, 2, 2), '║': (2, 2, 0, 0), '╔': (0, 2, 0, 2), '╗': (0, 2, 2, 0),
    '╚': (2, 0, 0, 2), '╝': (2, 0, 2, 0), '╠': (2, 2, 0, 2), '╣': (2, 2, 2, 0),
    '╦': (0, 2, 2, 2), '╩': (2, 0, 2, 2), '╬': (2, 2, 2, 2),
    '╒': (0, 1, 0, 2), '╓': (0, 2, 0, 1), '╕': (0, 1, 2, 0), '╖': (0, 2, 1, 0),
    '╘': (1, 0, 0, 2), '╙': (2, 0, 0, 1), '╛': (1, 0, 2, 0), '╜': (2, 0, 1, 0),
    '╞': (1, 1, 0, 2), '╟': (2, 2, 0, 1), '╡': (1, 1, 2, 0), '╢': (2, 2, 1, 0),
    '╤': (0, 1, 2, 2), '╥': (0, 2, 1, 1), '╧': (1, 0, 2, 2), '╨': (2, 0, 1, 1),
    '╪': (1, 1, 2, 2), '╫': (2, 2, 1, 1),
}
# Register C7: LJ6DTP's own Univers-only rounded box corners -- the driver
# substitutes ♥♦♣♠ (0x03-0x06) to these in Univers ONLY (`_LJ_SUBST_UNIVERS`),
# never to plain ┌┐└┘. WS7 (LJ6DTP-p3.png) draws a quarter-circle JOIN, not
# BOX_ARMS's sharp right angle -- real box borders elsewhere in the document
# (page 4's checkerboard, page 5's table) are typed as the ORDINARY
# box-drawing bytes and never touch this table, so keeping these as their
# own characters (rather than reusing ┌┐└┘ themselves) can never round a
# real box's corner by accident. Each entry: (vertical arm direction,
# horizontal arm direction) -- the SAME sense BOX_ARMS's own up/down/
# left/right already uses for the square glyphs these replace.
ARC_CORNERS = {
    '╭': ('down', 'right'),   # was ┌ -- upper-left rounded box corner
    '╮': ('down', 'left'),    # was ┐ -- upper-right
    '╰': ('up', 'right'),     # was └ -- lower-left
    '╯': ('up', 'left'),      # was ┘ -- lower-right
}
# Shades: ink coverage -> PDF fill gray (1 = white paper).
SHADE_GRAY = {'░': 0.75, '▒': 0.50, '▓': 0.25}
# Partial blocks: (x-frac, y-frac, w-frac, h-frac) of the cell.
PART_BLOCKS = {'▀': (0, 0.5, 1, 0.5), '▄': (0, 0, 1, 0.5),
               '▌': (0, 0, 0.5, 1), '▐': (0.5, 0, 0.5, 1),
               # cp437 0xFE: the PC-8 black square, WordStar-era bullet of
               # choice (Sawyer's -README list markers). Centered small
               # block, per the IBM glyph -- a TRUE square (fw == fh),
               # meaningful now that SQUARE_PART_BLOCKS scales both axes
               # by the same `sq = min(pitch, h)` reference (round 20,
               # slate item 8). The old (0.12, 0.18, 0.72, 0.55) pair was
               # tuned by eye against the un-squared rendering (pitch for
               # x, h for y independently) and came out 5.2x7.3pt on a
               # 12pt Courier cell -- visibly taller than wide, the
               # "squashed" defect reported. 0.65 keeps the same rough
               # visual weight ("centered small block") as a real square.
               '■': (0.175, 0.175, 0.65, 0.65)}
# ▀▄▌▐ are genuinely CELL-shaped (a "half block" means half the actual
# advance-width/line-height cell, whatever its aspect) -- only ■ is
# authored to look like a regular, roughly-square dot, so only it gets
# the square-cell correction _graphic_ops applies to SYMBOL_SHAPES
# (round 20, slate item 8: squashed cp437 vector glyphs).
SQUARE_PART_BLOCKS = frozenset('■')
# cp437 control-position symbol glyphs (Jon's ruling, 2026-08-11, extending
# the 2026-08-10 box ruling: "the card suits, etc. show up everywhere").
# LJ6DTP p3's "Shows on screen as" column is literal bytes 02-06/0F/F0 — on
# the era's screen: ☻ ♥ ♦ ♣ ♠ ☼ ≡. Latin-1 has none of them, so the text
# path degraded all seven to '?'. Like the box set, they are geometry:
# each entry is a list of filled sub-shapes in cell fractions (x up-right,
# y up from cell bottom):
#   ('poly', [(x,y)…])          closed filled polygon
#   ('disc', cx, cy, r)         filled circle (four Béziers)
#   ('rect', x, y, w, h)        filled rectangle
#   ('white', <sub-shape>)      same shapes, filled paper-white (knockouts)
# Scope is exactly the ruled seven; the rest of CP437_GRAPHICS (arrows,
# music notes …) still degrades until a document surfaces them.
SYMBOL_SHAPES = {
    # Round 20 (slate item 8): symmetric span (0.8 both axes -- was
    # 0.76w/0.84h, a minor pre-existing asymmetry harmless before the
    # pitch/h aspect fix made shape authoring finally square-meaningful).
    '♦': [('poly', [(0.50, 0.90), (0.90, 0.50), (0.50, 0.10), (0.10, 0.50)])],
    '♥': [('disc', 0.32, 0.62, 0.21), ('disc', 0.68, 0.62, 0.21),
          ('poly', [(0.09, 0.56), (0.91, 0.56), (0.50, 0.08)])],
    '♠': [('poly', [(0.50, 0.94), (0.22, 0.52), (0.78, 0.52)]),
          ('disc', 0.32, 0.42, 0.21), ('disc', 0.68, 0.42, 0.21),
          ('poly', [(0.44, 0.36), (0.56, 0.36), (0.62, 0.08), (0.38, 0.08)])],
    '♣': [('disc', 0.50, 0.68, 0.24), ('disc', 0.29, 0.42, 0.24),
          ('disc', 0.71, 0.42, 0.24),
          ('poly', [(0.44, 0.34), (0.56, 0.34), (0.62, 0.06), (0.38, 0.06)])],
    '☻': [('disc', 0.50, 0.50, 0.44),
          ('white', ('disc', 0.34, 0.64, 0.09)),
          ('white', ('disc', 0.66, 0.64, 0.09)),
          ('white', ('rect', 0.28, 0.28, 0.44, 0.09)),
          ('white', ('rect', 0.24, 0.34, 0.08, 0.08)),
          ('white', ('rect', 0.68, 0.34, 0.08, 0.08))],
    '☼': [('disc', 0.50, 0.50, 0.22),
          ('white', ('disc', 0.50, 0.50, 0.11)),
          ('rect', 0.45, 0.78, 0.10, 0.16), ('rect', 0.45, 0.06, 0.10, 0.16),
          ('rect', 0.06, 0.45, 0.16, 0.10), ('rect', 0.78, 0.45, 0.16, 0.10),
          ('rect', 0.17, 0.71, 0.12, 0.12), ('rect', 0.71, 0.71, 0.12, 0.12),
          ('rect', 0.17, 0.17, 0.12, 0.12), ('rect', 0.71, 0.17, 0.12, 0.12)],
    '≡': [('rect', 0.10, 0.62, 0.80, 0.09), ('rect', 0.10, 0.42, 0.80, 0.09),
          ('rect', 0.10, 0.22, 0.80, 0.09)],
}
GRAPHIC_CHARS = (frozenset('█') | set(BOX_ARMS) | set(SHADE_GRAY)
                 | set(PART_BLOCKS) | set(SYMBOL_SHAPES) | set(ARC_CORNERS))
_GRAPHIC_RUN = _re.compile('[%s](?:[%s ]*[%s])?' % tuple(
    _re.escape(''.join(GRAPHIC_CHARS)) for _ in range(3)))
# b26-modern item 2: Modern's word tokenizer (plain `' +|[^ ]+'`) splits a
# box-drawing row -- '<left border><interior spaces><right border>' -- into
# THREE separate tokens (border/gap/border), because the interior is pure
# whitespace and the generic tokenizer always breaks on space runs. Each
# piece then gets measured independently: the border tokens go through
# `_modern_w`'s graphic-pitch branch, but the all-space middle token does
# NOT contain a graphic char, so it falls through to ordinary proportional
# text measurement instead -- the two measurement systems only coincide by
# accident when a resolved fixed-pitch font `entry` is active (both sides
# reduce to the same `_span_pitch` formula then); a genuinely fontless
# region (`entry is None` -- every WS4 file, and any WS5+ document before
# its own first font-change record, e.g. a box that is the document's own
# first content) measures its border chars and its interior gap by two
# UNRELATED formulas, so the row's own drawn width stops matching its
# neighbouring rows -- the observed "first box mangled, later ones fine"
# shape (reproduced on the real corpus, BOXES.WS: its opening box, before
# any font record, measured 322pt; an IDENTICAL box appearing later in the
# same file, by then under a resolved font, measured 165.6pt).
# `_GRAPHIC_RUN` already matches a whole border-gap-border shape in ONE
# piece, and `_modern_w`'s graphic branch already advances such a piece
# uniformly at one pitch end to end -- the fix is to let the TOKENIZER
# find that same shape first, so a box row reaches width measurement (and
# `_modern_wrap`) as the ONE unit it visually is, rather than three
# fragments two different formulas disagree about. This is also exactly
# the "non-reflowing" behavior a graphic/char-array row needs: a single
# token cannot be broken mid-row by `_modern_wrap`'s greedy word-break.
_MODERN_TOK_RE = _re.compile(_GRAPHIC_RUN.pattern + r'|[^ ]+| +')

# b26-modern item 3 (screenplay ruling, BUILD-SLATES.md item 27, Jon's
# decided ruling): two line SHAPES that only matter INSIDE a screenplay-
# detected region (`core.detect_screenplay_blocks` -- gated the same way
# emit.py's own verse-forcing already is, `bi in screenplay_blocks`; a
# WordStar screenplay page-number marker or a numbered scene-list entry
# elsewhere in an ordinary document must never be swept up by these).
#
# A "page marker" line -- SCRIPT.WS's own "1." sitting alone at the top of
# its rendered screenplay page, real screenplay-software convention --
# is nothing but whitespace and a bare 1-4 digit number (optional trailing
# period). Fullmatch, so a slugline's own leading scene number ("1     INT.
# ...") never qualifies (it has letters after the digits on the same
# line).
_SCREENPLAY_PAGE_MARKER_RE = _re.compile(r'[ \t]*\d{1,4}\.?[ \t]*$')

# A genuine slugline (anchored the SAME way `core.detect_screenplay_blocks`
# itself anchors a scene) that also carries a RIGHT-HAND scene number --
# real screenplay convention repeats the scene number at both margins of
# its own slugline. Only a slugline actually shaped this way needs the
# non-wrap protection below; a slugline with no trailing number has
# nothing on its right edge to protect.
_SCREENPLAY_TRAILING_SCENE_NUM_RE = _re.compile(r'[ \t]\d{1,4}[ \t]*$')


# planning #251(c): a fixed cell-FRACTION line/arm thickness for
# `graphic_cell_rects` -- `_graphic_ops`'s own weight (`t = max(0.5, pt /
# 12.0)`) is a POINT thickness independent of pitch, which has no exact
# cell-fraction equivalent (the same 0.5pt hairline is a different
# fraction of a 6pt cell than of a 24pt one); this is a documented visual
# approximation, not a re-derivation fitted to every possible point size.
_GRAPHIC_CELL_LINE_FRAC = 0.08
_GRAPHIC_CELL_DOUBLE_GAP_FRAC = 0.08   # `_graphic_ops`'s own `d == t` rule


def graphic_cell_rects(char):
    """Unit-cell-space rects for one cp437 graphic character's filled
    sub-shapes -- `[(x, y, w, h), ...]`, each 0..1 fraction of the cell
    (x left-to-right, y bottom-to-top from the cell's own baseline-0.25pt
    floor `_graphic_ops` uses), ASSUMING A SQUARE CELL (pitch == height).
    `[]` for a character this module does not draw as geometry at all
    (`char not in GRAPHIC_CHARS`).

    Planning #251(c): the single PUBLIC accessor for every one of this
    module's six graphic-geometry categories (arcCorners/boxArms/
    shadeGray/partBlocks/symbolShapes/fullBlock) -- BOX_ARMS/ARC_CORNERS/
    SHADE_GRAY/PART_BLOCKS/SQUARE_PART_BLOCKS/SYMBOL_SHAPES themselves
    stay module-internal (leading underscore is this module's only
    public/private signal, `_span_pitch`'s own docstring); a consumer
    that wants to DRAW a graphic cell without linking this engine's own
    `_graphic_ops` (Soft Return.app's `PrintedVectorGraphics`, which used
    to hand-port boxArms/shadeGray/partBlocks/symbolShapes by eye from
    this file and had no arcCorners port at all -- that table was never
    exposed anywhere) calls this instead of reading the tables.

    Every rect here is exactly what `_graphic_ops` itself computes at
    pitch == h == 1 -- its own square-cell correction (`sq = min(pitch,
    h)`, used for ■/symbolShapes/arcCorners so those look REGULAR rather
    than squashed onto a non-square cell) reduces to the identity at that
    ratio, so these fractions are not a separate re-derivation, just that
    same arithmetic evaluated once at the square case. A caller with a
    real, non-square cell (Courier's own 12pt/7.2pt pitch is a 0.6
    aspect, the common case) scales x by its own pitch and y by its own
    cell height independently -- the same two-axis scale `_graphic_ops`
    already applies to a partBlocks/boxArms rect, just deferred to the
    caller here.

    `arcCorners` (╭╮╰╯) is the one lossy case: the real glyph is a
    quarter-circle fillet (`_graphic_ops`'s own Bezier join), which no
    rect can represent exactly. This returns the SAME two stub rects the
    sharp-cornered BOX_ARMS glyph it replaces (┌┐└┘) would -- an honest
    bounding approximation missing only the rounding, not a curve API;
    real curve drawing still needs `_graphic_ops`'s own point-level code.
    `shadeGray` (░▒▓) and `fullBlock` (█) both return the single full-cell
    rect `[(0, 0, 1, 1)]` -- shade's own ink-coverage FRACTION (SHADE_GRAY)
    is a fill color, not a geometry difference, and stays out of a
    rects-only return; a caller already needs its own gray/gradient table
    for that regardless of this function.
    `symbolShapes` (♦♥♠♣☻☼≡) returns one bounding-box rect per POSITIVE
    sub-shape (poly points' own min/max extent; a disc's `(cx-r, cy-r,
    2r, 2r)` box); a `white`-tagged sub-shape (a knockout CUT OUT of an
    already-filled area, e.g. ☻'s eyes/mouth) is a subtraction a flat
    rect list cannot express and is omitted -- the positive shapes alone
    already give a caller the glyph's own silhouette/extent."""
    if char == '█':
        return [(0.0, 0.0, 1.0, 1.0)]
    if char in SHADE_GRAY:
        return [(0.0, 0.0, 1.0, 1.0)]
    if char in PART_BLOCKS:
        return [PART_BLOCKS[char]]
    if char in SYMBOL_SHAPES:
        out = []
        for shape in SYMBOL_SHAPES[char]:
            kind = shape[0]
            if kind == 'white':
                continue
            if kind == 'rect':
                _, fx, fy, fw, fh = shape
                out.append((fx, fy, fw, fh))
            elif kind == 'disc':
                _, fx, fy, fr = shape
                out.append((fx - fr, fy - fr, 2 * fr, 2 * fr))
            elif kind == 'poly':
                xs = [p[0] for p in shape[1]]
                ys = [p[1] for p in shape[1]]
                out.append((min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
        return out
    if char in ARC_CORNERS:
        vdir, hdir = ARC_CORNERS[char]
        t = _GRAPHIC_CELL_LINE_FRAC
        rc = 0.42
        mx = my = 0.5
        v_far = 0.0 if vdir == 'down' else 1.0
        h_far = 1.0 if hdir == 'right' else 0.0
        ay = my + (rc if vdir == 'up' else -rc)
        bx = mx + (rc if hdir == 'right' else -rc)
        out = [(mx - t / 2, min(v_far, ay), t, abs(ay - v_far))]
        out.append((min(h_far, bx), my - t / 2, abs(bx - h_far), t))
        return out
    if char in BOX_ARMS:
        u, dn, l, r = BOX_ARMS[char]
        t = _GRAPHIC_CELL_LINE_FRAC
        d = _GRAPHIC_CELL_DOUBLE_GAP_FRAC
        mx = my = 0.5
        out = []
        for weight, xa, xb in ((l, 0.0, mx), (r, mx, 1.0)):
            if weight == 1:
                out.append((xa, my - t / 2, xb - xa, t))
            elif weight == 2:
                out.append((xa, my + d - t / 2, xb - xa, t))
                out.append((xa, my - d - t / 2, xb - xa, t))
        for weight, ya, yc in ((u, my, 1.0), (dn, 0.0, my)):
            if weight == 1:
                out.append((mx - t / 2, ya, t, yc - ya))
            elif weight == 2:
                out.append((mx - d - t / 2, ya, t, yc - ya))
                out.append((mx + d - t / 2, ya, t, yc - ya))
        return out
    return []


def graphic_cell_ops(char):
    """Drawing-grade geometry for one cp437 graphic character, in unit-cell
    space -- planning #251 follow-up (2026-09-10, app coder job 348,
    docs/KNOWN-ISSUES-REGISTER.md planning #216 row): where
    `graphic_cell_rects` hands a consumer bounding RECTS, this hands it the
    actual drawing OPERATIONS `_graphic_ops` itself executes -- filled
    rects/discs/polygons for the five table-driven categories (never
    bounding-boxed: a disc stays a true disc, a poly stays its exact vertex
    list, unlike `graphic_cell_rects`' own documented bounding-box
    simplification for those two), and for arcCorners a SINGLE
    `('stroke_path', segments, line_width_frac)` carrying the exact same
    four path commands and Bezier control points `_graphic_ops`'s own
    arcCorners branch computes (move-to the far stub end, line-to the near
    stub end, curve-to the quarter-circle join with `_graphic_ops`'s own
    K=0.5523 constant, line-to the other stub's far end) -- never split
    into separate shapes, so a consumer executing this op list draws the
    identical shape at the identical op count as the real PDF.
    `test_graphic_cell_ops_parity.py` replays each arcCorners character's
    ops back into the same raw PDF operator KIND sequence `_graphic_ops`
    itself emits (w, m, l, c, l, S) and asserts an exact match, both count
    and kind -- LJ6DTP.WS page 3's own regression (51 app-drawn ops
    against 35 real PDF ops, `graphic_cell_rects`' two-rects-per-arc
    reconstruction) is the corpus case this closes.

    Op shapes:
      ('fill_rect', x, y, w, h, gray)     gray is None except SHADE_GRAY's
                                           own entries, which carry their
                                           ink-coverage fraction
      ('fill_disc', cx, cy, r)
      ('fill_polygon', points)            points: [(x, y), ...]
      ('stroke_path', segments, line_width_frac)
                                           segments: [('m', x, y),
                                           ('l', x, y), ('c', c1x, c1y,
                                           c2x, c2y, x, y), ...]

    `[]` for a character this module does not draw as geometry at all
    (`char not in GRAPHIC_CHARS`), same convention `graphic_cell_rects`
    uses. Port of Swift's `graphicCellOps`."""
    if char == '█':
        return [('fill_rect', 0.0, 0.0, 1.0, 1.0, None)]
    if char in SHADE_GRAY:
        return [('fill_rect', 0.0, 0.0, 1.0, 1.0, SHADE_GRAY[char])]
    if char in PART_BLOCKS:
        fx, fy, fw, fh = PART_BLOCKS[char]
        return [('fill_rect', fx, fy, fw, fh, None)]
    if char in SYMBOL_SHAPES:
        out = []
        for shape in SYMBOL_SHAPES[char]:
            kind = shape[0]
            if kind == 'white':
                continue   # knockout -- see `graphic_cell_rects`' own doc comment
            if kind == 'rect':
                _, fx, fy, fw, fh = shape
                out.append(('fill_rect', fx, fy, fw, fh, None))
            elif kind == 'disc':
                _, fx, fy, fr = shape
                out.append(('fill_disc', fx, fy, fr))
            elif kind == 'poly':
                out.append(('fill_polygon', list(shape[1])))
        return out
    if char in ARC_CORNERS:
        vdir, hdir = ARC_CORNERS[char]
        t = _GRAPHIC_CELL_LINE_FRAC
        rc = 0.42
        mx = my = 0.5
        sv = 1.0 if vdir == 'up' else -1.0
        sh = 1.0 if hdir == 'right' else -1.0
        ax, ay = mx, my + sv * rc
        bx, by = mx + sh * rc, my
        K = 0.5523
        c1x, c1y = ax, my + sv * rc * (1 - K)
        c2x, c2y = mx + sh * rc * (1 - K), by
        v_far = 0.0 if vdir == 'down' else 1.0
        h_far = 1.0 if hdir == 'right' else 0.0
        segments = [
            ('m', mx, v_far),
            ('l', ax, ay),
            ('c', c1x, c1y, c2x, c2y, bx, by),
            ('l', h_far, my),
        ]
        return [('stroke_path', segments, t)]
    if char in BOX_ARMS:
        u, dn, l, r = BOX_ARMS[char]
        t = _GRAPHIC_CELL_LINE_FRAC
        d = _GRAPHIC_CELL_DOUBLE_GAP_FRAC
        mx = my = 0.5
        out = []
        for weight, xa, xb in ((l, 0.0, mx), (r, mx, 1.0)):
            if weight == 1:
                out.append(('fill_rect', xa, my - t / 2, xb - xa, t, None))
            elif weight == 2:
                out.append(('fill_rect', xa, my + d - t / 2, xb - xa, t, None))
                out.append(('fill_rect', xa, my - d - t / 2, xb - xa, t, None))
        for weight, ya, yc in ((u, my, 1.0), (dn, 0.0, my)):
            if weight == 1:
                out.append(('fill_rect', mx - t / 2, ya, t, yc - ya, None))
            elif weight == 2:
                out.append(('fill_rect', mx - d - t / 2, ya, t, yc - ya, None))
                out.append(('fill_rect', mx + d - t / 2, ya, t, yc - ya, None))
        return out
    return []


def _graphic_ops(text, x, y, pitch, pt, lead_factor=1.1):
    """Vector ops for one all-graphics span (spaces advance, draw nothing).

    `lead_factor * pt` is the glyph's own CELL height -- a box-drawing arm's
    vertical stroke spans the full cell, top to bottom (see the `else`
    branch below), so consecutive PHYSICAL lines' cells only chain into one
    continuous rule if this cell is at least as tall as the actual line-to-
    line advance. Printed's default (1.1) leaves deliberate slack against
    its own LEAD (12pt default, matching a 12pt font: 1.1*12=13.2 > 12, a
    harmless sub-point overlap, invisible on paper/PDF) because Printed's
    per-line leading can vary block to block (`.lh`) independently of any
    fixed relationship to `pt`.

    Modern has no such slack: its own line advance is EXACTLY
    `MODERN_LINE * pt` (`_modern_flow`'s own `h`, uniform per vline), so the
    default 1.1 factor left a real gap -- register b32, BOX.WS/BOXES.WS's
    box sides rendering as broken dashes in Modern PDF (1.1*14=15.4pt cell
    vs 1.2*14=16.8pt actual advance, a 1.4pt gap every line). Modern's own
    call site passes `MODERN_LINE` here so the cell height matches its own
    advance exactly -- cells touch with zero gap AND zero overlap, for any
    uniformly-sized run of lines (the ordinary case for ASCII box art)."""
    ops = []
    yb, h = y - 0.25 * pt, lead_factor * pt
    my = yb + h / 2.0
    t = max(0.5, pt / 12.0)                  # line weight
    # Register C12: a double-weight box-drawing rule (═, ║, and the table
    # junction characters built from them) is two hairlines with a hairline
    # GAP between them, not two hairlines a whole extra stroke-width apart.
    # `d` used to be an unmeasured guess (a bare pt/10, no citation); pixel-
    # sampled against LJ6DTP-p7.png's own proportional-spacing table at
    # 300dpi (10.05pt Courier, page 7's own PC-8/font-family grid, the
    # BEST-matching page in the document but for this): real WS7's double
    # rule is two ~3px strokes with a ~3px gap between them -- stroke and
    # gap the SAME size, i.e. d == t, not pt/10 (which measured a visibly
    # wider ~5px gap, "possibly doubled" reading heavier as a unit even
    # though the single-weight stroke elsewhere on the same page already
    # matched at 3px either way).
    d = t                                    # double-line half-gap
    def rect(rx, ry, rw, rh):
        ops.append(b'%.1f %.1f %.1f %.1f re f' % (rx, ry, rw, rh))
    K = 0.5523                               # Bézier circle constant
    def disc(cx, cy, r):
        k = K * r
        ops.append(b'%.1f %.1f m' % (cx + r, cy))
        ops.append(b'%.1f %.1f %.1f %.1f %.1f %.1f c'
                   % (cx + r, cy + k, cx + k, cy + r, cx, cy + r))
        ops.append(b'%.1f %.1f %.1f %.1f %.1f %.1f c'
                   % (cx - k, cy + r, cx - r, cy + k, cx - r, cy))
        ops.append(b'%.1f %.1f %.1f %.1f %.1f %.1f c'
                   % (cx - r, cy - k, cx - k, cy - r, cx, cy - r))
        ops.append(b'%.1f %.1f %.1f %.1f %.1f %.1f c'
                   % (cx + k, cy - r, cx + r, cy - k, cx + r, cy))
        ops.append(b'f')
    # Round 20 (slate item 8): a symbol glyph's fractional coordinates are
    # authored to look REGULAR (a round dot, a true diamond, a circular
    # sun) -- not cell-shaped like a box-drawing arm or a half-block.
    # Scaling x by `pitch` and y by `h` independently only reproduces
    # that intent when the two happen to be equal; a real printed cell
    # never is (12pt Courier: pitch 7.2pt advance, h 13.2pt) -- disc()'s
    # own radius already used `min(pitch, h)` (bisected b22-pin 142f478
    # vs current on CONVERT.WS: BYTE-IDENTICAL, so this was never a
    # regression -- the mismatch has always been there, just never
    # applied to poly/rect). `sq` and cell-CENTER-relative offsets make
    # every shape kind use the same single, consistent scale: a strict
    # generalization that reproduces the exact prior output whenever
    # pitch == h (the poly/rect formulas below reduce algebraically to
    # `x0 + fx*pitch, yb + fy*h` in that case) and only corrects the
    # aspect when it doesn't.
    sq = min(pitch, h)
    def symbol_shape(shape, x0):
        cx, cy = x0 + pitch / 2.0, yb + h / 2.0
        kind = shape[0]
        if kind == 'white':
            ops.append(b'q 1 g')
            symbol_shape(shape[1], x0)
            ops.append(b'Q')
        elif kind == 'poly':
            pts = [(cx + (fx - 0.5) * sq, cy + (fy - 0.5) * sq)
                  for fx, fy in shape[1]]
            ops.append(b'%.1f %.1f m' % pts[0])
            for p in pts[1:]:
                ops.append(b'%.1f %.1f l' % p)
            ops.append(b'h f')
        elif kind == 'disc':
            _, fx, fy, fr = shape
            disc(cx + (fx - 0.5) * sq, cy + (fy - 0.5) * sq, fr * sq)
        elif kind == 'rect':
            _, fx, fy, fw, fh = shape
            rect(cx + (fx - 0.5) * sq, cy + (fy - 0.5) * sq, fw * sq, fh * sq)
    for n, ch in enumerate(text):
        x0 = x + n * pitch
        if ch == ' ':
            continue
        if ch in SYMBOL_SHAPES:
            for shape in SYMBOL_SHAPES[ch]:
                symbol_shape(shape, x0)
        elif ch == '█':
            rect(x0, yb, pitch, h)
        elif ch in SHADE_GRAY:
            ops.append(b'q %.2f g' % SHADE_GRAY[ch])
            rect(x0, yb, pitch, h)
            ops.append(b'Q')
        elif ch in PART_BLOCKS:
            fx, fy, fw, fh = PART_BLOCKS[ch]
            if ch in SQUARE_PART_BLOCKS:
                cx, cy = x0 + pitch / 2.0, yb + h / 2.0
                rect(cx + (fx - 0.5) * sq, cy + (fy - 0.5) * sq,
                     fw * sq, fh * sq)
            else:
                rect(x0 + fx * pitch, yb + fy * h, fw * pitch, fh * h)
        elif ch in ARC_CORNERS:
            # Register C7: one vertical stub + one horizontal stub (same
            # extent as the matching BOX_ARMS glyph: cell-center to cell
            # edge), joined by a quarter-circle instead of meeting square
            # at the center. sh/sv pick which cell edge each stub reaches
            # (+1 = right/up, -1 = left/down) and, together, the arc's own
            # center C = (mx + sh*rc, my + sv*rc); A and B (the stub ends
            # ON the arc) sit exactly `rc` from C along the axes, so the
            # standard 4-point cubic-bezier quarter-circle (K, same
            # constant `disc()` uses above) joins them exactly.
            vdir, hdir = ARC_CORNERS[ch]
            mx = x0 + pitch / 2.0
            sv = 1.0 if vdir == 'up' else -1.0
            sh = 1.0 if hdir == 'right' else -1.0
            rc = 0.42 * min(pitch, h)
            ax, ay = mx, my + sv * rc                  # vertical stub's end,
            bx, by = mx + sh * rc, my                   # horiz stub's end --
                                                         # both ON the arc
            c1x, c1y = ax, my + sv * rc * (1 - K)
            c2x, c2y = mx + sh * rc * (1 - K), by
            v_far = (yb if vdir == 'down' else yb + h)
            h_far = (x0 + pitch if hdir == 'right' else x0)
            ops.append(b'%.2f w' % t)
            ops.append(b'%.1f %.1f m' % (mx, v_far))
            ops.append(b'%.1f %.1f l' % (ax, ay))
            ops.append(b'%.1f %.1f %.1f %.1f %.1f %.1f c'
                       % (c1x, c1y, c2x, c2y, bx, by))
            ops.append(b'%.1f %.1f l' % (h_far, my))
            ops.append(b'S')
        else:
            u, dn, l, r = BOX_ARMS[ch]
            mx = x0 + pitch / 2.0
            for weight, xa, xb in ((l, x0, mx), (r, mx, x0 + pitch)):
                if weight == 1:
                    rect(xa, my - t / 2, xb - xa, t)
                elif weight == 2:
                    rect(xa, my + d - t / 2, xb - xa, t)
                    rect(xa, my - d - t / 2, xb - xa, t)
            for weight, ya, yc in ((u, my, yb + h), (dn, yb, my)):
                if weight == 1:
                    rect(mx - t / 2, ya, t, yc - ya)
                elif weight == 2:
                    rect(mx - d - t / 2, ya, t, yc - ya)
                    rect(mx + d - t / 2, ya, t, yc - ya)
    return ops


def _split_graphics(segs):
    """Break mixed text/graphics spans so each piece is all-one-kind. Spans
    with no graphic character at all pass through whole. A font block is NOT
    required (Jon's ruling, 2026-08-10, overruling M11's printed-fontless
    doctrine): a cp437 box/block glyph is geometry regardless of the run
    carrying a WS5+ font block -- "the reason the box shows up is that it
    could be done in that era." Mirrors the Swift engine's c01470a."""
    out = []
    for seg in segs:
        text, styles, family, size_here, entry = seg
        if not (set(text) & GRAPHIC_CHARS):
            out.append(seg)
            continue
        pos = 0
        for m in _GRAPHIC_RUN.finditer(text):
            if m.start() > pos:
                out.append((text[pos:m.start()], styles, family, size_here,
                            entry))
            out.append((m.group(0), styles, family, size_here, entry))
            pos = m.end()
        if pos < len(text):
            out.append((text[pos:], styles, family, size_here, entry))
    return out


# ---------------------------------------- cp437 Greek/math/Dingbats fallback
#
# cp1252 (Printed PDF's declared /WinAnsiEncoding, _esc; Modern PDF's body
# faces the same) carries none of the Greek/math repertoire cp437 puts at
# 0xE0-0xEE -- real WS7 prints this fine (measured: jon_vault's -SCREEN.pcl +
# .measurements.json, the "αßΓπ..." line), because the driver routed those
# bytes through the Symbol PostScript font, not through the body face's own
# encoding. The same is true of cp437's own Dingbats repertoire wherever it
# turns up outside GRAPHIC_CHARS' card-suit/smiley vector shapes (those stay
# vectors -- see `_span_render`'s docstring and the GRAPHIC_CHARS guard
# below). `_pdf_family` already recognises a WHOLE span's font block as
# 'math'/'symbols' (a real `.symbol`/`.dingbat`-typestyle font); this is the
# same face-bypass for the common case, PLAIN COURIER PROSE that happens to
# carry a handful of cp437 Greek/math/Dingbats bytes with no Symbol/Dingbats
# font block in play at all. A character cp1252 cannot carry but
# symbolmap.symbol_fallback_kind can (the same Adobe Symbol/ZapfDingbats
# repertoire the real `.math`/`.symbols` path already writes) gets its own
# segment, face switched to Symbol or ZapfDingbats and untransliterated to
# the face's own byte code -- everything else in the run (including
# cp1252-representable look-alikes like micro sign / sharp-s, which are NOT
# this bug) stays on its own declared face untouched. Mirrors
# _split_graphics's declared-font bypass for box glyphs exactly, and (via
# the GRAPHIC_CHARS check below) never fights it for the same character.
#
# `_split_symbol_fallback` is Printed's own seg-list shape; `_symbol_
# fallback_split` is the same run-finding logic factored out to (text,
# family) pairs so Modern's per-token loop in `_modern_flow` can call it too
# (round 2026-09-07: Modern used to skip this fallback entirely -- every
# cp437 Greek/math/Dingbats byte in a fontless or plain-body Modern span
# rode straight to cp1252 encoding and came out '?'; Printed already had
# this fix, Modern's own `_modern_tok_font` never called it).
FALLBACK_FAMILY = {'math': 'Symbol', 'symbols': 'ZapfDingbats'}


def _cp1252_ok(ch):
    try:
        ch.encode('cp1252')
        return True
    except UnicodeEncodeError:
        return False


def _symbol_fallback_split(text, family):
    """[(piece_text, piece_family), ...] for one already-resolved (text,
    family) span/token: text broken at cp1252-fallback boundaries, a piece
    that needs Symbol or ZapfDingbats peeled onto that face (untransliterated
    to its own byte codes), everything else -- including any GRAPHIC_CHARS
    member, which _split_graphics/_modern_w's own vector-fill path owns, not
    this one -- staying on `family` untouched. A single-piece result with
    the input text unchanged (same object) means no fallback was needed."""
    if not text or all(_cp1252_ok(ch) or ch in GRAPHIC_CHARS for ch in text):
        return [(text, family)]                # fast path: no fallback needed
    runs, run_kind, buf_start, started = [], None, 0, False
    for i, ch in enumerate(text):
        kind = (None if (ch in GRAPHIC_CHARS or _cp1252_ok(ch))
                else symbol_fallback_kind(ch))
        if not started:
            run_kind, started = kind, True
        elif kind != run_kind:
            runs.append((buf_start, i, run_kind))
            buf_start, run_kind = i, kind
    runs.append((buf_start, len(text), run_kind))
    pieces = []
    for start, end, kind in runs:
        piece = text[start:end]
        if kind is None:
            pieces.append((piece, family))
        else:
            pieces.append((untransliterate(piece, kind), FALLBACK_FAMILY[kind]))
    return pieces


def _split_symbol_fallback(segs):
    out = []
    for seg in segs:
        text, styles, family, size_here, entry = seg
        if family in ('Symbol', 'ZapfDingbats'):
            # already on the real Symbol/Dingbats face (untransliterated
            # face codes, not Unicode -- nothing here could ever match).
            out.append(seg)
            continue
        for piece, piece_family in _symbol_fallback_split(text, family):
            out.append((piece, styles, piece_family, size_here, entry))
    return out


def _pdf_family(entry):
    """The base-14 family for one doc.fonts entry.

    Order is deliberate:
      1. the font's own symbol-map/name verdict (symbolmap.font_translit_kind)
         -- 'math' IS Symbol, 'symbols' IS ZapfDingbats, and those two we can
         reproduce exactly rather than approximate;
      2. THE PROPORTIONAL BIT, decisive (round 9, Jon's ruling, tier-1
         evidence): `entry['proportional'] is False` -> Courier, full stop,
         REGARDLESS of the typestyle's own name. This is the record's own
         declared pitch, not a name-based guess -- WSFORMAT's generic
         Non-PostScript typestyles 103/104 ("NPS SansSer Qual"/"NPS Serif
         Qual") are letter-quality dot-matrix categories, not real
         PostScript serif/sans faces, and a document can decl. proportional
         =False for ANY typestyle name, mono-sounding or not. Promoting one
         of these to Times/Helvetica was Jon's field-reviewed "crazy fat"
         defect (SCRIPT.WS, round 8/9): wrong weight (a full commercial
         proportional face reads heavier than the era's NLQ approximation)
         AND wrong advance widths (the existing HMI/Tz grid machinery
         already renders proportional=False content at its own true pitch
         -- Courier is the only base-14 family that grid can be honest at).
         Checked with `is False`, not falsy, so a dict that genuinely lacks
         the key (see 4) falls through instead of matching here by accident;
      3. fixed-pitch NAMES -> Courier (MONO_FAMILIES) -- tier-2, for a
         record whose own proportional bit is UNAVAILABLE rather than
         False (a style-record font field or other construction that
         doesn't carry the full WSFORMAT typestyle word -- WS4 has no font
         records at all and hits the `not entry` return above instead, so
         this tier is for anything else still short a clean bit);
      4. the font block's own generic-style bits: serif -> Times, sans ->
         Helvetica. 'script' also lands on Times and 'display' on Helvetica
         (Jon: "I don't think we have any option for script... maybe just
         Times"); the base-14 set has no chancery and no poster face, and the
         era's display typestyles are overwhelmingly sans-shaped, so those are
         the honest neighbours rather than an italic/bold pretence;
      5. anything unresolvable -> Courier, the emitter's own default.

    Bold and italic are NEVER decided here -- they come from the span's own
    b/i styles, exactly as they always have (a proportional=False record
    that's ALSO span-bold still renders Courier-Bold, never Times-Bold)."""
    if not entry:
        return 'Courier'
    kind = font_translit_kind(entry)
    if kind == 'math':
        return 'Symbol'
    if kind == 'symbols':
        return 'ZapfDingbats'
    if entry.get('proportional') is False:
        return 'Courier'
    fam = _font_family(entry.get('typestyle_name')).lower()
    if any(fam.startswith(m) for m in MONO_FAMILIES):
        return 'Courier'
    return {'serif': 'Times', 'sans': 'Helvetica',
            'script': 'Times', 'display': 'Helvetica'}.get(
                entry.get('generic_style'), 'Courier')


class FontRes:
    """The page-resource font table, built as the content streams are written.

    The Courier four are ALWAYS /F1../F4 and always emitted, used or not. That
    is not laziness: it is what keeps a document with no font runs -- every WS4
    file, every print stream, and most WS5+ documents -- byte-for-byte
    identical to what this emitter produced before fonts existed here. Emitting
    only the fonts a page really touches would renumber the object table for
    those files and change every PDF the project has ever made. Fonts BEYOND
    the Courier four are added on demand, in first-use order, so a Courier
    document still ships exactly four font objects."""

    def __init__(self):
        self.names = dict(FONT_NAMES)                       # 'F1' -> basefont
        self._by_base = {b: f for f, b in FONT_NAMES.items()}

    def ref(self, basefont):
        """The /Fn name for a base-14 font, registering it if new."""
        key = self._by_base.get(basefont)
        if key is None:
            key = 'F%d' % (len(self.names) + 1)
            self.names[key] = basefont
            self._by_base[basefont] = key
        return key


def _span_font(styles, fonts):
    """The doc.fonts entry a span's active 'fontN' tag points at, or None.
    (The 'altfont' tag -- WS4's ^PA printer-alternate flag -- is deliberately
    not consulted: it names no font, it only says "the other wheel".)"""
    if not fonts:
        return None
    idx = min((int(t[4:]) for t in styles
               if t.startswith('font') and t[4:].isdigit()), default=None)
    if idx is None or idx >= len(fonts):
        return None
    return fonts[idx]


def _span_render(text, styles, fonts, size):
    """(text-as-written, family, size, font-entry) for one span.

    Symbol/ZapfDingbats runs were transliterated to real Unicode at parse time
    (symbolmap.py) so that every text format renders without a font. Here we
    have the font, so the transliteration is undone: the original byte codes go
    back on the page with the real face selected, and a viewer draws the actual
    glyph -- alpha, not the letter 'a', with nothing embedded.

    cp437 block/shade/box-drawing glyphs (GRAPHIC_CHARS) are the one
    exception: those draw as VECTOR GEOMETRY (_split_graphics/_graphic_ops)
    regardless of which font the span carries -- even a span whose typestyle
    resolves to Symbol/ZapfDingbats here (sawyer/-LASERJE.FNT line 9: Brush
    Script's own font block declares symbol_map='math', so its twelve-glyph
    cp437 sample -- '░▒▓│┤╡╢╖╕╣║╗' -- used to hit this branch same as any
    other Symbol run). untransliterate()'s own documented contract degrades
    anything it cannot round-trip to '?' (symbolmap.py) -- exactly right for
    a real Symbol run, but it ran BEFORE _split_graphics ever got a look, so
    twelve real box/shade glyphs became twelve literal '?' text characters
    at the Symbol font's advance instead of the fills every other family
    already draws them as. GRAPHIC_CHARS members keep their true Unicode
    code points here so _split_graphics finds them downstream unchanged;
    everything else in the run still makes the real Symbol/Dingbats byte
    round trip, untouched."""
    entry = _span_font(styles, fonts)
    family = _pdf_family(entry)
    if family in ('Symbol', 'ZapfDingbats'):
        kind = font_translit_kind(entry)
        if set(text) & GRAPHIC_CHARS:
            text = ''.join(ch if ch in GRAPHIC_CHARS else untransliterate(ch, kind)
                           for ch in text)
        else:
            text = untransliterate(text, kind)
    pts = (entry or {}).get('points')
    # Tf has always been written as an integer here; the span's own size comes
    # from the font block's height word, falling back to the document's size.
    # The entry itself rides along because the LAYOUT needs its width word --
    # `width_1800`, the per-character advance WordStar used (_span_pitch).
    return text, family, (max(1, round(pts)) if pts else size), entry

# Lookalike degradations for glyphs cp1252 cannot carry -- applied before
# encoding so a middle dot from a header triple or a box glyph in a fontless
# span degrades to its nearest visible relative, not to '?'.
#
# Finding 2 (b26 visual pass, -README.WS/-README.pcl): cp437 code 158
# decodes to PESETA SIGN (U+20A7) -- cp1252/WinAnsi has no glyph for it
# either (base-14 has no euro glyph and no peseta glyph -- Symbol has
# neither), so it fell to '?' here same as any other unrepresentable
# character. -README.WS's OWN text explains the honest reading for a
# post-1999 WordStar install: "WordStar was last updated in 1992, seven
# years before the euro currency symbol was adopted in 1999" -- the
# corpus's dosbox-x setup patches three of its own PDFs (printer driver
# files) to show the euro at this exact code instead ("euro=158" in the
# [render] section), and its own worked example inserts code 158 to
# PROVE the euro renders. Substituting the one glyph cp1252 actually has
# at this position (EURO SIGN, U+20AC, cp1252 0x80) turns a guaranteed
# '?' into what a real modern WS7 install of this exact corpus shows.
#
# KNOWN LIMIT, recorded rather than hidden: DISPLAY.WS (Sawyer corpus)
# also carries one <1B 9E 1C> triple, in a bare cp437 code-to-glyph
# reference chart ("158 <glyph>") with no euro context at all -- real
# cp437 code 158 IS the peseta sign, not the euro, so this substitution
# is specifically right for -README's own documented intent and
# arguably wrong for DISPLAY's literal chart entry. Both currently show
# '?' at that position either way (no font in this pipeline can draw a
# real peseta glyph), so this is not a working document regressing --
# it is one broken cell resolved the same way in both, and DISPLAY.WS
# is outside the checked-in/gated corpus, so nothing here is verified
# against its own WS7 capture.
# Register C9: '•' (U+2022 BULLET -- WordStar's own cp437 0x07 list marker,
# CP437_GRAPHICS's own mapping) is NOT a fallback case at all: cp1252 has a
# real bullet glyph for it (0x95), same as every base-14 face's own
# /WinAnsiEncoding. It used to collapse to the SAME target as its lookalike
# '∙' (U+2219 BULLET OPERATOR, a math symbol genuinely absent from cp1252),
# downgrading every WordStar bulleted list (LJ6DTP's own Features list,
# page 1) from a round bullet to a middle dot for no encoding reason at
# all -- measured against LJ6DTP-p1.png. '∙' keeps its fallback; '•' needs
# none.
_ESC_FALLBACK = str.maketrans({'∙': '·', '‼': '!', '│': '|',
                               '─': '-', '═': '=', '₧': '€'})

def _esc(text):
    # cp1252, not latin-1: the declared /WinAnsiEncoding IS cp1252, and it is
    # what gives the base-14 faces curly quotes, en/em dashes, ellipsis and
    # the rest of the typographic range the LJ6DTP substitutions produce.
    raw = text.translate(_ESC_FALLBACK).encode('cp1252', 'replace')
    return raw.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')

# ----------------------------------------- Finding 1: synthetic Symbol style
#
# Symbol has ONE cut in the base-14 set (BASE14['Symbol'] above) -- a b/i
# span routed there loses its styling entirely, but real WS7 does not: the
# -SCREEN.WS Greek sample line prints all four runs (plain/bold/italic/
# bold-italic) visibly distinct. Measured against -SCREEN.pcl's own font-
# select bytes for that line (offset 2767, the four `ESC(s...T` groups):
#   plain       sp12v10.00hsb4099T
#   bold        sp12v10.00hs3b4099T        (style 0, weight 3)
#   italic      sp12v10.00h1sb4099T        (style 1, weight 0)
#   bold-italic sp12v10.00h1s3b4099T       (style 1, weight 3)
# -- i.e. HP PCL's own `s`(style: 0 upright/1 italic)/`b`(stroke weight: 0
# medium/3 bold) fields, decoded per the driver table this project already
# keeps (CLAUDE.md). All four select the SAME typeface (4099, Courier per
# font_mapping) at the SAME height (12v) and pitch (10.00h) -- confirmed by
# the measured chunk x-positions too: the run width for 14 glyphs is 108pt
# (1080 decipoints) in EVERY style (plain 504->1584, bold 1728->2808,
# italic 2952->4032), so the LaserJet's own font engine applied weight and
# posture to the SAME glyph cell rather than substituting a wider/narrower
# design. Synthetic styling here does the same: the run's advance is never
# touched (see call sites), only how the glyph is painted.
#   bold   -> text render mode 2 (fill THEN stroke), stroke colour matched
#             to the fill, stroke width a fraction of the point size (faux-
#             bold weight; there is no measured stroke width to derive this
#             from -- a printer's bold is a font-engine decision, not a PDF
#             one -- so 0.04 * pt is Jon's-instructions-standard "visibly
#             bolder, not blotted" faux-bold weight).
#   italic -> an oblique shear on the text matrix (Tm replaces Td), the
#             standard ~12-degree slant used industry-wide when a face has
#             no real italic cut; nothing in the measured evidence implies
#             a different angle (WS7's italic Greek run has the identical
#             108pt advance as plain/bold, so the printer wasn't shearing
#             the ADVANCE either -- a pure per-glyph oblique, which is
#             exactly what Tm's shear does here: e/f still place the run
#             at the same (x, y) the unstyled path would have used).
# An unstyled Symbol run (no 'b'/'i') is untouched -- this function is
# never called for it -- so every existing byte-identical guarantee holds.
_ITALIC_SHEAR = round(_math.tan(_math.radians(12)), 4)   # ~12 degrees
_BOLD_STROKE_FRAC = 0.04                                  # faux-bold weight


def _symbol_style_op(font, pt, rise, want, tz_state, x, y, text_bytes,
                     is_bold, is_italic):
    """One BT..ET op for a styled (bold and/or italic) Symbol-face run.
    Mirrors the plain-run op shape (Tf, [Tz], Ts, position, Tj) exactly,
    adding only what styling requires: `2 Tr <w> w` before Ts for bold
    (text render mode + stroke width; stroke colour is whatever fill
    colour is already active -- Symbol runs never carry LJ6DTP colour tags
    in the reference corpus, so this is always black, matching the fill),
    and Tm instead of Td for italic (the shear).

    Finding 3 (b26 visual pass, -SCREEN.WS): Tr is PDF general graphics
    state, not text state reset by BT -- it survives an ET/BT pair. This
    function is the ONLY writer of Tr anywhere in this module, so it used
    to write `2 Tr` before a bold run and simply say nothing for a
    non-bold one, trusting the DEFAULT (0, fill only) was still in
    effect. On -SCREEN's own Greek sample line the four styled runs
    print plain/bold/italic/bold-italic in that order on one content
    stream -- the italic-only run comes right after the bold run and,
    with no Tr op of its own, inherited the bold run's `2 Tr` (fill AND
    stroke) instead of the plain fill Jon's paper check confirms WS7
    actually used, which is exactly why the synthesized italic read
    heavier than the real printer's: it was quietly getting a bold
    stroke, not just a shear. (The same leak would have kept stroking
    every later op on the page too, symbol-styled or not, until
    whatever next set Tr some other way -- nothing else in this module
    ever did.) Always writing Tr now, every call, makes each styled run
    self-contained regardless of what the stream's state happened to be
    coming in."""
    parts = [b'BT /%s %d Tf' % (font.encode(), pt)]
    if want != tz_state[0]:
        parts.append(b'%.2f Tz' % want)
        tz_state[0] = want
    if is_bold:
        parts.append(b'2 Tr %.2f w' % round(pt * _BOLD_STROKE_FRAC, 2))
    else:
        parts.append(b'0 Tr')
    parts.append(b'%d Ts' % rise)
    if is_italic:
        parts.append(b'1 0 %.4f 1 %.1f %.1f Tm' % (_ITALIC_SHEAR, x, y))
    else:
        parts.append(b'%.1f %.1f Td' % (x, y))
    parts.append(b'(%s) Tj ET' % text_bytes)
    return b' '.join(parts)


def _wrap_line(spans, width):
    """Wrap one IR line's spans to `width` columns, preserving styles.
    Returns a list of segment-lines: [[(text, styles), ...], ...]."""
    tokens = []                                   # words and space-runs, styled
    for text, styles in spans:
        for piece in _re.split(r'( +)', text):
            if piece:
                tokens.append((piece, styles))
    lines, line, col = [], [], 0
    for text, styles in tokens:
        if not text.isspace() and col and col + len(text) > width:
            while line and line[-1][0].isspace():          # no trailing spaces
                col -= len(line.pop()[0])
            lines.append(line); line, col = [], 0
        line.append((text, styles)); col += len(text)
    while line and line[-1][0].isspace():
        line.pop()
    if line or not lines:
        lines.append(line)
    return lines

# ----------------------------------------------- printed footnote layout
#
# WordStar Professional 5 manual, pp. 138-139 (quoted in full in the module
# docstring's spirit, restated here at the point it's implemented):
#
#   "Footnotes are separated from the text by a line of 20 dashes. If a
#   footnote doesn't fit at the bottom of the page, the continued text is
#   printed in the footnote area at the bottom of the next page (except
#   after the last page of regular text, where footnotes are printed at
#   the top of the page). A minimum of three lines of regular text are
#   printed on a page regardless of the size of the footnote area except
#   on the last page of the document."
#
# The reference NEVER moves (no reserve-and-push/TeX-style lookahead --
# WordStar didn't do that); the footnote area at the page bottom grows to
# hold its notes, eating body-text space down to a floor of FOOTNOTE_FLOOR
# lines; whatever doesn't fit is split, continuing in the next page's area
# (marked with CONTINUATION_TEXT); the floor is lifted, and any final
# leftover prints at the page TOP instead, once there's no more body text.
#
# Endnotes never touch the per-page footnote area at all -- WordStar collects
# them at the true end of the document (no .pe support here -- see report),
# with NO heading (WordStar never printed one; see EXTENDING.md/report).
# Annotations print at the page bottom exactly like footnotes (same ruling).
# Comments never print (WordStar's own rule) and never reach this code --
# core.py never emits a reference sentinel for them.

def _note_marker(note, label, pad_cols=None):
    """Footnote reference-in-the-note, WSCHANGE factory default: no lead
    character, trailing '.' -> '1.'. Annotations have no documented mark of
    their own -- the spec gives them a free-text `tag` instead ("the text
    used to display and print the tag of the note"); `label` (from
    emit.py's _annotated_notes, shared so every format agrees) is already
    that tag when the author set one, falling back to a running count
    otherwise -- so this only ever needs to add the footnote's own
    trailing '.', never re-derive the tag-vs-number choice itself.

    `pad_cols` (Finding 4, round 26 visual pass): see
    `_notes_marker_pad_cols`. None for a FOOTNOTE (the overwhelming common
    case -- any document whose notes all share one marker width) means
    WS7's own capture carries NO padding and NO separating space at all
    between the marker and the note text -- measured directly (planning
    #202 residuals round, LYING.pcl's own single footnote: `'1.Did'`, ONE
    literal chunk, zero characters between the period and the capital D).
    A prior round's own docstring here read that exact same measurement
    as "ONE space" and left the join unchanged rather than acting on it;
    it was misread -- the PCL evidence has never had a space in it. Every
    OTHER footnote-bearing document measured so far also uses markers of
    ONE width throughout, so this is the path they all take too; none of
    them has its own WS7 capture to confirm or contradict the join, so
    the single confirmed reading (no separator) is what now governs all
    of them, not a guess independent of it. ANNOTATIONS keep the
    original space: their marker is a free-text tag with no trailing
    punctuation of its own (unlike a footnote's period), and no corpus
    capture has ever measured one -- widening the fix to a kind with no
    evidence either way is exactly the guess this fix itself replaces."""
    is_annotation = note.kind == 'annotation'
    base = f'{label}' if is_annotation else f'{label}.'
    if pad_cols is not None:
        return base.ljust(pad_cols)
    return f'{base} ' if is_annotation else base

def _endnote_marker(label, pad_cols=None):
    """Endnote reference-in-the-note, WSCHANGE factory default: lead '(',
    trail ')' -> '(1)'. `pad_cols`: see `_note_marker`."""
    base = f'({label})'
    return base.ljust(pad_cols) if pad_cols is not None else f'{base} '


def _notes_marker_pad_cols(doc):
    """Reserved marker-field width, in character columns, for this
    document's footnote/endnote/annotation area -- Finding 4 (round 26
    visual pass, -SCREEN.WS/-SCREEN.pcl). WS7's real capture hangs a
    note's text to a COMMON column when the document's own markers are
    not all the same width: -SCREEN.WS pairs a "1." footnote with a
    "(1)" endnote on the same page, and both entries' TEXT starts at the
    identical x -- measured 864 decipoints, i.e. column 5 from the
    note's own left margin (504 decipoints): the widest marker's own
    natural width ("(1)", 3 columns) plus 2 columns of padding. Every
    other note-bearing document measured so far (LYING.WS's own single
    footnote: LYING.pcl's "1.Did", ONE space, no hang) uses markers of
    ONE width throughout, so this returns None there -- meaning "leave
    _note_marker/_endnote_marker's plain single-space join alone",
    exactly the previous behaviour, byte-identical.

    Computed DOCUMENT-WIDE, not per page or per note-kind: a short
    document's footnotes and endnotes can land on the very SAME
    rendered page (`_endnote_pages` continuing `_paginate_printed_notes`'s
    last page when there's room -- exactly -SCREEN's own shape), built
    by two functions that don't otherwise share state, so one
    document-global number is what lets both agree without new
    cross-function plumbing. A comment's reference has no note-area
    entry of its own (see `_keep_span`) and never reaches here."""
    widths = set()
    for note, label in _annotated_notes(doc):
        if note.kind == 'footnote':
            widths.add(len(f'{label}.'))
        elif note.kind == 'endnote':
            widths.add(len(f'({label})'))
        elif note.kind == 'annotation':
            widths.add(len(f'{label}'))
    if len(widths) <= 1:
        return None
    return max(widths) + 2

def _note_wrap(marker, text, width):
    """One note's rendered lines for the page-bottom area or the endnote
    listing -- wrapped with the same engine body text uses. WordStar prints
    note text in the default font (no styling carried from the reference),
    so this only ever wraps plain text."""
    return _wrap_line([(marker, frozenset()), (text, frozenset())], width) or [[]]

def _pix_dims_pt(r, max_w_pt):
    """An embedded pix image's (width_pt, height_pt) -- the ONE sizing rule
    every PDF path shares (round 22 factored it out of `_doc_to_pagelines`
    so the Modern and notes-pagination paths size identically to the plain
    Printed path): the print-options record's physical size when the .PIX
    file carries one, else fit-to-text-measure at the source aspect ratio;
    either way capped at `max_w_pt` (the requesting path's own text
    measure)."""
    if r.width_in and r.height_in:
        w_pt, h_pt = r.width_in * 72.0, r.height_in * 72.0
    else:
        w_pt = max_w_pt
        h_pt = w_pt * (r.grows / r.gcols) if r.gcols else 0.0
    if w_pt > max_w_pt and w_pt > 0:
        scale = max_w_pt / w_pt
        w_pt *= scale
        h_pt *= scale
    return w_pt, h_pt


def _pix_reserved_advance(blk_lines, start_idx, own_lead_pt):
    """(reserved_lead_pt, n_blank_consumed) for an embedded pix tag whose
    own physical line already ended at `blk_lines[start_idx - 1]`.

    WordStar's own INSET convention: the author reserves the picture's
    print-time footprint as blank PHYSICAL LINES in the source (the tag's
    own line plus however many blank lines follow it, contiguously, in
    the same block) -- print time overlays the picture on exactly that
    reserved block, which is why the block's LINE COUNT governs the
    vertical advance, not the picture's own continuous pixel height (the
    two rarely match to the point; INSET's editor-time placeholder was
    drawn by eye).

    Measured 2026-08-20 against -README.WS/-README.pcl (fidelity_gate.py
    Finding A): the .PIX tag is followed by 7 contiguous blank lines
    before "COMPLETE WORDSTAR..." -- 8 lines * 12pt = 96pt reserved. WS7's
    own first-body baseline (167.7pt) matches `_printed_top`'s 60pt +
    96pt + this line's own 12pt lead to a 0.3pt residual, the same
    decipoint-rounding-sized gap as the rest of the confirmed corpus.
    Using the raster's raw height instead (73.9pt, from the print-options
    record) under-reserves by >20pt here and cascades into every
    following line's position. The SAME `ceil(h_pt/lead)` raw-height cost
    also feeds `_paginate_printed_notes`'s page-capacity budget, so this
    same fix is the leading candidate for -SCREEN's spurious page-2
    overflow (fidelity_gate.py Finding C) -- see `_body_stream_printed`'s
    matching substitution site, which this helper also serves."""
    n = 0
    while (start_idx + n < len(blk_lines)
           and not blk_lines[start_idx + n].text().strip()):
        n += 1
    return (1 + n) * own_lead_pt, n


def _spans_pix_substitution(spans, pix_map, max_w_pt):
    """(pix_index, w_pt, h_pt) when `spans` [(text, styles), ...] is exactly
    ONE resolved, decoded pix placeholder and nothing else with real text --
    the round-19 substitution rule, shared verbatim by every PDF path: text
    content is never silently dropped, so a (hypothetical) pix tag sharing
    its line with other prose renders as the ordinary placeholder text
    instead. None when no substitution applies (off / miss / shared line);
    the caller keeps the placeholder text unchanged."""
    pix_idx = None
    for text, styles in spans:
        tag = next((t for t in styles if t[:3] == 'pix' and t[3:].isdigit()),
                   None)
        if tag:
            if pix_idx is not None:
                return None                       # >1 tag on one line: bail
            pix_idx = int(tag[3:])
        elif text.strip():
            return None                           # real prose shares the line
    if pix_idx is None:
        return None
    r = pix_map.get(pix_idx)
    if r is None or not r.ok:
        return None
    w_pt, h_pt = _pix_dims_pt(r, max_w_pt)
    return pix_idx, w_pt, h_pt


def _printed_text_width_pt(doc):
    """The Printed text measure in points, for pix fit/cap sizing: Printed
    PDF has no per-block .rm resolved in points anywhere in this emitter
    (physical lines are pre-wrapped by the parser at authoring time), so
    the right inset is mirrored from the left one -- a disclosed
    approximation (round 19), same class as RTF's borrowed TOC page
    numbers."""
    size = _printed_size(doc)
    left = _printed_left(doc, size)
    page_w_pt = float((doc.meta.get('page') or {}).get('pw_in', 8.5)) * 72.0
    return max(72.0, page_w_pt - 2 * left)


def _body_stream_printed(doc, pix_results=None, pictures='off'):
    """Printed-mode body content as a flat stream for the layout loop below:
    each item is either None (a forced page break -- .pa/.cp or WordStar's
    own softpage) or (spans, refs), spans being one verbatim IR line (printed
    mode never wraps body text) and refs the ordered list of (label, Note)
    footnote/annotation references newly appearing on it. Endnote references
    are recognised (so a fnref span's index into `refs_all` stays intact)
    but never queued here -- they don't participate in the per-page footnote
    area, they collect at the document's end instead (_endnote_pages).

    The displayed body reference is `label`, NOT the fnref span's raw
    `.text` (core.py's shared fn_counter position across ALL non-comment
    kinds) -- footnotes and endnotes are numbered INDEPENDENTLY per kind
    (WordStar has separate `.f#`/`.e#` starting-value commands, which only
    make sense for two independent sequences), matching what emit.py's
    text/markdown/html output already does via _annotated_notes/
    _display_number. A bare superscript '1' can therefore legitimately mean
    footnote 1 OR endnote 1 in the body text -- WordStar resolved that
    ambiguity in the NOTE AREA via mark style ('1.' vs '(1)'), not by
    inventing a combined number, so the same label is used in both places.

    `pix_results`/`pictures` (round 22, closing round 19's documented
    scope cut): the same single-pix-placeholder substitution
    `_doc_to_pagelines` performs on the plain path -- a physical line
    whose only real content is one resolved, decoded pix tag becomes an
    image PageLine (empty segments, `.image` set, `.lead` = the image's
    height so the drawing loop's y-advance covers it exactly)."""
    refs_all = _ref_pairs(_annotated_notes(doc))
    embed_images = pictures in ('embed', 'export') and pix_results
    pix_map = {r.index: r for r in (pix_results or [])} if embed_images else {}
    size = _printed_size(doc)
    text_width_pt = _printed_text_width_pt(doc) if embed_images else 0.0
    default_lead_pt = _printed_lead(doc)
    # round 26 wave 3 (fidelity_gate.py Finding B): same carried-governing-
    # size mechanism as `_doc_to_pagelines` -- see `_font_lead_pt`.
    font_lead_state = [None]
    font_lead_ok = (any(f.get('proportional') for f in doc.fonts)
                    and doc.meta.get('page', {}).get('lh_source') != 'file')
    font_lead_base = _printed_size(doc) if font_lead_ok else None
    stream = []
    # Planning #245 (columns-rule research §7, closing the scope gap named
    # at planning #227): same region-boundary forced break AND the same
    # `.cb`/`.cc`/`.cp` sentinel mechanism `_doc_to_pagelines`'s own
    # plain-path block loop already uses -- see its comment for the full
    # evidence (WINGDING.CHT's absorbed `.pa`, PRINT.TST's own live `.cb`/
    # `.cc`). This function used to leave 'colbreak'/'condcolumn' (and
    # 'condpage', `.cp` -- a pre-existing gap of its own, not new here)
    # falling through as ordinary no-lines blocks, so a document routed
    # through the notes-aware paginator (`_paginate_printed_notes`, the
    # only caller) never saw them at all. `None` (unconditional break) and
    # `('cond', n)` (conditional -- resolved by `_paginate_printed_notes`'s
    # own fill loop, the only thing that knows how full the current
    # column/page actually is, exactly mirroring the plain path's identical
    # sentinel) now travel through `stream` the same way a real body line
    # does. Only sawyer/DEFAULT/PRINT.TST (the one `.co`-bearing corpus
    # document with placeable notes) exercises this in the current corpus.
    prev_cols = 1
    for bi, b in enumerate(doc.blocks):
        if b.kind == 'pagebreak' and prev_cols > 1:
            # Planning #227 (columns-rule research §7): a bare `.pa` inside
            # an active `.co n>1` region is absorbed, not honoured -- same
            # gate as `_doc_to_pagelines`'s own, see its comment for the
            # WINGDING.CHT evidence. `.cb` never gets this absorption
            # (handled unconditionally just below, same as the plain path).
            continue
        if b.kind in ('pagebreak', 'colbreak'):
            # `.cb` maps onto the same forced-break sentinel `.pa` uses
            # outside a columnar region (or always, for `.cb` itself) --
            # see `_doc_to_pagelines`'s identical comment. The column-
            # grouping post-pass (`_apply_columns`) turns every Nth forced
            # break into a real page break and the others into a column
            # advance once this stream reaches it, same as the plain path.
            stream.append(None)
            continue
        if b.kind in ('condpage', 'condcolumn'):
            # `.cp n`/`.cc n` -- a break ONLY if fewer than n lines remain
            # in the current column/page. Emitted as a sentinel so
            # `_paginate_printed_notes`'s own fill loop, the only thing
            # that knows how full the page/column actually is, can decide
            # -- identical contract to `_doc_to_pagelines`'s own `('cond',
            # n)` sentinel (see its comment).
            stream.append(('cond', b.heading or 1))
            continue
        if b.kind == 'para':
            cur_cols = b.columns or 1
            if prev_cols > 1 and cur_cols != prev_cols and stream and stream[-1] is not None:
                stream.append(None)
            prev_cols = cur_cols
        # Fix C (b26-print-fidelity-2): same per-block lookup as
        # _doc_to_pagelines -- see its own comment and `_entering_lead_pt`.
        prev_para_block = next((doc.blocks[k] for k in range(bi - 1, -1, -1)
                                if doc.blocks[k].kind == 'para'), None)
        first_line_of_block = True
        # Indexed (not a plain `for`) so an embedded pix substitution below
        # can look ahead and CONSUME the blank placeholder lines WordStar
        # reserved for it -- see `_pix_reserved_advance`.
        _li = 0
        while _li < len(b.lines):
            _idx = _li                          # planning #238 scope gap: same
                                                 # pre-increment index _doc_to_pagelines
                                                 # uses to spot a block's own last line
            line = b.lines[_li]
            _li += 1
            spans = []
            refs = []
            for s in line.spans:
                styles = _effective_span_styles(s, b, heading_bold=True)
                if 'fnref' in s.styles and s.text.isdigit():
                    k = int(s.text)
                    if 0 < k <= len(refs_all):
                        note, label = refs_all[k - 1]
                        if note.kind == 'comment':
                            continue           # never printed: no ink, no ref
                        spans.append((label, styles))          # per-kind number, not the
                                                                # raw shared fn_counter index
                        if note.kind in ('footnote', 'annotation'):
                            refs.append((label, note))
                        continue
                spans.append((s.text, styles))
            # Planning #251 (2026-09-09): same model-build-time bare-tab
            # expansion as `_doc_to_pagelines`'s own plain path -- see its
            # identical comment for why. This function is Printed-only by
            # construction (`_paginate_printed_notes`'s only caller), so no
            # `if printed:` guard is needed here the way the plain path
            # needs one.
            spans = _expand_bare_tabs_for_printed_layout(spans)
            # Same style-over-default precedence as the plain path
            # (_doc_to_pagelines) -- see _style_lead_pt. Computed BEFORE the
            # pix check (round 26, fidelity_gate.py Finding A) since the
            # image's own reserved-placeholder advance now needs it too.
            own_lead = _lead_pt(line.lead_48)
            # register b31: this line's own `.po` override, same "absolute
            # here, None means agrees with the document default" contract
            # `line.lead_48` above already has (core.py's back-dating pass).
            own_left = (_resolve_left_pt(line.po_cols, size)
                       if getattr(line, 'po_cols', None) is not None else None)
            # Planning #231 (.poe/.poo even/odd page offset): see
            # `_doc_to_pagelines`'s own identical comment -- duplicated here
            # for the same reason every other quantity in this sibling loop
            # is (different local names for the same thing).
            own_parity_left = None
            poe_c = getattr(line, 'poe_cols', None)
            poo_c = getattr(line, 'poo_cols', None)
            if poe_c is not None or poo_c is not None:
                fallback_pt = own_left if own_left is not None else _printed_left(doc, size)
                own_parity_left = (
                    _resolve_left_pt(poe_c, size) if poe_c is not None else fallback_pt,
                    _resolve_left_pt(poo_c, size) if poo_c is not None else fallback_pt)
            # Fix C (b26-print-fidelity-2): same blank/entering-line split
            # as _doc_to_pagelines -- see its own comment, `_style_lead_pt`'s
            # `raw` note, and `_entering_lead_pt`.
            is_blank = not any(t.strip() for t, _ in spans)
            if is_blank:
                style_lead = _style_lead_pt(b, doc, raw=True)
            elif first_line_of_block:
                style_lead = _entering_lead_pt(b, doc, prev_para_block)
            else:
                style_lead = _style_lead_pt(b, doc)
            if not is_blank:
                first_line_of_block = False
            if style_lead is not None and (
                    line.lead_48 is None or line.lead_48 == DEFAULT_LH_48):
                own_lead = style_lead
            if own_lead is None and font_lead_ok:
                own_lead = _font_lead_pt(line, doc.fonts, font_lead_base,
                                         font_lead_state)
            # Round 22: exactly one resolved pix tag, no other real text on
            # this physical line -> an image PageLine (same substitution,
            # sizing and never-drop-text rule as `_doc_to_pagelines`).
            # `refs` still travels: a comment reference sharing the line
            # contributes no text and queues nothing, so nothing is lost.
            # `.lead` is the RESERVED PLACEHOLDER block's height (round 26,
            # fidelity_gate.py Finding A/C -- `_pix_reserved_advance`), not
            # the raster's own continuous pixel height.
            if embed_images:
                sub = _spans_pix_substitution(spans, pix_map, text_width_pt)
                if sub is not None:
                    reserved, n_blank = _pix_reserved_advance(
                        b.lines, _li,
                        own_lead if own_lead is not None else default_lead_pt)
                    _li += n_blank
                    stream.append((PageLine([], soft=line.soft, lead=reserved,
                                            overprint=line.overprint,
                                            image=sub, bi=bi, left=own_left), refs))
                    continue
            # A PageLine, not a bare list, so the line's own `.lh` survives the
            # footnote paginator too -- body lines keep their lead whether or
            # not the document has notes.
            #
            # `bi=bi` (2026-09-07): this constructor call was the ONE PageLine
            # site in this module that never threaded the block index through
            # (`_doc_to_pagelines`'s own two PageLine calls, the plain-path
            # equivalent, both pass `bi=bi`) -- every line a document with
            # placeable footnotes/endnotes/annotations produces came out
            # `bi=None`. Invisible while `_pgnum_checkpoints`' default was
            # seeded OFF (a page with no `bi` at all falls back to `auto_page_
            # number=False`, the SAME value the old default always resolved
            # to anyway -- see `_emit_pdf_inner`'s `bis = [...]; ... if bis
            # else False`), but seeding it ON (ws7-prints/v3 finding #2)
            # exposed it: ANY notes-bearing document silently lost its stock
            # automatic page number under `auto`, regardless of what its own
            # `.pn`/`.pg`/`.op` said, purely because this one call site
            # dropped `bi`. Found via sr/ctrl-kd cross-engine parity
            # (AnswerKeyParityPrivateTests, fixtures-ws5/NOTES.TST -- sr's
            # Swift port threads its own block index through the equivalent
            # call correctly, so only ctrl-kd's own Printed PDF was missing
            # the number and the two engines' answer-key cells diverged).
            #
            # Planning #238 scope gap: this function is `_doc_to_pagelines`'s
            # own sibling for a document with placeable footnotes/endnotes
            # (`_paginate_printed_notes` calls it, never `_doc_to_pagelines`),
            # but it never set `justify_right_x` -- a `.oj on` paragraph that
            # happens to carry a footnote reference (sawyer/REF/CTRL-K.H1)
            # printed unjustified even though the SAME paragraph text through
            # a notes-free document justified correctly. Same rule, same
            # measured exception (a block's own last physical line stays
            # ragged) -- see `_doc_to_pagelines`'s own comment for the
            # captures this was measured against; duplicated rather than
            # shared because the two functions' loops read from different
            # local names (`b.lines`/`size` here, `blk_lines`/`size_for_left`
            # there) for otherwise-identical quantities.
            justify_right_x = None
            if b.align == 'justify' and _idx < len(b.lines) - 1:
                po_origin_pt = (own_left if own_left is not None
                                else _printed_left(doc, size))
                rm_cols = (b.right_margin if b.right_margin is not None
                          else 65.0)
                justify_right_x = po_origin_pt + rm_cols * _PDF_PT_PER_COL
            stream.append((PageLine(spans, soft=line.soft,
                                    lead=own_lead,
                                    overprint=line.overprint,
                                    bi=bi, left=own_left,
                                    justify_right_x=justify_right_x,
                                    parity_left=own_parity_left), refs))
    return stream

def _area_size(entries):
    """Total lines the footnote area occupies FOR PAGE-CAPACITY PURPOSES
    (how many body lines this paginator admits onto a page before the
    footnote area needs room, and this area's own share of
    `_footnote_ceiling`'s budget): the fixed 3-line header (blank / 20-dash
    separator / blank -- VMI 240 = one blank line at 6 LPI) plus each
    entry's own lines plus one blank line between entries (VMI 240
    "between notes"). 0 when there's nothing to show at all.

    DELIBERATELY NOT the same count `_render_area` visually draws
    (mechanism U, PCL-DIVERGENCE-TRIAGE.md, `ws7-prints/v3` PRISTINE.EXE
    round) -- see that function's own docstring for why the RENDERED area
    is 2 lines, not 3. Tried making the two agree (reducing this function
    to 2 as well) and it broke LYING's own page break: `ws7-prints/v3`'s
    real page 1 ends at "...was that commonest" (the SAME line this
    engine's page 1 already ended on, at every count from 3 up),
    continuing "and mildest form of lying..." on page 2 -- reducing this
    function to 2 let one MORE body line fit on page 1 before the cap,
    which real WS7 (both installs) does not do. So the capacity/pagination
    budget for this header is 3 lines even though only 2 of them are
    literally drawn; empirically necessary, not fully explained (a real
    stock document whose page break falls EXACTLY at this boundary, or
    doesn't, would be the way to pin this down further -- not attempted
    here, out of this round's scope)."""
    if not entries:
        return 0
    return 3 + sum(len(e) for e in entries) + (len(entries) - 1)

def _render_area(entries):
    if not entries:
        return []
    out = [[(FOOTNOTE_SEPARATOR, frozenset())], []]
    for k, e in enumerate(entries):
        if k:
            out.append([])
        out.extend(e)
    return out

def _admit_footnotes(entries, queue, ceiling):
    """Move whole/partial rendered note-chunks from the FRONT of `queue`
    into `entries` (mutating both) until the footnote area would exceed
    `ceiling` lines. A chunk that only partly fits is split: the part that
    fits joins `entries`, and the remainder goes back on the front of
    `queue` with CONTINUATION_TEXT prepended, ready to resume on a later
    page's area -- this is the only place a note's text is ever cut."""
    while queue:
        chunk = queue[0]
        overhead = 1 if entries else 3          # inter-note blank, or the
                                                 # area's header if it's empty so far
        room = ceiling - _area_size(entries) - overhead
        if room >= len(chunk):
            entries.append(chunk)
            queue.pop(0)
            continue
        # Splitting prepends a CONTINUATION_TEXT line to the remainder, so it
        # only advances when room >= 2: at room == 1 we would admit one line
        # and add one straight back, forever. When the page cannot even manage
        # that AND the area is still empty, force two lines through -- a page
        # that overflows slightly beats a hang or lost text (Jon's ruling on
        # the Modern spill case: no text lost, no infinite loops).
        if room >= 2:
            split = room
        elif not entries:
            split = min(len(chunk), 2)
        else:
            break                                # defer: next page starts empty
        entries.append(chunk[:split])
        rest = chunk[split:]
        if rest:
            queue[0] = [[(CONTINUATION_TEXT, frozenset())]] + rest
        else:
            queue.pop(0)
        break

def _footnote_ceiling(cap, body_len, is_terminal):
    """Max lines the footnote area may occupy on a page where `body_len`
    lines are already committed. Always bounded by the room actually left
    on the page (cap - body_len) -- entries can never push the total past
    cap. Additionally bounded by cap - FOOTNOTE_FLOOR on every page EXCEPT
    the one holding the document's last line of regular text, where the
    floor's protection lifts (the WS5 manual's stated exception).

    `body_len` (round 26 wave 3, Unit A) can now be FRACTIONAL -- a styled
    body line costs its own lead as a fraction of the document default,
    see `_paginate_printed_notes`'s `_line_cost` -- but the footnote AREA
    itself is still whole LINES (its own text carries no per-style
    leading; `_area_size`/`_admit_footnotes` count it that way). Floored,
    never rounded, so a fractional line of room already spent by the body
    never gets credited as a whole line the footnote area can use. The
    tiny epsilon guards against float accumulation (many fractional
    per-line costs summed) landing just under a whole number that should
    round up, not down."""
    room = int(cap - body_len + 1e-9)
    return room if is_terminal else min(room, cap - FOOTNOTE_FLOOR)

def _paginate_printed_notes(doc, cap, width, pix_results=None, pictures='off',
                            sentence_spacing=False):
    """The WS5-manual algorithm: paginate the body verbatim (references never
    move), growing each page's footnote area to hold whatever was referenced
    on it, splitting overflow into the next page's area (marked continued),
    floored at FOOTNOTE_FLOOR lines of body -- except on the page holding the
    last line of regular text, where the floor lifts and any leftover prints
    at the top of a fresh page instead of continuing to a bottom area that
    doesn't exist.

    `pix_results`/`pictures` (round 22, closing round 19's documented
    scope cut): an embedded image PageLine (built by `_body_stream_printed`)
    costs its own height in default-lead-sized lines against this
    paginator's line-count budget -- the image's vertical footprint enters
    the page-capacity model the same way `.lh` does in `_doc_to_pagelines`'s
    points model, just quantised to this algorithm's own line unit."""
    stream = _body_stream_printed(doc, pix_results=pix_results,
                                  pictures=pictures)
    default_lead = _printed_lead(doc)
    pad_cols = _notes_marker_pad_cols(doc)          # Finding 4: see docstring
    # Finding 2 bottom-anchor geometry (see _printed_notes_reserve_pt):
    # constant for the whole document, computed once.
    _notes_top = _printed_top(doc)
    _notes_page_h = _resolved_page_height(doc, True)
    _notes_reserve = _printed_notes_reserve_pt(doc)

    def _line_cost(pl):
        """This algorithm's whole budget (`cap`, `_area_size`, the footnote
        ceiling) is denominated in LINE units at the document's DEFAULT
        lead -- correct for the footnote area itself (its own text carries
        no per-style leading), wrong for BODY text once a WS7 paragraph
        STYLE governs a line's real leading (round 26 wave 3,
        fidelity_gate.py Unit A). A body line now costs its OWN lead as a
        FRACTION of the default lead -- 1.0 for a line at the document
        default (byte-identical pagination for every document that never
        varies leading, which is every document this algorithm's fixed-`1`
        cost was ever measured against), more or less than 1.0 for a line
        whose style set a bigger or smaller lead -- the same
        `own_lead / default_lead` conversion `_doc_to_pagelines`'s already
        point-based main loop uses (its `budget = (cap - 1) * default_lead`
        is the identical quantity in points; this keeps that page's true
        physical capacity while staying in this function's existing line
        unit, so `_area_size`/`_admit_footnotes`/`_footnote_ceiling` need
        no change of their own). MEASURED against LYING.pcl: this document
        undercounted every page (55 nominal lines actually spending 777.6pt
        of a 648pt budget -- 129.6pt, 10.8 default-lead lines, of real
        overflow per page) before this fix; the gate went from 3 engine
        pages (WS7: 4) to matching, see the round 26 wave 3 report.

        An image PageLine's `.lead` (round 26 wave 3, fidelity_gate.py
        Finding A/C) is ALREADY the RESERVED PLACEHOLDER block's height in
        points -- `_pix_reserved_advance`, computed once at
        `_body_stream_printed` build time -- not the raster's own
        continuous pixel height, so it takes the identical `own_lead /
        default_lead` conversion every other line here does; a prior
        version of this branch re-derived a cost from the raster's raw
        height directly (`ceil(h_pt / lead)`), double-guessing a number
        `_body_stream_printed` had already resolved correctly and, for a
        pix tag with few or no reserved blank lines, wildly OVER-costing
        the page-capacity budget relative to what `_page_stream` actually
        spends drawing it -- the leading suspect behind -SCREEN's spurious
        page-2 overflow before this fix."""
        own_lead = getattr(pl, 'lead', None) or default_lead
        return own_lead / default_lead

    last_idx = -1
    for i, item in enumerate(stream):
        # planning #245: a `('cond', n)` sentinel (`.cp`/`.cc`, see
        # `_body_stream_printed`) carries no real content of its own --
        # `item[0]` is the literal string `'cond'`, not a PageLine, so it
        # must be skipped here the same way `None` (a `.pa`/`.cb` forced
        # break) already is, or `.image` below raises.
        if item is None or (isinstance(item, tuple) and item[0] == 'cond'):
            continue
        if item[0].image is not None or any(t.strip() for t, _ in item[0]):
            last_idx = i

    pages = []
    queue = []                                  # list[list[line]]: rendered note
                                                 # chunks awaiting a footnote area,
                                                 # in document order
    last_page_cost = cap                        # see docstring's return-value note
    # round 27 (b28 note 6): whether the LAST page built here ends with a
    # footnote AREA or with plain BODY text -- `_endnote_pages` needs the
    # distinction to decide whether a blank line precedes the first endnote.
    last_page_has_area = False
    i, n = 0, len(stream)
    while i < n:
        body, entries, is_terminal = [], [], False
        body_len = 0                             # in line units, images > 1
        _admit_footnotes(entries, queue,
                         _footnote_ceiling(cap, body_len, is_terminal))   # carry-over first
        while i < n:
            item = stream[i]
            if item is None:
                i += 1
                break                            # forced break: page ends here
            if isinstance(item, tuple) and item[0] == 'cond':
                # planning #245: `.cp`/`.cc` -- break only if STRICTLY
                # FEWER than n lines remain in the current column/page
                # (same strict-less-than test `.cp`'s own docstring and
                # `_doc_to_pagelines`'s identical `('cond', n)` handling
                # use). `body_len`/`cap`/`_area_size(entries)` are already
                # the same "line units" quantities the natural-overflow
                # check just below uses, so no column-aware variant of
                # this room computation is needed (research §4: a
                # column's own height always equals the page's).
                room = cap - body_len - _area_size(entries)
                i += 1
                if room < item[1] and body:
                    break                        # forced break: page ends here
                continue
            spans, refs = item
            cost = _line_cost(spans)
            # `body` non-empty guard: an image taller than the whole page
            # must still be admitted somewhere or this loop would never
            # advance -- a slightly overflowing page beats a hang or lost
            # content (the same doctrine _admit_footnotes documents).
            if body and body_len + cost + _area_size(entries) > cap:
                break                            # natural page-full: line moves on
            body.append(spans)
            body_len += cost
            if i == last_idx:
                is_terminal = True
            i += 1
            for label, note in refs:
                note_text = (_sentence_spacing_texts([note.text])[0]
                            if sentence_spacing else note.text)
                queue.append(_note_wrap(_note_marker(note, label, pad_cols), note_text, width))
            _admit_footnotes(entries, queue, _footnote_ceiling(cap, body_len, is_terminal))
        area = _render_area(entries)
        if entries:
            # Bottom-anchor (Finding 2): the area's FIRST line (the
            # 3-line header's leading blank) gets an overridden `.lead`
            # that lands it exactly `_notes_reserve` above the page
            # bottom, counting up through the area's own remaining
            # lines -- rather than wherever the body's sequential flow
            # happened to leave off. `body_y` is the body's own last
            # baseline (top-down points): `_line_cost` makes `own_lead /
            # default_lead` exact, so `body_len * default_lead` is the
            # TRUE point advance the body already spent, not an
            # approximation. APPLIED whenever it pushes the area DOWN AT
            # ALL (`override > 0`) -- NOT gated on exceeding one whole
            # default-lead gap (planning #202 residuals round: that
            # gate's own rationale -- "a full page (LYING.WS) already
            # lands within a line of the target on its own, so this is a
            # no-op there, byte-identical" -- assumed the flow path's own
            # ordinary single-blank-line gap could only ever UNDERSHOOT
            # the target when `override` came out under one lead. LYING
            # is a full page and its own real WS7 capture (LYING.pcl)
            # measures its footnote line at y=708pt, but the flow path's
            # plain `default_lead` gap OVERSHOOTS the anchor by 4.8pt
            # (natural 676.8pt vs the anchor's own 672.0pt target,
            # `override` a genuine 7.2pt -- less than one 12pt lead, so
            # the old `> default_lead` gate skipped it and left the
            # 4.8pt overshoot standing) -- the assumption held for every
            # oracle it was checked against, but was never actually
            # correct for a SMALL positive override, only ever
            # coincidentally close enough not to be caught. A negative
            # or zero override (the body's own flow already reached or
            # passed the target) is still left alone -- "never move
            # backward into the body" is unchanged.
            body_y = _notes_top + body_len * default_lead
            target_first = (_notes_page_h - _notes_reserve
                            - (len(area) - 1) * default_lead)
            override = target_first - body_y
            if override > 0:
                area = [PageLine(area[0], lead=override)] + area[1:]
        pages.append(body + area)
        last_page_cost = body_len + _area_size(entries)
        last_page_has_area = bool(entries)
    # Whatever's STILL queued once the document is exhausted prints at the
    # TOP of its own page(s) -- "except after the last page of regular text,
    # where footnotes are printed at the top of the page."
    while queue:
        entries = []
        _admit_footnotes(entries, queue, _footnote_ceiling(cap, 0, True))
        pages.append(_render_area(entries))
        last_page_cost = _area_size(entries)
        last_page_has_area = True
    return pages, last_page_cost, last_page_has_area

def _endnote_pages(doc, cap, width, last_page=None, last_page_cost=0.0,
                   last_page_has_area=False, sentence_spacing=False):
    """Endnotes collect at the true end of the document with NO heading
    (WordStar never printed one -- any "Notes"/"Sources" heading in a period
    document was typed by the author). No .pe support: this always renders
    them at document end, never at an earlier .pe point (see report).

    Numbered from endnotes' OWN independent sequence (via emit.py's
    _annotated_notes/_display_number, doc.meta['endnote_number_start']) --
    NOT the shared fn_counter position -- so a document with 2 footnotes
    then 2 endnotes shows endnotes (1)/(2), matching the same labels their
    body references now display (see _body_stream_printed), not (3)/(4).

    `last_page`/`last_page_cost` (round 26 wave 3, fidelity_gate.py
    Finding C): the LAST page `_paginate_printed_notes` built, and how
    many `cap`-units of it are already spent. When there's room
    (`last_page_cost < cap`), endnotes CONTINUE that page instead of
    always forcing a fresh one, not a fresh 3-line area header, since
    this is one more entry in the SAME note area, not a new section. A
    page with NO room left (`last_page_cost >= cap`, the overwhelmingly
    common multi-page case) is untouched: endnotes start fresh exactly
    as before.

    `last_page_has_area` (round 27, b28 note 6) decides whether a blank
    line precedes the first endnote, and it is NOT unconditional. WS7's
    note face is 12-point, so ONE note line advances 120 decipoints --
    the 2026-08-20 measurement that put a blank line here read the
    natural 240dp two-line advance as "24pt, one blank line" and applied
    it to both cases. Re-measured 2026-08-23 against the WS7 captures:

      -SCREEN.pcl  "1. Footnote" V=7080 -> "(1) Endnote" V=7320 = 240dp
                   = ONE BLANK LINE after a FOOTNOTE AREA.
      TESTING.pcl  last body line V=3765 -> "(1)This is our test
                   endnote." V=3885 = 120dp = NO BLANK LINE after BODY
                   TEXT.
      TESTING.pcl  endnote (1) V=3885 -> (2) V=4125 = 240dp = one blank
                   line BETWEEN entries (the `if k` gap below, correct).

    So the leading gap belongs only when the last page ends with a
    footnote area -- it is one more entry joining that area. When the
    endnotes follow plain body text they butt straight up against it,
    which is what Jon reported in the b27 review: the endnotes go
    IMMEDIATELY after the text."""
    endnotes = [(note, label) for note, label in _annotated_notes(doc) if note.kind == 'endnote']
    if not endnotes:
        return []
    pad_cols = _notes_marker_pad_cols(doc)          # Finding 4: see docstring
    lines = []
    for k, (note, label) in enumerate(endnotes):
        if k:
            lines.append([])
        note_text = (_sentence_spacing_texts([note.text])[0]
                    if sentence_spacing else note.text)
        lines.extend(_note_wrap(_endnote_marker(label, pad_cols), note_text, width))
    pages = []
    continuing = bool(last_page and last_page_cost < cap)
    if continuing:
        page = list(last_page)
        room = cap - last_page_cost
        if last_page_has_area:                  # see docstring: WS7 measurements
            lines = [[]] + lines
    else:
        page = []
        room = cap
    # #228 (research/2026-09-08_trailing-pa-rule.md): a FRESH endnote page
    # (not a continuation of the body's own last page) has no `.bi`-
    # carrying line of its own -- every line here is a bare
    # `_note_wrap`/`_render_area` tuple, never a PageLine -- so the auto-
    # page-number lookup at render time has nothing to resolve against.
    # `explicit_break_bi` (the document's own highest block index --
    # "wherever the document's own state was by its own end") stands in,
    # the same fallback the trailing-`.pa` blank page (_doc_to_pagelines,
    # the plain path) already uses. Confirmed against sawyer/DISPLAY.WS:
    # WS7's own page 2 (the endnote, on its own page once the trailing-
    # `.pa` continuation fix above stops it merging with page 1) carries
    # the automatic page number "2".
    last_bi = len(doc.blocks) - 1
    first_flushed = True
    def _flush(pg):
        nonlocal first_flushed
        if first_flushed and continuing:
            pages.append(pg)
        else:
            wrapped = Page(pg)
            wrapped.explicit_break_bi = last_bi
            pages.append(wrapped)
        first_flushed = False
    for l in lines:
        if room < 1:
            _flush(page)
            page, room = [], cap
        page.append(l)
        room -= 1
    if page:
        _flush(page)
    return pages

def _has_placeable_notes(doc):
    return any(n.kind in ('footnote', 'endnote', 'annotation') for n in doc.notes)

class PageLine(list):
    """One laid-out line: a list of (text, styles) segments, plus the SOFT flag
    and the line's own LEAD.

    Added 2026-08-03. A paginated line used to be a bare list, so `Line.soft` --
    which the IR has carried since 2.0.0 -- never reached the paginated
    representation. Anything working from pagelines therefore could not tell a
    soft return (WordStar's own word wrap, and the filler `.ls > 1` materialises)
    from a hard one (the author pressing Return). That distinction is not
    cosmetic: it is what carries authorial intent at a page top, and it is what
    Soft Return.app needs for Show Invisibles.

    Deliberately a LIST SUBCLASS rather than a new type: every existing consumer
    iterates a pageline as a list of segments and keeps working untouched, while
    new code can ask for `.soft`. Changing the contract outright would have
    touched the emitters, the footnote paginator and both geometry oracles at
    once, for no behavioural gain.

    `lead` (added 2026-08-05) is this line's baseline-to-baseline advance in
    POINTS, or None for "the document's default". It is core.Line.lead_48 --
    the `.lh` in force where the line sat -- converted once here, so the
    layout loop never has to know about 48ths. Lines this emitter MAKES rather
    than reads (footnote areas, wrapped Modern text, blank fillers) leave it
    None by construction: they are the emitter's own furniture and belong on
    the document's default lead.

    `fi` (added round 17, ledger row 5/7): this line's own first-line-indent
    override in POINTS, or None -- `.pm`'s effect (mirrors RTF's `\fi` from
    round 6), set ONLY on a `.para` block's own first content line. `.psa`/
    `.psb` reuse `lead` itself rather than a new field: WordTsar's space-
    before/after is exactly one MORE baseline-to-baseline distance to spend
    before a line prints, the same quantity `lead` already carries -- `sb`
    is added into the block's own first line's `lead`, `sa` into whatever
    PageLine comes next after the block ends (pending_sa in
    `_doc_to_pagelines`), so the existing pagination cost model
    (`_cost`/`spent`/`budget`) accounts for both with no change to itself."""

    # `bi` (round 18, ledger row 4): the source Block's own index in
    # doc.blocks, for `_toc_page_numbers` to resolve which page a
    # `.tc`/`.ix` entry's own block landed on -- the REAL paginator's
    # answer, not an estimate. None for a line this emitter MAKES rather
    # than reads (matches `lead`'s own "furniture" convention).
    #
    # `image` (round 19, PIX images RULED IN, ledger PIX row): (pix_index,
    # width_pt, height_pt) when this PageLine IS a resolved, embedded
    # picture rather than text -- `segments` is empty by construction and
    # `_page_stream` draws the XObject instead of running text ops. `lead`
    # is set to height_pt (+ any `.psb`/`.psa` spacing, same as an
    # ordinary line) so the existing budget/cost model (`_cost` in
    # `_doc_to_pagelines`) accounts for the image's vertical footprint
    # with NO change of its own -- reusing exactly the mechanism round 17
    # built for `.psa`/`.psb`.
    # `ws4_spacing` (Finding 1, round 26 visual pass): True for a blank
    # PageLine that `_ws4_spacing_blank_indices` classified as this WS4
    # document's OWN double-spacing idiom rather than authored content --
    # see that function's docstring, and the pagination loop's own use of
    # this flag (`_doc_to_pagelines`'s `full` computation) for why it
    # matters: a blank flagged this way never forces a page break BY
    # ITSELF, an authored blank (flag False, every non-WS4 document's
    # blanks included) is untouched, exactly the previous behaviour.
    # `kerning` (register C7): core.Line.kerning, the `.KR` state in force
    # where this line sat -- True (WordStar's own default) for every line
    # this emitter MAKES rather than reads, same "furniture" convention as
    # `lead`/`bi`. Consumed by `_lj_substitute`.
    # `left` (register b31): this line's own left-edge override in POINTS,
    # already resolved (`_resolve_left_pt`), or None for "the document's
    # default" -- core.Line.po_cols -> PageLine.left, the SAME `.lh`-shaped
    # stateful contract `lead` above documents for `.lh`, just for `.po`.
    # Converted here (not at render time) for the same reason `lead` is:
    # `_page_stream`'s layout loop never has to know about print columns.
    # `roll` (register b32-N10): this line's own `.sr` sub/superscript roll
    # in POINTS, already resolved, or None for "the document's default" --
    # core.Line.roll_48 -> PageLine.roll, the SAME `.lh`-shaped stateful
    # contract `lead`/`left` above document, just for `.sr`. Unlike
    # `lead`/`left`, `Line.roll_48` is never itself None (see its own
    # docstring: no style/font precedence chain to defer to), so `roll` is
    # None only for a PageLine this emitter MAKES rather than reads --
    # `_page_stream` falls back to the document-wide `roll_pt` parameter
    # for those, exactly as it already does for `left`.
    # `justify_right_x` (planning #238, `.oj on` full justification): this
    # line's own right text-margin, in ABSOLUTE points, or None for an
    # unjustified line -- set by `_doc_to_pagelines` only on a line inside a
    # `.oj on`/`align='justify'` block that is NOT that block's own last
    # physical line (see `_line_ops_printed`'s own docstring for the
    # measured rule). Consumed by `_line_ops_printed`; a PageLine this
    # emitter MAKES rather than reads (furniture) leaves it None, same
    # convention as `lead`/`bi`.
    # `parity_left` (planning #231, `.poe`/`.poo` even/odd page offset):
    # `(even_pt, odd_pt)` -- this line's own resolved left origin for EACH
    # page parity, or None for a line no `.poe`/`.poo` ever governs.
    # `_doc_to_pagelines`/`_body_stream_printed` cannot resolve which of
    # the two applies at BUILD time (that depends on which page this line
    # lands on, a pagination question); `left` stays None until the
    # page-filling loop's own `_close_page` -- the one place that actually
    # knows this line's page's parity -- picks the right member of the
    # pair and overwrites it. A line neither `.poe` nor `.poo` ever
    # touched leaves this None, zero behaviour change.
    # `col` (planning #227 follow-up, 2026-09-09): this line's own 0-based
    # column index within an active `.co n>1` region, or None for every
    # ordinary (non-columnar) line -- same "furniture"/"document default"
    # convention as `left`/`bi`. Set ONLY by `_apply_columns`, at the same
    # site that already resolves this line's own `left` for its column
    # (`base_left + col_idx * (column_width_pt + gutter_pt)`) -- `left`
    # alone cannot tell a consumer THIS IS A NEW COLUMN, RESET Y apart from
    # an ordinary mid-document `.po`/`.poe`/`.poo` left-edge change (which
    # must NOT reset the vertical flow); `col` is the unambiguous signal
    # `emit_layout` and Soft Return.app's Native view both need for that
    # distinction. A page's own column COUNT/geometry lives on `Page`
    # (`columns`/`column_gutter_pt`/`column_width_pt`) below, once per
    # page rather than repeated on every line.
    # `justify_word_x` (planning #251(b), 2026-09-09): this line's own
    # PRECOMPUTED `_justify_pieces_printed` result -- `[(piece, x_pt,
    # width_pt), ...]` covering the whole line left to right -- or None.
    # Set by `_attach_justify_word_x_printed` ONLY when this is a
    # `justify_right_x`-carrying line that resolves (after the SAME
    # `_split_indent`/`_split_symbol_fallback`/`_split_graphics`/
    # `_lj_substitute` pipeline `_line_ops_printed` itself runs) to
    # exactly one FIXED-PITCH, untagged span with a real gap to stretch --
    # every other justified line (styled/mixed, proportional, a pctl/tab
    # span, or one with no slack to distribute) leaves this None, and
    # `_line_ops_printed` falls back to computing it fresh at render time,
    # unchanged from before this field existed.
    # `line_no` (planning #251(d), 2026-09-09): this line's own `.l#`
    # gutter label and ABSOLUTE x, as `(label, x_pt)`, or None for a line
    # no active `.l#` interval numbers -- moved off `_page_stream`'s own
    # render-time `line_no_state` counter (which reset every PAGE, per
    # planning #247's own oracle) onto the model by
    # `_attach_line_numbers_printed`, called from `_doc_to_pagelines`
    # right before it returns. `_page_stream` now only draws from this
    # field (still gated by its own `line_no_checkpoints is not None`
    # parameter, which is how `--line-numbers off` keeps suppressing the
    # draw even though the model carries the label unconditionally --
    # same "model states it, a flag may still tell the WRITER not to
    # draw it" shape `headers`/`footers`/`show_headers` already use).
    # `graphic_cells` (planning #251(c), 2026-09-09): every cp437
    # box-drawing/graphic character this line draws as a vector, as
    # `[(char, x_pt, width_pt), ...]` in document order, or None for a
    # line with no graphic character at all. Set by
    # `_attach_graphic_cells_printed` from a real (throwaway-state) call
    # to `_line_ops_printed` itself -- see that function's own
    # `record_graphic_cells` parameter -- so the values are exactly what
    # the writer draws, not a parallel re-derivation.
    __slots__ = ('soft', 'lead', 'overprint', 'fi', 'bi', 'image', 'ws4_spacing',
                'kerning', 'left', 'roll', 'justify_right_x', 'parity_left', 'col',
                'justify_word_x', 'line_no', 'graphic_cells')

    def __init__(self, segments=(), soft=False, lead=None, overprint=False, fi=None,
                bi=None, image=None, ws4_spacing=False, kerning=True, left=None,
                roll=None, justify_right_x=None, parity_left=None, col=None,
                justify_word_x=None, line_no=None, graphic_cells=None):
        super().__init__(segments)
        self.soft = soft
        self.overprint = overprint      # bare-CR ^PM: the NEXT line prints
                                        # at THIS line's baseline
        self.lead = lead
        self.bi = bi
        self.fi = fi
        self.image = image
        self.ws4_spacing = ws4_spacing
        self.kerning = kerning
        self.left = left
        self.roll = roll
        self.justify_right_x = justify_right_x
        self.parity_left = parity_left
        self.justify_word_x = justify_word_x
        self.col = col
        self.line_no = line_no
        self.graphic_cells = graphic_cells


class Page(list):
    """One paginated page: a list of PageLines plus the running head and
    foot IN FORCE when this page printed (replayed from doc.hf_events).
    A list subclass for the same reason PageLine is: every existing consumer
    iterates a page as a list and keeps working untouched.

    `mt_lines`/`mb_lines` (Finding 3, b26-print-fidelity-2): the .mt/.mb
    IN FORCE when this page's own pagination started -- None for "the
    document's global (first-occurrence) value", which is every page of
    every document that never changes .mt/.mb mid-document (see
    `_mt_mb_checkpoints`). Threading the SAME resolved pair from
    pagination-time (which already had to know it, to size the page's own
    capacity) through to render-time (`_emit_pdf_inner`'s per-page loop)
    keeps the two in agreement by construction, rather than re-deriving
    the same answer twice from doc.meta['dot_positions']."""

    __slots__ = ('headers', 'footers', 'mt_lines', 'mb_lines', 'pl_lines',
                'hm_lines', 'fm_lines', 'po_cols', 'po_parity',
                'explicit_break', 'explicit_break_bi',
                'columns', 'column_gutter_pt', 'column_width_pt',
                'header_lines', 'footer_lines', 'auto_pageno',
                'head_hf_override', 'foot_hf_override')

    def __init__(self, seq=()):
        super().__init__(seq)
        self.headers = {}
        self.footers = {}
        # planning #250: `{1: (font_idx, tab_rec)}` -- set ONLY by
        # `_close_page`'s own `_parity_hf`, only when THIS page's line 1
        # came from a `.h1e`/`.h1o`/`.f1e`/`.f1o` parity variant (not a
        # plain `.h1`/`.fo`). None (the "no opinion, read `doc.header_
        # fonts`/`header_tabs` as before" default) for every page of
        # every document that never uses the family -- same convention as
        # `po_cols`/`po_parity` just above.
        self.head_hf_override = None
        self.foot_hf_override = None
        # `header_lines`/`footer_lines`/`auto_pageno` (planning #251(d),
        # 2026-09-10): this page's own RESOLVED running head/foot -- `#`
        # substituted, fontless right-tab realignment baked, `y`/`x`/
        # `font` attached -- set ONLY by `_attach_head_foot_lines_printed`
        # (`_doc_to_pagelines`'s own post-pagination pass), from
        # `_resolve_head_foot_lines` (the SAME function `_running_ops`,
        # the PDF writer, calls to render). None (not `[]`/`{}`) for
        # "not yet resolved" -- every page of every document until that
        # attach function runs, and every page `_paginate_printed_notes`
        # builds as a bare list rather than a `Page` (see `_apply_
        # columns`'s own `merged.headers` comment for why `None` is the
        # deliberate "no opinion" default throughout this class)."""
        self.header_lines = None
        self.footer_lines = None
        self.auto_pageno = None
        self.mt_lines = None
        self.mb_lines = None
        # `columns`/`column_gutter_pt`/`column_width_pt` (planning #227
        # follow-up, 2026-09-09): this page's own `.co n` geometry, set
        # ONLY by `_apply_columns` on a page it actually merged from a
        # columnar group -- None/None/None for every ordinary page, the
        # same "no opinion" convention `po_cols` etc. already use. One
        # page-level record rather than repeating gutter/width on every
        # PageLine (`PageLine.col` carries the per-line column INDEX;
        # this is the shared geometry every index on this page resolves
        # against). `column_width_pt` is one column's own width -- the
        # block's `.rm` minus `.po`, exactly the docstring on
        # `_apply_columns` derives it, NOT the page width divided by n.
        self.columns = None
        self.column_gutter_pt = None
        self.column_width_pt = None
        # #228 (research/2026-09-08_trailing-pa-rule.md, planning #228): a
        # trailing `.pa` followed by at least one more real content
        # paragraph -- even a blank one -- before EOF opens a final page
        # with no body; real WS7 still stamps its running footer/page
        # number there (worked example: sawyer/REF/PAGESIZE.WS's WS7 page
        # 6 is a single line, the footer digit "6", no body -- confirmed
        # a genuine saved blank paragraph via the file's own trailer
        # bytes, doc.meta['pa_eof_blank_after']). `explicit_break` marks
        # a page force-closed by exactly that condition (never popped by
        # the empty-trailing-page cleanup below); `explicit_break_bi` is
        # the block index of the `.pa` itself, so the auto-page-number
        # lookup (which normally reads a real line's own `.bi`) has
        # something to resolve against on a page with no lines at all.
        # Both stay at their default (False/None) for every ordinary
        # page -- only `_doc_to_pagelines`'s new post-loop branch sets
        # them, and ONLY when doc.meta['pa_eof_blank_after'] is True (a
        # bare trailing `.pa` with nothing after it -- the overwhelming
        # majority of `.pa`-terminated documents -- opens no page at all,
        # per the research above; DISPLAY.WS/NOTES.TST's own extra page
        # is a completely different, already-working mechanism --
        # WordStar's default endnote-collection placement -- not this
        # one).
        self.explicit_break = False
        self.explicit_break_bi = None
        # `.pl` in force when this page's own pagination started -- None
        # for "the document's global (first-occurrence) value", the same
        # contract as mt_lines/mb_lines above (register b31-dot-command-
        # sweep, `_pl_checkpoints`).
        self.pl_lines = None
        # `.hm`/`.fm` in force when this page's own pagination started --
        # same None/"document global" contract again (register b31-dot-
        # command-sweep, `_hm_fm_checkpoints`).
        self.hm_lines = None
        self.fm_lines = None
        # `.po` (page offset) in force when this page's own pagination
        # started -- same None/"document global" contract again (register
        # b31-dot-command-sweep follow-up, `_po_checkpoints`). Feeds
        # `_running_ops`'s own header/footer left edge ONLY -- body text
        # already carries a per-LINE `.po` override (core.Line.po_cols),
        # this is the page-granularity twin that mechanism was missing.
        self.po_cols = None
        # planning #231/#241 follow-up (2026-09-08):
        # whether `po_cols` above came from an ACTIVE `.poe`/`.poo` parity
        # override, as opposed to a plain mid-document `.po` reset. #241's
        # `page_geom_changed` gate exists to keep a HOLYMAC-style transient
        # `.po` (a local body-margin excursion, no real page-layout change)
        # from leaking into the running head/foot -- but `.poe`/`.poo` ARE
        # themselves a page-layout decision by definition (WSFORMAT.WS:
        # "specify even or odd number page offsets"), so they must bypass
        # that gate rather than be silently caught by it. Measured: sawyer/
        # MAILLIST/PHONE.LST (`.poo .20"`/`.poe .20"`, no plain `.po`) and
        # its own running head, rendered at the document default 57.6pt
        # instead of the declared 14.4pt -- same fallback, `_running_ops`
        # reads `page_po`/`page_geom_changed` only.
        self.po_parity = False


def _is_blank_line(line):
    """A physical Line with no non-whitespace span text -- the same test
    the per-line PageLine-building loop in `_doc_to_pagelines` already
    applies inline (its own `is_blank`), factored out here so
    `_ws4_spacing_blank_indices` can classify a whole block's lines before
    that loop runs."""
    return not any(s.text.strip() for s in line.spans)


def _ws4_spacing_blank_indices(doc, ls_confirmed):
    """Finding 1 (round 26 visual pass, private WS4 paper corpus, never
    entering this repo): `{block_index: set(line indices into that
    block's own .lines)}` -- every blank Line that is this document's
    OWN double-spacing idiom, not authored content. ONLY CALLED for a
    `variant == 'ws4'` document -- see the call site's own docstring
    note for why this never even runs for anything else.

    WordStar's OWN manual gives this a physical story, already quoted
    elsewhere in this module (`_text_lines_per_page`): "when you use
    line spacing, the blank lines become part of the file" (WS7 manual,
    "Line Spacing") -- `.LS`'s blank lines are not computed at print
    time, they are literal Lines the file itself carries. A classified
    blank stays exactly that: a literal Line, its own ordinary PageLine
    at its own natural (single) lead -- `_doc_to_pagelines` does NOT
    fold it into a neighbour's lead. An early version of this fix did
    fold (collapsing a double-spaced pair into one PageLine at 2x lead)
    and it broke on irregular paragraph lengths: real WS7's own page-top
    baseline cycles through THREE distinct phases 12pt apart (measured:
    a WS4 source with long, regular paragraphs holds one phase for every
    interior page, 71.7pt; a WS4 source built mostly from short dialogue
    paragraphs cycles 71.7/83.7/95.7pt depending on whether the page
    break happened to land on odd or even raw-line parity) -- collapsing
    every pair into a single 2x-lead unit can only ever reproduce ONE of
    those phases, because it throws away exactly the raw single-line
    parity information a page break's real position depends on. Classifying
    which blanks are spacing (this function) but leaving them as literal
    RAW PageLines preserves that parity; only their ELIGIBILITY to force a
    page break changes (`_doc_to_pagelines`'s own pagination loop, via each
    PageLine's own `ws4_spacing` flag).

    Classified PER BLOCK first (a block is WordStar's own paragraph
    unit), because a WS4 fiction manuscript mixes double-spaced
    narrative with single-spaced inserts (verse quoted verbatim, a
    bibliography) at exactly that granularity, not document-wide -- a
    block whose own lines are `T,T,...` (two real lines with no blank
    between them) or start with a leading blank never counts, regardless
    of anything nearby. Neither measured WS4 source sets `.LS` at all
    (checked their own raw dot-command bytes directly): WS4 predates
    `.LS` even being a documented dot command, so there is usually no
    stateful signal to key off and this has to read the rhythm off the
    pattern itself -- `ls_confirmed` (True only when the file's own
    `.LS` dot-command positively declares spacing > 1,
    `page['ls_source'] == 'file'`) trusts direct file evidence over the
    inferred pattern when it exists.

    A block whose shape is a clean alternation (T,B,T,B,... with no two
    adjacent same-kind lines, ignoring a possible TRAILING blank run at
    its very end -- see below) is COMPATIBLE with the rhythm; one that
    also has >= threshold interior blanks (an interior blank is real
    text on BOTH sides, within the same block) on its own is CONFIRMED.
    threshold is 1 under `ls_confirmed`, else 2 -- 2 because a real
    document can carry a single, genuinely authored blank line in the
    middle of an ordinary paragraph (measured: a Sawyer corpus document's
    own block, "PS: ... " / blank / "(Yes, it's awkward ...)" -- one
    isolated interior blank, never repeated anywhere else in that block)
    -- that is authored spacing, not a rhythm, and one occurrence alone
    must never count it. (That document is `ws5+`, so the WS4 gate alone
    already keeps it untouched -- the threshold is the SECOND
    independent reason, for a future WS4 capture that turns out to carry
    the same kind of aside.)

    STATE, carried across blocks in document order like any other
    WordStar dot-command state (round 22's `.oc`/`.oj`/etc. precedent):
    a CONFIRMED block turns spacing mode on; a COMPATIBLE-but-unconfirmed
    block counts too WHILE mode is already on (this is what a lone short
    line of dialogue, "T,B" or "T,B,T,B" -- too short to confirm 2
    interior repeats by itself -- needs: measured against a real WS4
    source, several consecutive short dialogue paragraphs sit between
    longer confirmed ones, and their own 24pt gaps to their neighbours
    check out against that source's own baselines exactly like the
    confirmed ones'). An INCOMPATIBLE block (leading blank, or two real
    lines back to back) turns the mode back OFF -- the one hard stop, so
    a verse quotation or a bibliography section breaks the chain exactly
    where the document's own shape says it should, not where a
    document-wide guess would. A COMPATIBLE-but-unconfirmed block seen
    BEFORE the first CONFIRMED one (mode still off) is left alone --
    there is no evidence yet to count it against.

    TRAILING RUN: a block that counts at all (confirmed, or compatible
    while mode is on) counts its OWN trailing blanks too -- from its
    last real line to its own end -- even though a trailing run is never
    "interior" (there is no following real line left within THIS block
    for it to sit between). WordStar's "blank lines become part of the
    file" is a property of `.LS`, not of which physical line happens to
    be a paragraph's last -- measured: a WS4 source's paragraph
    boundaries carry a 2-3 blank RUN, not the single blank its own
    within-paragraph rhythm uses (the paragraph's last line still owes
    its own spacing filler; the author's own blank-line gap between
    paragraphs, typed under the same `.LS`, owes its own filler too), and
    the resulting larger gap (measured: 48pt across a 3-blank boundary,
    exactly 2x a normal 24pt gap) checks out against the source's own
    baselines too."""
    threshold = 1 if ls_confirmed else 2
    spacing_map = {}
    spacing_mode = False
    for bi, b in enumerate(doc.blocks):
        if b.kind != 'para':
            continue                          # sentinels never reset the state
        flags = [not _is_blank_line(ln) for ln in b.lines]
        if not flags or not flags[0]:
            spacing_mode = False              # empty, or opens on a blank
            continue
        last_real = max(i for i, f in enumerate(flags) if f)
        core = flags[:last_real + 1]
        compatible = all(core[i] != core[i + 1] for i in range(len(core) - 1))
        if not compatible:
            spacing_mode = False
            continue
        interior = [i for i in range(1, len(flags) - 1)
                    if flags[i - 1] and not flags[i] and flags[i + 1]]
        confirmed = len(interior) >= threshold
        if confirmed or spacing_mode:
            spacing = set(interior)
            spacing.update(range(last_real + 1, len(flags)))
            spacing_map[bi] = spacing
            spacing_mode = True
        # else: compatible, but neither confirmed itself nor inheriting an
        # already-on mode -- no evidence yet; leave uncounted, mode stays off
    return spacing_map


def _apply_columns(doc, pages, size):
    """Planning #227 (research/2026-09-08_columns-rule.md): regroup a
    finished, ordinary single-column `pages` list into real `.co n`
    newspaper-column pages -- a POST-PASS over pagination's own output,
    not a change to the pagination budget loop itself.

    Why a post-pass works at all: a column is never vertically shorter
    than the page it's on (measured: every `.co`-bearing document in the
    corpus), so the ordinary single-column pagination loop, run unmodified,
    already produces exactly the right BREAK POINTS for a columnar
    region's content -- each "page" it closes is precisely one column's
    worth of material, because column height and page height are the same
    budget. `_doc_to_pagelines`'s own block loop guarantees (by forcing a
    break on every `columns` state change, research §7) that a real page
    coming out of that loop is either wholly non-columnar or wholly one
    columnar region's own single N/gutter pair -- never a mix. All that is
    left to do here is fold every N consecutive columnar "pages" into ONE
    physical page, side by side, in fill order (down column 1, then column
    2, ... -- research §4, confirmed directly against WINGDING.CHT/
    SYMBOL.CHT/PRINT.TST's own real captures).

    Column geometry (research §3): a column's own width is the block's
    `.rm` minus `.po` -- the SAME number that already defines an ordinary
    single-column line's own right edge, NOT the page width divided by n.
    An author who wants 3 real columns sets `.rm` to ONE column's own
    width first. Column i's left edge is therefore
    `base_left + i * (column_width_pt + gutter_pt)`, where `base_left` is
    whatever this line's own left origin already resolved to (its `.po`/
    parity override if it has one, `_printed_left(doc, size)` otherwise --
    the identical fallback every other per-line left computation in this
    module uses).

    No balancing (research §5): a trailing group of fewer than n columnar
    pages is merged into one physical page using only the columns actually
    present -- the remaining column slots are simply never drawn into,
    matching WINGDING.CHT's own measurably short last column and
    SYMBOL.CHT's own entirely-unused 5th column exactly."""
    if not pages:
        return pages
    out = []
    i = 0
    n_pages = len(pages)
    while i < n_pages:
        pg = pages[i]
        # A page's own columnar-ness is decided by the FIRST columnar block
        # referenced ANYWHERE on it, not just its first line's -- a page can
        # legitimately open with a non-columnar PREFIX (a title/ruler line
        # ahead of the chart body) and then, on the SAME page, enter its
        # `.co n` region with no break between them (research §7's own
        # corrected finding: sawyer/REF/SYMBOL.CHT's real WS7 capture puts
        # its title on the SAME page as its columnar chart, and 4 of the 9
        # corpus documents share this shape -- SYMBOL.CHT, WINGDING.CHT, and
        # all three FONTCRIB siblings). The prefix lines themselves stay
        # exactly where the ordinary single-column pass already put them --
        # they become column 0's own leading lines, unshifted, which is
        # correct since column 0's own x IS the page's ordinary left origin.
        first_col_bi = next((getattr(pl, 'bi', None) for pl in pg
                             if getattr(pl, 'bi', None) is not None
                             and 0 <= pl.bi < len(doc.blocks)
                             and (doc.blocks[pl.bi].columns or 1) > 1), None)
        cols = ((doc.blocks[first_col_bi].columns or 1)
                if first_col_bi is not None else 1)
        if not pg or cols <= 1:
            out.append(pg)
            i += 1
            continue
        blk = doc.blocks[first_col_bi]
        gutter_cols = blk.column_gutter or 0.0
        rm_cols = blk.right_margin if blk.right_margin is not None else 65.0
        gutter_pt = gutter_cols * _PDF_PT_PER_COL
        rm_pt = rm_cols * _PDF_PT_PER_COL
        merged = Page([])
        # Group metadata (headers/footers/margins/geometry) comes from the
        # FIRST sub-page in the group -- "page just started" state, exactly
        # what an ordinary page's own metadata already means. `getattr`
        # with a default throughout: the notes-aware paginator
        # (`_paginate_printed_notes`) builds some of ITS OWN pages as plain
        # lists rather than `Page` instances (its footnote-area pages in
        # particular) -- pre-existing, not something this pass changes --
        # so a source page here is not guaranteed to carry these attributes.
        # planning #245: the default here MUST be `None`, not `{}` --
        # `_emit_pdf_inner`'s per-page loop (`getattr(pl, 'headers', None)`)
        # treats `None` as "this page has no opinion, fall back to
        # `doc.headers`" (`_running_ops`'s own `headers = doc.headers if
        # headers is None else headers`) and treats a real (even empty)
        # dict as an authoritative answer. A plain-list source page from
        # `_paginate_printed_notes` was ALWAYS meant to fall back that way
        # -- every non-columnar notes-path page already does, invisibly,
        # because `getattr(pl, ...)` on a bare list hits ITS OWN default
        # of `None` directly in `_emit_pdf_inner`. This merge function
        # short-circuited that for any page a `.co` column group happened
        # to land on: defaulting to `{}` here manufactures an explicit
        # "no header" answer that skips `_running_ops`'s fallback,
        # dropping a real running head from that one physical page.
        # Measured on sawyer/DEFAULT/PRINT.TST (WS7 v4 capture): `.h1
        # WordStar and Your Printer` (defined once, at the very top of the
        # file, in force for the whole document) prints on all 4 real
        # pages -- ctrl-kd was dropping it from page 2 alone, the one page
        # `_apply_columns` merges from the document's `.co3` region.
        merged.headers = getattr(pg, 'headers', None)
        merged.footers = getattr(pg, 'footers', None)
        # planning #250: carry the source page's own parity font/tab
        # override through the merge, same passthrough as headers/footers
        # just above -- None on every page this feature never touches.
        merged.head_hf_override = getattr(pg, 'head_hf_override', None)
        merged.foot_hf_override = getattr(pg, 'foot_hf_override', None)
        merged.mt_lines = getattr(pg, 'mt_lines', None)
        merged.mb_lines = getattr(pg, 'mb_lines', None)
        merged.pl_lines = getattr(pg, 'pl_lines', None)
        merged.hm_lines = getattr(pg, 'hm_lines', None)
        merged.fm_lines = getattr(pg, 'fm_lines', None)
        merged.po_cols = getattr(pg, 'po_cols', None)
        merged.po_parity = getattr(pg, 'po_parity', False)
        merged.explicit_break = getattr(pg, 'explicit_break', False)
        merged.explicit_break_bi = getattr(pg, 'explicit_break_bi', None)
        # planning #227 follow-up (2026-09-09): this page's own column
        # geometry, recorded once here rather than re-derived per line by
        # every consumer -- `emit_layout` and Soft Return.app's Native view
        # both need it to draw column boundaries/reset the vertical flow
        # at each column change (see `PageLine.col`'s own comment).
        # `column_width_pt` is captured from the FIRST real PageLine below
        # (whichever column it's in -- the formula is the same for all of
        # them), not re-derived from `_printed_left` here, so it agrees
        # exactly with the per-line `left` values this same loop sets.
        merged.columns = cols
        merged.column_gutter_pt = gutter_pt
        merged.column_width_pt = None
        group_end = min(i + cols, n_pages)
        # A later sub-page belonging to a DIFFERENT columns/gutter pair (a
        # new `.co` restatement) or a non-columnar page ends the group
        # early -- the forced break on state-change (research §7) means
        # this should only ever happen exactly at `i + cols`, never inside
        # it, but the check is cheap insurance against a state change the
        # forced-break guarantee somehow missed.
        col_idx = 0
        for j in range(i, group_end):
            sub = pages[j]
            sub_bi = next((getattr(pl, 'bi', None) for pl in sub
                          if getattr(pl, 'bi', None) is not None
                          and 0 <= pl.bi < len(doc.blocks)
                          and (doc.blocks[pl.bi].columns or 1) > 1), None)
            sub_cols = ((doc.blocks[sub_bi].columns or 1)
                       if sub_bi is not None else 1)
            sub_gutter = (doc.blocks[sub_bi].column_gutter or 0.0
                         if sub_bi is not None else 0.0)
            if sub_cols != cols or sub_gutter != gutter_cols:
                break
            for pl in sub:
                if not hasattr(pl, 'left'):
                    # A non-PageLine row (this notes-aware paginator's
                    # footnote-area lines are sometimes plain lists/tuples,
                    # never participants in a `.co` region in this corpus) --
                    # pass through unshifted rather than guess at a shape it
                    # doesn't have.
                    merged.append(pl)
                    continue
                base_left = pl.left if pl.left is not None else _printed_left(doc, size)
                # `rm_pt` is column 0's own right edge, measured from the
                # SAME page-left origin `base_left` is -- so `rm_pt -
                # base_left` is exactly one column's own width (docstring).
                column_width_pt = rm_pt - base_left
                if merged.column_width_pt is None:
                    merged.column_width_pt = column_width_pt
                pl.left = base_left + col_idx * (column_width_pt + gutter_pt)
                # planning #227 follow-up: the unambiguous "which column,
                # RESET Y" signal -- see PageLine.col's own comment. Every
                # real line this loop touches belongs to a column (0 for
                # the page's own non-columnar prefix lines too, per
                # `_apply_columns`'s docstring: column 0's x IS the page's
                # ordinary left origin).
                pl.col = col_idx
                merged.append(pl)
            col_idx += 1
        out.append(merged)
        i += col_idx if col_idx else 1
    return out


def _doc_to_pagelines(doc, printed, pix_results=None, pictures='off',
                      sentence_spacing=False):
    """IR -> list of pages, each a list of segment-lines.

    `sentence_spacing` (N9, b33 field notes): pre-resolved bool (True =
    'single') -- False is the correct default for every internal re-
    pagination caller (`_toc_page_numbers`), since Printed's physical
    lines never wrap, so collapsing an interior double space never
    changes line/page counts and this parameter cannot affect where
    anything lands; only the real render call (`_emit_pdf_inner`) needs
    to pass the resolved value through.

    `pix_results`/`pictures` (round 19, PIX images RULED IN; round 22
    closed the round-19 scope cuts -- `_paginate_printed_notes` above and
    Modern's `_modern_streams` now substitute too): when embedding is
    live on the printed path here and a
    physical line's ONLY real content is a single resolved, decoded pix
    placeholder (the real-corpus shape: a picture reference standing
    alone on its own paragraph, confirmed against all 5 acceptance
    documents), that PageLine becomes an image line instead of a text
    one. If a hypothetical pix tag ever shares a line with OTHER real
    text, this deliberately does NOT substitute -- text content is never
    silently dropped, so that occurrence renders as the ordinary
    unresolved-equivalent placeholder text instead (still correct, just
    not embedded)."""
    if printed and _has_placeable_notes(doc):
        cap = _printed_cap(doc)
        pages, last_page_cost, last_page_has_area = _paginate_printed_notes(
            doc, cap, MAX_COLS, pix_results=pix_results, pictures=pictures,
            sentence_spacing=sentence_spacing)
        # #228 (research/2026-09-08_trailing-pa-rule.md): a trailing `.pa`
        # -- the document's own LAST block -- closes the current page
        # (WordStar's own "force a new page" signal) even when nothing
        # real follows it before EOF and no visible extra page ever
        # opens (`doc.meta['pa_eof_blank_after']` False, the ordinary
        # case). Forcing `last_page_cost` to `cap` here makes the
        # continuation guard below correctly refuse to merge the
        # document's endnotes onto page 1's remaining room, matching
        # WordStar's own documented default endnote placement
        # (WSFORMAT.TXT: no `.PE` -> "endnotes will be printed at the
        # very end of the document ... starting a new page if they don't
        # fit what's left"). Confirmed against sawyer/DISPLAY.WS and
        # sawyer/REF/NOTES.TST: both end in a bare `.pa` (nothing after)
        # and both need their real endnote content on ITS OWN fresh
        # page, not merged with the footnote already on page 1 -- their
        # "extra page" was misclassified by the original triage as this
        # same trailing-`.pa`-opens-a-blank-page cause; it is not (see
        # the research doc's "Corrections" section) -- it is this
        # continuation-guard fix instead, one level removed from `.pa`
        # itself but still gated on the document ending in one.
        if doc.blocks and doc.blocks[-1].kind == 'pagebreak':
            last_page_cost = cap
        last_page = pages[-1] if pages else None
        # round 26 wave 3 (fidelity_gate.py Finding C): endnotes CONTINUE
        # the last body/footnote page when it has room, rather than
        # always starting fresh -- see _endnote_pages's docstring. The
        # `last_page and last_page_cost < cap` test decides which of
        # _endnote_pages' OWN returned pages is a continuation of
        # `last_page` (replace it) vs a genuinely new one (append it);
        # it's the identical guard _endnote_pages applies internally.
        end_pages = _endnote_pages(doc, cap, MAX_COLS, last_page=last_page,
                                   last_page_cost=last_page_cost,
                                   last_page_has_area=last_page_has_area,
                                   sentence_spacing=sentence_spacing)
        if end_pages and last_page and last_page_cost < cap:
            pages = pages[:-1] + end_pages
        else:
            pages = pages + end_pages
        while (len(pages) > 1 and not pages[-1]
               and not getattr(pages[-1], 'explicit_break', False)):
            pages.pop()
        pages = _apply_columns(doc, pages, _printed_size(doc))
        _attach_justify_word_x_printed(doc, pages, _printed_size(doc))
        _attach_line_numbers_printed(doc, pages, _printed_size(doc))
        _attach_graphic_cells_printed(doc, pages, _printed_size(doc))
        _attach_head_foot_lines_printed(doc, pages, _printed_size(doc))
        return pages or [[]]

    refs_all = _ref_pairs(_annotated_notes(doc))

    def _keep_span(s):
        # a comment's reference mark is position, not ink -- it renders
        # nowhere on this path (printed facsimile, or the plain line layer)
        if 'fnref' in s.styles and s.text.isdigit():
            k = int(s.text)
            if 0 < k <= len(refs_all) and refs_all[k - 1][0].kind == 'comment':
                return False
        return True

    # Header/footer changes, replayed at the block they precede so each
    # page carries the running head IN FORCE when it printed (doc.hf_events;
    # OLDTIMES defines its head after page 1's title -- a manuscript has no
    # running head on page 1, and now doesn't get one).
    # planning #250: `doc.hf_events_parity` is INDEX-ALIGNED with `doc.
    # hf_events` itself ('E'/'O'/None, `.h1e`/`.h1o`/`.f1e`/`.f1o` vs an
    # ordinary `.h#`/`.f#` -- see `Document.hf_events_parity`'s own
    # docstring for why this is a separate list rather than a wider tuple)
    # -- zipped in here so a page's own PARITY (known only once it closes,
    # same as `.poe`/`.poo`'s `cur_po`/`cur_poe`/`cur_poo`) can pick the
    # right variant below.
    hf_events = getattr(doc, 'hf_events', ())
    hf_parity = getattr(doc, 'hf_events_parity', None) or [None] * len(hf_events)
    hf_by_block = {}
    for (kind, lno, txt, anchor), parity in zip(hf_events, hf_parity):
        hf_by_block.setdefault(anchor, []).append((kind, lno, txt, parity))
    # round 17 (RULINGS-LEDGER row 5/7): `.pm`/`.psa`/`.psb` extend round 6's
    # RTF vertical-space model to Printed PDF, same relative-computation
    # rules, Printed only (Modern's own `else` branch below never reads
    # either helper). `pending_sa` carries a block's own `sa` forward to
    # whatever PageLine gets appended NEXT (which may be several `lines`
    # entries away across an intervening `.hf`/pagebreak/condpage sentinel)
    # -- applied the moment a real PageLine is built, regardless of source.
    doc_sb, doc_sa = _printed_doc_spacing_pt(doc) if printed else (None, None)
    pending_sa = None
    default_lead_pt = _printed_lead(doc) if printed else LEAD
    # register b31: `.po`'s own per-line override needs the printed type
    # size for the same edge-of-page clamp `_printed_left` already applies
    # (`_resolve_left_pt`); Modern never reads it (own_left stays unused
    # there -- see the `else` branch below).
    size_for_left = _printed_size(doc) if printed else None
    # Finding 1 (round 26 visual pass): scoped, per Jon's binding ruling,
    # to a POSITIVELY-DETECTED condition -- `variant == 'ws4'` -- rather
    # than trusting the block-pattern detector alone to stay harmless
    # everywhere else. `-README`/`VERSIONS` (both `ws5+`) picked up real
    # cross-page drift the FIRST time this fix shipped scoped only by
    # pattern (0.0 -> 0.0089 / 0.0047 XPAGE) -- both had matched their
    # own WS7 captures EXACTLY before that, so "a rule that un-matches
    # exact documents to fix others is not WS7's real rule" (Jon).
    # `ws4_spacing` being False makes `spacing_map` the literal empty
    # dict below for every non-WS4 document -- `_ws4_spacing_blank_indices` is
    # never even CALLED -- so every non-WS4 document's own code path is
    # identical to before this fix, by construction, not by trusting the
    # pattern to happen not to fire. Widening this gate past `ws4` (to
    # `ws3`, or to a WS5+ document that turns out to want the same
    # treatment) needs its own oracle evidence -- a real WS7 capture
    # showing the same constant-lines-per-page signature this fix was
    # built from -- not an assumption that the mechanism generalises.
    ws4_spacing = printed and doc.meta.get('variant') == 'ws4'
    # Prefer the file's OWN `.LS` dot-state when it exists (WS7 manual,
    # "Line Spacing": ".LS's blank lines become part of the file" -- see
    # `_ws4_spacing_blank_indices`); neither WS4 source measured for this
    # finding sets `.LS` at all (WS4 predates the dot command), so this
    # is False for them and the structural fallback in
    # `_ws4_spacing_blank_indices` carries the detection instead -- but a
    # future WS4 capture that DOES carry an explicit `.LS 2`+ should be
    # trusted over the pattern, not re-inferred from it.
    ls_confirmed = bool(ws4_spacing and doc.meta.get('page', {}).get('ls_source') == 'file'
                        and (doc.meta.get('page', {}).get('ls') or 1) > 1)
    spacing_map = _ws4_spacing_blank_indices(doc, ls_confirmed) if ws4_spacing else {}
    # round 26 wave 3 (fidelity_gate.py Finding B): `_font_lead_pt`'s
    # carried-governing-size state, threaded across every physical line
    # of the document in source order, same cross-block carry as
    # `pending_sa`. `lh_source == 'file'` guard mirrors `_style_lead_pt`'s
    # own -- see `_font_lead_pt`'s docstring.
    font_lead_state = [None]
    font_lead_ok = (printed and any(f.get('proportional') for f in doc.fonts)
                    and doc.meta.get('page', {}).get('lh_source') != 'file')
    font_lead_base = _printed_size(doc) if font_lead_ok else None
    embed_images = printed and pictures in ('embed', 'export') and pix_results
    pix_map = {r.index: r for r in (pix_results or [])} if embed_images else {}
    # "fit to text measure" (ruled fallback/cap) sizing lives in
    # `_pix_dims_pt`/`_printed_text_width_pt` (round 22 factored them out,
    # shared with the notes-pagination and Modern paths).
    text_width_pt = _printed_text_width_pt(doc) if embed_images else 0.0

    lines = []                                            # None = forced page break
    # #228: block index of the MOST RECENT explicit pagebreak, so a
    # trailing one (nothing real follows it) can still hand the render
    # step something to resolve auto-page-number state against -- see
    # `explicit_break_bi` above and the post-loop branch below. Only
    # read when that pagebreak turns out to be the document's last
    # thing AND doc.meta['pa_eof_blank_after'] is True; harmless
    # otherwise.
    last_pagebreak_bi = None
    # Planning #227 (columns-rule research §7): entering or leaving a
    # `.co n>1` region forces a page break if the current page already has
    # real content -- measured directly against sawyer/DEFAULT/PRINT.TST's
    # own capture (its `.co` off transition starts a fresh page, not a
    # continuation of the last, still-partial column). `prev_cols` tracks
    # the columns state of the most recently processed REAL ('para') block;
    # sentinel blocks (pagebreak/condpage/colbreak/condcolumn) never change
    # it, matching how `prev_para_block` below also skips them.
    prev_cols = 1
    for bi, b in enumerate(doc.blocks):
        for ev in hf_by_block.get(bi, ()):
            lines.append(('hf',) + ev)
        if b.kind == 'pagebreak' and prev_cols > 1:
            # Planning #227 (columns-rule research, corrected): a bare `.pa`
            # occurring INSIDE an active `.co n>1` region is ABSORBED, not
            # honoured as a real break. Measured directly against
            # sawyer/REF/WINGDING.CHT's own real WS7 capture: its source
            # carries `.pa` markers the AUTHOR placed between chart-entry
            # groups (a manual column-simulation convention predating, or
            # kept alongside, the real `.co5` that now governs the same
            # content) -- honouring them as real page breaks fragmented one
            # real ~47-line column into a 44-line page plus an orphaned
            # 3-line page, inflating WINGDING.CHT to 2 engine pages against
            # WS7's real 1. Columns fill by height alone once `.co n>1` is
            # active (research §4); only `.cb` forces an early break inside
            # one (handled below, unconditionally, regardless of this gate --
            # confirmed live and DISTINCT from `.pa` on sawyer/DEFAULT/
            # PRINT.TST, which uses `.cb` deliberately where `.pa` would not
            # have fired at all).
            last_pagebreak_bi = bi
            continue
        if b.kind in ('pagebreak', 'colbreak'):
            # `.cb` (unconditional column break) maps onto the SAME forced-
            # break sentinel `.pa` uses OUTSIDE a columnar region (or always,
            # for `.cb` itself -- it never gets the absorption above). Inside
            # an active `.co n>1` region, the column-grouping post-pass
            # (`_apply_columns`) turns every Nth forced break into a real
            # page break and the others into a column advance -- exactly
            # what a column break means; outside any columnar region (`.cb`
            # never appears there in this corpus -- research §7's own open
            # point), there is nothing to group and it degrades to an
            # ordinary forced page break, the documented fallback.
            lines.append(None)
            last_pagebreak_bi = bi
            continue
        if b.kind in ('condpage', 'condcolumn'):
            # `.cp n` -- a break ONLY if fewer than n lines remain. Measured on
            # WordStar 4 (2026-08-03): exactly n remaining is enough room and
            # does NOT break; the test is strictly `remaining < n`. Emitted as a
            # sentinel so the page-filling loop below, which is the only thing
            # that knows how full the page is, can decide.
            #
            # `.cc n` (planning #227) shares this sentinel for the identical
            # reason `.cb` shares `.pa`'s above: "room remaining in the
            # current column" and "room remaining in the current page" are
            # the SAME question whenever a column's height equals a page's
            # (always, in this engine -- a column is never vertically
            # shorter than the page it's on), so the underlying budget check
            # needs no column-aware variant at all.
            lines.append(('cond', b.heading or 1))
            continue
        if printed and b.origin == 'fi':
            # #241: `.fi` (file insert) on a target this engine cannot
            # resolve fabricates a visible `[insert: NAME]` placeholder
            # paragraph (core.py's `_parse_collect_dot`/parse_ws, origin=
            # 'fi') -- useful in Modern (an editorial note about what the
            # source asked for), but WS7's real behaviour on an
            # unresolvable `.fi` target is to print NOTHING: measured
            # directly (sawyer/RTF-RJS's own `.fi C:\WS\RTF-RJS\LINKS.MRG`
            # probes, a target that exists nowhere in the corpus) -- WS7's
            # capture goes straight from the line before `.fi` to the
            # document's own next real text, no gap, no placeholder line
            # at all. Printed mode (this engine's WS7-emulation surface)
            # skips the block entirely -- zero lines, zero page-advance --
            # matching WS7; Modern is untouched (still shows the
            # placeholder, per Jon's ruling: "report what Modern does and
            # leave it").
            continue
        cur_cols = (b.columns or 1) if printed else 1
        # Planning #227 (columns-rule research §7, corrected): only LEAVING
        # a columnar region forces a break -- confirmed against
        # sawyer/DEFAULT/PRINT.TST's own `.co` off transition. ENTERING one
        # does NOT: sawyer/REF/SYMBOL.CHT's own title line sits on the SAME
        # page as its chart's columnar content in the real WS7 capture (1
        # page total) -- an early version of this rule forced a break on
        # ANY columns-state change and split SYMBOL.CHT onto 2 pages,
        # contradicting that capture directly.
        if printed and prev_cols > 1 and cur_cols != prev_cols and lines and lines[-1] is not None:
            lines.append(None)
        prev_cols = cur_cols
        fi_pt = _printed_pm_fi_pt(b) if printed else None
        first_line_of_block = True
        # Fix C (b26-print-fidelity-2): the nearest earlier REAL ('para')
        # block, skipping pagebreak/condpage sentinels -- `_entering_lead_pt`'s
        # own "outgoing" reference for this block's first line, computed
        # once per block since it never changes within one.
        prev_para_block = next((doc.blocks[k] for k in range(bi - 1, -1, -1)
                                if doc.blocks[k].kind == 'para'), None)
        # printed renders PHYSICAL lines (a soft return broke the line on
        # paper); modern reflows LOGICAL lines (soft runs joined back --
        # core.merged_lines, the 2.0.0 split). Indexed (not a plain `for`)
        # so an embedded pix substitution below can look ahead and CONSUME
        # the blank placeholder lines WordStar reserved for it -- see
        # `_pix_reserved_advance`.
        blk_lines = b.lines if printed else _merged_lines(b)
        # Finding 1: see `ws4_spacing`'s own comment above -- `spacing_map`
        # is the literal empty dict for every non-WS4 document, so `.get`
        # here always returns the empty set and nothing below can touch one.
        spacing_blanks = spacing_map.get(bi, set())
        _li = 0
        while _li < len(blk_lines):
            _idx = _li
            line = blk_lines[_li]
            _li += 1
            # the docstring's "headings bold" promise: heading blocks render in
            # Courier-Bold (found unimplemented by the Swift port, job-011)
            kept = [s for s in line.spans if _keep_span(s)]
            # N9 (b33 field notes): applied to the KEPT spans' text, in
            # order -- state carries across them the same as every other
            # emitter's own choke point (a span filtered out by
            # `_keep_span` above never renders, so it never counts as
            # "the last character seen" either).
            texts = (_sentence_spacing_texts([s.text for s in kept])
                    if sentence_spacing else [s.text for s in kept])
            spans = [(t, _effective_span_styles(s, b, heading_bold=True))
                     for s, t in zip(kept, texts)]
            if printed:
                # Planning #251 (2026-09-09): bare-tab expansion moves from
                # RENDER time (`_line_ops_printed` used to call
                # `_expand_bare_tabs_for_printed_layout` on a transient copy
                # just before drawing) to MODEL-BUILD time, here -- the
                # model's own segments now carry the expanded spaces
                # directly, so `emit_layout`'s 'printed' pagelines (which
                # read this PageLine's segments verbatim, never through the
                # PDF writer) stop handing a raw, unexpanded 0x09 byte to
                # any consumer (planning #251, item 9: the app's own
                # docToPagelines inherited the same raw byte and mis-placed
                # RNFOREST/RECYCLE/WETLAND by a full modulus-8 stop). Same
                # column-counting semantics as before (one call = one
                # physical printed line, col/space_run reset fresh) --
                # `_expand_bare_tabs_for_printed_layout`'s own docstring for
                # the rule itself, unchanged. Guarded inside `if printed:`
                # (never in the `else:` wrap-for-Modern branch below) so
                # Modern still sees the bare, un-expanded byte exactly as
                # every other emitter does -- unaffected.
                spans = _expand_bare_tabs_for_printed_layout(spans)
                # verbatim, no wrap -- carrying the line's own soft flag and
                # the `.lh` that was in force where it sat
                own_lead = _lead_pt(line.lead_48)
                # register b31: this line's own `.po` override, same
                # "absolute here, None means agrees with the document
                # default" contract `line.lead_48` above already has.
                own_left = (_resolve_left_pt(line.po_cols, size_for_left)
                           if getattr(line, 'po_cols', None) is not None
                           else None)
                # Planning #231 (.poe/.poo even/odd page offset): which of
                # the two ever governs a given line depends on the PARITY
                # of the page it lands on -- not known at this build stage
                # (pagination is a later, separate pass) -- so this only
                # ever records a CANDIDATE `(even_pt, odd_pt)` pair;
                # `_close_page` (the one place page parity is actually
                # known) picks the real one once pagination assigns this
                # line to a page. None (the overwhelming common case: a
                # document that never uses `.poe`/`.poo`) costs nothing.
                own_parity_left = None
                poe_c = getattr(line, 'poe_cols', None)
                poo_c = getattr(line, 'poo_cols', None)
                if poe_c is not None or poo_c is not None:
                    fallback_pt = (own_left if own_left is not None
                                  else _printed_left(doc, size_for_left))
                    own_parity_left = (
                        _resolve_left_pt(poe_c, size_for_left) if poe_c is not None
                        else fallback_pt,
                        _resolve_left_pt(poo_c, size_for_left) if poo_c is not None
                        else fallback_pt)
                # register b32-N10: this line's own `.sr` roll, already
                # resolved -- core.Line.roll_48 is never None on a real
                # parsed line (its own docstring), so this is simply the
                # 1/48in -> points conversion `_printed_roll_pt` already
                # uses for the document-wide fallback, applied per line.
                own_roll = (line.roll_48 * 1.5
                           if getattr(line, 'roll_48', None) is not None
                           else None)
                # A WS7 paragraph STYLE's own line height (core.Block.
                # line_height_vmi) governs OVER the generic `.lh`/document
                # default -- same precedence _new_block() already gives a
                # style's align/margins/wrap over the running dot-command
                # state. _style_lead_pt itself withholds an answer (None) for
                # any document that ever used a real `.lh` at all (its own
                # docstring), so this line's own lead_48 only matters as a
                # belt-and-braces check for a genuinely per-line override.
                # LYING.WS carries no `.lh` at all, so every one of its
                # lines takes this branch (measured 2026-08-20).
                #
                # Fix C (b26-print-fidelity-2): a BLANK line (no real
                # text -- nothing to clip, so Finding B's fallback never
                # applies to it, see `_style_lead_pt`'s `raw` note) always
                # gets the raw, unfallen-back value. A block's own FIRST
                # REAL line is the one `_entering_lead_pt` may floor
                # against the PRECEDING block's own raw lead (its
                # docstring); any other real line keeps the plain
                # fallback-eligible value, unchanged from every call site
                # before this fix.
                is_blank = not any(t.strip() for t, _ in spans)
                if is_blank:
                    style_lead = _style_lead_pt(b, doc, raw=True)
                elif first_line_of_block:
                    style_lead = _entering_lead_pt(b, doc, prev_para_block)
                else:
                    style_lead = _style_lead_pt(b, doc)
                if style_lead is not None and (
                        line.lead_48 is None or line.lead_48 == DEFAULT_LH_48):
                    own_lead = style_lead
                # round 26 wave 3 (fidelity_gate.py Finding B): a WS5+
                # FONT-BLOCK document with no style governing this line
                # (own_lead still None -- every LYING-shaped line already
                # took the style branch above and never reaches this) gets
                # its lead from the font block actually in force. See
                # `_font_lead_pt`.
                if own_lead is None and font_lead_ok:
                    own_lead = _font_lead_pt(line, doc.fonts, font_lead_base,
                                             font_lead_state)
                # Finding 1: this blank IS the block's own double-spacing
                # (see `_ws4_spacing_blank_indices`) -- it still becomes its
                # own literal PageLine, at its own natural (unextended)
                # lead, EXACTLY as any other blank always has; only its
                # `ws4_spacing` flag differs, which the pagination loop
                # below reads to decide whether this blank alone may force
                # a page break (see that loop's own comment for why
                # collapsing it into a neighbour's lead, an earlier version
                # of this fix, broke on irregular paragraph lengths).
                ws4_spacing_line = is_blank and _idx in spacing_blanks
                extra = 0.0
                if pending_sa is not None:
                    extra += pending_sa
                    pending_sa = None
                if first_line_of_block and doc_sb and bi > 0:
                    # no space-before on the document's own opening paragraph
                    # -- nothing above it to space away from.
                    extra += doc_sb
                if extra:
                    own_lead = (own_lead if own_lead is not None else default_lead_pt) + extra
                # Round 19: exactly one pix tag, no other real text on this
                # physical line (see _doc_to_pagelines's own docstring) ->
                # an image PageLine instead of a text one. own_lead becomes
                # the RESERVED PLACEHOLDER block's height (the tag line plus
                # its contiguous following blanks, see
                # `_pix_reserved_advance` -- round 26, fidelity_gate.py
                # Finding A; NOT the raster's own continuous pixel height,
                # + whatever .psb/.psa extra was already computed above),
                # reusing the pagination budget model unchanged. (Round 22:
                # the detection/sizing rule is `_spans_pix_substitution`,
                # shared with the notes and Modern paths.)
                if embed_images:
                    sub = _spans_pix_substitution(spans, pix_map, text_width_pt)
                    if sub is not None:
                        pix_idx, w_pt, h_pt = sub
                        reserved, n_blank = _pix_reserved_advance(
                            blk_lines, _li,
                            own_lead if own_lead is not None else default_lead_pt)
                        _li += n_blank
                        pl = PageLine([], soft=line.soft,
                                     lead=reserved + extra, overprint=line.overprint,
                                     bi=bi, image=(pix_idx, w_pt, h_pt),
                                     left=own_left)
                        lines.append(pl)
                        first_line_of_block = False
                        continue
                # Planning #238 (.oj on full justification, research/
                # 2026-09-08_justification-rule.md): every line of a
                # `align='justify'` block EXCEPT ITS OWN LAST is stretched to
                # the block's resolved right margin -- measured directly
                # against WS7 (sawyer/LSRBOX/LSRBOX.WS): the paragraph's
                # final physical line sits short of the margin, ragged,
                # while every line above it reaches the margin exactly.
                # `right_margin` is `.rm` in print columns, measured from the
                # SAME `.po` origin as the left edge (confirmed against two
                # independent captures: LSRBOX's own explicit `.po .7"/.rm
                # 6.5"` and CTRL-K.H1's all-defaults line, both landing on
                # their real WS7 right edge as po_origin + rm_cols*7.2pt,
                # never rm alone) -- 65.0 is WordStar's own factory default
                # (WSFORMAT.TXT gives no numeric default; confirmed instead
                # against CTRL-K_EXT_H1.pcl's real flush-right edge, 525.6pt
                # = the same default .po 8 cols (57.6pt) + 65 cols (468pt)).
                justify_right_x = None
                if (printed and b.align == 'justify'
                        and _idx < len(blk_lines) - 1):
                    po_origin_pt = (own_left if own_left is not None
                                    else _printed_left(doc, size_for_left))
                    rm_cols = (b.right_margin if b.right_margin is not None
                              else 65.0)
                    justify_right_x = po_origin_pt + rm_cols * _PDF_PT_PER_COL
                pl = PageLine(spans, soft=line.soft, lead=own_lead,
                             overprint=line.overprint,
                             fi=(fi_pt if first_line_of_block else None), bi=bi,
                             ws4_spacing=ws4_spacing_line,
                             kerning=getattr(line, 'kerning', True),
                             left=own_left, roll=own_roll,
                             justify_right_x=justify_right_x,
                             parity_left=own_parity_left)
                lines.append(pl)
                first_line_of_block = False
            else:
                lines.extend(PageLine(w, soft=line.soft)
                             for w in _wrap_line(spans, MAX_COLS))
        if not printed and b.lines:
            lines.append([])                              # blank line between paragraphs
        if printed and doc_sa and b.lines and not first_line_of_block:
            # `not first_line_of_block`: this block actually appended at
            # least one real PageLine (an empty-text block leaves it True,
            # nothing to space away from). Carried to whatever PageLine
            # comes next, however many sentinel entries away that is.
            pending_sa = doc_sa
    if not printed:
        # Printed mode's own layout is handled above (period-authentic,
        # per-page); this end-of-document dump is this legacy helper's own
        # Modern-only tail. Real Modern PDF output goes through
        # `_modern_streams` (ruling 2026-08-05) and never reaches this
        # branch -- it survives only because existing unit tests call
        # `_doc_to_pagelines(doc, False)` directly (see e.g.
        # test_style_pass_through_pdf, test_pdf_exact_fill_no_blank_sheet).
        # b26 notes wave: this dump used to renumber every kept note
        # (doc.footnotes, which mixes footnote/endnote/annotation) through
        # one shared sequential index regardless of kind, so a footnote #1
        # and an endnote #1 both printed as "[1]"/"[2]" -- silently
        # disagreeing with _annotated_notes/_display_number, the one label
        # every real emitter (and this same file's own `_note_marker`/
        # `_endnote_marker`) agrees on. Now per-kind: "1." for footnotes/
        # annotations, "(1)" for endnotes -- oracle-verified (-SCREEN.WS:
        # "1.  Footnote" / "(1)  Endnote").
        placeable = [(n, label) for n, label in _annotated_notes(doc)
                     if n.kind in ('footnote', 'endnote', 'annotation')]
        if placeable:
            lines += [[], [('-' * 20, frozenset())], []]
            for note, label in placeable:
                marker = (_endnote_marker(label) if note.kind == 'endnote'
                          else _note_marker(note, label))
                note_text = (_sentence_spacing_texts([note.text])[0]
                            if sentence_spacing else note.text)
                lines.extend(_wrap_line([(marker + note_text, frozenset())],
                                        MAX_COLS))
    # Finding 3 (b26-print-fidelity-2): a fresh page picks up whatever
    # .mt/.mb was in force at its OWN first block, not the document's
    # first-occurrence pair -- see _mt_mb_checkpoints. `global_mt`/
    # `global_mb` are what _printed_cap(doc) itself would use; a page
    # whose own checkpoint matches them leaves `Page.mt_lines`/`mb_lines`
    # at their None default (render side: "use the document global",
    # untouched).
    mt_mb_checkpoints = _mt_mb_checkpoints(doc) if printed else None
    global_mt, global_mb = (mt_mb_checkpoints[0][1], mt_mb_checkpoints[0][2]) \
        if mt_mb_checkpoints else (None, None)
    cur_mt, cur_mb = global_mt, global_mb
    # register b31-dot-command-sweep: `.pl` is stateful too, same
    # mechanism as mt/mb above -- see `_pl_checkpoints`.
    pl_checkpoints = _pl_checkpoints(doc) if printed else None
    # `_pl_at(.., 0)`, NOT `pl_checkpoints[0][1]`: block 0's seed is
    # WordStar's hardcoded default, which a document that declares `.pl`
    # right at its own start immediately supersedes with another (bi=0)
    # checkpoint -- `_pl_at` resolves that correctly, a raw index-0 read
    # would not (see `_pl_checkpoints`'s docstring).
    global_pl = _pl_at(pl_checkpoints, 0) if pl_checkpoints else None
    cur_pl = global_pl
    # register b31-dot-command-sweep follow-up: `.po` too -- see
    # `_po_checkpoints`. Feeds `_running_ops`'s own header/footer LEFT
    # edge only (body text's per-LINE `.po` already works, core.Line.
    # po_cols) -- still ride the SAME per-page-start recompute so
    # `Page.po_cols` is known by the time a page closes, exactly like
    # pl_lines.
    po_checkpoints = _po_checkpoints(doc) if printed else None
    global_po = _po_at(po_checkpoints, 0) if po_checkpoints else None
    cur_po = global_po
    # planning #231: `.poe`/`.poo` -- see `_poe_poo_checkpoints`. No
    # block-0 seed (unlike `po_checkpoints` above): "never used" is a real,
    # different answer from "used at the document default," and
    # `_left_for_parity` already treats an empty/None value as "fall back
    # to `cur_po`" -- exactly what a document that never writes `.poe`/
    # `.poo` needs, byte-identical to before this feature existed.
    poe_checkpoints = _poe_poo_checkpoints(doc, _POE_CMD_RE) if printed else None
    poo_checkpoints = _poe_poo_checkpoints(doc, _POO_CMD_RE) if printed else None
    cur_poe = _po_at(poe_checkpoints, 0) if poe_checkpoints else None
    cur_poo = _po_at(poo_checkpoints, 0) if poo_checkpoints else None
    # register b31-dot-command-sweep: `.hm`/`.fm` too -- see
    # `_hm_fm_checkpoints`. Neither feeds capacity/budget (only the
    # header/footer ROW and the notes-area bottom anchor read them), but
    # they still ride the SAME per-page-start recompute so `Page.hm_lines`/
    # `fm_lines` are known by the time a page closes, exactly like pl_lines.
    hm_fm_checkpoints = _hm_fm_checkpoints(doc) if printed else None
    global_hm, global_fm = (_hm_fm_at(hm_fm_checkpoints, 0)
                            if hm_fm_checkpoints else (None, None))
    # `_close_page`'s "does this page need its own render-time override"
    # test can NOT compare against `global_pl`/`global_hm`/`global_fm`
    # above: those are seeded at WordStar's hardcoded default (correct for
    # BEFORE any real occurrence), but the render loop's fallback ("Page.*
    # left None means use doc.meta['page'] AS IS") reads core.py's own
    # first-occurrence value, which -- in the exact degenerate case the
    # seed fix above exists for (a command whose ONLY occurrence sits
    # mid-document) -- is that SAME later value, wrongly, for every page.
    # Comparing against the RAW doc.meta['page'] reading instead makes a
    # page whose resolved value happens to DIFFER from it get its own
    # override even when that resolved value equals the (correct)
    # checkpoint global, which is exactly the pages BEFORE such a
    # command's first real occurrence.
    from .core import (DEFAULT_PL_LINES, DEFAULT_HM_LINES, DEFAULT_FM_LINES,
                       DEFAULT_PO_COLS)
    _pg0 = doc.meta.get('page') or {}
    doc_pl = _pg0.get('pl_lines', DEFAULT_PL_LINES)
    doc_hm = _pg0.get('hm_lines', DEFAULT_HM_LINES)
    doc_fm = _pg0.get('fm_lines', DEFAULT_FM_LINES)
    doc_po = _pg0.get('po_cols', DEFAULT_PO_COLS)
    cur_hm, cur_fm = global_hm, global_fm
    cap = _printed_cap(doc) if printed else LINES_MODERN
    # Printed pagination is by ACCUMULATED POINTS, not line count. Paper is
    # physical: WordStar advances each line by the `.lh` in force and starts
    # a new page when the next advance would leave the text area -- so a
    # document that varies its leading (LJ6DTP's title page swaps 10pt/14pt/
    # 16pt leads around 72pt banners) fits more or fewer lines than the
    # default-lead count says. The budget is (cap - 1) leads at the document
    # default -- the first line sits at the top, each following line spends
    # its own lead -- which makes a uniform-lead document paginate EXACTLY as
    # the old line count did (n - 1 defaults == cap - 1 defaults at n == cap),
    # so no fontless byte moves. Overprint lines spend no lead at all, on
    # paper and here. (Resolves register #15's visible symptom -- an orphan
    # line pushed onto its own page ahead of a `.pa`.)
    default_lead = _printed_lead(doc) if printed else LEAD
    budget = (cap - 1) * default_lead
    # round 17b (RULINGS-LEDGER row 5/6, register C8): `.sb` suppresses
    # blank lines specifically at the TOP of a page -- WordStar's own
    # pagination concern, not a text-content one, so it belongs in THIS
    # loop (the only place that knows a page just started) rather than
    # `_doc_to_pagelines`'s line-building pass above. `.sb` rides in
    # doc.meta['formatting'] for free, same as every other item this round.
    suppress_blanks = printed and bool(doc.meta.get('formatting', {}).get('suppress_blanks', False))
    pages, page, spent = [], [], 0.0
    cur_hdrs, cur_ftrs = {}, {}
    page_hdrs, page_ftrs = {}, {}      # state at the OPEN page's start
    # planning #250: the SAME flat/snapshot machinery as `cur_hdrs`/
    # `page_hdrs` above, one independent pair per parity -- `.h1e`/`.f1e`
    # write only `cur_hdrs_e`/`cur_ftrs_e`, `.h1o`/`.f1o` only `cur_hdrs_o`/
    # `cur_ftrs_o`; a plain `.h1`/`.fo` never clears either (same "each
    # command in this family is independently stateful" rule `.poe`/`.poo`
    # already established -- `_left_for_parity`'s own docstring). Resolved
    # against the real page parity only in `_close_page`, the one place
    # that knows it.
    cur_hdrs_e, cur_hdrs_o, cur_ftrs_e, cur_ftrs_o = {}, {}, {}, {}
    page_hdrs_e, page_hdrs_o, page_ftrs_e, page_ftrs_o = {}, {}, {}, {}
    def _cost(ln):
        lead = getattr(ln, 'lead', None) or default_lead
        if not page:                              # first line on page is free
            # b26-mtmb-general (pictures-mode pagination parity, -README.WS):
            # an embedded image's `.lead` is a RESERVED-BAND total (the pix
            # tag's own line plus its contiguous following blanks --
            # `_pix_reserved_advance`), not one physical line's advance. The
            # "first line is free" rule below assumes the opposite -- that
            # `.lead` represents exactly the ONE source line `budget`'s own
            # `(cap - 1)` already accounts for (see `budget`'s comment) --
            # so crediting the WHOLE reserved band when the image happens to
            # land as a page's first line freed 7 extra lines' worth of
            # budget (96pt reserved band, 84pt of which should have stayed
            # charged) that the `pictures=off` path, where the SAME tag
            # line and blanks are ordinary PageLines and only the tag
            # line's own one-line advance is ever free, never received --
            # off matches WS7's real page break exactly, embed ran several
            # lines longer before this fix. Only the amount ABOVE one
            # line's own advance is charged even at a page's own start, so
            # embed's image-band cost matches off's natural per-line
            # accumulation exactly, regardless of where either mode's
            # break happens to fall.
            # planning #236 remainder (sawyer/INTERVU.WS): the credit
            # above is scoped to `default_lead`'s OWN worth, same as the
            # image case just above -- a page's first line was always
            # free even when a STYLE (not `.lh`) gives it a bigger real
            # lead than the document default, over-crediting the page by
            # (real lead - default_lead) points of budget that were never
            # actually free. INTERVU.WS's whole body runs at the "MS Body
            # Copy" style's own 24pt VMI while the document's `.lh`
            # (hence `default_lead`) stays the unset 12pt default -- every
            # page opening on a body line pockets 12pt of phantom room
            # this way, which is exactly the margin a later `.cp2` needed
            # to correctly push a whole paragraph to the next page.
            # Mathematically identical to the previous flat `0.0` for
            # every document whose first line's lead already equals
            # `default_lead` (the overwhelming common case).
            return max(0.0, lead - default_lead)
        if getattr(page[-1], 'overprint', False):
            return 0.0                             # this line shares a baseline
        return lead
    def _close_page(explicit=False, break_bi=None):
        pg = Page(page)
        pg.headers = {k: v for k, v in page_hdrs.items() if v}
        pg.footers = {k: v for k, v in page_ftrs.items() if v}
        # #228: only ever True from the post-loop trailing-`.pa` branch
        # below, and only when `page` (this closing page's own body) is
        # empty -- a page WITH content already carries real `.bi`-bearing
        # lines, so it needs no fallback and stays exempt from the
        # empty-trailing-page cleanup on its own (that cleanup only pops
        # truly-empty pages to begin with).
        if explicit and not pg:
            pg.explicit_break = True
            pg.explicit_break_bi = break_bi
        if (cur_mt, cur_mb) != (global_mt, global_mb):
            pg.mt_lines, pg.mb_lines = cur_mt, cur_mb
        if cur_pl != doc_pl:
            pg.pl_lines = cur_pl
        if (cur_hm, cur_fm) != (doc_hm, doc_fm):
            pg.hm_lines, pg.fm_lines = cur_hm, cur_fm
        # planning #231: this page's own PARITY -- `len(pages)` is exactly
        # the count of pages already closed, so the page closing right now
        # is page number `len(pages) + 1`, known for the FIRST time here
        # (nothing upstream of pagination can know it). `_left_for_parity`
        # falls back to `cur_po` whenever neither `.poe` nor `.poo` is in
        # force, so a document that never uses either resolves to `cur_po`
        # on every page, byte-identical to before this feature existed.
        is_even_page = (len(pages) + 1) % 2 == 0
        parity_po = _left_for_parity(cur_po, cur_poe, cur_poo, is_even_page)
        if parity_po != doc_po:
            pg.po_cols = parity_po
            # #241 follow-up: mark that this override is a live `.poe`/
            # `.poo` parity decision (not a plain mid-document `.po`
            # excursion) so the running head/foot's own `page_geom_changed`
            # gate -- correctly built to exclude a HOLYMAC-style transient
            # `.po` -- lets it through regardless. See `Page.po_parity`.
            pg.po_parity = cur_poe is not None or cur_poo is not None
        # planning #250: `.h1e`/`.h1o`/`.f1e`/`.f1o` -- this page's own
        # PARITY (`is_even_page`, just resolved above) picks its real
        # line-1 text the same way `.poe`/`.poo` picks its own left
        # origin: its OWN parity variant if the document ever set one FOR
        # THIS PARITY, else whatever plain `.h1`/`.he`/`.f1`/`.fo` governs
        # (`page_hdrs`/`page_ftrs`, already the page's own snapshot,
        # unchanged). `page_hdrs_e`/`_o`/`page_ftrs_e`/`_o` all empty (no
        # document that never uses `.h1e`/`.h1o`/`.f1e`/`.f1o`) means
        # `_parity_hf` returns None every time below -- `pg.headers`/
        # `pg.footers` stay byte-identical to before this feature existed.
        #
        # "Only one of the pair set" (brief's own open question; no corpus
        # document exercises it): the un-set parity has no override of its
        # own here and falls through to `page_hdrs`/`page_ftrs` -- the
        # flat dict every `.h#`/`.f#` command ALSO writes (`core.py`'s
        # `_parse_head_foot`, unconditionally, parity or not), the SAME
        # last-in-source-order-wins projection Modern/RTF/plain-text
        # already read -- so a document with `.h1e` alone never shows a
        # blank header on odd pages, or a crash. This is NOT necessarily
        # "the plain `.h1`'s own text": a parity-specific override is
        # independently stateful (the `.poe`/`.poo` precedent -- a later
        # plain `.h1` never clears an `.h1e`/`.h1o` already in force, and
        # vice versa), so the flat fallback is whichever `.h#`/`.f#`
        # command -- of EITHER shape -- fired LAST at any given point in
        # the document; only the PARITY-SPECIFIC state is sticky, the flat
        # projection keeps its pre-existing simple last-wins reading.
        # `test_head_foot_parity_h1e_without_h1o_falls_back_to_the_flat_
        # value` and `test_head_foot_parity_a_plain_h1_after_h1e_updates_
        # only_the_flat_fallback` (tests/test_ctrlkd.py) pin both halves
        # of this reading.
        def _parity_hf(even_map, odd_map, fonts_parity, tabs_parity):
            if 1 not in even_map and 1 not in odd_map:
                return None
            if is_even_page and 1 in even_map:
                letter, text = 'E', even_map[1]
            elif not is_even_page and 1 in odd_map:
                letter, text = 'O', odd_map[1]
            else:
                return None
            font_idx = fonts_parity.get(1, {}).get(letter)
            tab_rec = tabs_parity.get(1, {}).get(letter)
            return text, font_idx, tab_rec
        head = _parity_hf(page_hdrs_e, page_hdrs_o,
                          doc.header_fonts_parity, doc.header_tabs_parity)
        if head is not None:
            text, font_idx, tab_rec = head
            if text:
                pg.headers[1] = text
            else:
                pg.headers.pop(1, None)
            pg.head_hf_override = {1: (font_idx, tab_rec)}
        foot = _parity_hf(page_ftrs_e, page_ftrs_o,
                          doc.footer_fonts_parity, doc.footer_tabs_parity)
        if foot is not None:
            text, font_idx, tab_rec = foot
            if text:
                pg.footers[1] = text
            else:
                pg.footers.pop(1, None)
            pg.foot_hf_override = {1: (font_idx, tab_rec)}
        # Body text: `_doc_to_pagelines`/`_body_stream_printed` could not
        # resolve a `.poe`/`.poo`-governed line's own left origin at BUILD
        # time (which page, and therefore which parity, a line lands on is
        # a pagination question, not a parse-order one) -- they left a
        # `(even_pt, odd_pt)` candidate pair on `.parity_left` instead.
        # Resolved now, in place, the one moment this loop actually knows
        # this page's parity.
        for pl in pg:
            parity_left = getattr(pl, 'parity_left', None)
            if parity_left is not None:
                pl.left = parity_left[0 if is_even_page else 1]
        pages.append(pg)
    def _recompute_geom(bi):
        """(mt, mb, pl, hm, fm, po) in force at block `bi`, for the page about
        to start there -- shared by BOTH places a fresh page begins:

        1. Right here (below), when the page break is EXPLICIT (`.pa`/
           `.cp`/WordStar's own softpage -- a `None` sentinel in `lines`,
           or the `cond` branch above) -- `page` is already empty by the
           time this line is reached, so the `not page` gate at the top
           of the loop catches it on the very next iteration.
        2. At the organic-overflow close below (`full`), where `page` is
           NOT yet empty at the top of THIS iteration (it still holds the
           page that is about to close) -- the top-of-loop gate can never
           see `l` as starting a fresh page, because `l` itself is what
           triggered the close, and it lands on the NEW page in this same
           iteration. Missed until register b31-dot-command-sweep: the two
           real oracles behind `_mt_mb_checkpoints` (SCRIPT.WS, LJ6DTP.WS)
           both happen to change `.mt`/`.mb` right after an explicit `.pa`,
           so path 1 alone reproduced them and path 2's absence was
           invisible. `.pl`'s own oracle (PL_PROBE, dosbox-x) has NO `.pa`
           at all -- an ordinary organic page break -- and real WS7 still
           used the new `.pl` starting the very next page, which only
           path 2 can reproduce."""
        mt, mb = _mt_mb_at(mt_mb_checkpoints, bi) if mt_mb_checkpoints else (global_mt, global_mb)
        pl = _pl_at(pl_checkpoints, bi) if pl_checkpoints else global_pl
        hm, fm = _hm_fm_at(hm_fm_checkpoints, bi) if hm_fm_checkpoints else (global_hm, global_fm)
        po = _po_at(po_checkpoints, bi) if po_checkpoints else global_po
        poe = _po_at(poe_checkpoints, bi) if poe_checkpoints else None
        poo = _po_at(poo_checkpoints, bi) if poo_checkpoints else None
        return mt, mb, pl, hm, fm, po, poe, poo
    # #228: True only in the gap between processing a forced pagebreak
    # (`l is None`) and either the next real line or the end of `lines`
    # -- set True right where the loop `continue`s on `l is None`, set
    # False right before any real content is appended to `page`. If it
    # is STILL True once the loop ends, the document's very last thing
    # was an explicit pagebreak with nothing after it -- whether that
    # opens a page depends on doc.meta['pa_eof_blank_after'] (see the
    # post-loop branch below).
    trailing_pagebreak = False
    for _li, l in enumerate(lines):
        if isinstance(l, tuple) and l and l[0] == 'hf':
            _, kind, lno, txt, parity = l
            # planning #250: `.h1e`/`.f1e` write ONLY `cur_hdrs_e`/
            # `cur_ftrs_e`, `.h1o`/`.f1o` ONLY `cur_hdrs_o`/`cur_ftrs_o` --
            # a plain `.h1`/`.fo` (parity is None) still ALSO writes the
            # flat `cur_hdrs`/`cur_ftrs`, exactly as before this feature
            # existed (the fallback `_close_page`'s own `_parity_hf` reads
            # when neither variant governs this page's own parity).
            if parity == 'E':
                (cur_hdrs_e if kind == 'H' else cur_ftrs_e)[lno] = txt
            elif parity == 'O':
                (cur_hdrs_o if kind == 'H' else cur_ftrs_o)[lno] = txt
            (cur_hdrs if kind == 'H' else cur_ftrs)[lno] = txt
            if not page:                   # nothing printed on this page yet:
                page_hdrs, page_ftrs = dict(cur_hdrs), dict(cur_ftrs)
                page_hdrs_e, page_hdrs_o = dict(cur_hdrs_e), dict(cur_hdrs_o)
                page_ftrs_e, page_ftrs_o = dict(cur_ftrs_e), dict(cur_ftrs_o)
            continue
        if isinstance(l, tuple) and l and l[0] == 'cond':
            # strictly fewer than n lines left -> break; exactly n is enough.
            # planning #236 remainder (sawyer/INTERVU.WS): the same style-
            # vs-document-default gap `_cost`'s first-line credit above was
            # just fixed for. This document's body runs at the "MS Body
            # Copy" style's own 24pt VMI while `.lh` (hence `default_lead`)
            # stays the unset 12pt document default -- a flat `n *
            # default_lead` room estimate prices the upcoming `.cp2`'s 2
            # reserved lines at 2*12=24pt when they actually cost 2*24=48pt,
            # so it measured `room == 3` (12pt-units) against `l[1] == 2`
            # and let a `.cp2` sitting right after a Q&A paragraph break
            # print its first reserved line on the closing page, when only
            # 36pt of real room was left and both lines together need
            # 48pt. Real WS7 pushes the WHOLE paragraph to a fresh page
            # instead -- measured directly against the WS7 capture (page
            # 2's last body line, 636pt, never advancing to the answer at
            # all). Look ahead at the REAL cost of the next `l[1]`
            # PageLines (skipping sentinels) instead of assuming each one
            # is exactly `default_lead` tall -- confirmed necessary and not
            # merely redundant with the `_cost` fix: without this lookahead
            # too, the same document still mispaginates (page 2 keeps the
            # answer's opening line after all, just elsewhere in the
            # document happens to still total 9 pages by coincidence).
            if printed:
                needed, seen = 0.0, 0
                for peek in lines[_li + 1:]:
                    if peek is None:
                        break
                    if isinstance(peek, tuple) and peek and peek[0] in ('hf', 'cond'):
                        continue
                    needed += getattr(peek, 'lead', None) or default_lead
                    seen += 1
                    if seen >= l[1]:
                        break
                short = (budget - spent) < needed - 1e-6
            else:
                short = (cap - len(page)) < l[1]
            if short and page:
                _close_page(); page, spent = [], 0.0
                page_hdrs, page_ftrs = dict(cur_hdrs), dict(cur_ftrs)
                page_hdrs_e, page_hdrs_o = dict(cur_hdrs_e), dict(cur_hdrs_o)
                page_ftrs_e, page_ftrs_o = dict(cur_ftrs_e), dict(cur_ftrs_o)
            continue
        # Finding 3: a line about to start a FRESH page (whether the page
        # was just closed above, by the `cond` branch, or this is simply
        # the document's first line) picks up the .mt/.mb in force at ITS
        # OWN block -- recomputing `cap`/`budget` for THIS page only, so a
        # page whose geometry never changes never recomputes to a
        # different number (see `_printed_cap_for`'s docstring).
        if printed and not page and mt_mb_checkpoints and getattr(l, 'bi', None) is not None:
            cur_mt, cur_mb, cur_pl, cur_hm, cur_fm, cur_po, cur_poe, cur_poo = _recompute_geom(l.bi)
            cap = _printed_cap_for(doc, cur_mt, cur_mb, cur_pl)
            budget = (cap - 1) * default_lead
        overflow = (spent + _cost(l) > budget + 1e-6) if printed \
                  else len(page) >= cap
        # Finding 1 (round 26 visual pass): the FIRST `ws4_spacing`
        # blank (see `_ws4_spacing_blank_indices`) to overflow a page's
        # budget never triggers the break by itself -- a physical
        # blank-line paper advance right at the bottom margin doesn't
        # need a fresh sheet, and giving it its OWN page-break decision
        # was this finding's original bug (a page break landing mid
        # text/blank pair silently spent one line of the NEXT page's
        # budget on ink-free paper, growing a cumulative real-line
        # deficit every other page). ONLY a PageLine this document's own
        # `_ws4_spacing_blank_indices` positively classified gets this
        # exemption -- an ordinary blank (every non-WS4 document's
        # blanks, and a WS4 document's own authored ones, chapter-drops
        # included) still forces the break exactly as before this fix,
        # since `ws4_spacing` defaults False and nothing here changes
        # that default. `already_over` denies the exemption to a SECOND
        # consecutive over-budget spacing blank (a paragraph boundary's
        # own 2-3 blank run): forgiving every blank in a run over-admits
        # a whole extra real line one measured source's own WS7 capture
        # didn't have.
        already_over = printed and spent > budget + 1e-6
        full = overflow and not (printed and getattr(l, 'ws4_spacing', False)
                                 and not already_over)
        if l is None or full:
            if page or l is None:
                _close_page(); page, spent = [], 0.0
                page_hdrs, page_ftrs = dict(cur_hdrs), dict(cur_ftrs)
                page_hdrs_e, page_hdrs_o = dict(cur_hdrs_e), dict(cur_hdrs_o)
                page_ftrs_e, page_ftrs_o = dict(cur_ftrs_e), dict(cur_ftrs_o)
                # organic overflow (see `_recompute_geom`'s docstring,
                # path 2): `l` itself is the new page's first line and
                # never reaches the top-of-loop `not page` gate, since it
                # is already mid-iteration by the time `page` empties.
                if printed and full and mt_mb_checkpoints and getattr(l, 'bi', None) is not None:
                    cur_mt, cur_mb, cur_pl, cur_hm, cur_fm, cur_po, cur_poe, cur_poo = _recompute_geom(l.bi)
                    cap = _printed_cap_for(doc, cur_mt, cur_mb, cur_pl)
                    budget = (cap - 1) * default_lead
            if l is None:
                trailing_pagebreak = True
                continue
        trailing_pagebreak = False
        if (suppress_blanks and not page and not getattr(l, 'image', None)
                and not any(t.strip() for t, _ in l)):
            continue          # `.sb`: a blank line at the top of a page doesn't print
        if printed:
            spent += _cost(l)
        page.append(l)
    if page:
        _close_page()
    elif trailing_pagebreak and printed and doc.meta.get('pa_eof_blank_after'):
        # #228 (research/2026-09-08_trailing-pa-rule.md, planning #228):
        # "WS7 opens the page after a forced `.pa` break ONLY when at
        # least one more real content paragraph -- even an entirely
        # blank one -- follows that `.pa` before end-of-file." The
        # document's last thing was an explicit `.pa`, `page` is empty
        # by construction (reset when that pagebreak was processed
        # above, never touched since), and doc.meta['pa_eof_blank_after']
        # (computed once at parse time from the file's own saved-trailer
        # bytes -- core.py's `_trailing_pa_has_content_after`) confirms
        # this specific document really did save a blank paragraph after
        # that `.pa`, not just a bare unconditional pagebreak (the
        # overwhelming majority of `.pa`-terminated documents, which
        # open no extra page at all). Gated on `printed`: Modern never
        # reaches this function with printed=False in current usage
        # (Modern's own PDF is currently a wholly separate pipeline,
        # `_modern_streams`), but the gate is here in case a future
        # caller does -- "drop in Modern" per the ruling.
        _close_page(explicit=True, break_bi=last_pagebreak_bi)
    # We supply the paper margins, so WordStar's own margin blanks in a print
    # stream would double up. But deliberate spacing (a chapter-drop on page 1)
    # must survive: the MACHINE margin is uniform on every page, so strip only
    # the minimum leading-blank count seen on pages 2+ — anything beyond it on
    # any page is the author's layout. Trailing blanks are always machine.
    # Round 19 (PIX images RULED IN): an image PageLine has no text
    # segments (`[]`, by construction -- see the substitution above), so
    # the blank-line tests below must check `.image` FIRST or an embedded
    # picture sitting last in a short document (the real-corpus shape:
    # every acceptance document's own pix tag is its own final content)
    # reads as a trailing machine blank and gets silently popped off the
    # page it was just placed on.
    def _is_blank(l):
        return not getattr(l, 'image', None) and not any(t.strip() for t, _ in l)

    def leading(pg):
        n = 0
        while n < len(pg) and _is_blank(pg[n]):
            n += 1
        return n
    # ...but ONLY for a PRINT STREAM. Corrected 2026-08-03: this repair was
    # written for print-to-disk output, where WordStar physically emitted its
    # top margin as blank lines. A WS4/WS5+ DOCUMENT has no machine margin in
    # it at all -- `.mt` is a dot command and the emitter applies it as paper
    # margin -- so every leading blank in one is the author's. Running the
    # stripper on a document deleted an author's chapter drop outright, and on any
    # SINGLE-page document it deleted every leading blank, because the
    # `len(pages) > 1` fallback measures the only page against itself.
    if printed and pages and doc.meta.get('variant') == 'printstream':
        machine = min(leading(pg) for pg in pages[1:]) if len(pages) > 1 \
                  else leading(pages[0])
        for pg in pages:
            del pg[:min(machine, leading(pg))]
            while pg and _is_blank(pg[-1]):
                pg.pop()
    elif printed and pages:
        # A document: keep leading blanks (authorial), drop trailing (machine).
        for pg in pages:
            while pg and _is_blank(pg[-1]):
                pg.pop()
    else:
        for pg in pages:
            del pg[:leading(pg)]
            while pg and _is_blank(pg[-1]):
                pg.pop()
    # Trailing empty pages produce blank sheets. The pop must run AFTER the
    # blank-stripping above — stripping is what hollows out a final page that
    # held only blank lines (1.1.5 popped before stripping and missed it; found
    # by the Swift port, job-012). Interior blanks from .pa .pa are preserved.
    # #228: an empty page reached via the confirmed trailing-`.pa`-plus-
    # saved-blank-paragraph shape (`explicit_break`, set only by the
    # post-loop branch above) is real WS7 output -- its footer/page
    # number prints even with no body -- and is exempt from this pop.
    while len(pages) > 1 and not pages[-1] and not pages[-1].explicit_break:
        pages.pop()
    if printed:
        pages = _apply_columns(doc, pages, size_for_left)
        _attach_justify_word_x_printed(doc, pages, size_for_left)
        _attach_line_numbers_printed(doc, pages, size_for_left)
        _attach_graphic_cells_printed(doc, pages, size_for_left)
        _attach_head_foot_lines_printed(doc, pages, size_for_left)
    return pages or [[]]


def _attach_line_numbers_printed(doc, pages, size):
    """planning #251(d): sets `PageLine.line_no = (label, x_pt)` on every
    line an active `.l#` interval numbers -- moved from `_page_stream`'s
    own render-time `line_no_state` counter, replicated here in the exact
    same shape (`_page_stream` is invoked once per PAGE, so the interval/
    counter pair starts fresh at every page's own first line -- planning
    #247's own oracle, sawyer/PRINT.TST: `.l#2` activates on a page's own
    first body line, `.l# 0` deactivates on its last). A document that
    never declares `.l#` (`line_numbering_checkpoints` stays at its
    `(0, None)` seed) walks every line and sets nothing -- no behaviour
    change, just an O(lines) no-op pass."""
    checkpoints = _line_numbering_checkpoints(doc)
    _, gutter_family, gutter_size, _ = _span_render('', (), doc.fonts, size)
    for page in pages:
        line_no_state = [None, 0]
        for line in page:
            line_bi = getattr(line, 'bi', None)
            interval = (_line_numbering_at(checkpoints, line_bi)
                       if line_bi is not None else None)
            if interval != line_no_state[0]:
                line_no_state[0] = interval
                line_no_state[1] = 0
            k = line_no_state[1]
            line_no_state[1] += 1
            if interval and k % interval == 0:
                label = str(k // interval + 1)
                gx = LINE_NO_RIGHT_PT - len(label) * gutter_size * 0.6
                line.line_no = (label, gx)


def _attach_justify_word_x_printed(doc, pages, size):
    """planning #251(b): sets `PageLine.justify_word_x` (see that field's
    own comment) on every justified line that resolves, through the SAME
    preprocessing pipeline `_line_ops_printed` itself runs (bare-tab
    expansion; `_lj_substitute`; `_split_graphics`; `_split_symbol_
    fallback`; `_split_indent`), to exactly one FIXED-PITCH, untagged
    span with real slack to distribute. Anything outside that -- a
    styled/mixed line, a proportional span, a `pctl`/`tabhmi`-tagged span
    (the writer's own preamble branches off those BEFORE reaching
    ordinary per-character placement, so this function's own arithmetic
    does not apply), or a line with no elastic gap or no slack -- leaves
    `justify_word_x` unset; `_line_ops_printed` then computes it fresh at
    render time, byte-identical to before this function existed."""
    fonts = doc.fonts
    left = _printed_left(doc, size)
    roll_pt = _printed_roll_pt(doc)
    colour_map = (_COLOUR_GRAY_LJ6DTP
                 if doc.meta.get('printer_driver') == 'LJ6DTP' else {})
    for page in pages:
        for line in page:
            if getattr(line, 'justify_right_x', None) is None:
                continue
            segs = []
            for text, styles in _coalesce(line):
                if not text:
                    continue
                written, family, size_here, entry = _span_render(
                    text, styles, fonts, size)
                segs.append((written, styles, family, size_here, entry))
            segs = _expand_bare_tabs_for_printed_layout(segs)
            if colour_map:
                segs = _lj_substitute(segs, getattr(line, 'kerning', True))
            segs = _split_indent(_split_symbol_fallback(_split_graphics(segs)))
            if len(segs) != 1:
                continue
            text, styles, family, size_here, entry, seg_indent = segs[0]
            if any(t.startswith('pctl') or t.startswith('tabhmi')
                  for t in styles):
                continue
            if entry is not None and entry.get('proportional'):
                continue           # rule 4: fixed-pitch spans only
            own_left = getattr(line, 'left', None)
            left_here = left if own_left is None else own_left
            fi = getattr(line, 'fi', None)
            if fi and seg_indent:
                fi = None
            x0 = left_here + (fi or 0)
            pt, rise = _sized(styles, size_here, roll_pt, family)
            basefont = BASE14[family][('b' in styles) + 2 * ('i' in styles)]
            pitch = (_sup_sub_span_pitch(entry, styles, family, size_here)
                    or _span_pitch(entry, pt))
            pieces = _justify_pieces_printed(text, pitch, x0,
                                             line.justify_right_x, basefont, pt)
            if pieces:
                line.justify_word_x = pieces


def _attach_graphic_cells_printed(doc, pages, size):
    """planning #251(c): sets `PageLine.graphic_cells` (see that field's
    own comment) on every line carrying a cp437 graphic character, via a
    real -- but THROWAWAY-STATE (fresh `FontRes`/`tz_state`/`col_state`,
    a dummy `y`) -- call to `_line_ops_printed` itself, using its own new
    `record_graphic_cells` parameter. None of the throwaway state can
    change a graphic cell's own x/width: `_graphic_ops`'s advance is
    `pitch` alone (font-metric-driven Tz scaling, the fill colour state,
    and the actual `y` never enter that arithmetic -- see `_line_ops_
    printed`'s own graphics branch), so this is not a parallel
    re-derivation, it is the SAME function computing the SAME values,
    just once, ahead of the real render pass. The ops themselves are
    discarded; only the recorded `(char, x_pt, width_pt)` list survives.

    Skips a line outright when its RAW (pre-substitution) text has no
    character in `GRAPHIC_CHARS` at all -- `_lj_substitute`'s own tables
    (`_LJ_SUBST`/`_LJ_SUBST_UNIVERS`) never turn a NON-graphic character
    into a graphic one (only graphic-to-non-graphic, ☻/☼, or graphic-to-
    graphic, ♥♦♣♠ to the matching arc corner), so this is a safe
    necessary-condition filter, not an approximation -- it just spares
    the overwhelming majority of ordinary prose lines a throwaway render
    call."""
    fonts = doc.fonts
    left = _printed_left(doc, size)
    roll_pt = _printed_roll_pt(doc)
    ul_continuous = bool(doc.meta.get('formatting', {}).get('underline_blanks', True))
    colour_map = (_COLOUR_GRAY_LJ6DTP
                 if doc.meta.get('printer_driver') == 'LJ6DTP' else {})
    pcl_programs = doc.pcl_programs
    page_h = _resolved_page_height(doc, True)
    for page in pages:
        for line in page:
            if not any(set(text) & GRAPHIC_CHARS for text, _ in line):
                continue
            segs = []
            for text, styles in _coalesce(line):
                if not text:
                    continue
                written, family, size_here, entry = _span_render(
                    text, styles, fonts, size)
                segs.append((written, styles, family, size_here, entry))
            own_left = getattr(line, 'left', None)
            left_here = left if own_left is None else own_left
            own_roll = getattr(line, 'roll', None)
            roll_here = roll_pt if own_roll is None else own_roll
            record = []
            _line_ops_printed(
                segs, left_here, 0.0, size, FontRes(), [TZ_DEFAULT],
                [('g', 0.0), False], colour_map or {}, roll_here,
                getattr(line, 'fi', None), ul_continuous, pcl_programs, page_h,
                getattr(line, 'kerning', True),
                getattr(line, 'justify_right_x', None),
                getattr(line, 'justify_word_x', None),
                record_graphic_cells=record)
            if record:
                line.graphic_cells = record


def attach_graphic_cells_modern(doc, notes, note_refs):
    """planning #251 follow-up (2026-09-10, app coder job 348): every
    `sem['items']` index (`_layout.modern_flow(doc, notes=notes,
    note_refs=note_refs)`'s own item list -- the SAME call `emit_layout`'s
    `modern['items']` serializes) with at least one drawn cp437 graphic-
    character cell, mapped to that paragraph's own cells `(char, x_pt,
    width_pt, page)`, document order across however many wrapped visual
    lines/pages the paragraph's own non-wrapping graphic run lands on --
    via a real (throwaway-resources) call to `_modern_streams` itself,
    using its own `attach_graphic_cells` recording parameter, so the
    values are exactly what Modern PDF draws (`_graphic_ops`), never a
    parallel re-derivation. Mirrors `_attach_graphic_cells_printed`'s own
    precedent for Printed. Port of Swift's `attachGraphicCellsModern`.

    Skipped outright (returns `{}`) when NO block anywhere in the
    document carries a graphic character at all -- the same necessary-
    condition short-circuit `_attach_graphic_cells_printed` applies per
    LINE, applied once here per DOCUMENT (the only granularity available
    before `_modern_streams`' own pagination has run), sparing the
    overwhelming majority of documents a full throwaway Modern-PDF
    pagination pass.

    `notes`/`note_refs` come from the caller and must be the SAME values
    passed to `_layout.modern_flow` at the `emit_layout` call site, so a
    cell's own item index always lines up with the `sem['items']` that
    produced it; every other option (pix_results/pictures/sentence_
    spacing) is the library default `_modern_streams` itself uses when
    `options` carries none of them, matching `_layout.modern_flow`'s own
    "document's own unconverted text" convention (`_modern_flow`'s own
    `sentence_spacing` docstring) -- a pix-substituted paragraph never
    carries a graphic character in the first place (its runs are "exactly
    one resolved, decoded pix placeholder"), so `pictures='off'` here
    changes nothing this function could ever attach to."""
    has_graphic_content = any(
        set(span.text) & GRAPHIC_CHARS
        for block in doc.blocks for line in block.lines for span in line.spans)
    if not has_graphic_content:
        return {}
    cells = {}
    _modern_streams(doc, {'notes': notes, 'note_refs': note_refs},
                    FontRes(), attach_graphic_cells=cells)
    return cells


def _attach_head_foot_lines_printed(doc, pages, size):
    """planning #251(d): sets `Page.header_lines`/`footer_lines`/`auto_
    pageno` -- the running head/foot's own resolved (text, x, y, font)
    entries, one per declared `.h#`/`.f#` slot in force on this page --
    moved from `_running_ops`'s own render-time-only computation (called
    fresh, once per page, by `_emit_pdf_inner`'s per-page loop) onto the
    page-lines model, via the SAME `_resolve_head_foot_lines` function
    (no parallel re-derivation: this and `_running_ops` both call it,
    each simply doing something different with its answer -- rendering
    vs recording, exactly `_attach_graphic_cells_printed`'s own
    precedent above).

    Resolves under the document's own NATURAL state -- `auto_page_number`
    from `_pgnum_checkpoints` (the `.pn`/`.pg`/`.op` state the file
    itself carries) and every declared header/footer -- the same "model
    states it unconditionally, a flag only tells the WRITER whether to
    draw it" convention `headers`/`footers`/`line_no` already use: a
    caller that renders with `--headers off` or an explicit `--page-
    numbers on/off` override still gets a PDF from `_running_ops`'s own
    fresh, independent call (this function's answer is for the model/
    JSON export only, never substituted into the render path) -- so
    those flags stay exactly as free to override the writer's own output
    as they always were.

    Replicates `_emit_pdf_inner`'s own per-page geometry swap (`.mt`/
    `.mb`/`.pl`/`.hm`/`.fm`/`.po` overrides, `page_geom_changed`/
    `po_parity`-gated `running_left`) and its `page_numbers_mode ==
    'auto'` branch (the `.bi`-keyed `_pgnum_at` lookup, with the #228
    trailing-`.pa` `explicit_break_bi` fallback for a page with no lines
    of its own) verbatim -- see that loop's own dense per-line comments
    for WHY each piece exists; this is the identical arithmetic, run
    once here instead of once per real render."""
    from .core import DEFAULT_HM_LINES as _DEF_HM
    if not pages:
        return
    lead = _printed_lead(doc)
    left = _printed_left(doc, size)
    page_h = _resolved_page_height(doc, True)
    pgnum_checkpoints = _pgnum_checkpoints(doc)
    page_numbers = _resolve_page_numbers(_pn_checkpoints(doc), pages)
    for page_index, pg in enumerate(pages):
        page_mt = getattr(pg, 'mt_lines', None)
        page_mb = getattr(pg, 'mb_lines', None)
        page_pl = getattr(pg, 'pl_lines', None)
        page_hm = getattr(pg, 'hm_lines', None)
        page_fm = getattr(pg, 'fm_lines', None)
        page_po = getattr(pg, 'po_cols', None)
        page_geom_changed = (page_mt is not None or page_mb is not None
                             or page_hm is not None or page_fm is not None)
        page_po_parity = getattr(pg, 'po_parity', False)
        running_left = (_resolve_left_pt(page_po, size)
                        if page_po is not None
                            and (page_geom_changed or page_po_parity)
                        else left)
        saved_pg = None
        if (page_mt is not None or page_mb is not None or page_pl is not None
                or page_hm is not None or page_fm is not None):
            eff = dict(doc.meta['page'])
            if page_mt is not None:
                eff['mt_lines'], eff['mt_source'] = page_mt, 'file'
            if page_mb is not None:
                eff['mb_lines'], eff['mb_source'] = page_mb, 'file'
            if page_pl is not None:
                eff['pl_lines'] = page_pl
            if page_hm is not None:
                eff['hm_lines'] = page_hm
                eff['hm_source'] = 'file' if page_hm != _DEF_HM else 'default'
            if page_fm is not None:
                eff['fm_lines'], eff['fm_source'] = page_fm, 'file'
            saved_pg, doc.meta['page'] = doc.meta['page'], eff
        bis = [bi for bi in (getattr(ln, 'bi', None) for ln in pg) if bi is not None]
        if bis:
            auto_page_number = _pgnum_at(pgnum_checkpoints, max(bis))
        else:
            fallback_bi = getattr(pg, 'explicit_break_bi', None)
            auto_page_number = (_pgnum_at(pgnum_checkpoints, fallback_bi)
                                if fallback_bi is not None else False)
        resolved = _resolve_head_foot_lines(
            doc, page_numbers[page_index], page_h, lead, size, running_left,
            True, headers=getattr(pg, 'headers', None),
            footers=getattr(pg, 'footers', None),
            auto_page_number=auto_page_number,
            head_hf_override=getattr(pg, 'head_hf_override', None),
            foot_hf_override=getattr(pg, 'foot_hf_override', None))
        if saved_pg is not None:
            doc.meta['page'] = saved_pg
        if resolved is None:
            continue
        if not isinstance(pg, Page):
            # planning #251 part d fix (found by the app coder, job 348
            # follow-up: sawyer/-SCREEN.WS page 1, the app's own
            # BOTHNOTE.WS page 1): `_paginate_printed_notes`'s own
            # footnote-area pages are sometimes plain lists, not `Page`
            # instances (see `_apply_columns`'s own `merged.headers`
            # comment) -- an attribute ASSIGNMENT (unlike every other
            # consumer's read-only `getattr(pl, ..., None)`) raises on a
            # bare list. This USED TO `continue` here, leaving the
            # model's own copy unresolved for every such page even
            # though `_running_ops` (the writer) draws their header/
            # footer/auto-page-number correctly from this SAME `resolved`
            # answer, via its own `getattr(pl, 'headers', None)` fallback
            # a few lines above -- two sources of truth that could (and
            # did) disagree: the writer put "1" at 291.6/732.0 on
            # -SCREEN.WS page 1 while the model said `None`.
            #
            # Promoting the bare list to a real `Page` here instead
            # closes the gap -- `headers`/`footers` set explicitly to
            # `None` (not `Page.__init__`'s own `{}` default, which would
            # instead SUPPRESS the doc-global running-head fallback these
            # pages have always relied on; every other `Page.__init__`
            # field default already matches what `getattr(bare_list,
            # attr, None)` returned, so nothing else about this page's
            # resolved behaviour changes). `pages[page_index]` is
            # reassigned so `_emit_pdf_inner`'s own render loop -- which
            # reads this SAME `pages` list a few lines later -- keeps
            # seeing byte-identical `getattr(pl, 'headers', None)`
            # answers; PDF bytes do not move.
            pg = Page(pg)
            pg.headers = None
            pg.footers = None
            pages[page_index] = pg
        if resolved['headers']:
            pg.header_lines = [{'text': text, 'x': running_left, 'y': y, 'font': font_idx}
                               for _n, text, y, font_idx in resolved['headers']]
        if resolved['footers']:
            pg.footer_lines = [{'text': text, 'x': running_left, 'y': y, 'font': font_idx}
                               for _n, text, y, font_idx in resolved['footers']]
        if resolved['auto'] is not None:
            text, x, y = resolved['auto']
            pg.auto_pageno = {'text': text, 'x': x, 'y': y}


def _toc_page_numbers(doc, pix_results=None, pictures='off'):
    """{block_index: page_number} -- the REAL paginator's own answer for
    which page each block's FIRST printed line landed on (round 18,
    RULINGS-LEDGER row 4). `start_no` matches whatever page number
    actually prints in the corner (`_emit_pdf_inner`'s own convention). A
    `.tc`/`.ix` entry whose own block never reached a printed page (a
    stray or malformed dot line, or an empty block) simply gets no entry
    here -- `compile_toc`/`compile_index` (core.py) treat a missing key
    as "no page number available", not a crash. Re-runs the SAME
    `_doc_to_pagelines` pass emit_pdf's own printed branch uses -- one
    extra pagination pass, paid once per TOC/Index-enabled conversion,
    not per entry.

    `pix_results`/`pictures` (round 19): threaded through so an embedded
    picture's own vertical footprint shifts these page numbers exactly
    the way it shifts the real render -- without this, TOC page numbers
    could disagree with where the real PDF put things.

    Per-page numbers come from `_resolve_page_numbers`/`_pn_checkpoints`
    (register b31-dot-command-sweep) rather than a flat `start_no +
    page_index` -- a document whose `.pn` re-anchors mid-document would
    otherwise give a TOC entry the WRONG page number past that point."""
    pages = _doc_to_pagelines(doc, True, pix_results=pix_results, pictures=pictures)
    page_numbers = _resolve_page_numbers(_pn_checkpoints(doc), pages)
    resolved = {}
    for page_index, pg in enumerate(pages):
        for ln in pg:
            bi = getattr(ln, 'bi', None)
            if bi is not None and bi not in resolved:
                resolved[bi] = page_numbers[page_index]
    return resolved


def _toc_index_pagelines(doc, page_numbers):
    """Plain PageLines for the compiled TOC/Index section -- TOC before
    Index (round 18, RULINGS-LEDGER row 4), each clearly headed, a TOC
    entry indented two columns per level (`.tc`/`.tc1`-`.tc9`, WSFORMAT's
    own outline levels). A page-number column is right-justified onto the
    print measure when the resolved page number is not already inline
    (an entry with no literal `#` got its number appended by
    `core.compile_toc`/`compile_index`, plain text -- no special alignment
    beyond what's already there; this keeps the simple case simple)."""
    from .core import compile_toc, compile_index
    lines = []
    toc = compile_toc(doc, page_numbers)
    if toc:
        lines.append(PageLine([('TABLE OF CONTENTS', frozenset({'b'}))]))
        lines.append(PageLine([]))
        for level, text in toc:
            lines.append(PageLine([('  ' * max(0, level - 1) + text, frozenset())]))
        lines.append(PageLine([]))
    idx = compile_index(doc, page_numbers)
    if idx:
        lines.append(PageLine([('INDEX', frozenset({'b'}))]))
        lines.append(PageLine([]))
        for text in idx:
            lines.append(PageLine([(text, frozenset())]))
    return lines


def _coalesce(line):
    """Merge adjacent same-style segments into single text runs."""
    out = []
    for text, styles in line:
        if out and out[-1][1] == styles:
            out[-1][0] += text
        else:
            out.append([text, styles])
    return out

def _resolve_head_foot_lines(doc, page_no, page_h, lead, size, left, printed,
                             headers=None, footers=None, auto_page_number=False,
                             head_hf_override=None, foot_hf_override=None):
    """The running head/foot's own GEOMETRY and TEXT resolution -- WHERE
    (each line's `y`; `x` is simply the caller's already-resolved `left`,
    since -- unlike `y` -- no header/footer line's own starting x has ever
    depended on `page_no`, only on the page's own `.po`/`.poe`/`.poo`
    state, which `_emit_pdf_inner`'s own per-page `running_left` already
    resolves and threads straight through as this function's `left`
    parameter) and WHAT TEXT (the `#` page-number substitution, and --
    fontless/Courier lines with their own right-align tab only -- the
    print-time-baked realignment spacing WS7 re-evaluates against THIS
    page's own actual page-number width).

    Planning #251(d), 2026-09-10: this is the MODEL half of what used to
    be one function, `_running_ops`. `_running_ops` (the PDF writer) now
    calls this and turns its resolved (text, y, font_idx) lines into
    content-stream ops; `_attach_head_foot_lines_printed` (the page-lines
    model, `_doc_to_pagelines`'s own post-pagination pass, below) calls
    the SAME function to put page-level `Page.header_lines`/`footer_
    lines`/`auto_pageno` on the model the app reads -- planning #251's
    own running thread: "every per-word x the writer computes ... lives
    on the page-lines model, the writer renders from it." Neither caller
    duplicates this arithmetic; both call this one function.

    Geometry MEASURED on WordStar 4 (2026-08-03), not inferred:
        line 0                      header line 1
        ...                         header lines 2-5, if used
        .hm blank lines
        body
        .fm blank lines
        line pl-.mb+.fm             footer line 1
    so the header sits at the very top of the paper and the footer `.fm` lines
    below the body's last line. `#` becomes the page number -- WordStar's own
    token, seen rendering as "PAGE 1 / PAGE 2 / PAGE 3" in the probe.

    `.op` ("omit page number ... unless the # has been used in footers or
    headers") suppresses the substitution, leaving the literal token out.

    `auto_page_number` (E3 item 2, register b31, 2026-08-25): the caller's
    ALREADY-RESOLVED answer to "does WordStar's own AUTOMATIC page number
    (the one `.pc` positions -- a completely separate mechanism from a `#`
    the author placed inside a real `.he`/`.fo`) show on THIS page" --
    combining `--page-numbers auto/on/off` and, for `auto`, the per-page
    `_pgnum_checkpoints` state. This function itself only resolves WHERE
    (from `.po`/`.pc` via `_auto_pageno_x_pt`) and WHETHER a real footer
    pre-empts it (WSFORMAT.WS: "active only when the footers are not in
    use") -- never the on/off DECISION itself, which needs page-level
    context (the checkpoint state, the CLI flag) this function does not
    have. A caller that never passes it (every existing `_running_ops`
    call site but the one main per-page loop wires it into; `_attach_
    head_foot_lines_printed` below always resolves the document's own
    NATURAL 'auto' answer, the same "model states it unconditionally, a
    flag only tells the WRITER whether to draw it" convention `headers`/
    `footers` themselves already use) gets `False`, byte-identical to
    before this parameter existed -- TOC/Index pages included, which pass
    `headers={}`/`footers={}` explicitly and must not suddenly grow a
    number they never had.

    Returns None for "nothing to place here" (the caller distinguishes
    this from an empty-but-real result by testing for None, not falsy --
    there is no ops list of its own to be empty). Otherwise `{'headers':
    [(n, text, y, font_idx), ...], 'footers': [(n, text, y, font_idx),
    ...], 'auto': (text, x, y) or None}`, ascending `n`, only slots
    carrying real (truthy) text. `text` is FULLY resolved (`#`
    substituted; fontless lines with their own right-align tab also get
    the baked realignment spaces) but keeps WordStar's own inline style
    TOGGLE BYTES intact -- a consumer still runs it through `hf_runs` for
    STYLING/per-run advance, exactly as the raw `headers`/`footers` dict
    already requires (this function resolves WHERE and WHAT TEXT, never
    how to draw it). `font_idx` is the same `doc.fonts` index `doc.
    header_fonts`/`footer_fonts` already carry, or None for the
    fontless/Courier default."""
    # Planning #250: a document with NO real body blocks at all (GALLEYS.
    # DOT/ADVANCE.DOT -- pseudogalley templates, `doc.blocks` is empty)
    # never builds a real per-page `Page` (`_close_page`, the ordinary
    # per-page parity resolver, never runs -- nothing ever calls it) --
    # `_doc_to_pagelines` falls back to a single bare `[]` "page," and
    # every caller here passes `headers=None`/`footers=None` for it
    # (`getattr(bare_list, 'headers', None)`, unlike a real `Page`, whose
    # `.headers` is ALWAYS a dict, `_close_page`'s own or the class
    # default `{}` -- see `Page.__init__`). `headers_flat`/`footers_flat`
    # (the caller's OWN args, before the `doc.headers` fallback just
    # below) distinguish that real "no per-page answer exists" case from
    # an ordinary page whose own resolved dict simply happens to be
    # falsy/empty (TOC pages pass `headers={}` explicitly, never None) --
    # only the former needs this page-number-parity fallback; a real
    # page's own already-`_close_page`-resolved dict is authoritative and
    # must never be second-guessed here.
    headers_flat, footers_flat = headers is None, footers is None
    headers = doc.headers if headers is None else headers
    footers = doc.footers if footers is None else footers
    if headers_flat and head_hf_override is None and doc.headers_parity.get(1):
        letter = 'E' if page_no % 2 == 0 else 'O'
        pv = doc.headers_parity[1]
        if letter in pv:
            headers = dict(headers)
            headers[1] = pv[letter]
            head_hf_override = {1: (doc.header_fonts_parity.get(1, {}).get(letter),
                                    doc.header_tabs_parity.get(1, {}).get(letter))}
    if footers_flat and foot_hf_override is None and doc.footers_parity.get(1):
        letter = 'E' if page_no % 2 == 0 else 'O'
        pv = doc.footers_parity[1]
        if letter in pv:
            footers = dict(footers)
            footers[1] = pv[letter]
            foot_hf_override = {1: (doc.footer_fonts_parity.get(1, {}).get(letter),
                                    doc.footer_tabs_parity.get(1, {}).get(letter))}
    footer_in_use = bool(footers) and any(footers.values())
    show_auto_num = printed and auto_page_number and not footer_in_use
    if not (headers or footers or show_auto_num) or not printed:
        return None
    page = doc.meta.get('page') or {}
    # `.op` does NOT suppress a `#` in a header or footer. MEASURED on WordStar 4
    # (2026-08-03): a document carrying `.op` and `.fo Page #` printed "Page 1" on
    # page 1 and "Page 2" on page 2. WSFORMAT.TXT says the same -- ".OP  Omit page number.  At print time no page numbers are
    # printed UNLESS THE '#' HAS BEEN USED IN FOOTERS OR HEADERS." It suppresses
    # the AUTOMATIC page number, the one `.pc` positions; a `#` the author put in
    # a running head is the exemption, not the target.
    #
    # This was implemented backwards: `.op` blanked the `#`, so a document that
    # turned off the automatic number ALSO lost the page number it had explicitly
    # asked for. The spec sentence was quoted in this very docstring while the code
    # did the opposite of it. `.pg` (which restores numbering after `.op`) was not
    # handled at all, so the state was one-way as well.
    pl = int(page.get('pl_lines', 66))
    mb = int(page.get('mb_lines', 8))
    fm = int(page.get('fm_lines', 2))

    def render(txt):
        return txt.replace('#', str(page_no))

    def _resolve_line_text(txt, font_idx, tab_rec):
        """The final substituted (and, for a fontless line with its own
        right-align tab, realignment-baked) text for one header/footer
        LINE -- the TEXT half of what used to be `_hf_line_ops`'s own
        `tab_rec` branch, moved here (planning #251(d)) so it runs once
        per PAGE at model-build time instead of once per PDF RENDER --
        same formula, same result; `_running_ops` never recomputes it,
        it calls `_resolve_head_foot_lines` (this function's own
        caller) exactly like every other consumer.

        `tab_rec` (planning #202, -README's own running head) is this
        line's own `doc.header_tabs`/`footer_tabs` entry: `(char_idx,
        cols, abs_hmi)`, or None. A right/center/decimal-align tab typed
        into a `.h#`/`.f#` argument gets its own `cols` spaces BAKED
        into the text at parse time (`_symmetric_blocks`/`_tab_columns`,
        same as a body span's) -- sized for whatever the eventual `#`
        substitution was assumed to be wide when the file was LAST SAVED
        (always 1 column: WordStar's own screen shows the literal '#'
        token, never the eventual printed number). Real WS7 re-evaluates
        the tab at PRINT TIME against THAT page's own actual page-number
        width instead (measured, -README.WS pages 9->10: WS7's own
        "WordStar" moves 7.2pt LEFT the instant the page number grows a
        second digit, while the number's own right edge -- the tab's
        real target column -- never moves).

        `abs_hmi` (content[2:4], "absolute tab size in HMIs" -- the SAME
        field a body span's own tab mark carries) is WHERE THE BAKED
        PADDING ITSELF ENDS, measured from the document's own left
        reference -- i.e. it already encodes `target_col - saved_suffix_
        width`, using the file's OWN (1-digit-'#') suffix width at save
        time. Reversing that (`+ the STORED suffix's own un-substituted
        width, un-styled control bytes stripped`) recovers `target_col`
        without ever hardcoding a right margin. Re-deriving `target_col`
        this way, then subtracting THIS page's own ACTUAL (post-`#`-
        substitution) suffix width, reproduces both of -README's real
        WS7 x positions exactly (352.8pt pages 2-9, one digit; 345.6pt
        pages 10-16, two digits) -- see `tests/test_ctrlkd.py`'s own
        synthetic case for the same arithmetic against a made-up
        right-tab and page number.

        UPDATE (mechanism W follow-up trace, PCL-DIVERGENCE-TRIAGE.md,
        planning task, 2026-09-07): this formula used to subtract an
        EXTRA constant 1 from `saved_target_col` -- "content[2:4] cols
        41 + stored suffix width 24 = 65, but the real print-time target
        measures 64" -- fit against `ws7-prints/v1`/`v2`'s own numbers
        for the 2-digit-page case ONLY, while `-README`'s header row was
        STILL 24pt too low (mechanism W's own bug, not fixed until this
        same round), which masked every header word's own horizontal
        residual behind its much larger vertical one -- the `-1` was
        never actually checked against a page where the header's Y
        position was already correct. Once mechanism W's own fix landed
        first, `-README`'s `ws7-prints/v3` PRISTINE.EXE capture showed
        BOTH digit-width buckets uniformly 7.2pt (one column) LEFT of
        this formula's own output -- the extra `-1` bias, not a real
        WS7 rule (WS7's own suffix-final print column is INCLUSIVE of
        the tab's own SIZE-convention target column, not exclusive as
        the reverted comment claimed). Removed: `saved_target_col` is
        simply `round(abs_hmi / _TAB_HMI_PER_COL) + len(stripped_suffix)`
        now, and both digit-width buckets land exactly on the pristine
        measurements above with zero residual.

        Fixed-pitch (`entry is None`, Courier) only: a proportional header
        face has no single column width to divide the HMI target by, and no
        oracle in the corpus combines the two, so that case is left at the
        baked `cols` -- unchanged, same as before this existed."""
        entry = (doc.fonts[font_idx]
                if font_idx is not None and 0 <= font_idx < len(doc.fonts)
                else None)
        if entry is None and tab_rec is not None:
            char_idx, cols, abs_hmi = tab_rec
            if 0 <= char_idx and char_idx + cols <= len(txt):
                suffix = txt[char_idx + cols:]
                stripped_suffix = ''.join(c for c in suffix if ord(c) >= 0x20)
                saved_target_col = round(abs_hmi / _TAB_HMI_PER_COL) + len(stripped_suffix)
                new_cols = max(0, saved_target_col - len(render(stripped_suffix)))
                txt = txt[:char_idx] + (' ' * new_cols) + suffix
        return render(txt)

    # The header block is anchored to the BODY, not the paper edge: its last
    # line sits `.hm` lines above the first body line, inside `.mt` (".MT ...
    # The header is printed within this margin"; ".HM ... the distance between
    # the header and the text"). At WordStar's defaults (.mt 3, .hm 2, one
    # header line) that IS paper line 0 -- which is why rendering headers at
    # the literal top of the sheet looked right for years -- but a document
    # that widens .mt (LJ6DTP's .mt 1.1") moves its header DOWN with the
    # body, where a laser printer can physically print it (Jon's finding,
    # 2026-08-05: no printer lays ink at y = 0).
    #
    # b26-header-round2 / register b31-dot-command-sweep / mechanism W
    # (PCL-DIVERGENCE-TRIAGE.md, planning task, 2026-09-06/07 -- SUPERSEDES
    # both rounds below): every measurement that ever justified GATING hm's
    # participation on mt_source/hm_source (-README, SCRIPT, LJ6DTP,
    # HMFM_PROBE -- all five of b26-header-round2's own oracles, plus
    # HMFM_PROBE which b31 added) was captured through Robert J. Sawyer's
    # own WSCHANGE-customized `WS.EXE` (`ws7-prints/v1`/`v2`, or an
    # equivalent dosbox-x probe against the SAME install) -- the identical
    # install mechanisms S (`.po` factory default) and T (auto-leading
    # factor) already found personalizes settings that had been mistaken
    # for WordStar 7's stock behaviour. `-README` is the corpus's ONLY
    # header-bearing document with mt_source/hm_source BOTH 'default', and
    # a `PRISTINE.EXE` (factory, no WSCHANGE) recapture of it
    # (`ws7-prints/v3`) measures its header at 12.0pt (head_base 0 = mt(3)
    # - hm(2) - top_head(1), hm FULLY SUBTRACTED) -- not 35.7pt/head_base 2
    # (hm zeroed), what every gated formula below predicts for this exact
    # combination. hm participating UNCONDITIONALLY, with no gate on either
    # source at all, is what stock WordStar 7 actually does -- and it was
    # already the engine's own understanding once, before b26-header-round2
    # (see the 2026-08-12 stock-header finding this triage's own memory
    # cites: ".mt3/.hm2 puts the header baseline at line 1, gap exactly 3
    # lines" -- head_base 0, hm fully subtracted, for the exact same
    # all-default case PRISTINE.EXE has now reconfirmed directly).
    #
    # This does NOT reopen SCRIPT/LJ6DTP: both are mt_source == 'file' (or,
    # for LJ6DTP's second page, the per-page swap's own local 'file' value)
    # on every oracle page below, so EVERY gate this history ever tried
    # (mt_source-only, hm_source-only, the b31 OR) already had hm
    # participating there -- dropping the gate changes nothing for a
    # document that ever states mt or hm itself; it only changes the
    # all-default case, which until -README's own `ws7-prints/v3` capture
    # had never been checked against a non-Sawyer install at all. SCRIPT's
    # own PRISTINE.EXE recapture (also `ws7-prints/v3`, `pytest -m pcl`)
    # confirms zero regression: still clean, all four of its own
    # mt/hm-explicit header rows below included.
    #
    # Superseded history, kept for the numbers (still real WS7
    # measurements, just from the WSCHANGE'd install, and every one of them
    # STILL fits "hm participates unconditionally" -- none of these five
    # ever exercised the all-default case that turned out to need
    # correcting):
    #   b26-header-round2: hm's participation is keyed on mt_source, not
    #     hm_source (LJ6DTP.WS broke the OLDER "hm_source == 'file'" rule
    #     on Jon's paper review -- LJ6DTP is mt EXPLICIT but hm at its own
    #     default, separating the two hypotheses). Four measured WS7
    #     header baselines (WS7 frame, the usual -0.3pt decipoint
    #     residual), fitting hm-participates-unconditionally exactly as
    #     well as the mt_source gate they were built to justify:
    #       SCRIPT normal (.MT 7 EXPLICIT, .HM 3 explicit): WS7 48.0 ==
    #         head_base 3 = mt(7) - hm(3) - top_head(1).
    #       SCRIPT figure-1 (.mt1 mid-doc EXPLICIT, .HM 3 carries): WS7
    #         12.0 == head_base max(0, 1-3-1) = 0.
    #       SCRIPT figure-2 (.mt1" mid-doc EXPLICIT, .HM 3 carries): WS7
    #         36.0 == head_base 2 = mt(6) - hm(3) - top_head(1).
    #       LJ6DTP (.mt 1.1" EXPLICIT globally, its own mid-document
    #         .mt1"/.mb1" -- b26-mtmb-general's per-page swap sets THIS
    #         page's mt_lines/mt_source to the LOCAL 6.0/'file', the SAME
    #         value _printed_top already renders the (correct, unchanged)
    #         86.0pt body baseline from; .hm never touches at all, stays
    #         2/'default'): WS7 48.0 == head_base 3 = mt(6.0) - hm(2) -
    #         top_head(1).
    #   register b31-dot-command-sweep: HMFM_PROBE (dosbox-x, Sawyer's own
    #     WS.EXE) held `.mt` at its factory default for the WHOLE document
    #     and still measured the header move to a different PCL row --
    #     35.7pt before a mid-document `.hm 6`, 12.0pt after it. Read as
    #     "hm participates unconditionally" rather than "hm participates
    #     because hm_source == 'file' on the pages that moved": the SAME
    #     35.7/12.0 numbers fall out (head_base max(0,3-2-1)=2 before,
    #     max(0,3-6-1)=0 after) with no gate at all -- b31's own OR-widening
    #     was one gate-shaped explanation of this data, not the only one,
    #     and the all-default half of it (35.7, head_base 2) is now known
    #     (mechanism W, above) to be the Sawyer-install artifact, not the
    #     real stock reading for that combination.
    #
    # `.mt`/`.hm` are LINE-COUNT dot commands in WordStar's own file
    #     format, always at the FIXED 6 LPI (12pt) baseline (core.py's
    #     `_resolve_lines_arg`: "Unit-less .mt/.mb are lines at the fixed
    #     6 LPI baseline") -- a SEPARATE unit from `.lh`, the document's
    #     own (possibly customized) BODY TEXT leading. This function's
    #     head_base-to-points conversion used the caller's `lead`
    #     parameter (the document's `.lh`-derived body lead) instead of
    #     that fixed 12pt/line unit -- invisible on every prior oracle
    #     (-README, SCRIPT: both `.lh`-default, 12pt either way) until
    #     LJ6DTP, whose own `.lh` is customized to 14pt (9.333/48in): the
    #     wrong-lead bug ALONE gave head_base 5.0 * 14pt lead + 12 = 82.0,
    #     the exact wrong baseline on Jon's paper -- squarely inside
    #     LJ6DTP's own body text (86.0pt, unaffected: `_printed_top`'s
    #     top-margin reservation was never mixed with `.lh` to begin
    #     with). LEAD (this module's own 6 LPI constant, already used for
    #     the fontless/default-.lh case everywhere else) replaces `lead`
    #     here; `size` is untouched (the header's own font size, never a
    #     margin-count unit).
    mt = float(page.get('mt_lines', 3))
    # mechanism W: hm participates UNCONDITIONALLY -- no gate on
    # mt_source/hm_source at all. See the long comment above this
    # function's own `head_base` block for the full derivation and why
    # every gated formula this project ever shipped (b26-header-round2's
    # mt_source-only rule, register b31's OR-of-both-sources widening)
    # was fit entirely against Robert J. Sawyer's WSCHANGE-customized WS7
    # install and never actually distinguished from this simpler rule
    # until `-README`'s own `ws7-prints/v3` PRISTINE.EXE recapture.
    hm = float(page.get('hm_lines', 2))
    top_head = max(headers, default=1)
    head_base = max(0.0, mt - hm - top_head)
    resolved_headers = []
    for n, txt in sorted(headers.items()):
        if not txt:
            continue
        y = page_h - (head_base + n - 1) * LEAD - size
        # planning #250: `head_hf_override` (this page's own `.h1e`/`.h1o`
        # resolution, `pdf.py`'s `_close_page`) wins for whichever line it
        # names -- None (every page of every document that never uses the
        # family) falls straight through to the flat `doc.header_fonts`/
        # `header_tabs` reads, byte-identical to before this existed.
        if head_hf_override is not None and n in head_hf_override:
            font_idx, tab_rec = head_hf_override[n]
        else:
            font_idx, tab_rec = doc.header_fonts.get(n), doc.header_tabs.get(n)
        text = _resolve_line_text(txt, font_idx, tab_rec)
        resolved_headers.append((n, text, y, font_idx))
    # b26-header-baseline: `fm` is deliberately UNCHANGED -- checked for the
    # same default/explicit asymmetry `.hm` turned out to have, above, and
    # NOT applying it here on the evidence actually available. No oracle in
    # the corpus can test it directly: -README (the coordinator's cited
    # footer example) has no `.fo` at all -- `doc.footers` is empty, this
    # was a wrong steer -- and LJ6DTP's own footer is two raw print-control
    # bytes with no visible text baseline to measure. The one real data
    # point that DOES exist, `test_head_foot_land_where_wordstar_puts_them`
    # (WordStar 4, 2026-08-03, footer at line `.pl - .mb + .fm` = 60, `.fm`
    # at its DEFAULT value, unconditionally applied), argues AGAINST
    # extending the header's fix here by symmetry -- it is real, if dated,
    # evidence that a default `.fm` already participates in the footer's
    # own placement, unlike a default `.hm` in the header's. Reported, not
    # acted on.
    foot_line = pl - mb + fm
    resolved_footers = []
    for n, txt in sorted(footers.items()):
        if not txt:
            continue
        y = page_h - (foot_line + n - 1) * lead - size
        if y < 0:
            continue
        # planning #250: same override as the header loop above.
        if foot_hf_override is not None and n in foot_hf_override:
            font_idx, tab_rec = foot_hf_override[n]
        else:
            font_idx, tab_rec = doc.footer_fonts.get(n), doc.footer_tabs.get(n)
        text = _resolve_line_text(txt, font_idx, tab_rec)
        resolved_footers.append((n, text, y, font_idx))
    auto = None
    if show_auto_num:
        # WordStar's own AUTOMATIC number rides the SAME row a footer line 1
        # would (n=1: `foot_line + 1 - 1 == foot_line`) -- measured, every
        # E3-item-2 probe that ever showed both together (PN_FOHASH_PROBE's
        # footer text and its OWN `#`-substituted number; the plain-auto-
        # number probes' bottom digits) landed at the identical y a real
        # `.fo` line 1 uses. `show_auto_num` already excludes the case a
        # real footer is in use (WSFORMAT.WS's own "active only when the
        # footers are not in use"), so this never collides with the loop
        # just above -- at most one of the two ever fires for a given page.
        y = page_h - foot_line * lead - size
        if y >= 0:
            auto = (str(page_no), _auto_pageno_x_pt(doc), y)
    return {'headers': resolved_headers, 'footers': resolved_footers, 'auto': auto}


def _running_ops(doc, page_no, page_h, lead, size, left, printed,
                 headers=None, footers=None, res=None, auto_page_number=False,
                 head_hf_override=None, foot_hf_override=None):
    """Header and footer text for one page, as content-stream ops -- a
    thin RENDERING shell over `_resolve_head_foot_lines` (planning
    #251(d)): that function resolves WHERE (`y`, and this page's own
    `left`) and WHAT TEXT (page-number substitution, fontless tab-
    realignment baking); this function only turns each already-resolved
    line into PDF content-stream ops -- font resource registration
    (`res`), toggle-byte STYLING (`hf_runs`), and a proportional header/
    footer face's own per-run natural-width advance. See `_resolve_head_
    foot_lines`'s own docstring for the geometry/text derivation (mt/hm
    participation, `.op`, right-tab realignment, the WS4 header/footer
    row layout) -- this docstring covers rendering only."""
    resolved = _resolve_head_foot_lines(doc, page_no, page_h, lead, size, left,
                                        printed, headers, footers, auto_page_number,
                                        head_hf_override, foot_hf_override)
    if resolved is None:
        return []

    def _hf_line_ops(txt, y, font_idx):
        """One already-resolved header/footer LINE's ops (register C6).
        `font_idx` is the doc.fonts index found on this line's own
        .h#/.f# (doc.header_fonts/footer_fonts -- None when that line
        opened with no font-change block of its own). Resolved the SAME
        way a body span's own 'fontN' tag is (_pdf_family), so LJ6DTP's
        running head -- Antique Olive, a proportional sans face, per its
        own `.h1` -- no longer falls back to a hardcoded Courier just
        because header text has no span machinery of its own. `hf_runs`
        (emit.py; already used by Modern/RTF for this exact text) turns
        WordStar's own typed toggle bytes into styles, so a genuinely
        bold run still renders bold in whatever face this resolves to,
        and the toggle bytes themselves never reach the page as literal
        control characters.

        `txt` arrives here ALREADY fully resolved (`#` substituted, any
        fontless right-tab realignment baked -- `_resolve_head_foot_
        lines`'s own `_resolve_line_text`) -- this function never
        touches page numbers or tab arithmetic, only glyphs.

        No font on this line (the overwhelmingly common case -- every
        document that never opens a `.h#`/`.f#` with a font block) is
        BYTE-IDENTICAL to before this existed: one Tj, the whole string,
        Courier -- PROVIDED the line has no toggle bytes of its own to
        interpret (mechanism M residuals round, 2026-09-06): a fontless
        `.h#`/`.f#` line that DOES type an inline style toggle (WS_TOGGLES,
        e.g. `^Y` for italic) used to skip `hf_runs` entirely and write the
        raw control byte straight into the Tj string -- a real PDF viewer
        (and this repo's own fidelity gate, reproducing one) then advances
        the pen by whatever width its font gives an undefined glyph code,
        landing it as a phantom extra character glued onto the following
        word. Confirmed on -README.WS's own running head (`.h1`, no font
        block, wrapped in a single `^Y`...`^Y` italic pair): the engine's
        Printed PDF carried a literal `\\x19` before "WordStar" on every
        page, shifting "7.0"/"Archive" 7.2-14.4pt right of WS7's own real
        (correctly italic-then-restored, no phantom glyph) position. `res`
        is required for the run-by-run path (it registers whatever base-14
        font gets used in the page's own /Font resources); a caller that
        omits it gets the old single-Tj behaviour regardless (there is no
        way to register a font without one), same as before this fix."""
        entry = (doc.fonts[font_idx]
                if font_idx is not None and res is not None
                and 0 <= font_idx < len(doc.fonts) else None)
        if entry is None and (res is None or not any(ord(c) < 0x20 for c in txt)):
            # `txt.replace('∙', '•')`: this fast path (no font block, no control/
            # toggle byte anywhere) never calls `_hf_runs` at all -- fine for style
            # and control-byte handling, since the gate above already proves there
            # is neither to interpret, but `_hf_runs` ALSO does one plain character
            # substitution unconditionally (register C9, above): '∙' (U+2219 BULLET
            # OPERATOR) -> '•' (U+2022 BULLET), because cp1252 carries a real bullet
            # glyph and WordStar's own list marker means the round one. This path
            # skipped that too, reintroducing the exact "downgrades a round bullet
            # to a middle dot for no encoding reason" regression C9 fixed for every
            # OTHER header/footer line -- found corpus-wide by `tools/verify_head_
            # foot_model.py` on sawyer/REF/ADVANCE.DOT's own running head (a
            # fontless `.h1`, no toggle bytes, `∙` typed directly) once that script
            # started comparing the model's `header_lines` text (which DOES carry
            # the original `∙`, pre-`_hf_runs`, by design) against the PDF's own
            # drawn bytes: the two agreed neither more nor less than the SAME
            # substitution both are supposed to apply on their own read of it.
            return [b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET' %
                   (FONTS[(False, False)].encode(), size, left, y,
                    _esc(txt.replace('∙', '•')))]
        family = _pdf_family(entry) if entry is not None else 'Courier'
        pt = (max(1, round(entry['points']))
              if entry is not None and entry.get('points') else size)
        ops, x = [], left
        for i, (run_text, styles) in enumerate(_hf_runs(txt)):
            if not run_text:
                continue
            if (i == 0 and not run_text.strip()
                    and entry is not None and entry.get('proportional')):
                # WordStar re-stamps a tab-derived leading indent as 10-CPI
                # machine spaces regardless of the font in force (the SAME
                # rule this module's own _split_indent applies to body
                # text) -- a proportional face's space glyph is much
                # narrower, so advancing on IT would pull the header text
                # back toward the margin instead of where WS7's own
                # absolute-position PCL puts it (measured: LJ6DTP.pcl's
                # `&a1718H` immediately before this exact line's "LJ6DTP").
                # A fontless (Courier) line never takes this branch --
                # Courier's own per-character advance already IS
                # `_PDF_PT_PER_COL`, so the general natural-width path
                # below already lands leading spaces correctly.
                x += len(run_text) * _PDF_PT_PER_COL
                continue
            basefont = BASE14[family][('b' in styles) + 2 * ('i' in styles)]
            font = res.ref(basefont)
            ops.append(b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET' %
                       (font.encode(), pt, x, y, _esc(run_text)))
            x += _natural_width_pt(run_text, basefont, pt)
        return ops

    ops = []
    for _n, txt, y, font_idx in resolved['headers']:
        ops += _hf_line_ops(txt, y, font_idx)
    for _n, txt, y, font_idx in resolved['footers']:
        ops += _hf_line_ops(txt, y, font_idx)
    if resolved['auto'] is not None:
        text, x, y = resolved['auto']
        ops.append(b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET' %
                   (FONTS[(False, False)].encode(), size, x, y,
                    _esc(text)))
    return ops


# Mechanism G (research: 2026-09-06_ws7-blank-lines-and-superscript-advance.
# md, "G -- superscript/subscript advance in fixed-pitch text"). Real WS7's
# *Reference* manual (ch. 10 "Style," Sub/Superscript, p. 10-8/9) states the
# reduced size is "the x-height... of the original height" and gives ONE
# worked example -- 12pt Times Roman -> 8.1pt (ratio 0.675) -- but that ratio
# is Times Roman's own, not a universal constant: raw PCL from two
# independent real WS7 captures (a private paper's own .pcl, -SCREEN.pcl -- byte-identical
# `ESC(sp9.25v13.04hsb4099T` font-select command in both, typeface 4099 =
# Courier) measures Courier's own ratio at 9.25pt from a 12pt body = 0.7708,
# a DIFFERENT number. Confirms the manual's own wording: this is a real,
# font-specific x-height fraction, not a flat scale -- so it is a lookup
# keyed by family, not one constant. Only Courier has a captured data point
# in this corpus (both fixed-pitch documents use it); every other face keeps
# this emitter's long-standing flat 2/3 default, unverified against any real
# WS7 sup/sub-in-that-face capture.
_SUP_SUB_XHEIGHT_RATIO = {'Courier': 9.25 / 12.0}
_SUP_SUB_DEFAULT_RATIO = 2.0 / 3.0


def _sized(styles, size, roll_pt=None, family=None):
    """(point size, baseline rise) for a span set at `size`. Superscript/
    subscript are raised/lowered and reduced by `family`'s own x-height
    ratio (`_SUP_SUB_XHEIGHT_RATIO`, mechanism G) -- 2/3 (8pt at the default
    12, the ratio this emitter used before mechanism G) for any family with
    no measured WS7 ratio of its own. `family=None` (every call site that
    predates mechanism G) keeps the flat 2/3 default unconditionally, so
    nothing outside Printed's fixed-pitch line renderer changes behaviour.

    `roll_pt` (round 17, RULINGS-LEDGER row 3, register C22): the declared
    `.sr` roll, ALREADY converted to points -- Printed's own domain only.
    `None` (every Modern call site, and any caller that predates this)
    keeps the exact prior fixed 3/-2 rise, same "reader owns presentation"
    doctrine as every other Printed-only vertical-space item. WSFORMAT's
    own text: "[.SR] The increments... which the carriage is to roll up
    OR DOWN for subscript and superscript printing" -- ONE symmetric
    amount, so a real `.sr` corrects BOTH the sup rise (the old hardcoded
    +3 happened to already look plausible) and the sub rise (the old -2
    was never spec-derived at all -- confirmed empirically byte-identical
    across `.sr 0`/`.sr 40`/absent, i.e. never actually read)."""
    ratio = _SUP_SUB_XHEIGHT_RATIO.get(family, _SUP_SUB_DEFAULT_RATIO)
    if 'sup' in styles:
        return max(1, round(size * ratio)), (roll_pt if roll_pt is not None else 3)
    if 'sub' in styles:
        return max(1, round(size * ratio)), (-roll_pt if roll_pt is not None else -2)
    return size, 0


def _rules(styles, text, x, y, w, continuous=True):
    """Underline / strikethrough as stroked paths (PDF has no text attribute
    for either), for a span occupying `w` points from `x`.

    `continuous` (Jon's ruling 2026-08-20, REVERSING round 17b's default --
    RULINGS-LEDGER row 5/6, register C21): the DEFAULT is now continuous,
    spaces included. Real WS7 LaserJet output (ws7-prints/v1; Jon's
    physical M479fdw print of those captures) underlines the gaps: WS7
    emits one UL-ON..UL-OFF span per ^PS phrase with ESC&aH cursor moves
    between words, and PCL underlines ALL horizontal movement while
    enabled. None of those documents carries any `.ul`, so the measured
    no-`.ul` default is continuous -- the WS3.3 manual's "^PS does NOT
    underline blank spaces" clause (round 17b's basis) describes a surface
    this driver demonstrably does not share. Jon: "With Printed we are
    making a best attempt to match what you would get straight from WS
    with no additional software." An EXPLICIT `.ul off` is still the
    file's own request for characters-only underline and still honored
    (`.ul` support ruled 2026-08-17) -- the parser records the key only
    when the command is present, so absent and `.ul off` are
    distinguishable. Modern's own call site never passes this (stays
    `True`, its prior and only behavior)."""
    ops = []
    if not text.strip():
        return ops
    if 'strike' in styles:
        ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S' % (x, y + 3, x + w, y + 3))
    if 'u' not in styles:
        return ops
    if continuous or ' ' not in text:
        ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S' % (x, y - 1.5, x + w, y - 1.5))
        return ops
    # Break the rule at each run of space characters -- approximated by
    # character-count proportion of `w` (WordStar printed text is fixed-
    # pitch or near-uniform within one styled run; sub-point imprecision at
    # a word boundary is not visible on paper or screen).
    n = len(text)
    per_char = w / n
    i = 0
    while i < n:
        if text[i] == ' ':
            i += 1
            continue
        j = i
        while j < n and text[j] != ' ':
            j += 1
        ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S'
                   % (x + i * per_char, y - 1.5, x + j * per_char, y - 1.5))
        i = j
    return ops


def _span_pitch(entry, pt):
    """Per-character advance in POINTS for one span -- WordStar's own number.

    A WS5+ font block's FIRST word is the font width in HMIs (1/1800in): the
    pitch WordStar itself laid the document out on, and the pitch it sent the
    printer. 1800 HMI = 1 inch = 72 pt, so the conversion is /25.

    A span with no font block -- every WS4 file, every print stream, and every
    run before a WS5+ document's first font change -- gets the document's own
    `.cw`-derived pitch instead. `.cw` is character width in 1/120in, which
    _printed_size already resolved into the point size for exactly this
    reason (a Courier em advances 0.6, so cw/120in per character IS a cw-point
    font), so the pitch here is that size's 0.6em. Written in POINTS rather
    than converted through HMI on purpose: it is arithmetically the same
    number and it is the same float this emitter has always produced, which is
    what keeps a fontless PDF byte-identical.

    Twin: Swift's `spanPitch` (CtrlKD/PDFWriter.swift) is PUBLIC (2026-09-08) so
    Soft Return.app's Native renderer can pin fixed-pitch advances to this same
    number instead of deriving one of its own -- Python has no public/internal
    split, so this docstring is that side's contract."""
    w = (entry or {}).get('width_1800')
    if w:
        return w / HMI_PER_POINT
    return pt * 0.6


# Mechanism G, the pitch half (research: 2026-09-06_ws7-blank-lines-and-
# superscript-advance.md). The manual is silent on this; the raw PCL is not:
# WS7 does not merely draw a smaller glyph at the document's ambient
# fixed-pitch cell -- it RESELECTS a narrower pitch for the sup/sub span, an
# independent field of the same PCL font-selection command, restored to the
# body's own H/V values immediately on exit. Measured directly (-SCREEN's
# own unjustified demo line, clean of any justification confound): a 7.2pt
# (10.00cpi) Courier body cell narrows to a 5.5pt (13.04cpi) cell for the
# span -- confirmed to the decipoint against -SCREEN.pcl's raw x-positions.
# `_SUP_SUB_CELL_RATIO` is that measured 5.5/7.2 fraction, applied
# proportionally to whatever the span's own body cell actually is (Courier
# only -- no other face has a captured sup/sub-in-fixed-pitch example in
# this corpus); a body cell other than 7.2pt is unverified extrapolation.
#
# Two real shapes hit this, both confirmed against the corpus directly:
#   - a WS7 span with its own font block (`entry` carries `width_1800`) --
#     `_span_pitch` normally IGNORES `pt` entirely once a font block exists,
#     which is exactly why the engine used to draw the full, un-narrowed
#     body cell for a sup/sub run and land everything after it +1.7pt (one
#     character's worth of the 7.2/5.5 shortfall) too far right (-SCREEN).
#   - a WS4/print-stream span (no font block at all, `entry` is `None`) --
#     `_span_pitch` falls back to `pt * 0.6`, where `pt` was already the
#     REDUCED sup/sub size (`_sized`'s own return) -- narrowing the cell
#     TWICE (once for the smaller drawn glyph, a second time implicitly via
#     `pt`) to 4.8pt, 0.7pt narrower than WS7's real 5.5pt, landing
#     everything after it that same 0.7pt too far LEFT (a private paper). Passing
#     `body_pt` (the span's own UNREDUCED declared size, `size_here` at the
#     call site) rather than the already-reduced `pt` fixes both shapes with
#     the one call: `_span_pitch(entry, body_pt)` always answers "the span's
#     own BODY cell," which this then scales down by the measured ratio.
_SUP_SUB_CELL_RATIO = 5.5 / 7.2


def _sup_sub_span_pitch(entry, styles, family, body_pt):
    """The per-character advance for a sup/sub run inside a fixed-pitch
    span (mechanism G), or `None` when the override does not apply -- the
    caller falls back to the ordinary `_span_pitch(entry, pt)` unchanged."""
    if family not in _SUP_SUB_XHEIGHT_RATIO or not ({'sup', 'sub'} & styles):
        return None
    body_cell = _span_pitch(entry, body_pt)
    if not body_cell:
        return None
    return body_cell * _SUP_SUB_CELL_RATIO


def _tz_scale(text, basefont, pt, target_w):
    """(Tz percentage or None, width actually occupied) for one span asked to
    fill `target_w` points.

    Courier lands on WordStar's grid by construction -- 600/1000 em is exactly
    the 0.6 the pitch was derived from -- so the ratio comes out 100 and no Tz
    is emitted at all. Nothing else does: Times at 12pt sets a word in
    whatever width Times wants, which is not the width WordStar reserved for
    it, and by the end of a line the accumulated error is a word or more.
    afm.py gives the natural width; Tz (horizontal scaling, percent) closes
    the gap, so the span occupies the grid slot the file asked for and the
    NEXT span starts where WordStar put it.

    None means "emit no scaling" and comes from three different places, all of
    which want the same operator (or the absence of one) but not the same
    width:
      * the ratio is 100 -- Courier, or any face whose metrics happen to agree.
        Occupies the target; nothing to say.
      * the ratio is outside [TZ_MIN, TZ_MAX] -- the metrics disagree
        pathologically (see the clamp's own note). The span keeps its NATURAL
        width and the rest of the line shifts with it, because overprinting
        the next span is worse than losing the grid.
      * there is no metric at all (a face afm.py cannot measure, or a string
        of glyphs it has no widths for). Nothing to compute a ratio from."""
    natural = _natural_width_pt(text, basefont, pt)
    if natural <= 0 or target_w <= 0:
        return None, natural
    scale = target_w / natural * 100.0
    if round(scale, 2) == TZ_DEFAULT:
        return None, target_w
    if not TZ_MIN <= scale <= TZ_MAX:
        return None, natural
    return scale, target_w


def _split_indent(segs):
    """`segs` with each entry gaining an INDENT flag, and the first span split
    where a line's leading whitespace ends.

    NARROWED SCOPE (the real-tab-position fix): a type-9 tab's own padding no
    longer needs this function's guesswork -- it now carries the block's real
    ABSOLUTE target as a 'tabhmi<N>' mark (core._symmetric_blocks), and
    _line_ops_printed's own tab branch intercepts a span carrying that tag
    BEFORE this function's flag is ever consulted, jumping the pen to the
    real stop instead of inferring one from a leading run's width. This
    function is therefore never the reason a TAB lands correctly any more --
    but it is not dead code: `.lm`/`.pm`/a plain typed indent re-stamp their
    leading spaces directly into the byte stream with NO type-9 block at all
    (no mark to carry a real target), and those still need their width read
    in document print columns rather than the run's own font advance
    (test_pm_first_line_indent_not_doubled_when_source_already_types_it has
    no tab block in it whatsoever and still depends on exactly this). It is
    also harmless to run on an ALREADY tab-marked span: `_coalesce` (pdf.py's
    own same-style-SET merge) never merges a 'tabhmi<N>'-tagged span with the
    real text before or after it (that tag is unique to it), so a tab's own
    padding always reaches this function as an all-padding span -- pad
    equals 0 or the whole length, never a mixed split -- and whichever `indent`
    flag it gets here is simply ignored by the tab branch that fires first.

    The indent is rarely a span of its own for the cases this function DOES
    still matter for: a typed indent and the text after it carry the same
    styles and the same font, so _coalesce has already merged them into one
    run by the time layout sees it. Peeling it off here is what lets the
    indent be measured in the document's own print columns while the text
    keeps the font's advance (see _line_ops_printed for why those are
    different measures).

    A span with NO font block is never flagged: the run's own pitch already IS
    the document's there, so the flag would change nothing -- and not raising
    it keeps every fontless line's arithmetic, and therefore its bytes,
    untouched. A FIXED-PITCH font block is never flagged either: its space
    advances at its own pitch on the printer, full stop -- LJ6DTP's PC-8
    chart draws its box in the 11.9-CPI COURIER PC 12, and measuring its
    border's leading spaces in 10-CPI document columns shoved the box top
    16pt right of the box sides. (For 10-CPI Courier the two measures are
    the same number, so nothing else moves.) The document-column rule is for
    PROPORTIONAL runs, where WordStar re-stamps tab/margin positioning as
    10-CPI machine spaces: the reference archive's 72pt shadow banner and
    LJ6DTP's own flush-right bar segment both land exactly on that measure."""
    out, leading = [], True
    for seg in segs:
        text, styles, family, size_here, entry = seg
        if not leading:
            out.append(seg + (False,))
            continue
        pad = len(text) - len(text.lstrip(' '))
        if entry is not None and entry.get('proportional') and pad:
            if pad < len(text):
                out.append((text[:pad], styles, family, size_here, entry, True))
                out.append((text[pad:], styles, family, size_here, entry, False))
                leading = False
            else:
                out.append(seg + (True,))       # the whole span is indent
            continue
        out.append(seg + (False,))
        if text.strip():
            leading = False
    return out


# ---- LJ6DTP parity C2: embedded PCL rectangles ------------------------------
#
# A 0x0F user print control's raw printer payload (core.py's doc.pcl_programs,
# indexed by a span's own 'pcl<N>' tag) is real PCL, not decoration. LJ6DTP.WS
# draws its page border (all 8 pages) and page 4's checkerboard entirely this
# way; our engine drew neither, because the pctl branch below only ever
# advanced `x` by the control's declared (zero) width and threw the bytes
# away. Scanning the whole file byte-for-byte (2026-08-2x) found exactly four
# PCL forms in use -- cursor push/pop, cursor position (absolute or relative
# per axis), and rectangle fill (solid, or a 4-parameter shaded form the
# initial inventory missed: `ESC*c<w>a<h>b<pct>g2P` draws the checkerboard's
# 15%/100% gray squares, not the plain `f=0` solid form the border uses).
# Nothing else appears; anything else is recorded as ignored rather than
# guessed at or failed on -- this is NOT a general PCL interpreter.
#
# Position command grammar (HP PCL5): unsigned value = ABSOLUTE (from the
# printer's own page origin); a leading +/- = RELATIVE (added to wherever the
# cursor already is). `ESC*p<x>x<y>Y` sets both axes; `ESC*p<y>Y` (no `x`
# group) sets only the vertical -- LJ6DTP's checkerboard uses both shapes in
# the same control.
_PCL_POS_RE = _re.compile(rb'\x1b\*p(?:([+-]?\d+)x)?([+-]?\d+)Y')
_PCL_FILL_RE = _re.compile(rb'\x1b\*c(\d+)a(\d+)b(\d+)(?:g(\d+))?P')
_PCL_PUSH_RE = _re.compile(rb'\x1b&f0S')
_PCL_POP_RE = _re.compile(rb'\x1b&f1S')

# HP LaserJet's own logical-page registration (measured against gpcl6's
# render of the genuine WS7 PCL output, LJ6DTP-p1.png at 300dpi -- 1 PCL unit
# per pixel there): absolute PCL x=2 lands at pixel column 77 (2+75), x=2369
# lands at 2444 (2369+75) -- a flat +75-unit (0.25in) offset on X across both
# the left and right border rules. Y needs NONE: PCL y=85 lands at pixel row
# 85 exactly, and y=3202 at row 3202. This is the printer's own unprintable-
# area registration, not a WordStar margin -- raw PCL bypasses WordStar's own
# cursor/margin machinery and addresses the physical page directly.
_PCL_ABS_X_OFFSET_UNITS = 75
_PCL_ABS_Y_OFFSET_UNITS = 0
_PCL_UNIT_PT = 72.0 / 300.0            # PCL unit (1/300in) -> point, exact


def _parse_pcl_program(data: bytes) -> list:
    """Tokenize one 0x0F control's raw printer payload into the small,
    explicit op list this document's PCL actually uses:
    ('push',) / ('pop',) / ('movex'|'movey', raw_signed_bytes) /
    ('fill', w_units, h_units, gray) / ('ignored', raw_bytes).

    An escape sequence matching none of the four recognised forms is
    recorded as 'ignored' rather than raised or silently dropped -- exactly
    the gap this task's own initial inventory fell into (it missed the
    shaded fill form entirely, having scanned only the plain `b<f>P` shape).
    """
    ops = []
    i, n = 0, len(data)
    while i < n:
        m = _PCL_PUSH_RE.match(data, i)
        if m:
            ops.append(('push',))
            i = m.end()
            continue
        m = _PCL_POP_RE.match(data, i)
        if m:
            ops.append(('pop',))
            i = m.end()
            continue
        m = _PCL_POS_RE.match(data, i)
        if m:
            xraw, yraw = m.group(1), m.group(2)
            if xraw is not None:
                ops.append(('movex', xraw))
            ops.append(('movey', yraw))
            i = m.end()
            continue
        m = _PCL_FILL_RE.match(data, i)
        if m:
            w, h, f, g = m.groups()
            w, h, f = int(w), int(h), int(f)
            if g is not None:
                # Shading pattern: `f` here is the ink PERCENTAGE (0-100),
                # not a fill-type code -- 100% reads as solid black, same
                # as fill type 0 below.
                ops.append(('fill', w, h, 1.0 - f / 100.0))
            elif f == 0:
                ops.append(('fill', w, h, 0.0))   # solid black -- the only
                                                   # plain fill type this
                                                   # document ever sends
            else:
                ops.append(('ignored', m.group(0)))
            i = m.end()
            continue
        if data[i] == 0x1b:
            j = data.find(b'\x1b', i + 1)
            j = n if j == -1 else j
            ops.append(('ignored', data[i:j]))
            i = j
        else:
            i += 1
    return ops


def _pcl_rect_ops(prog_ops, anchor_x, anchor_y, page_h, restore_gray):
    """Execute one parsed PCL program, anchored at (anchor_x, anchor_y) --
    the PDF page position (points, PDF's own bottom-up frame) wherever the
    running text cursor already is. Returns PDF content-stream ops for every
    fill, restoring `restore_gray` afterward so later text on the same line
    is unaffected.

    The cursor is tracked in POINTS throughout (the PCL-unit -> point factor,
    72/300 = 0.24, is exact, so there is no precision cost to converting
    each move immediately rather than accumulating in PCL units).

    An ABSOLUTE move (unsigned) jumps to this document's own PCL page origin
    (_PCL_ABS_X_OFFSET_UNITS/_PCL_ABS_Y_OFFSET_UNITS, converted against
    `page_h`) -- the anchor is irrelevant to it, exactly as real absolute
    cursor addressing ignores wherever the print head happens to be. This is
    the page BORDER's whole program: it never reads the anchor at all.

    A RELATIVE move (signed) adds to whatever position is already current --
    which for a program that opens with a push (LJ6DTP's checkerboard
    controls) IS the anchor: the print position the control sits at inline
    in the running text, since its own HMI word is 0 (zero character
    advance, so the anchor equals the pen position at that exact point in
    the line) -- ALREADY CORRECTED into this printer's own raw-PCL frame by
    the caller (register b31): `_line_ops_printed` hands this function
    `x + _PCL_ABS_X_OFFSET_UNITS*_PCL_UNIT_PT` (and the Y equivalent), the
    SAME registration constant the absolute branch above applies, since a
    relative program's raw PCL addresses the physical page exactly as an
    absolute one does -- only the STARTING point differs. Passing a raw,
    uncorrected anchor here would land every relative fill 0.25in left of
    where gpcl6 actually draws it (measured against LJ6DTP-p4.png's
    checkerboard, board left/centre 2.750in/4.123in)."""
    ops = []
    cur = [anchor_x, anchor_y]
    stack = []
    gray = [restore_gray]

    def set_gray(g):
        if g != gray[0]:
            ops.append(b'%.2f g' % g)
            gray[0] = g

    for op in prog_ops:
        kind = op[0]
        if kind == 'push':
            stack.append((cur[0], cur[1]))
        elif kind == 'pop':
            if stack:
                cur[0], cur[1] = stack.pop()
        elif kind == 'movex':
            raw = op[1]
            if raw[:1] in (b'+', b'-'):
                cur[0] += int(raw) * _PCL_UNIT_PT
            else:
                cur[0] = (int(raw) + _PCL_ABS_X_OFFSET_UNITS) * _PCL_UNIT_PT
        elif kind == 'movey':
            raw = op[1]
            if raw[:1] in (b'+', b'-'):
                cur[1] -= int(raw) * _PCL_UNIT_PT
            else:
                cur[1] = page_h - (int(raw) + _PCL_ABS_Y_OFFSET_UNITS) * _PCL_UNIT_PT
        elif kind == 'fill':
            w_units, h_units, fgray = op[1], op[2], op[3]
            if w_units and h_units:               # a 0-size fill draws
                                                    # nothing on a real
                                                    # printer either
                w_pt = w_units * _PCL_UNIT_PT
                h_pt = h_units * _PCL_UNIT_PT
                set_gray(fgray)
                ops.append(b'%.2f %.2f %.2f %.2f re f'
                          % (cur[0], cur[1] - h_pt, w_pt, h_pt))
        # 'ignored': nothing to draw, cursor unchanged
    set_gray(restore_gray)
    return ops


# A bare 0x09 tab byte's print-time expansion target, in document columns --
# WSFORMAT.WS's own file-format reference (WordStar's control-code table,
# byte 09h ^I): "At print time the number of hard spaces required to reach
# a modulus 8 print position is generated."
_TAB_MODULUS = 8


def _expand_bare_tabs_for_printed_layout(segs):
    """Expand every bare 0x09 tab byte in `segs`' own text into the literal
    spaces WordStar's print-time rule computes -- planning #244 (the
    round-trip gauntlet fix).

    This used to happen in `_decode_spans` at PARSE time (planning #202/
    #237): a running document-column count since the start of the physical
    line, and on a bare 0x09, pad with however many spaces are needed to
    reach the next multiple of 8 (a tab already sitting on a stop still
    advances a full `_TAB_MODULUS`, the standard tab convention). That was
    the RIGHT structural rule but the WRONG place to apply it -- baking the
    expansion into the parsed Span.text makes a computed space
    indistinguishable from one the author actually typed, so the native
    WordStar writer's round-trip (tests/test_writer.py's corpus gauntlet,
    tools/roundtrip_census.py) re-emits spaces instead of the original
    0x09 byte and never reproduces the source file (sawyer/MACROS/HOLYMAC/
    -HOLYMAC.WS, sawyer/REF/WINDOWS7.WS, sawyer/REF/wordstar-file-format.ws
    -- found 2026-09-08, planning #244). `_decode_spans` now keeps the
    literal byte (`buf.append(b)`, restored to its pre-#237 form -- the
    document model IS the source bytes, unexpanded); this function applies
    the SAME rule here instead, at PRINTED-mode render time only, on a
    transient copy of the segment text. The underlying Span.text the
    writer reads back out is never touched -- Modern mode and every other
    emitter (text, markdown, html, rtf) never call this and keep seeing
    the bare, un-expanded byte, exactly their own pre-#237 behavior
    (unchanged -- #237's fidelity fix was Printed-PDF-only in its own
    evidence, WS7 LaserJet PCL captures, despite living in a function
    every mode shared).

    Column-tracking matches `_decode_spans`'s own former semantics
    exactly: a running count across the WHOLE physical line (every `segs`
    entry, in order, regardless of style -- a font/colour change never
    consumes a column), reset to 0 for each call (one call = one physical
    line, since Printed mode renders physical lines verbatim, never
    rewrapped). `segs` entries with no tab byte are returned unchanged --
    most printed lines never carry one, so this is a no-op scan for them,
    not a copy.

    Planning #237 remainder (probed 2026-09-09, `research/2026-09-09_
    space-tab-lattice-shift.md`): a literal space (or a WS5+ soft space,
    0xA0 -- already collapsed to plain ' ' by decode, see `core.py`'s
    `0xA0` branch) immediately preceding a bare 0x09 does NOT just occupy
    its own column like any other character before the tab. WS7's
    LaserJet driver computes the tab's modulus-8 stop from the column
    BEFORE that trailing run of space(s) -- as if it had not yet flushed
    them to its own column tracker -- then adds the run's length back on
    top of that stop. Eight probe documents (four columns crossed with
    space/no-space/on-stop, plus two documents reproducing WIN7.ETC's
    exact ` Subject: <TAB>`/` To: <TAB>` shape) printed through real WS7
    confirm this exactly, including a shape the corpus never previously
    exercised (a trailing space run that itself lands EXACTLY on a
    modulus-8 stop): probe `P4`, 7 characters then one space (column 8,
    already on a stop) lands the next word at column 9, not the old
    same-column rule's on-stop-advances-a-full-8 answer of 16. `space_run`
    below tracks the length of the CONSECUTIVE run of literal space
    characters immediately preceding the current position, across `segs`
    entries; on a bare tab, the modulus lands on `col - space_run`,
    falling back to the plain `col` when there is no preceding space run
    (`space_run == 0`) -- the ORIGINAL rule, unchanged for every tab not
    preceded by a space (confirmed clean by probes `P1`/`P3` and by the
    already-fixed `wordstar-file-format.ws` case, neither of which has a
    space before its tab)."""
    if not any('\t' in entry[0] for entry in segs):
        return segs
    col = 0
    space_run = 0
    out = []
    for entry in segs:
        text = entry[0]
        if '\t' not in text:
            col += len(text)
            trailing = len(text) - len(text.rstrip(' '))
            space_run = space_run + trailing if trailing == len(text) else trailing
            out.append(entry)
            continue
        pieces = []
        for ch in text:
            if ch == '\t':
                base = col - space_run
                needed = _TAB_MODULUS - (base % _TAB_MODULUS)
                pieces.append(' ' * needed)
                col = base + needed + space_run
                space_run = 0
            elif ch == ' ':
                pieces.append(ch)
                col += 1
                space_run += 1
            else:
                pieces.append(ch)
                col += 1
                space_run = 0
        out.append((''.join(pieces),) + entry[1:])
    return out


def _justify_pieces_printed(text, pitch, x0, justify_right_x, basefont, pt):
    """[(piece, x, width), ...] left to right from `x0` -- one FIXED-PITCH
    justified line's own word/gap split (planning #238's measured rule,
    factored out planning #251(b) so `_doc_to_pagelines` can call the
    EXACT SAME arithmetic at model-build time and attach the result to
    `PageLine.justify_word_x`; `_line_ops_printed` then renders from that
    stored list when given one, byte-identical to before by construction
    -- same function, same inputs, computed once). Returns None when the
    line has no single-blank gap to stretch or no slack to distribute --
    the caller falls back to the un-split natural-width path, unchanged.

    Cumulative-floor Bresenham distribution across the elastic (single-
    blank) gaps, in whole decipoints: `stretch[i] = floor((i+1)*S/G) -
    floor(i*S/G)`, S = the line's total slack in decipoints, G = elastic
    gap count -- see `_line_ops_printed`'s own docstring for the measured
    rule and its documented approximation. A run of 2+ literal blanks is
    left at its natural width, like every non-space WORD piece: only
    `_tz_scale`'s own target changes (the gap's own stretched width, not
    a fresh `pw`), which is why a piece's stored `width` alone is enough
    for a later caller to reproduce its own `pscale` -- `_tz_scale(piece,
    basefont, pt, width)` on an ALREADY-RESOLVED width reproduces the
    same scale/actual-width pair `_tz_scale(piece, basefont, pt, pw)`
    produced the first time (self-consistent: in-clamp, `width == pw`
    already; out-of-clamp, `width` IS the natural width, so scaling to it
    is a no-op ratio of 100 either way)."""
    pieces = _re.findall(r' +|[^ ]+', text)
    elastic = [i for i, p in enumerate(pieces) if p == ' ']   # exactly one blank
    natural_total = sum(len(p) * pitch for p in pieces)
    stretch_total = justify_right_x - x0 - natural_total
    if not (elastic and stretch_total > 0):
        return None
    n = len(elastic)
    stretch_total_dp = round(stretch_total * 10)
    stretch_dp = [
        ((i + 1) * stretch_total_dp) // n - (i * stretch_total_dp) // n
        for i in range(n)
    ]
    out = []
    x = x0
    ei = 0
    for pi, piece in enumerate(pieces):
        pw = len(piece) * pitch
        is_elastic_gap = (piece == ' ' and ei < len(elastic) and elastic[ei] == pi)
        if is_elastic_gap:
            pw += stretch_dp[ei] / 10.0
            ei += 1
            actual_w = pw          # nothing is ever drawn for a space piece
                                   # (see docstring) -- no glyph-metric lookup
        else:
            _, actual_w = _tz_scale(piece, basefont, pt, pw)
        out.append((piece, x, actual_w))
        x += actual_w
    return out


def _line_ops_printed(segs, left, y, size, res, tz_state,
                      col_state=None, colour_map=None, roll_pt=None, fi=None,
                      ul_continuous=False, pcl_programs=(), page_h=PAGE_H,
                      kerning=True, justify_right_x=None, justify_word_x=None,
                      record_graphic_cells=None):
    """One laid-out line, on the document's own horizontal grid.

    `record_graphic_cells` (planning #251(c)): a list, or None. When
    given, every cp437 graphic character this call draws as a vector
    (see the `GRAPHIC_CHARS` branch below) appends its own `(char, x_pt,
    width_pt)` -- the SAME x/width `_graphic_ops` just drew from -- so
    `_doc_to_pagelines`'s `_attach_graphic_cells_printed` can record the
    model's own answer with a real (throwaway-state) call to this
    function instead of re-deriving the advance rule itself. None (every
    ordinary render call) costs nothing extra.

    `justify_word_x` (planning #251(b)): this line's own PRECOMPUTED
    `_justify_pieces_printed` result (`PageLine.justify_word_x`, set by
    `_doc_to_pagelines`'s `_attach_justify_word_x_printed`), or None. When
    given, the justify branch below renders from it directly instead of
    recomputing the Bresenham split -- the model states it, the writer
    places it. None (every call site this function had before this field
    existed, and any line `_attach_justify_word_x_printed` could not
    resolve on its own -- a styled/tagged span outside its narrow scope)
    falls back to computing it fresh here, unchanged from before.

    `justify_right_x` (planning #238, `.oj on` full justification): the
    ABSOLUTE x this line's own right text-margin sits at, or None for an
    unjustified line -- `_doc_to_pagelines` sets it only on a PageLine it
    already knows is (a) inside a `.oj on`/`align='justify'` block, (b) NOT
    that block's own last physical line (WordStar never justifies a
    paragraph's trailing line -- confirmed directly against
    ws7-prints/v4/sawyer__LSRBOX__LSRBOX_EXT_WS.pcl, whose paragraph's own
    final line sits short of the margin, ragged, while every line above it
    reaches the margin exactly), and (c) resolves to exactly ONE coalesced
    span (a styled/mixed line is left unjustified this pass -- narrow,
    documented scope, see research/2026-09-08_justification-rule.md).
    Applied only to a FIXED-PITCH span (a proportional line's own
    per-word-natural-width path, just above, is unmodified -- no evidenced
    proportional `.oj on` capture was found in the corpus this pass).

    The measured rule (same research note): WS7 stretches ONLY the
    single-character inter-word gaps of the line (a run of 2+ literal
    blanks -- e.g. an author's own end-of-sentence double space -- is left
    at its natural width), distributing the line's own total slack across
    those gaps so the line's last character lands exactly on
    `justify_right_x`. The measured LSRBOX/CTRL-K.H1 captures show WS7's
    own per-gap split is NOT perfectly flat even when the total divides
    evenly (e.g. one 8-gap, 72dp-total line measured 7,7,10,9,10,9,10,10
    decipoints rather than a flat 9 each) -- WS7's own internal rounding
    for that split was not reverse-engineered to the decipoint this pass
    (research/2026-09-08_justification-gap-model.md). What ships here is
    cumulative-floor Bresenham distribution across the elastic gaps,
    computed in whole decipoints: `stretch[i] = floor((i+1)*S/G) -
    floor(i*S/G)`, S = the line's total slack in decipoints, G = elastic
    gap count. It reproduces every measured whole-column-slack gap
    (including the 7,7,10,9,10,9,10,10 example above) exactly, and is a
    measured improvement over flat-even-split everywhere else it was
    tested (mean residual 0.43dp vs 0.49dp on whole-column slack, 0.80dp
    vs 0.89dp on fractional slack, across 376 measured gaps) -- but it is
    still a disclosed approximation, not a fidelity-gate pass: it does not
    hit every gap to the decipoint, and the true algorithm remains
    unidentified (candidates ruled out and still open are in the research
    note). The split is done in integer decipoints deliberately, not
    float points, so the result never depends on summation order.

    Every span gets its own text object at an ABSOLUTE x, and that x is
    WordStar's: the characters before it, each at its own run's HMI advance
    (_span_pitch). This replaced two paths -- a Courier one that did exactly

    Every span gets its own text object at an ABSOLUTE x, and that x is
    WordStar's: the characters before it, each at its own run's HMI advance
    (_span_pitch). This replaced two paths -- a Courier one that did exactly
    this arithmetic with a hardcoded 0.6, and a proportional one that put the
    whole line in a single text object and let PDF's natural advance carry the
    pen. The second was the right call while this emitter had no font metrics:
    with no way to know how wide Times actually set a word, a computed x was a
    guess and natural advance at least never overlapped. afm.py removes that
    limitation, and Jon's ruling followed it: "Printed that ignores fonts
    can't call itself Printed" -- the document's own layout math governs, so
    the grid is computed and each span is width-matched onto it with Tz.

    `tz_state` is a one-element list carrying the CURRENT horizontal scaling
    across calls. Tz is text state, and text state survives ET -- an 85 Tz set
    on one span would silently scale every span after it, on every following
    line of the same content stream. So the operator is written only when the
    value CHANGES, which also means a document that never needs scaling (every
    fontless file, and Modern mode entirely) never emits one and its bytes are
    exactly what they were before any of this existed.

    THE ONE EXCEPTION to the HMI grid, and it is the document's own math too:
    a line's LEADING WHITESPACE is positioning, measured in the document's
    print columns rather than in the font. WordStar re-stamps a left indent
    from `.tb`/`.lm`/`.po` as machine spaces, and every one of those commands
    is specified in 10-CPI print columns -- core._tab_columns literally
    converts the tab's HMI size to columns before emitting the padding. Run
    that padding at a 72pt display font's own advance and a one-column shadow
    offset becomes a six-inch one: the reference archive's own banner document
    tabs to 1.39in on one line and 1.4in on the next, an offset of exactly one
    print column (7.2pt at 10 CPI), to print a display face twice with a
    shadow. On the font's advance the second copy landed off the right edge of
    the paper. Interior spaces -- inside a run, after real text -- are the
    author's own characters and stay on the font's advance.

    (The exception only fires for a span that HAS a font block: without one
    the run's pitch already IS the document's, so it cannot change a fontless
    byte.)"""
    # round 17 (RULINGS-LEDGER row 5/7): `.pm`'s first-line indent -- a
    # column position in the SAME absolute frame `.lm`/`.po` use (WSFORMAT
    # semantics, matching round 6's own RTF `\fi` reading), so it shifts the
    # line's own STARTING point; the typed leading-whitespace handling below
    # still measures relative to wherever the line begins.
    #
    # Finding A (b26-print-fidelity-2, WARPRAYR.WS): that stacking is right
    # ONLY when the line's own text does NOT already carry a typed leading
    # indent of its own -- `.pm` exists for the paragraph whose first line
    # starts flush in the SOURCE and relies on `.pm` alone for its visual
    # indent. WARPRAYR's Quote style (`.pm 5`) is the other case: every
    # line is typed with its own real leading spaces (5 on a continuation,
    # 10 on a stanza's own first line -- the author's hanging-indent
    # convention), so `_split_indent` below ALREADY produces the block's
    # first line's full, correct indent from those typed spaces alone.
    # Adding `fi` on top double-counts it. Measured (WARPRAYR.pcl): the
    # couplet's first line ('"God the all-terrible!', 10 typed spaces)
    # and the prayer's own first line ('"O Lord our Father', 10 typed
    # spaces) both belong at x=122.4 -- the SAME position a MID-block
    # stanza's own first line reaches ('"For our sakes', also 10 typed
    # spaces, not `fi`-eligible since it isn't the block's first physical
    # line) purely from its typed indent. `fi` stacked on top of it pushed
    # the block's own first line to 158.4, the +36pt (`.pm`'s own 5 cols)
    # double-count this fixes. A line with NO typed leading whitespace of
    # its own (indent never fires) is unaffected -- `fi` remains its only
    # indent source, unchanged.
    # Planning #244 (the round-trip gauntlet fix) moved this expansion out
    # of `_decode_spans` (parse time) into render time, here. Planning #251
    # (2026-09-09) moved it AGAIN, one step earlier still: body text now
    # arrives already expanded -- `_doc_to_pagelines`'s plain path and its
    # notes-aware sibling `_body_stream_printed` both call
    # `_expand_bare_tabs_for_printed_layout` themselves when they build each
    # PageLine's segments, so the MODEL carries the expansion (consumers
    # other than this writer -- `emit_layout`'s 'printed' pagelines chief
    # among them -- stopped seeing a raw 0x09 byte). The call below is now a
    # no-op for that text (no '\t' left to find, `_expand_bare_tabs_for_
    # printed_layout`'s own fast path returns `segs` untouched) and is kept
    # ONLY as the still-active path for footnote/endnote/annotation AREA
    # text (`_render_area`/`_note_wrap`'s own word-wrapped lines) -- those
    # do not yet build their segments through either model site above, so a
    # bare tab inside note text (untested in the current corpus; no
    # document exercises it) still depends on this call. Not migrated this
    # round: note-area text is WRAPPED, not verbatim-physical like body
    # text, so "one call = one physical line" column-counting would need
    # its own rule first. Named here, not silently left unmentioned,
    # planning #251 audit item (d).
    segs = _expand_bare_tabs_for_printed_layout(segs)
    if colour_map:
        # colour_map is non-empty exactly when the document declares driver
        # LJ6DTP -- the same gate covers its character substitutions.
        segs = _lj_substitute(segs, kerning)
    segs = _split_indent(_split_symbol_fallback(_split_graphics(segs)))
    if fi and segs and segs[0][5]:            # segs[0][5] is that first
        fi = None                             # segment's own `indent` flag
    ops, x = [], left + (fi or 0)
    # Justification only ever touches the ONE span that IS the whole line
    # (see this function's own docstring, "justify_right_x") -- a line that
    # split into several segs (a styled word mid-sentence, a leading indent,
    # graphics) is left unjustified rather than guess how to divide the
    # slack among them.
    justify_eligible = justify_right_x is not None and len(segs) == 1
    # A pctl span whose display string carries a graphic char (box-drawing,
    # LJ6DTP's own «...┌─│...» labels) gets fragmented by _split_graphics
    # above into several pieces that all still carry the same 'pctl'/'pcl<N>'
    # tags -- drawn_pcl guards against executing the same control's PCL
    # program once per fragment.
    drawn_pcl = set()
    for text, styles, family, size_here, entry, indent in segs:
        # A 0x0F user print control's display string is SCREEN-ONLY: on paper
        # WordStar sent the raw printer payload and advanced by the block's
        # own HMI word (0 for LJ6DTP's rule-drawing controls, whose payload
        # draws with no character advance at all). The facsimile does the
        # same: no text, the declared width of empty space -- PLUS, when the
        # control's raw PCL survived parsing (core.py's doc.pcl_programs,
        # tagged 'pcl<N>'), the rectangles that PCL actually draws (register
        # C2: LJ6DTP's page border and page 4's checkerboard).
        pctl = next((t for t in styles if t.startswith('pctl')), None)
        if pctl:
            pcl_tag = next((t for t in styles
                            if t.startswith('pcl') and not t.startswith('pctl')),
                           None)
            if pcl_tag is not None:
                idx = int(pcl_tag[3:])
                if idx not in drawn_pcl and idx < len(pcl_programs):
                    drawn_pcl.add(idx)
                    prog = _parse_pcl_program(pcl_programs[idx])
                    # col_state[0] is ('g', gray) or ('p', pattern-index)
                    # since the HP-pattern branch above; a raw PCL fill
                    # always draws in plain DeviceGray (LJ6DTP's own
                    # program bytes carry the gray directly, never a
                    # pattern), so the restore value is that gray -- and
                    # LJ6DTP.WS never puts an embedded PCL program on a
                    # line that also carries an HP-pattern colour, so the
                    # 0.0 fallback for a live pattern is never actually
                    # exercised, just a safe default if that ever changes.
                    restore_gray = (col_state[0][1]
                                    if col_state and col_state[0][0] == 'g'
                                    else 0.0)
                    # register b31 (E1's own resolved-anchor question): a
                    # RELATIVE-move program (LJ6DTP's checkerboard, `push`
                    # then signed moves throughout -- see _pcl_rect_ops's own
                    # docstring) inherits `x`/`y`, this engine's own IR-
                    # computed running text position -- but that position is
                    # in WordStar's own document-column frame, and the raw
                    # PCL this control sends bypasses that frame entirely to
                    # address the PHYSICAL PAGE, exactly like an ABSOLUTE
                    # move already does (whose own +75/+0-unit correction is
                    # `_PCL_ABS_X_OFFSET_UNITS`/`_PCL_ABS_Y_OFFSET_UNITS`,
                    # this same printer's own measured unprintable-area
                    # registration). The two frames disagree by that SAME
                    # constant regardless of which addressing mode a given
                    # PCL move uses -- measured against gpcl6's LJ6DTP-p4.png:
                    # page 4's checkerboard left/centre land at 2.750in/
                    # 4.125in with this correction (vs 2.500in/3.875in
                    # without it), matching gpcl6's own 2.750in/4.123in
                    # board measurement to within rounding, board WIDTH
                    # identical either way (2.75in) -- confirming a uniform
                    # anchor shift, not a stretched or mis-sized grid. A
                    # no-op for the border's own 100%-absolute program: an
                    # absolute move ignores the anchor outright.
                    ops += _pcl_rect_ops(prog, x + _PCL_ABS_X_OFFSET_UNITS * _PCL_UNIT_PT,
                                         y - _PCL_ABS_Y_OFFSET_UNITS * _PCL_UNIT_PT,
                                         page_h, restore_gray)
            x += int(pctl[4:]) / HMI_PER_POINT
            continue
        pt, rise = _sized(styles, size_here, roll_pt, family)
        basefont = BASE14[family][('b' in styles) + 2 * ('i' in styles)]
        font = res.ref(basefont)
        # Driver-aware colour: a span tagged colourN under a driver whose
        # palette we know renders at that palette's gray. Emitted only when
        # the value CHANGES (fill gray is graphics state, like Tz), so every
        # all-black document -- and every driver we cannot read -- writes not
        # one extra byte. This is what makes LJ6DTP's knockouts work: white
        # (15) text overprinted onto a black bar punches out of it exactly
        # as the LaserJet printed it.
        if col_state is not None and colour_map:
            ctag = next((t for t in styles if t.startswith('colour')), None)
            cidx = int(ctag[6:]) if ctag else None
            # colour9-14 (HP1-HP6) fill with a tiling PATTERN instead of a
            # flat gray -- registered per-page in /Resources by emit_pdf,
            # same mechanism as /Font and /XObject. Anything else (or no
            # colour tag at all) keeps the plain DeviceGray fill.
            if cidx is not None and cidx in _LJ6DTP_HP_PATTERNS:
                want = ('p', cidx)
                want_darken = False
            else:
                want = ('g', colour_map.get(cidx, 0.0) if cidx is not None else 0.0)
                # register b31 E2: colour1-7 fills draw with a Darken blend,
                # not flat opaque paint. LJ6DTP's masthead types "LJ6DTP" in
                # black, sets `.lh.05"`, and types "LJ6DTP" again in colour4
                # (0.75 gray) to overprint a shadow 0.05in below-right -- two
                # SEQUENTIAL lines, not the bare-CR overprint mechanism
                # (Line.overprint), so nothing already re-orders their paint.
                # Real halftone ink over already-inked paper stays dark; this
                # emitter painted file-order and opaque, so the gray shadow
                # REPLACED the black title outright (measured against
                # ws7-prints/gpcl6-renders/LJ6DTP-p1.png: black on top, gray
                # peeking below-right only -- the opposite of what shipped).
                # Scoped to cidx 1-7 only, per test_lj6dtp_hp_patterns.py's
                # own settled ruling (colour1-7 fills, line 15-23) -- colour15
                # (white knockouts, pdf.py's `want`/`0.0` default black
                # NEVER get it: Darken is a no-op on white paper regardless
                # (nothing below a fresh page to darken against), so p5's
                # swatches and p6's knockouts are unchanged BY CONSTRUCTION,
                # not by a separate exemption this code has to maintain.
                want_darken = cidx is not None and 1 <= cidx <= 7
            if want != col_state[0]:
                if want[0] == 'p':
                    ops.append(b'/Pattern cs /P%d scn' % want[1])
                else:
                    ops.append(b'%.2f g' % want[1])
                col_state[0] = want
            if want_darken != col_state[1]:
                ops.append(b'/GS1 gs' if want_darken else b'/GS0 gs')
                col_state[1] = want_darken
        # A tab-marked span carries its block's own ABSOLUTE target
        # (content[2:4], HMI from the LEFT MARGIN -- core._symmetric_blocks'
        # 'tab' mark) -- so the pen is SET, not advanced, for every tab, not
        # only a line's own leading one. MEASURED against real WS7 PCL
        # (LJ6DTP.pcl page 5): two table rows whose tabs fire at DIFFERENT
        # pen positions (one right after "Black", the other after a
        # dot-leader run) both carry the SAME content[2:4] (4680 HMI), and
        # only reading it as absolute-from-margin reproduces both rows' real
        # bar position -- relative-from-pen would put the second bar 0.43in
        # further right than WS7 actually printed it.
        #
        # This never collides with `_split_indent` below: that function's
        # pad-based split only ever fires on a MIXED span (typed leading
        # spaces followed by real text merged into one run by `_coalesce`),
        # and `_coalesce` merges strictly on style-SET equality -- this span's
        # own unique 'tabhmi<N>' tag means it is never merged with the text
        # before or after it, so it always reaches here as a span of its own,
        # entirely padding, and `_split_indent` either flags it whole or not
        # at all. It also retires that function's REASON for existing for
        # this case (the tab's true stop no longer needs to be inferred from
        # a leading run's own width) -- but not the function itself: a typed
        # indent with no type-9 block at all (test_pm_first_line_indent_not_
        # doubled_when_source_already_types_it) carries no mark and still
        # needs the pad-based measure.
        tab_hmi_tag = next((t for t in styles if t.startswith('tabhmi')), None)
        if tab_hmi_tag is not None:
            target_x = left + int(tab_hmi_tag[6:]) / HMI_PER_POINT
            leader_tag = next((t for t in styles if t.startswith('tableader')),
                              None)
            leader_byte = int(leader_tag[9:]) if leader_tag else 0x20
            if target_x <= x:
                # Overrun guard, the standard degenerate tab case: the stop
                # is at or behind the pen already. Never move backward --
                # advance by a single space width instead, the same
                # document-column measure the fill branch below uses.
                x += size * 0.6
            elif leader_byte == 0x20:
                # A PLAIN tab (hard/soft/decimal/center/right types all
                # degrade to space padding -- see _tab_columns): WS7 prints
                # NO ink here at all, only a horizontal-position escape
                # (MEASURED, same page-5 capture's "Black" row -- nothing
                # between the two ESC&a..H moves). Jump the pen; draw
                # nothing, matching the real printer exactly.
                x = target_x
            else:
                # A DOT-LEADER tab: WS7 DOES print the fill characters
                # (MEASURED, the same capture's "85%" row: literal '.....'
                # between its two ESC&a..H moves) -- but it REPEATS the
                # leader glyph at its own NATURAL advance to fill the gap;
                # it never stretches a fixed run to fit it. MEASURED against
                # LJ6DTP.pcl page 5 directly: the type-9 block's own declared
                # run is 16 characters (content[0:2]'s HMI / TAB_HMI_PER_COL,
                # what `text` holds here), but the real printer output
                # between ESC&a2066H and the pattern fill that starts the
                # row's bar (shared with the next row's plain-tab target,
                # 3168) is 27 literal periods at THEIR natural width -- WS7's
                # own PCL never carries a horizontal-scale escape for a
                # leader run at all. So: count how many natural-width glyphs
                # fit in the gap and draw exactly that many, unscaled.
                # Floored, not rounded, so the run stops short of the target
                # rather than lands on or past it -- the same capture never
                # shows a leader dot colliding with what follows. The pen
                # still jumps to the target EXACTLY afterward (every tab
                # branch here does that), so a short-by-a-fraction leader
                # never mispositions the NEXT span even though it does leave
                # a sliver of unfilled gap immediately before the target,
                # exactly as a real dot leader looks.
                w_gap = target_x - x
                leader_char = chr(leader_byte)
                char_w = _natural_width_pt(leader_char, basefont, pt)
                count = int(w_gap / char_w) if char_w > 0 else len(text)
                run_text = leader_char * count
                symbol_bold = family == 'Symbol' and 'b' in styles
                symbol_italic = family == 'Symbol' and 'i' in styles
                if count == 0:
                    pass
                elif symbol_bold or symbol_italic:
                    ops.append(_symbol_style_op(
                        font, pt, rise, TZ_DEFAULT, tz_state, x, y,
                        _esc(run_text), symbol_bold, symbol_italic))
                elif TZ_DEFAULT == tz_state[0]:
                    ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td (%s)'
                              b' Tj ET' %
                              (font.encode(), pt, rise, x, y, _esc(run_text)))
                else:
                    ops.append(b'BT /%s %d Tf %d Ts %.2f Tz %.1f %.1f'
                              b' Td (%s) Tj ET' %
                              (font.encode(), pt, rise, TZ_DEFAULT, x, y,
                               _esc(run_text)))
                    tz_state[0] = TZ_DEFAULT
                if count:
                    ops += _rules(styles, run_text, x, y, char_w * count,
                                  ul_continuous)
                x = target_x
            continue
        # cp437 graphics (blocks, shades, box-drawing) draw as vectors at the
        # span's own advance -- see BOX_ARMS/_graphic_ops. _split_graphics
        # guarantees a span reaching here is either all-graphics or has none.
        #
        # In a PROPORTIONAL face a block advances at the EM, not the face's
        # nominal average width. The document proves it in its own prose:
        # LJ6DTP's "full line of black ... precisely the length of your ruler
        # line" is two 24-block segments, one left-anchored and one
        # flush-right, that "overlap" -- at 13pt Univers that arithmetic only
        # closes at 24 x 13pt per segment (312 + 312 over a 468pt measure,
        # overlapping exactly as described); at the nominal 6.72pt the
        # segments cannot even meet. Fixed-pitch blocks stay on the pitch --
        # the same document's COURIER PC bars are correct there.
        # A span with NO font block (every WS4 file) has no 'proportional' to
        # ask -- _span_pitch(None, pt) already answers that case with the
        # document's own Courier 0.6em column (Jon's 2026-08-10 ruling;
        # mirrors Swift c01470a).
        if set(text) & GRAPHIC_CHARS:
            pitch = (pt if (entry is not None and entry.get('proportional'))
                     else _span_pitch(entry, pt))
            ops += _graphic_ops(text, x, y, pitch, pt)
            # planning #251(c): the model's own per-cell x/width -- see
            # `record_graphic_cells`'s own doc on this function's
            # signature. Recorded here, the ONE place this run's per-
            # character cell positions are ever computed, rather than
            # re-derived by a model-build-time caller.
            if record_graphic_cells is not None:
                record_graphic_cells.extend(
                    (ch, x + i * pitch, pitch) for i, ch in enumerate(text))
            x += len(text) * pitch
            continue
        if entry is not None and entry.get('proportional') and not indent:
            # PROPORTIONAL runs advance at NATURAL widths, face-scaled. Every
            # piece (word or space run) occupies its own AFM width times the
            # FACE-constant Tz -- the scale that lands the face's AVERAGE
            # character on its HMI grid, so a line's total comes out on the
            # author's measure while every glyph and every space keeps its
            # true proportion. This is what the printer did: the driver
            # advanced real per-character widths, and the patched PS tables
            # made WordStar's own arithmetic use them too -- LJ6DTP's
            # space-count-tuned tables were designed against real widths, so
            # real widths are what reproduce them. One op per word bounds a
            # viewer's substitute-metric drift to a single word.
            #
            # (A one-day detour anchored each word to its CHARACTER-COUNT
            # grid position instead: any caps-heavy word overran its
            # count-based slot into the next word, and grid-width spaces --
            # an average CHARACTER wide, ~0.46em -- read as gaping and
            # uneven. Word overlaps everywhere; Jon's review, 2026-08-05.)
            pitch = _span_pitch(entry, pt)
            want = _face_tz(basefont, pitch, pt)
            factor = want / 100.0
            # Continuous underline (Jon's ruling 2026-08-20, see `_rules`):
            # one-op-per-word pieces would break the rule at every space no
            # matter what `_rules` decides (space pieces draw no text and
            # never reach it with ink), which is exactly the per-word look
            # the ruling reverses -- and exactly how WS7's own PCL does NOT
            # behave (one UL-ON..UL-OFF per phrase, moves between words).
            # So underline is lifted out of the per-piece calls here and
            # drawn once, first inked piece to last inked piece, spaces
            # between covered. Explicit `.ul off` keeps the per-piece path.
            span_ul = ul_continuous and 'u' in styles
            piece_styles = (styles - {'u'}) if span_ul else styles
            symbol_bold = family == 'Symbol' and 'b' in styles
            symbol_italic = family == 'Symbol' and 'i' in styles
            ul_x0 = ul_x1 = None
            for m in _re.finditer(r' +|[^ ]+', text):
                piece = m.group(0)
                nat = _natural_width_pt(piece, basefont, pt)
                pw = nat * factor if nat > 0 else len(piece) * pitch
                if piece[0] != ' ':
                    if symbol_bold or symbol_italic:
                        ops.append(_symbol_style_op(
                            font, pt, rise, want, tz_state, x, y,
                            _esc(piece), symbol_bold, symbol_italic))
                    elif want == tz_state[0]:
                        ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td (%s)'
                                   b' Tj ET' %
                                   (font.encode(), pt, rise, x, y,
                                    _esc(piece)))
                    else:
                        ops.append(b'BT /%s %d Tf %d Ts %.2f Tz %.1f %.1f'
                                   b' Td (%s) Tj ET' %
                                   (font.encode(), pt, rise, want, x, y,
                                    _esc(piece)))
                        tz_state[0] = want
                    if ul_x0 is None:
                        ul_x0 = x
                    ul_x1 = x + pw
                ops += _rules(piece_styles, piece, x, y, pw, ul_continuous)
                x += pw
            if span_ul and ul_x0 is not None:
                ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S'
                           % (ul_x0, y - 1.5, ul_x1, y - 1.5))
            continue
        if indent:
            scale, w = None, len(text) * size * 0.6      # document print columns
        else:
            # Fixed-pitch (and metric-less) runs: width-matched onto the font
            # block's own HMI grid with Tz -- for Courier the ratio is 100 by
            # construction and no operator is ever written, which is what
            # keeps every fontless PDF byte-identical.
            #
            # A sup/sub run gets mechanism G's own narrower cell instead of
            # the body's (see `_sup_sub_span_pitch`) -- `size_here` (the
            # span's UNREDUCED declared size), not `pt` (already reduced by
            # `_sized`), so a fontless (WS4/print-stream) sup/sub span's
            # cell is not narrowed twice.
            pitch = (_sup_sub_span_pitch(entry, styles, family, size_here)
                     or _span_pitch(entry, pt))
            if justify_eligible:
                # Planning #238/#251(b): this line IS the whole span
                # (justify_eligible guarantees it) and it is fixed-pitch --
                # split it into word/gap pieces and stretch only the
                # single-blank gaps. `justify_word_x` (the model's own
                # precomputed answer, when `_attach_justify_word_x_printed`
                # could resolve one) is used directly when present; every
                # other call site recomputes via the same pure function.
                # See `_justify_pieces_printed`'s own docstring for the
                # measured rule and its documented approximation.
                word_pieces = (justify_word_x if justify_word_x is not None
                              else _justify_pieces_printed(
                                  text, pitch, x, justify_right_x, basefont, pt))
                if word_pieces:
                    symbol_bold = family == 'Symbol' and 'b' in styles
                    symbol_italic = family == 'Symbol' and 'i' in styles
                    ul_x0 = ul_x1 = None
                    span_ul = ul_continuous and 'u' in styles
                    piece_styles = (styles - {'u'}) if span_ul else styles
                    for piece, piece_x, actual_w in word_pieces:
                        # Nothing is drawn for a bare elastic gap (a single
                        # blank -- `piece.strip()` below is what actually
                        # gates the draw); `_tz_scale` is skipped for it
                        # too, same as before this was factored out (see
                        # `_justify_pieces_printed`'s own docstring for why
                        # recomputing against the STORED width is safe for
                        # every piece that IS drawn).
                        if piece == ' ':
                            pscale = None
                        else:
                            pscale, _ = _tz_scale(piece, basefont, pt, actual_w)
                        pwant = TZ_DEFAULT if pscale is None else round(pscale, 2)
                        if piece.strip():
                            if symbol_bold or symbol_italic:
                                ops.append(_symbol_style_op(
                                    font, pt, rise, pwant, tz_state, piece_x, y,
                                    _esc(piece), symbol_bold, symbol_italic))
                            elif pwant == tz_state[0]:
                                ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td'
                                          b' (%s) Tj ET' %
                                          (font.encode(), pt, rise, piece_x, y,
                                           _esc(piece)))
                            else:
                                ops.append(b'BT /%s %d Tf %d Ts %.2f Tz %.1f'
                                          b' %.1f Td (%s) Tj ET' %
                                          (font.encode(), pt, rise, pwant, piece_x,
                                           y, _esc(piece)))
                                tz_state[0] = pwant
                            if ul_x0 is None:
                                ul_x0 = piece_x
                            ul_x1 = piece_x + actual_w
                        ops += _rules(piece_styles, piece, piece_x, y, actual_w,
                                     ul_continuous)
                    if span_ul and ul_x0 is not None:
                        ops.append(b'0.6 w %.1f %.1f m %.1f %.1f l S'
                                  % (ul_x0, y - 1.5, ul_x1, y - 1.5))
                    # Land EXACTLY on the margin regardless of any rounding
                    # accumulated across the pieces above -- the one part of
                    # the measured rule confirmed on every justified line in
                    # the corpus, never left to float drift.
                    x = justify_right_x
                    continue
            target = len(text) * pitch
            scale, w = _tz_scale(text, basefont, pt, target)
        want = TZ_DEFAULT if scale is None else round(scale, 2)
        symbol_bold = family == 'Symbol' and 'b' in styles
        symbol_italic = family == 'Symbol' and 'i' in styles
        if symbol_bold or symbol_italic:
            ops.append(_symbol_style_op(font, pt, rise, want, tz_state, x, y,
                                        _esc(text), symbol_bold,
                                        symbol_italic))
        elif want == tz_state[0]:
            ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td (%s) Tj ET' %
                       (font.encode(), pt, rise, x, y, _esc(text)))
        else:
            ops.append(b'BT /%s %d Tf %d Ts %.2f Tz %.1f %.1f Td (%s) Tj ET' %
                       (font.encode(), pt, rise, want, x, y, _esc(text)))
            tz_state[0] = want
        ops += _rules(styles, text, x, y, w, ul_continuous)
        x += w
    return ops


def _page_stream(pagelines, top, page_h=PAGE_H, lead=LEAD, size=SIZE,
                 left=float(MARGIN), running=(), fonts=(), res=None,
                 colour_map=None, roll_pt=None, ul_continuous=False,
                 line_no_checkpoints=None, pcl_programs=()):
    """One page's content stream. `fonts` is doc.fonts in PRINTED mode and
    empty everywhere else (Modern is Courier by design), so a span only leaves
    the document's own fixed pitch when the file itself asked for another face,
    another size or another advance.

    `lead` is the DOCUMENT DEFAULT. A line that carries its own (PageLine.lead,
    from the `.lh` in force where it sat) advances by that instead -- the
    stateful-`.lh` half of the same ruling.

    `left` is likewise the DOCUMENT DEFAULT (register b31): a line that
    carries its own (PageLine.left, from the `.po` in force where it sat --
    LJ6DTP.WS moves it to 2.5" for page 4's checkerboard) draws at that
    instead, the same stateful shape just below (`left_here`).

    A LINE'S LEAD IS THE SPACE ABOVE IT, not below it, and that is measured
    rather than assumed. `.lh` is a printer VMI: WordStar sets the vertical
    motion index and the line feeds that follow use it, so the command --
    which sits in the file before the line it was typed for -- governs the
    feed that arrives ON that line. The reference archive's banner document
    proves it: it prints one 72pt word, sets `.lh.05"`, and prints the same
    word again, to overprint a shadow 0.05in (3.6pt) below the first. Read the
    other way round -- each lead spending itself below its own line -- the two
    copies land 14pt apart and the shadow is just a second, blurry banner.

    The first line of a page takes its position from `top` and ITS OWN
    lead (not a flat `size`, and not always the document default `lead`
    parameter) -- round 26 wave 3, fidelity_gate.py Unit B. Measured
    2026-08-20 against LYING.pcl: the title block (`.lh` auto, vmi=-2,
    16pt Times-Bold -- `_style_lead_pt` gives 1.2*16=19.2pt) has its real
    WS7 baseline at PCL y=78.9pt; `top`=60pt (see _printed_top) + this
    line's OWN lead 19.2pt = 79.2pt, a 0.3pt residual -- the same
    decipoint-rounding-sized gap as every unstyled Courier document (where
    the line's own lead equals the document default 12pt, which is also
    why using a flat `size` here never looked wrong before: for every
    previously-measured doc, size and lead were both 12). Using the
    line's own `.lead` here is the SAME rule every other line on the page
    already follows (`if n and not prev_overprint: y -= line.lead or
    lead`, just below) -- unifying the first line with the rest rather
    than special-casing it on a quantity (font size) no other line uses
    for vertical placement."""
    res = FontRes() if res is None else res
    ops = list(running)
    first_lead = getattr(pagelines[0], 'lead', None) if pagelines else None
    first_lead = first_lead or lead
    y = page_h - top - first_lead
    # Horizontal scaling persists across text objects within a content stream;
    # it starts at PDF's own default on every page. See _line_ops_printed.
    tz_state = [TZ_DEFAULT]
    # Fill colour likewise: graphics state, reset per page. col_state[0] is
    # ('g', gray) or ('p', pattern-index) -- driver-aware, see
    # _line_ops_printed's colour block. col_state[1] (register b31 E2): the
    # Darken blend mode's own on/off state, tracked separately from the fill
    # colour itself -- two colour1-7 spans in a row change col_state[0]
    # (a new gray) without needing a second `gs` operator, but ENTERING or
    # LEAVING the colour1-7 family always needs one.
    col_state = [('g', 0.0), False]
    prev_overprint = False
    # planning #251(d): the `.l#` running counter that used to live here
    # (planning #247, `line_no_state`) moved to `_doc_to_pagelines`'s own
    # `_attach_line_numbers_printed` -- see `PageLine.line_no`'s own
    # comment. This call site now only gates the DRAW (`line_no_checkpoints
    # is not None`, below), it no longer resolves the label/x itself.
    # planning #227 follow-up (2026-09-09): `_apply_columns` concatenates
    # every column's own lines into ONE flat `pagelines` list (column 0's,
    # then column 1's, ...; PageLine.col records which) -- this loop must
    # therefore reset Y when `col` climbs, the same way it already resets
    # per PHYSICAL page (the `y = page_h - top - first_lead` line above).
    # Never implemented: Y instead kept decrementing across every column
    # in sequence, so column 1 continued DOWN from wherever column 0
    # ended instead of restarting at the top -- harmless on a document
    # whose columns happen to be nearly page-height (fontcrib.ws, where
    # this went unnoticed), but on a document with materially shorter
    # columns (sawyer/REF/WINGDING.CHT, 5 columns of ~45 lines on a page
    # with room for far more) it walked later columns' text hundreds of
    # points below the sheet -- confirmed via tools/fidelity_gate.py's
    # own PG1_MED_DY metric (WINGDING.CHT: 1231.8pt median Y residual
    # before this fix) and directly in the PDF's own text-positioning
    # operators. `prev_col` starts at `pagelines[0]`'s own column (or
    # None on a non-columnar page, where it can never differ from any
    # later line's `None` either) so the FIRST line is never treated as
    # a "new column" -- it already got its correct position from `y`'s
    # initial assignment above.
    prev_col = getattr(pagelines[0], 'col', None) if pagelines else None
    for n, line in enumerate(pagelines):
        cur_col = getattr(line, 'col', None)
        if n and not prev_overprint:
            if cur_col is not None and cur_col != prev_col:
                y = page_h - top - (getattr(line, 'lead', None) or lead)
            else:
                y -= getattr(line, 'lead', None) or lead
        prev_col = cur_col
        prev_overprint = getattr(line, 'overprint', False)
        # register b31: this line's own `.po` override (already resolved to
        # points -- PageLine.left, see its own docstring), or the document
        # default `left` param when the line never overrides it. Explicit
        # `is None` (not `or`) because a resolved left of 0.0 -- `.po 0` --
        # is a real, falsy-but-valid value, unlike `lead` above which can
        # never legitimately be zero.
        own_left = getattr(line, 'left', None)
        left_here = left if own_left is None else own_left
        # register b32-N10: this line's own `.sr` roll (already resolved to
        # points -- PageLine.roll, see its own docstring), or the document
        # default `roll_pt` param when the line never overrides it. Same
        # `is None` guard as `left_here` above -- a resolved roll of 0.0
        # (`.sr 0`, "do not shift at all") is a real, falsy-but-valid value.
        own_roll = getattr(line, 'roll', None)
        roll_here = roll_pt if own_roll is None else own_roll
        # Round 19 (PIX images RULED IN, ledger PIX row): an image
        # PageLine (see _doc_to_pagelines) draws its XObject instead of
        # text. `y` has already advanced by this line's `.lead`, which
        # since round 26 wave 3 (fidelity_gate.py Finding A) is the
        # RESERVED PLACEHOLDER block's height (`_pix_reserved_advance`:
        # the tag line plus its contiguous following blanks), not the
        # raster's own continuous pixel height -- so `y` now marks the
        # BOTTOM of that reserved band, not the image's own bottom edge.
        # Measured 2026-08-20 against -README.pcl: WS7 draws the picture
        # FLUSH WITH THE TOP of its reserved band (leaving any leftover
        # slack as blank space BELOW the image, before the next real
        # content), not flush with the band's bottom -- shifting the
        # drawn box up by (reserved - h_pt) reproduces that: `img_y` is
        # the band's top edge (`y + (reserved - h_pt)`) minus the image's
        # own height, i.e. flush with the band's top. `/Im<N>` is
        # registered in every page's /XObject resources by emit_pdf
        # (round 19), one entry per embedded pix index, shared exactly
        # like the /Font dict already is.
        #
        # Mechanism Y (PCL-DIVERGENCE-TRIAGE.md, planning #211 follow-up):
        # "the band's top edge" above is the PREVIOUS line's own BASELINE
        # (that is what subtracting `reserved` from the previous line's y
        # lands on) -- but real WS7 does not start the picture flush with
        # that baseline. Measured against three independent `ws7-prints/v3`
        # PRISTINE.EXE captures (PREVIEW, -SCREEN, -README, all embedding
        # the same INSET/PIX/WORDSTAR.PIX), the raster's real top edge sits
        # a further 2.7-3.0pt BELOW that baseline on every one of them --
        # x and width/height already matched to within decipoint-rounding
        # noise (<=0.58pt), only this vertical offset was missing. 3.0pt is
        # exactly `0.25 * size` for these captures' own 12pt default text
        # (-SCREEN and -README land on the WS7 figure to 0.0pt once it is
        # applied; PREVIEW to 0.3pt, itself decipoint-rounding-sized, the
        # same tolerance this module already accepts elsewhere for a
        # measured-vs-predicted fit). `0.25 * pt` is not a new constant:
        # it is the SAME baseline-to-cell-bottom (descent) fraction
        # `_graphic_ops` already uses for a box-drawing glyph's own cell
        # (`yb = y - 0.25 * pt`) -- applied here to the PRECEDING line's
        # cell instead of the image's own, because the picture cannot
        # start until that line's full cell (baseline plus descent) has
        # cleared, the same physical constraint a text glyph's own cell
        # observes. `size` is this function's own default text size
        # parameter (the same one already threaded to `_line_ops_printed`
        # and the `.l#` gutter below) -- pix tags reserve blank PHYSICAL
        # lines at the document's own default size, never a per-line
        # override PageLine tracks (see the "image" docstring above), so
        # reusing it here matches every other furniture line's own
        # assumption instead of adding a new one.
        img = getattr(line, 'image', None)
        if img is not None:
            pix_idx, w_pt, h_pt = img
            reserved = getattr(line, 'lead', None) or h_pt
            img_y = y + (reserved - h_pt) - 0.25 * size
            ops.append(b'q %.2f 0 0 %.2f %.2f %.2f cm /Im%d Do Q'
                      % (w_pt, h_pt, left_here, img_y, pix_idx))
            continue
        # round 17b (RULINGS-LEDGER row 5/6, register C11), corrected by
        # planning #247 against a real WS7 capture (LINE_NO_RIGHT_PT's own
        # comment): `.l#`'s own gutter. N = the interval in force on THIS
        # LINE (resolved from `line_no_checkpoints` just below) -- planning
        # #247's actual bug: a flat document-wide value read the LAST
        # `.l#` in the file, which in both real oracles is the one that
        # turns numbering back OFF, so nothing ever rendered anywhere.
        #
        # `line_no_checkpoints` is resolved PER LINE, by that line's own
        # `.bi`, not once for the whole page: PRINT.TST's own `.l#2`/
        # `.l# 0` pair both land on the SAME page (the "Line Numbers"
        # demo section opens the page and turns numbering on; a few
        # lines later, at the very end of the SAME page, `.l# 0` turns
        # it back off) -- a single per-page value (mirroring how `.mt`/
        # `.hm` are resolved once at page-open) cannot represent that; a
        # true per-line lookup, exactly like `left_here`'s own `.po`
        # override just above, can.
        #
        # `line_no_state[1]` (a 0-based count of physical lines, BLANK
        # ones included -- measured: the real capture numbers blank
        # physical lines exactly like text-bearing ones, so the previous
        # "blank lines are never numbered" guard here was an unverified
        # assumption, not evidence -- since the interval last CHANGED
        # value, its own comment above) stands in for a plain page-
        # relative `n`: a physical line is numbered when that count is a
        # multiple of N, and its label is a SEQUENTIAL COUNT of numbered
        # lines so far (1, 2, 3, ...), not the raw line index: measured
        # against the real capture, `.l#2`'s labels run 1, 2, 3, 4... one
        # per numbered line, never 2, 4, 6, 8 (which a raw page-relative
        # index would have printed). Right-aligned to `LINE_NO_RIGHT_PT`,
        # an ABSOLUTE page position (see its own comment) -- never
        # relative to `left_here`, so it draws in the margin WordStar's
        # own `.po` already reserved without shifting `left` itself, same
        # as a running head does. Rendered in the document's own default
        # body font (`_span_render` with no styles -- the SAME resolution
        # an ordinary unstyled span gets), not a hardcoded face: the one
        # real oracle happens to be Courier, which is also this engine's
        # own fallback, so this is untested against a document whose
        # default body font is something else.
        # planning #251(d): the label/x themselves are now
        # `_doc_to_pagelines`'s own decision (`_attach_line_numbers_
        # printed`, set on `PageLine.line_no`) -- this call site's only
        # remaining job is the `--line-numbers off` gate, which still
        # works exactly as before: that flag makes `_emit_pdf_inner` pass
        # `line_no_checkpoints=None` into this function, same as today,
        # so the draw is suppressed regardless of what the model carries
        # (same shape `show_headers`/`headers` already use).
        line_no = (getattr(line, 'line_no', None)
                  if line_no_checkpoints is not None else None)
        if line_no is not None:
            label, gx = line_no
            _, gutter_family, gutter_size, _ = _span_render('', (), fonts, size)
            gutter_font = res.ref(gutter_family)
            ops.append(b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET'
                      % (gutter_font.encode(), gutter_size, gx, y, label.encode()))
        segs = []
        for text, styles in _coalesce(line):
            if not text:
                continue
            written, family, size_here, entry = _span_render(
                text, styles, fonts, size)
            segs.append((written, styles, family, size_here, entry))
        ops += _line_ops_printed(segs, left_here, y, size, res, tz_state,
                                 col_state, colour_map or {}, roll_here,
                                 getattr(line, 'fi', None), ul_continuous,
                                 pcl_programs, page_h,
                                 getattr(line, 'kerning', True),
                                 getattr(line, 'justify_right_x', None),
                                 getattr(line, 'justify_word_x', None))
    return b'\n'.join(ops)


# ---- Modern layout: the printed form of the Modern RTF ---------------------
#
# Ruled 2026-08-05: "Modern PDF needs to be the printed version of Modern
# RTF." One content model for the Modern column -- the RTF model (reflowed,
# document fonts carried, footnotes anchored) -- with PDF as its paper
# rendering. Everything here mirrors what Word does when you print the RTF:
# proportional wrap at the real measure, single spacing by the line's own
# type size, footnotes at the page bottom, paragraph gaps, .pa honored.
# Fontless text is base-14 Times at the sophisticated size (Georgia has no
# base-14 seat; "the PDF needs to work no matter what").

MODERN_BODY_PT = 14           # the sophisticated size (Jon's specimen ruling)
MODERN_NOTE_PT = 11
MODERN_LINE = 1.2             # single-spacing: baseline advance = 1.2 x size


def _modern_geometry(doc):
    """(left, top_margin, bottom_margin, text_width) in points. The
    document's declared geometry wins (governing principle); silence is the
    modern page: 1in margins on Letter. The right margin is always 1in --
    WordStar's right edge is a text measure, not a page property."""
    page = doc.meta.get('page') or {}
    margt = (float(page.get('mt_lines', 6.0)) * 12.0
             if page.get('mt_source', 'default') != 'default' else 72.0)
    margb = (float(page.get('mb_lines', 6.0)) * 12.0
             if page.get('mb_source', 'default') != 'default' else 72.0)
    margl = (float(page.get('po_cols', 10.0)) * 7.2
             if page.get('po_source', 'default') != 'default' else 72.0)
    page_w = float(page.get('pw_in', 8.5)) * 72.0     # A4 files are narrower
    return margl, margt, margb, max(144.0, page_w - margl - 72.0)


def _modern_tok_font(text, styles, fonts, nonprop_fallback=False):
    """(written, family, pt, entry) for one modern token. _span_render does
    the real work (untransliteration, entry sizes); the one modern rule on
    top: a token with NO font information reads in Times at the
    sophisticated size, never Courier -- the typescript aesthetic lives
    only in Printed now.

    `nonprop_fallback` (planning #252, Jon's ruling 2026-09-09 verbatim):
    the ONE exception to that rule. A document can carry font blocks
    elsewhere (so this run's own lack of one is a real gap, not a fontless
    document) AND separately declare itself non-proportional at the
    document level (`.ps off`, WSFORMAT register C19 -- core.py's
    `doc.meta['formatting']['proportional'] is False`, the SAME flag round
    9 already found and deliberately left unhonoured -- see info.py's
    `ps_note`). Round 9's ruling stands for every run a real font block DOES
    cover (`_pdf_family`'s own `entry['proportional'] is False` check,
    unchanged); this is only the uncovered-run fallback, which round 9
    never addressed because Modern's own Times-fallback didn't exist to
    ask the question of until this round. Caller resolves `nonprop_fallback`
    ONCE per document (`bool(doc.fonts) and doc.meta['formatting'].get(
    'proportional') is False`) -- a document with zero font blocks anywhere
    stays Times regardless of `.ps`, matching the ruling's explicit "no
    fonts -> Times (unchanged)"."""
    written, family, pt, entry = _span_render(text, styles, fonts,
                                              MODERN_BODY_PT)
    if entry is None:
        family = 'Courier' if nonprop_fallback else 'Times'
    return written, family, pt, entry


def _modern_w(text, styles, family, pt, entry, printed_pt):
    """A token's advance in points under modern layout: natural face widths
    (face-scaled for entries, straight AFM for fontless Times), the fixed
    grid only where a fixed-pitch font block asks for it.

    `printed_pt` (planning #254, 2026-09-10): the document's OWN fixed-pitch
    type size (`_printed_size(doc)`), never the Modern reading size -- a
    graphic character (box-drawing, block, shade) draws on the Printed
    fixed-pitch cell REGARDLESS of a resolved font entry's own `proportional`
    flag (WordStar counted a `.cw`-pitch column grid for these glyphs no
    matter what printer face the document declared; Modern's reading face
    is irrelevant to that count -- Jon's ruling). Before this fix, a
    fontless run (`entry is None`, every WS4 file and any run before a
    WS5+ document's first font-change record) advanced graphic cells at the
    Modern BODY size (14pt) instead: -README's 65-column `=` rule measured
    65*14 = 910pt in a 468pt measure, 370pt past the sheet's right edge.
    `_span_pitch(entry, printed_pt)` already ignores `printed_pt` entirely
    once `entry` carries its own `width_1800` (a real WS5+ font block), so
    this same call is correct for a resolved fixed-pitch OR proportional
    entry too -- passing `printed_pt` here (not `spt`) only changes the
    FALLBACK branch (`entry is None`), which is exactly the shape that was
    wrong."""
    spt, _rise = _sized(styles, pt)
    basefont = BASE14[family][('b' in styles) + 2 * ('i' in styles)]
    if set(text) & GRAPHIC_CHARS:
        # mixed tokens split into graphic runs (cell advance) and text
        # (natural), same rule as printed's _split_graphics. FONTLESS spans
        # take this path too under Modern (round 3, 2026-08-06): a cp437
        # box/block glyph has no cp1252 slot, and '?' is nobody's take --
        # the geometry IS the glyph. Printed keeps its fontless-untouched
        # doctrine; Modern draws the shape at the em advance.
        total = 0.0
        pitch = _span_pitch(entry, printed_pt)
        pos = 0
        for m in _GRAPHIC_RUN.finditer(text):
            if m.start() > pos:
                total += _modern_w(text[pos:m.start()], styles, family, pt,
                                   entry if not (set(text[pos:m.start()])
                                                 & GRAPHIC_CHARS) else entry,
                                   printed_pt)
            total += len(m.group(0)) * pitch
            pos = m.end()
        if pos < len(text):
            total += _modern_w(text[pos:], styles, family, pt, entry, printed_pt)
        return total
    if entry is not None and not entry.get('proportional'):
        return len(text) * _span_pitch(entry, spt)
    nat = _natural_width_pt(text, basefont, spt)
    if entry is not None:
        return nat * _face_tz(basefont, _span_pitch(entry, spt), spt) / 100.0
    return nat


def _modern_flow(doc, keep, note_refs='word', pix_results=None,
                 pictures='off', text_width_pt=0.0, sentence_spacing=False,
                 record_sem_index=None):
    """The MEASURED Modern flow: layout.modern_flow's semantic items (the
    single implementation of the M-rules -- see layout.py's contract)
    converted to this emitter's tuples:
        ('para', toks, align, [(note_row, label)...], indent_pt, cut_pt,
         no_wrap, page_marker, end_notes_start)
        ('blank', height) | ('break',) | ('cond', n)
        ('hf', 'H'|'F', line_no, text)
        ('image', pix_index, w_pt, h_pt)
    A tok is (text, styles, family, pt, entry, width). This adapter adds
    exactly what a PDF needs -- font resolution, AFM widths, points -- and
    decides nothing about WHAT renders: that is layout.py's job, shared
    with the app's native text stack and the `layout` JSON emitter.

    `pix_results`/`pictures` (round 22, closing round 19's documented
    Modern scope cut): a para whose runs are exactly one resolved, decoded
    pix placeholder becomes an ('image', ...) item, sized by the same
    shared rule as the Printed paths (`_pix_dims_pt`: print-options record
    when present, else fit to `text_width_pt` at source aspect, capped at
    the measure). A run carrying a note reference counts as real content
    (anchors are never silently dropped), so such a line keeps its
    placeholder text -- same never-drop rule as `_spans_pix_substitution`.

    `sentence_spacing` (N9, b33 field notes): pre-resolved bool (True =
    'single'), applied to `it['runs']` text HERE, in this PDF-only
    adapter, never inside `_layout.modern_flow` itself -- the shared
    layout.py model (this function's own `sem`) is also the `layout` JSON
    emitter's contract, and that schema does not move for this ruling
    (register: schema moves only when both engines move together). The
    JSON emitter therefore always serializes the document's own
    unconverted text; a consumer (this adapter, the app's native text
    stack) applies sentence-spacing on top, same as every other emit_*
    option that never reaches layout.py's semantic items.

    `record_sem_index` (planning #251 follow-up, 2026-09-10): a list, or
    None. When given, one entry is appended per element of the RETURNED
    flow, in order -- the index into `sem['items']` (this function's own
    `_layout.modern_flow(doc, ...)` result) that produced it. `'tabs'` is
    the one `sem['items']` entry that produces NO flow entry at all (an
    editor-time-only item, `continue`d before any append below) -- every
    other kind appends exactly one flow entry per `sem['items']` entry, in
    the same order, so this is pure bookkeeping alongside the existing
    loop, never a parallel re-derivation of what that loop already
    decides. `_attach_graphic_cells_modern` uses it to attribute a
    wrapped/paginated visual line's own graphic cells back to the
    semantic item the `layout` JSON's own `modern['items']` array will
    serialize it against."""
    embed_images = pictures in ('embed', 'export') and pix_results
    pix_map = {r.index: r for r in (pix_results or [])} if embed_images else {}
    # planning #254: the document's own fixed-pitch size, for a graphic
    # character's cell advance ONLY (`_modern_w`'s own `printed_pt` doc) --
    # never the Modern reading size.
    printed_pt = _printed_size(doc)
    sem = _layout.modern_flow(doc, notes=keep, note_refs=note_refs)
    note_rows = sem['notes']
    col_pt = float((doc.meta.get('page') or {}).get('cw_120', 12.0)) * 0.6
    blank_h = MODERN_LINE * MODERN_BODY_PT
    # b26-modern item 3: computed once, not per-line -- detect_screenplay_
    # blocks already walks the whole document itself.
    screenplay_blocks = _detect_screenplay_blocks(doc)
    # The page-marker rule (a)/(b) needs one more block index than
    # `screenplay_blocks` itself carries: a real screenplay's own page-
    # number marker sits BEFORE its scene's slugline (SCRIPT.WS's own
    # shape -- block 75, "1." -- immediately precedes block 76, the
    # slugline that anchors the detected region), but
    # detect_screenplay_blocks's region growth is documented to extend
    # only FORWARD from its slugline anchor, never backward, so the
    # marker's own block index is never a member of `screenplay_blocks`.
    # Widen candidacy by one or two blocks forward (covering an
    # intervening blank-only block) rather than touching the shared
    # detector's own region-growth rule, which carries its own zero-
    # false-positive corpus gate this wave must not risk.
    screenplay_marker_bis = {bi for bi in range(len(doc.blocks))
                             if bi + 1 in screenplay_blocks
                             or bi + 2 in screenplay_blocks} if screenplay_blocks else frozenset()
    # planning #252 (Jon's ruling 2026-09-09): resolved ONCE per document,
    # not per token -- see _modern_tok_font's own docstring for the full
    # reasoning. `doc.fonts` non-empty means the document really does
    # declare fonts somewhere (an uncovered run here is a real gap); the
    # `.ps off` flag is the document-level non-proportional declaration
    # round 9 already parsed but never wired to a consumer.
    nonprop_fallback = (bool(doc.fonts)
                        and doc.meta.get('formatting', {}).get('proportional') is False)
    flow = []

    def _emit(entry, _sem_i):
        flow.append(entry)
        if record_sem_index is not None:
            record_sem_index.append(_sem_i)

    for sem_i, it in enumerate(sem['items']):
        k = it['kind']
        if k == 'blank':
            _emit(('blank', blank_h), sem_i)
        elif k == 'break':
            _emit(('break',), sem_i)
        elif k == 'cond':
            _emit(('cond', it['lines']), sem_i)
        elif k == 'hf':
            _emit(('hf', it['which'], it['line'], it['text']), sem_i)
        elif k == 'tabs':
            continue          # editor-time state: no rendered consequence
        elif k == 'note-separator':
            sep_w = _natural_width_pt(FOOTNOTE_SEPARATOR, 'Times-Roman',
                                      MODERN_NOTE_PT)
            # `end_notes_start=True`: this is the ONE item that opens the
            # end-matter appendix (layout.py's `modern_flow` emits exactly
            # one 'note-separator', always immediately before the first
            # 'note' item, when `end_rows` is non-empty) -- Jon's ruling
            # 2026-09-07 fires here, in `_modern_streams`.
            _emit(('para', [(FOOTNOTE_SEPARATOR, frozenset(), 'Times',
                            MODERN_NOTE_PT, None, sep_w)],
                  'left', [], 0.0, 0.0, False, False, True), sem_i)
        elif k == 'note':
            note_text = (_sentence_spacing_texts([it['text']])[0]
                        if sentence_spacing else it['text'])
            _emit(('para', _modern_note_toks(it['label'], note_text,
                                             it['note_kind']),
                  'left', [], 0.0, 0.0, False, False, False), sem_i)
        else:                                                   # para
            if embed_images and not any('ref' in r for r in it['runs']):
                sub = _spans_pix_substitution(
                    [(r['text'], r['styles']) for r in it['runs']],
                    pix_map, text_width_pt)
                if sub is not None:
                    _emit(('image',) + sub, sem_i)
                    continue
            toks = []
            # N9: applied to the run texts, in order, same cross-piece
            # state-carrying as every other emitter's own choke point --
            # the pix-substitution check above already ran on the RAW
            # runs (a structural placeholder match, not prose).
            run_texts = (_sentence_spacing_texts([r['text'] for r in it['runs']])
                        if sentence_spacing else [r['text'] for r in it['runs']])
            for run, run_text in zip(it['runs'], run_texts):
                styles = frozenset(run['styles'])
                if 'ref' in run:
                    if not run_text:
                        # a zero-width comment anchor (round 22, layout.py's
                        # run contract): position data for Show Invisibles,
                        # no ink on paper -- skipping it keeps Modern PDF
                        # bytes exactly what they were
                        continue
                    marker = (run_text, styles, 'Times', MODERN_BODY_PT,
                              None)
                    toks.append(marker + (_modern_w(*marker, printed_pt),))
                    continue
                for m in _MODERN_TOK_RE.finditer(run_text):
                    written, family, pt, entry = _modern_tok_font(
                        m.group(0), styles, doc.fonts, nonprop_fallback)
                    # b26-modern item 4 (2026-09-07): a token whose family
                    # isn't already Symbol/ZapfDingbats may still carry
                    # cp437 Greek/math/Dingbats bytes cp1252 can't encode --
                    # same fallback Printed's _split_symbol_fallback applies,
                    # factored out so both paths share one answer.
                    if family in ('Symbol', 'ZapfDingbats'):
                        fb_pieces = ((written, family),)
                    else:
                        fb_pieces = _symbol_fallback_split(written, family)
                    for piece, piece_family in fb_pieces:
                        w = _modern_w(piece, styles, piece_family, pt, entry,
                                     printed_pt)
                        toks.append((piece, styles, piece_family, pt, entry, w))
            # b26-modern item 3 (screenplay ruling): only lines inside a
            # DETECTED screenplay region (or immediately preceding one,
            # for the page-marker case -- see screenplay_marker_bis
            # above) are even candidates -- an ordinary document's own
            # numbered list or table never qualifies, same discipline as
            # emit.py's own `bi in screenplay_blocks` gate.
            align = it['align']
            no_wrap = page_marker = False
            bi = it.get('bi')
            if bi in screenplay_blocks or bi in screenplay_marker_bis:
                visible = ''.join(r['text'] for r in it['runs']
                                  if 'ref' not in r)
                if _SCREENPLAY_PAGE_MARKER_RE.match(visible):
                    # "1." alone at the top of a real screenplay page:
                    # render flush against the right margin, below the
                    # header -- rule (b). Leading whitespace tokens stay in
                    # `toks` untouched: _modern_line_ops's own right-align
                    # spends them as blank advance before the visible
                    # glyph, landing it flush regardless of how much
                    # leading space the source typed.
                    page_marker = True
                    align = 'right'
                elif (bi in screenplay_blocks
                      and _SCREENPLAY_SLUGLINE_RE.match(visible)
                      and _SCREENPLAY_TRAILING_SCENE_NUM_RE.search(visible)):
                    # A slugline carrying its own right-hand scene number
                    # (real screenplay convention: the number repeats at
                    # both margins) must never wrap the number onto its
                    # own line -- rule (c). `_modern_streams` gives this
                    # line an unbounded wrap width instead of reflowing
                    # per-token widths differently. (bi in screenplay_
                    # blocks specifically -- a marker-lookahead block is
                    # never also a slugline.)
                    no_wrap = True
            notes = [(note_rows[ni], label) for ni, label in it['footnotes']]
            _emit(('para', toks, align, notes,
                  it['indent_cols'] * col_pt,
                  it['cut_cols'] * col_pt, no_wrap, page_marker, False), sem_i)
    return flow


def _modern_wrap(toks, width):
    """Greedy wrap of one logical line's tokens -> visual lines. Leading
    whitespace stays (paragraph indent); a space token at a wrap point is
    swallowed, exactly as any renderer would."""
    lines, cur, curw = [], [], 0.0
    for tok in toks:
        text, w = tok[0], tok[5]
        if cur and curw + w > width and text.strip():
            lines.append(cur)
            cur, curw = [], 0.0
        if not cur and not text.strip() and lines:
            continue                      # swallow the wrap-point space
        cur.append(tok)
        curw += w
    if cur or not lines:
        lines.append(cur)
    return lines


def _modern_note_toks(label, text, kind='footnote'):
    """One note as its Modern entry tokens, Times MODERN_NOTE_PT.

    Footnote/endnote entries (ruling 2026-08-23/24, Jon verbatim: "1.
    Footnoote. and i. Endnote. No brackets. No superscript"): `LABEL. text`
    -- `label` arrives here already in its final display form (arabic for
    a footnote, lower-roman for an endnote under the `word` scheme -- see
    layout.py's `endnote_label`/`_shown_labels`), so this only has to drop
    the brackets in favour of a period. Annotation/comment entries are
    UNCHANGED by that ruling (it named only footnote/endnote appearance)
    and keep the pre-existing `[label]` bracket form -- their label is a
    WordStar tag or a running count, not a number, and nothing in the
    register asked for their look to change.
    """
    text = ('%s. %s' % (label, text) if kind in ('footnote', 'endnote')
            else '[%s] %s' % (label, text))
    toks = []
    for m in _re.finditer(r' +|[^ ]+', text):
        w = _natural_width_pt(m.group(0), 'Times-Roman', MODERN_NOTE_PT)
        toks.append((m.group(0), frozenset(), 'Times', MODERN_NOTE_PT, None, w))
    return toks


def _modern_note_lines(label, text, width, kind='footnote'):
    """A page-bottom note as wrapped visual lines of Times MODERN_NOTE_PT."""
    return _modern_wrap(_modern_note_toks(label, text, kind), width)


def _modern_hf_ops(txt, page_no, left, y, width, res, tz_state, printed_pt):
    """One modern running-head/foot line: Times MODERN_NOTE_PT in the margin
    zone, WordStar's `#` token as the page number (same rule as printed:
    `.op` never suppresses an explicit `#`). The header keeps its own baked
    spaces -- that is how a 1990 head positioned its parts, and a running
    head is a page fixture, not reflowing text. Raw toggle bytes in the
    stored head (`^B` bold and friends -- LJ6DTP's `.h1`) are interpreted
    as styles via emit.hf_runs, so measurement and drawing agree; letters
    overlapped when the toggles were measured as glyphs (round 3).

    `printed_pt` (planning #254): threaded to `_modern_line_ops` only for
    the graphic-cell cases neither header nor footer text has ever been
    observed to carry -- see that parameter's own docstring."""
    toks = []
    for run_text, styles in _hf_runs(txt):
        run_text = run_text.replace('#', str(page_no))
        for m in _re.finditer(r' +|[^ ]+', run_text):
            basefont = BASE14['Times'][('b' in styles) + 2 * ('i' in styles)]
            w = _natural_width_pt(m.group(0), basefont, MODERN_NOTE_PT)
            toks.append((m.group(0), styles, 'Times', MODERN_NOTE_PT, None, w))
    if not toks:
        return []
    return _modern_line_ops(toks, left, y, width, 'left', res, tz_state,
                            printed_pt)


def _modern_line_ops(toks, left, y, width, align, res, tz_state, printed_pt,
                     record_graphic_cells=None):
    """Content-stream ops for one modern visual line. One op per word keeps
    a viewer's substitute-metric drift bounded, same as printed.

    `printed_pt` (planning #254, 2026-09-10): the document's own fixed-pitch
    type size (`_printed_size(doc)`) -- see `_modern_w`'s own docstring for
    the full rule and the bug this closes (a graphic row's own cell advance
    must never depend on the Modern reading size). Threaded (not recomputed
    -- no `doc` reaches this function) from every real caller: `_modern_
    streams` (body/footnote lines) and `_modern_hf_ops` (running heads/
    feet), and through this function's own recursive sub-calls below so a
    graphic run split across several sub-calls always agrees with the piece
    that measured it in `_modern_w`.

    `record_graphic_cells` (planning #251 follow-up, 2026-09-10): same
    contract as `_line_ops_printed`'s parameter of the same name -- None
    to record nothing (every ordinary render call), a real list to
    EXTEND with this call's own cp437 graphic-character placements
    (never cleared first: a caller collecting across several calls, as
    `_attach_graphic_cells_modern` does across a paragraph's own wrapped
    visual lines, gets one running list). Threaded through this
    function's own recursive sub-calls (the non-graphic pieces flanking
    a graphic run) for the same reason those sub-calls never themselves
    append anything: a piece `_GRAPHIC_RUN` extracts BETWEEN two runs is,
    by construction, never itself a graphic run."""
    lw = sum(t[5] for t in toks)
    while toks and not toks[-1][0].strip():
        lw -= toks[-1][5]
        toks = toks[:-1]
    x = left
    if align == 'center':
        x += max(0.0, (width - lw) / 2)
    elif align == 'right':
        x += max(0.0, width - lw)
    ops = []
    for text, styles, family, pt, entry, w in toks:
        spt, rise = _sized(styles, pt)
        basefont = BASE14[family][('b' in styles) + 2 * ('i' in styles)]
        font = res.ref(basefont)
        if set(text) & GRAPHIC_CHARS:
            # split mixed tokens: graphic runs draw as vectors at the cell
            # advance, interleaved text renders through the normal path
            # (fontless spans included under Modern -- round 3, 2026-08-06)
            pitch = _span_pitch(entry, printed_pt)
            pos, gx = 0, x
            for m in _GRAPHIC_RUN.finditer(text):
                if m.start() > pos:
                    piece = text[pos:m.start()]
                    pw = _modern_w(piece, styles, family, pt, entry, printed_pt)
                    ops += _modern_line_ops(
                        [(piece, styles, family, pt, entry, pw)],
                        gx, y, width, 'left', res, tz_state, printed_pt,
                        record_graphic_cells=record_graphic_cells)
                    gx += pw
                run = m.group(0)
                # b32: Modern's own line-to-line advance is exactly
                # `MODERN_LINE * pt` (`_modern_flow`'s own `h`) -- pass it
                # as the glyph cell's height too, so a box-drawing arm's
                # vertical stroke chains continuously across physical
                # lines instead of leaving `_graphic_ops`'s Printed-tuned
                # default gap (see `_graphic_ops`'s own docstring).
                ops += _graphic_ops(run, gx, y, pitch, spt,
                                    lead_factor=MODERN_LINE)
                # planning #251 follow-up (2026-09-10): the model's own
                # per-cell x/width -- same "recorded here, the ONE place
                # this run's per-character cell positions are ever
                # computed" precedent `_line_ops_printed`'s own
                # `record_graphic_cells` doc states. `pitch` (planning #254)
                # is always `_span_pitch`'s own float now, entry or no --
                # the old int/float split this comment used to describe
                # tracked a since-removed branch that advanced a fontless
                # run's graphic cells at the Modern reading size instead.
                if record_graphic_cells is not None:
                    record_graphic_cells.extend(
                        (ch, gx + i * pitch, pitch) for i, ch in enumerate(run))
                gx += len(run) * pitch
                pos = m.end()
            if pos < len(text):
                piece = text[pos:]
                pw = _modern_w(piece, styles, family, pt, entry, printed_pt)
                ops += _modern_line_ops(
                    [(piece, styles, family, pt, entry, pw)],
                    gx, y, width, 'left', res, tz_state, printed_pt,
                    record_graphic_cells=record_graphic_cells)
            x += w
            continue
        if text.strip():
            if entry is not None and not entry.get('proportional'):
                want, _w = _tz_scale(text, basefont, spt,
                                     len(text) * _span_pitch(entry, spt))
                want = TZ_DEFAULT if want is None else round(want, 2)
            elif entry is not None:
                want = _face_tz(basefont, _span_pitch(entry, spt), spt)
            else:
                want = TZ_DEFAULT
            if want == tz_state[0]:
                ops.append(b'BT /%s %d Tf %d Ts %.1f %.1f Td (%s) Tj ET' %
                           (font.encode(), spt, rise, x, y, _esc(text)))
            else:
                ops.append(b'BT /%s %d Tf %d Ts %.2f Tz %.1f %.1f Td (%s)'
                           b' Tj ET' %
                           (font.encode(), spt, rise, want, x, y, _esc(text)))
                tz_state[0] = want
        ops += _rules(styles, text, x, y, w)
        x += w
    return ops


def _modern_streams(doc, options, res, attach_graphic_cells=None):
    """All page content streams for Modern mode.

    `attach_graphic_cells` (planning #251 follow-up, 2026-09-10): same
    contract as `_attach_graphic_cells_printed`'s own `_line_ops_printed`
    call -- None for every ordinary render (`emit_pdf`'s own call), a
    real (empty) dict for `_attach_graphic_cells_modern`'s throwaway
    pass, which this function fills keyed by `sem['items']` index (see
    the `body` tuple's own 6th field below) with every graphic cell that
    paragraph's own wrapped visual lines draw, in document order, ACROSS
    however many visual lines/pages that paragraph's own non-wrapping
    graphic run actually lands on -- the SAME `_modern_line_ops` call the
    real content stream is built from, so the values are exactly what
    the PDF draws, never a parallel re-derivation.

    Scope: body paragraphs, and the end-matter appendix's own endnote/
    annotation entries (both flow through `body` below) -- a FOOTNOTE's
    own text is collected and drawn through the separate `notes_lines`/
    `nlines` mechanism, which carries no `sem['items']` identity, so a
    graphic character inside a footnote's own text (not observed
    anywhere in the public corpus) is not attached; this mirrors
    `layout` JSON's own existing choice to leave raw headers/footers
    unresolved onto `PageLine` (`header_lines`/`footer_lines`, planning
    #251(d), are the separate, already-resolved answer for those)."""
    keep = frozenset(options.get('notes', ())) or frozenset(
        ('footnote', 'endnote', 'annotation'))
    margl, margt, margb, width = _modern_geometry(doc)
    # planning #254: threaded to every `_modern_line_ops`/`_modern_hf_ops`
    # call below -- see `_modern_w`'s own docstring.
    printed_pt = _printed_size(doc)
    # N9 (b33 field notes): this function only ever runs the Modern path
    # (printed=False by construction -- `_emit_pdf_inner`'s own `else`
    # branch), so 'auto' always resolves to single here.
    ss_on = _resolve_sentence_spacing(options.get('sentence_spacing', 'auto'), False)
    sem_index_of_item = [] if attach_graphic_cells is not None else None
    flow = _modern_flow(doc, keep, options.get('note_refs') or 'word',
                        pix_results=options.get('pix_results'),
                        pictures=options.get('pictures', 'off'),
                        text_width_pt=width, sentence_spacing=ss_on,
                        record_sem_index=sem_index_of_item)
    note_lead = MODERN_LINE * MODERN_NOTE_PT
    sep_h = note_lead

    pages = []            # each: (body, [note lines], headers, footers)
    body, notes_lines, seen_notes = [], [], set()
    y = PAGE_H - margt
    cur_h, cur_f = {}, {}          # running-head state as events replay
    page_h, page_f = {}, {}        # state when the OPEN page took content
    opened = False
    # b26-modern item 4: a blank line's own advance must scale with the
    # SURROUNDING text's font size, same principle as Printed's established
    # "a blank advances at the preceding block's own leading" rule
    # (test_style_leading.py) -- Modern already computes each real line's
    # own size-proportional `h` (MODERN_LINE * that line's own max token
    # size) below, but a 'blank' item used to carry a FIXED height baked at
    # flow-build time (MODERN_LINE * MODERN_BODY_PT, the 14pt document
    # default) regardless of what was actually on the page. Measured on
    # PREVIEW.WS (real corpus, font-sample page mixing 24pt/20pt/12pt
    # lines): a blank between two 24pt lines advanced by the SAME fixed
    # 16.8pt a blank between a 24pt and an 8pt line would -- the total
    # inter-paragraph gap tracked only the ENTERING line's own size, never
    # the size actually being LEFT, so two structurally-identical "one
    # blank line" transitions produced visibly different gaps whenever the
    # preceding line's size differed. Fix: track the most recently placed
    # line's own `h` and use THAT for the next blank, falling back to the
    # 14pt default only when nothing has been placed yet (unchanged
    # behavior for a leading blank).
    last_h = MODERN_LINE * MODERN_BODY_PT

    def note_block_h():
        return (sep_h + note_lead * len(notes_lines)) if notes_lines else 0.0

    def open_page():
        # the page's running heads are the state in force when it takes its
        # first content -- OLDTIMES defines .h1 after page 1's title, and a
        # manuscript has no running head on page 1 (same rule as printed)
        nonlocal opened, page_h, page_f
        if not opened:
            page_h, page_f = dict(cur_h), dict(cur_f)
            opened = True

    def close():
        nonlocal body, notes_lines, y, opened
        open_page()
        pages.append((body, list(notes_lines), page_h, page_f))
        body, notes_lines[:] = [], []
        y = PAGE_H - margt
        opened = False

    for fi, item in enumerate(flow):
        sem_i = sem_index_of_item[fi] if sem_index_of_item is not None else None
        if item[0] == 'hf':
            _, kind, lno, txt = item
            (cur_h if kind == 'H' else cur_f)[lno] = txt
            continue
        if item[0] == 'break':
            close()
            continue
        if item[0] == 'cond':
            need = item[1] * MODERN_LINE * MODERN_BODY_PT
            if body and y - (margb + note_block_h()) < need:
                close()
            continue
        if item[0] == 'blank':
            if not body:
                continue                      # no blank at a page top
            h = last_h
            if y - h < margb + note_block_h():
                close()
                continue
            y -= h
            continue
        if item[0] == 'image':
            # Round 22 (closing round 19's Modern scope cut): an embedded
            # pix image spends its own height against the page exactly as
            # a body line does; the drawing loop below paints its XObject
            # with the bottom edge at the y this advance lands on (same
            # convention as Printed's `_page_stream`).
            #
            # b27-WP3 item 4: `last_h` is exclusively a TEXT-leading memory
            # -- the height a following 'blank' item should reuse (see the
            # 'blank' case above). An image's own height is a page-space
            # cost, not a leading, so it must NEVER be written into
            # `last_h`: doing so let a blank run immediately after an
            # image inherit the image's height instead of the surrounding
            # text's leading (measured on -README.WS: an inline image
            # 73.9pt tall followed by 7 blank source lines advanced
            # 7 x 73.9 = 517.3pt instead of the correct 7 x 16.8 = 117.6pt
            # 14pt-body leading). `last_h` is left exactly as it was --
            # the most recently placed TEXT line's own leading, or the
            # 14pt default if no text has been placed yet.
            _, pix_idx, w_pt, h_pt = item
            if body and y - h_pt < margb + note_block_h():
                close()
            open_page()
            y -= h_pt
            body.append((y, item, 'left', 0.0, 0.0, sem_i))
            continue
        _, toks, align, notes, indent, cut, no_wrap, page_marker, end_notes_start = item
        if page_marker and body:
            # b26-modern item 3, rule (a): a real screenplay page-number
            # marker starts a new real page -- if this Modern page already
            # has content on it (no explicit .pa immediately preceded this
            # marker, the ordinary case), force the break here instead of
            # letting the marker land mid-page. A marker that is already
            # the first thing on a fresh page (an explicit .pa DID
            # precede it, SCRIPT.WS's own shape) costs nothing extra --
            # `close()` on an empty page would just insert a spurious
            # blank one, so this only fires when there is something to
            # separate FROM.
            close()
        if end_notes_start and body and notes_lines:
            # Jon's ruling 2026-09-07 (RULINGS-LEDGER.md verbatim): "endnotes
            # go right at the end of text / image on the last page unless
            # there are footnotes on that page. Then the endnotes start on a
            # new page." Endnotes are never interleaved with a footnote
            # block. `notes_lines` is exclusively footnote text here
            # (layout.py's own M1 split: footnote -> the per-paragraph
            # page-bottom area; endnote/annotation -> `end_rows`, collected
            # into this ONE 'note-separator'-opened appendix) -- non-empty
            # means the CURRENT page already carries at least one footnote,
            # so the appendix starts fresh instead of continuing directly
            # after the last body line/image. `body` guards the same way
            # `page_marker`'s check does: a fresh, still-empty page needs no
            # extra break (nothing to separate FROM).
            close()
        # rule (c): a screenplay slugline carrying its own right-hand scene
        # number never wraps -- an unbounded width means _modern_wrap's
        # greedy break condition (`curw + w > width`) can never trigger,
        # so the whole line places as ONE visual line regardless of its
        # natural width, exactly as real screenplay software keeps a
        # slugline unbroken.
        line_w = _math.inf if no_wrap else max(36.0, width - indent - cut)
        vis = _modern_wrap(toks, line_w)
        new_note_lines = []
        for note, label in notes:
            if id(note) in seen_notes:
                continue
            note_text = (_sentence_spacing_texts([note['text']])[0]
                        if ss_on else note['text'])
            new_note_lines += _modern_note_lines(label, note_text, width,
                                                  note['kind'])
        for vi, vline in enumerate(vis):
            h = MODERN_LINE * max([_sized(t[1], t[3])[0] for t in vline]
                                  or [MODERN_BODY_PT])
            extra = ((sep_h if not notes_lines else 0.0)
                     + note_lead * len(new_note_lines)) if (vi == 0 and
                                                            new_note_lines) else 0.0
            if body and y - h < margb + note_block_h() + extra:
                close()
            open_page()
            y -= h
            last_h = h
            body.append((y, vline, align, indent, cut, sem_i))
            if vi == 0 and new_note_lines:
                notes_lines.extend(new_note_lines)
                for note, label in notes:
                    seen_notes.add(id(note))
                new_note_lines = []
    close()
    while len(pages) > 1 and not pages[-1][0] and not pages[-1][1]:
        pages.pop()

    streams = []
    start_no = int((doc.meta.get('page') or {}).get('pn_start', 1))
    for pi, (body, nlines, hdrs, ftrs) in enumerate(pages):
        tz_state = [TZ_DEFAULT]
        ops = []
        page_no = start_no + pi
        # running heads live in the margin zones: header lines walk down
        # from ~0.6in off the top edge, footer lines sit ~0.6in off the
        # bottom -- inside Modern's 1in margins, clear of the body
        for lno in sorted(hdrs):
            if not hdrs[lno]:
                continue
            hy = PAGE_H - 44.0 - (lno - 1) * note_lead
            ops += _modern_hf_ops(hdrs[lno], page_no, margl, hy, width,
                                  res, tz_state, printed_pt)
        for lno in sorted(ftrs):
            if not ftrs[lno]:
                continue
            fy = max(8.0, 44.0 - (lno - 1) * note_lead)
            ops += _modern_hf_ops(ftrs[lno], page_no, margl, fy, width,
                                  res, tz_state, printed_pt)
        for y, toks, align, indent, cut, sem_i in body:
            if isinstance(toks, tuple) and toks and toks[0] == 'image':
                _, pix_idx, w_pt, h_pt = toks
                ops.append(b'q %.2f 0 0 %.2f %.2f %.2f cm /Im%d Do Q'
                           % (w_pt, h_pt, margl, y, pix_idx))
                continue
            line_cells = [] if attach_graphic_cells is not None else None
            ops += _modern_line_ops(list(toks), margl + indent, y,
                                    max(36.0, width - indent - cut),
                                    align, res, tz_state, printed_pt,
                                    record_graphic_cells=line_cells)
            if sem_i is not None and line_cells:
                attach_graphic_cells.setdefault(sem_i, []).extend(
                    (ch, x, w, page_no) for ch, x, w in line_cells)
        if nlines:
            block = [None] + nlines           # None = the separator rule
            total = len(block)
            for i, ln in enumerate(block):
                ly = margb + note_lead * (total - 1 - i)
                if ln is None:
                    f = res.ref('Times-Roman')
                    ops.append(b'BT /%s %d Tf 0 Ts %.1f %.1f Td (%s) Tj ET' %
                               (f.encode(), MODERN_NOTE_PT, margl, ly,
                                _esc(FOOTNOTE_SEPARATOR)))
                else:
                    # Footnote text: no `sem['items']` identity to attach
                    # to (see this function's own doc comment) -- always
                    # discarded.
                    ops += _modern_line_ops(list(ln), margl, ly, width,
                                            'left', res, tz_state, printed_pt)
        streams.append(b'\n'.join(ops))
    return streams


@emitter('pdf')
def emit_pdf(doc, mode='printed', **options):
    """Assemble the PDF: catalog, page tree, the font table (the Courier four
    always, plus whatever base-14 faces a document's own font runs reached
    for), one content stream per page, xref. Returns bytes — PDF is a binary
    format.

    `page_settings` (option): {'mt_lines': .., 'mb_lines': .., 'po_cols': ..,
    'hm_lines': .., 'fm_lines': ..} -- replacement DEFAULTS for geometry the
    document does not declare itself (a field is overridden only when its
    *_source is 'default'; a document's own dot commands always win). The CLI
    resolves its --page-settings flag (presets `default`/`sawyer`/`modern`,
    or raw values) into this dict. Named "Page Settings" at every layer by
    ruling (2026-08-05)."""
    printed = mode == 'printed' or _printed(doc)
    page_settings = options.get('page_settings')
    saved_page = None
    if doc.meta.get('page') is not None:
        page = doc.meta['page']
        if page_settings:
            from .core import effective_page
            page = effective_page(page, page_settings)
        # round 17 (RULINGS-LEDGER row 2): `.pr or=l` -- Printed only, same
        # doctrine as every other Printed-only geometry item.
        if printed and doc.meta.get('formatting', {}).get('orientation') == 'landscape':
            page = _landscape_page(page)
        if page is not doc.meta['page']:
            saved_page = doc.meta['page']
            doc.meta['page'] = page
    try:
        return _emit_pdf_inner(doc, printed, options)
    finally:
        if saved_page is not None:
            doc.meta['page'] = saved_page


def _emit_pdf_inner(doc, printed, options):
    # round 17 (RULINGS-LEDGER row 1): the "+ toggle flag" half of the
    # headers/footers/page-numbers ruling -- default ON per the ruled
    # flag defaults (register, "Flag UI + defaults" entry: "headers/
    # footers ON"). `_running_ops` already treats `headers=None`/
    # `footers=None` as "nothing to render" (its own default), so turning
    # the flag off just means never passing the real values through.
    show_headers = options.get('headers', True)
    # Round 19 (PIX images RULED IN, ledger PIX row) wired the Printed
    # path; round 22 closed the two documented scope cuts (Modern PDF via
    # `_modern_streams`, the notes-pagination path via
    # `_paginate_printed_notes`). `pictures` off (or no results) costs
    # nothing on any path: every substitution site skips itself when
    # embedding is not live, byte-identical to before.
    pictures = options.get('pictures', 'off')
    pix_results = options.get('pix_results') or []
    # N9 (b33 field notes): mode-aware default, flag overrides either way.
    ss_on = _resolve_sentence_spacing(options.get('sentence_spacing', 'auto'), printed)
    # Modern never touches driver-specific colour at all (see colour_map's
    # own use below, gated `if printed`); this default just keeps the name
    # bound for the pattern-object step near the bottom, which runs on both
    # paths and needs to know "no patterns to build" on Modern's.
    colour_map = {}
    if printed:
        pages = _doc_to_pagelines(doc, printed, pix_results=pix_results, pictures=pictures,
                                  sentence_spacing=ss_on)
        top = _printed_top(doc)
        lead = _printed_lead(doc)
        size = _printed_size(doc)
        left = _printed_left(doc, size)
        roll_pt = _printed_roll_pt(doc)
        # Jon's ruling 2026-08-20 (reverses round 17b; RULINGS-LEDGER row
        # 5/6, register C21): default CONTINUOUS -- measured WS7 LaserJet
        # behavior, see `_rules`'s docstring. Explicit `.ul off` still
        # breaks at spaces (the parser only records the key when the
        # command is present, so absent-vs-off is distinguishable).
        ul_continuous = bool(doc.meta.get('formatting', {}).get('underline_blanks', True))
        # round 17b (RULINGS-LEDGER row 5/6, register C11), corrected by
        # planning #247: `.l#`'s own interval, flag-gated -- default ON
        # (same shape as `--headers`), but the FEATURE only ever fires
        # when the document itself declared `.l#` (line_numbering_checkpoints
        # stays at its `(0, None)` seed otherwise): the flag's job is
        # letting a caller SUPPRESS what the file asked for, not
        # inventing numbering a silent file never requested.
        # `line_no_checkpoints` carries the FULL positional answer
        # (`core.line_numbering_checkpoints`) -- `_page_stream` resolves
        # the interval in force PER LINE from it (a single per-page value
        # cannot represent PRINT.TST's own `.l#2`/`.l# 0` pair, both of
        # which land on the SAME page; see `_page_stream`'s own comment).
        line_no_checkpoints = (_line_numbering_checkpoints(doc)
                               if options.get('line_numbers', True) else None)
        page_h = _resolved_page_height(doc, printed)
        fonts = doc.fonts
        colour_map = _COLOUR_GRAY_LJ6DTP if (
            doc.meta.get('printer_driver') == 'LJ6DTP') else {}
        start_no = int((doc.meta.get('page') or {}).get('pn_start', 1))
        # register b31-dot-command-sweep: `.pn` re-anchors mid-document
        # too (see `_resolve_page_numbers`) -- one number per real page,
        # replacing the flat `start_no + page_index` below.
        page_numbers = _resolve_page_numbers(_pn_checkpoints(doc), pages)
        # E3 item 2 (register b31, 2026-08-25): `--page-numbers auto`
        # (default) lets the document's own `.pn`/`.pg`/`.op` decide (see
        # `_pgnum_checkpoints`, seeded ON 2026-09-07 -- stock WS7's own
        # factory default) -- byte-identical to every existing capture/
        # oracle for the overwhelming majority of documents that never
        # touch any of those four commands: they get the stock automatic
        # number, same as `on` below. `on` forces WordStar's stock
        # default numbering even on a document that explicitly turned it
        # off with `.op`; `off` suppresses it unconditionally. Neither
        # `on` nor `off`
        # touches an explicit `#` the author placed inside a real
        # `.he`/`.fo` -- that is running-title content, substituted by
        # `_running_ops`'s own `render()` regardless of this flag.
        page_numbers_mode = options.get('page_numbers', 'auto')
        pgnum_checkpoints = (_pgnum_checkpoints(doc)
                             if page_numbers_mode == 'auto' else None)
        res = FontRes()
        streams = []
        for page_index, pl in enumerate(pages):
            # Finding 3 (b26-print-fidelity-2): a page whose own .mt/.mb
            # (Page.mt_lines/mb_lines, set by _doc_to_pagelines from
            # _mt_mb_checkpoints) differs from the document's global pair
            # gets ITS OWN top-margin/header-footer geometry -- the SAME
            # temporary doc.meta['page'] swap `emit_pdf` already uses for
            # `page_settings`/landscape, scoped to just this page's
            # `_printed_top`/`_running_ops` calls. None/None (every page
            # of every document that never changes .mt/.mb mid-document)
            # skips the swap entirely: `page_top` is the SAME `top` value
            # computed once above, byte-identical to before this fix.
            page_mt = getattr(pl, 'mt_lines', None)
            page_mb = getattr(pl, 'mb_lines', None)
            # register b31-dot-command-sweep: `.pl` alone (no .mt/.mb
            # change) still needs the swap below -- `_running_ops`'s own
            # footer-row placement reads `pl_lines` too (WSFORMAT's "line
            # pl-.mb+.fm" footer geometry), so a page whose `.pl` changed
            # but whose `.mt`/`.mb` did not would otherwise render its
            # footer at the WRONG row (the document's stale global `.pl`).
            page_pl = getattr(pl, 'pl_lines', None)
            # register b31-dot-command-sweep: `.hm`/`.fm` -- read by
            # `_printed_top` (the body's own top offset, gated on
            # mt_source) and by `_running_ops` (the header/footer ROW
            # itself) -- need the SAME per-page swap, or a page whose
            # `.hm`/`.fm` changed renders its running head/foot at the
            # document's stale global row (measured against real WS7,
            # HMFM_PROBE: header/footer moved to a different PCL row
            # after a mid-document `.hm`/`.fm` with `.mt` untouched).
            page_hm = getattr(pl, 'hm_lines', None)
            page_fm = getattr(pl, 'fm_lines', None)
            # register b31-dot-command-sweep follow-up: `.po` -- read by
            # `_running_ops` (the header/footer LEFT edge). Body text
            # already carries a mid-document `.po` change correctly (each
            # physical Line's own `po_cols`, applied per line in
            # `_page_stream`); `_running_ops` had no such per-page
            # equivalent and always rendered at the document's global
            # `left`. SCRIPT.WS is the oracle (`_po_checkpoints`'s own
            # docstring): its worked-example figures reset `.po` to
            # `.5"` alongside their `.mt`/`.hm` changes, and WS7's real
            # capture moves the running head's own left edge with it --
            # 21.6pt (3 columns) this engine used to leave on the table.
            page_po = getattr(pl, 'po_cols', None)
            # #241 (MACROS/HOLYMAC/-HOLYMAC.WS): SCRIPT.WS's own oracle
            # above ALWAYS pairs its `.po .5"` reset with an `.mt`/`.mb`
            # change on the very same page (measured: `.po.5"` immediately
            # followed by `.mt1`/`.mb0`, twice) -- a genuine page-geometry
            # reset. HOLYMAC's box-diagram examples set `.po .3i` (with
            # `.rm 79`, widening the measure for the diagram) and revert
            # it a few lines later WITHOUT ever touching `.mt`/`.mb`/`.hm`/
            # `.fm` -- a purely local body-margin excursion for one
            # figure, not a page-layout change. Measured directly: WS7's
            # running head sits at the SAME 72pt left edge on every page
            # of this document (12, 13, 16, 17...), even the three (12,
            # 13, 17) where this engine's own `cur_po` snapshot -- taken
            # at PAGE OPEN, `_recompute_geom` -- happens to land mid-
            # diagram (`.po .3i` already set, its own revert not yet
            # reached). Gating `running_left` on a genuine geometry change
            # co-occurring (mt/mb/hm/fm) keeps SCRIPT.WS's own confirmed
            # behaviour unchanged while no longer letting a diagram's own
            # transient `.po` leak into the header/footer position.
            page_geom_changed = (page_mt is not None or page_mb is not None
                                 or page_hm is not None or page_fm is not None)
            # #241 follow-up (2026-09-08, planning #231):
            # `.poe`/`.poo` are themselves a page-layout decision (WSFORMAT.
            # WS: "specify even or odd number page offsets"), not a
            # HOLYMAC-style transient body-only `.po` excursion -- the one
            # thing `page_geom_changed` above exists to filter out. A live
            # parity override (`Page.po_parity`, set in `_close_page`) must
            # reach the running head/foot regardless of whether `.mt`/`.mb`/
            # `.hm`/`.fm` also changed on this page. Measured: sawyer/
            # MAILLIST/PHONE.LST (`.poo .20"`/`.poe .20"`, no `.mt`/`.hm`
            # change ever) -- running head was stuck at the document
            # default 57.6pt instead of the declared 14.4pt.
            page_po_parity = getattr(pl, 'po_parity', False)
            running_left = (_resolve_left_pt(page_po, size)
                            if page_po is not None
                                and (page_geom_changed or page_po_parity)
                            else left)
            saved_pg = None
            if (page_mt is not None or page_mb is not None or page_pl is not None
                    or page_hm is not None or page_fm is not None):
                eff = dict(doc.meta['page'])
                if page_mt is not None:
                    eff['mt_lines'], eff['mt_source'] = page_mt, 'file'
                if page_mb is not None:
                    eff['mb_lines'], eff['mb_source'] = page_mb, 'file'
                if page_pl is not None:
                    eff['pl_lines'] = page_pl
                if page_hm is not None:
                    # 'file' only if THIS page's own resolved hm is a real
                    # override of WordStar's hardcoded default, not merely
                    # different from the document's (possibly WRONG, in
                    # the degenerate mid-document-only-occurrence case)
                    # global reading -- `_running_ops`'s OR-gate treats
                    # hm_source == 'file' as "the author touched .hm",
                    # which must stay false for a page that sits BEFORE
                    # a document's only `.hm` ever fires, even though it
                    # still needs its own override (back to the true
                    # default) to correct core.py's global reading.
                    from .core import DEFAULT_HM_LINES as _DEF_HM
                    eff['hm_lines'] = page_hm
                    eff['hm_source'] = 'file' if page_hm != _DEF_HM else 'default'
                if page_fm is not None:
                    eff['fm_lines'], eff['fm_source'] = page_fm, 'file'
                saved_pg, doc.meta['page'] = doc.meta['page'], eff
                page_top = _printed_top(doc)
            else:
                page_top = top
            # E3 item 2: resolve THIS page's own automatic-number state.
            # `--headers off` already suppresses page numbers per its own
            # documented scope ("headers, footers, and page numbers");
            # `on`/`off` need no page-level lookup at all, `auto` resolves
            # from the SAME block-index range `_resolve_page_numbers` uses.
            if not show_headers or page_numbers_mode == 'off':
                auto_page_number = False
            elif page_numbers_mode == 'on':
                auto_page_number = True
            else:
                bis = [bi for bi in (getattr(ln, 'bi', None) for ln in pl)
                      if bi is not None]
                if bis:
                    auto_page_number = _pgnum_at(pgnum_checkpoints, max(bis))
                else:
                    # #228: a page with no lines at all has no `.bi` to
                    # read -- true of both an ordinary degenerate page
                    # (kept False, as before) and our new confirmed
                    # trailing-`.pa` page, which DOES need a number (WS7
                    # stamps one). `explicit_break_bi` (the `.pa` block's
                    # own index) stands in for "wherever the document's
                    # own state was when this page opened."
                    fallback_bi = getattr(pl, 'explicit_break_bi', None)
                    auto_page_number = (_pgnum_at(pgnum_checkpoints, fallback_bi)
                                        if fallback_bi is not None else False)
            running = _running_ops(doc, page_numbers[page_index], page_h, lead,
                                   size, running_left, printed,
                                   headers=(getattr(pl, 'headers', None) if show_headers else {}),
                                   footers=(getattr(pl, 'footers', None) if show_headers else {}),
                                   res=res, auto_page_number=auto_page_number,
                                   head_hf_override=(getattr(pl, 'head_hf_override', None)
                                                     if show_headers else None),
                                   foot_hf_override=(getattr(pl, 'foot_hf_override', None)
                                                     if show_headers else None))
            if saved_pg is not None:
                doc.meta['page'] = saved_pg
            streams.append(_page_stream(pl, page_top, page_h, lead, size, left,
                                        running, fonts, res, colour_map, roll_pt,
                                        ul_continuous, line_no_checkpoints,
                                        doc.pcl_programs))
        # round 18 (RULINGS-LEDGER row 4): TOC/Index compiled as ADDITIONAL
        # pages at the document's own end (Jon: "It should probably export
        # in all formats even though non-paged ones couldn't be
        # referenced"), TOC before Index. `--toc off` (the ruled default)
        # leaves the page count exactly as it always was. These extra
        # pages carry no running head/footer of their own -- a documented
        # simplification, not the document's own running content replayed
        # past its last real page.
        if options.get('toc', False) and (doc.toc_entries or doc.index_entries):
            toc_lines = _toc_index_pagelines(
                doc, _toc_page_numbers(doc, pix_results=pix_results, pictures=pictures))
            cap = max(1, _printed_cap(doc))
            for chunk_start in range(0, len(toc_lines), cap):
                chunk = toc_lines[chunk_start:chunk_start + cap]
                page_index = len(streams)
                running = _running_ops(doc, start_no + page_index, page_h, lead,
                                       size, left, printed, headers={}, footers={},
                                       res=res)
                streams.append(_page_stream(chunk, top, page_h, lead, size, left,
                                            running, fonts, res, colour_map, roll_pt,
                                            ul_continuous, None))
    else:
        # Modern: the printed form of the Modern RTF (ruling 2026-08-05) --
        # document fonts carried, proportional reflow at the real measure,
        # footnotes at the page bottom, fontless body Times 14. The page is
        # the document's declared size (Letter/Legal/A4 -- ruled 2026-08-06);
        # silence is Letter, exactly as before.
        page_h = int(round(float((doc.meta.get('page') or {})
                                 .get('height_in', 11.0)) * 72))
        res = FontRes()
        streams = _modern_streams(doc, options, res)
    # Width joined the page model 2026-08-06 ("the 3 main page sizes"):
    # inferred from the height -- A4-tall pages are 210mm wide, everything
    # else is the 8.5in sheet -- so a default document stays exactly 612.
    page_w = int(round(float((doc.meta.get('page') or {})
                             .get('pw_in', 8.5)) * 72))
    n_pages = len(streams)
    objs = []                                             # (obj_number, bytes)

    font_objs = {}                                        # F1..Fn -> obj num
    next_num = 3
    for f, basefont in res.names.items():
        font_objs[f] = next_num
        # /WinAnsiEncoding on the ALPHABETIC faces: without a declared
        # encoding a Type1 font falls back to its built-in StandardEncoding,
        # where the cp1252 bytes _esc writes for curly quotes, dashes and ©
        # name the WRONG glyphs. Symbol and ZapfDingbats keep their built-in
        # encodings -- their bytes are glyph indices by design (symbolmap).
        if basefont in ('Symbol', 'ZapfDingbats'):
            objs.append((next_num,
                         b'<< /Type /Font /Subtype /Type1 /BaseFont /%s >>'
                         % basefont.encode()))
        else:
            objs.append((next_num,
                         b'<< /Type /Font /Subtype /Type1 /BaseFont /%s'
                         b' /Encoding /WinAnsiEncoding >>'
                         % basefont.encode()))
        next_num += 1
    font_dict = b' '.join(b'/%s %d 0 R' % (f.encode(), n) for f, n in font_objs.items())

    # Round 19 (PIX images RULED IN, ledger PIX row): one Image XObject per
    # embedded pix result, built from pix.decode()'s own RGB rows (NOT the
    # PNG bytes RTF/HTML use -- PDF's native image mechanism needs no PNG
    # container at all, and this avoids writing a PNG decoder just to
    # re-read what pix.py already decoded once). Always DeviceRGB/8bpc
    # (even for a mono source) -- simpler and correct for every source
    # depth; a real size optimisation (1-bit for mono, mirroring to_png's
    # own choice) is left for later, noted rather than silently assumed.
    # Shared across every page exactly like `font_dict` already is --
    # an XObject unused on a given page costs nothing per the PDF spec.
    image_objs = {}                                       # pix index -> obj num
    if pictures in ('embed', 'export') and pix_results:
        for r in pix_results:
            if not r.ok or r.raw_bytes is None:
                continue
            try:
                gcols, grows, rgb_rows = _pixdecode.decode(r.raw_bytes)
            except _pixdecode.PixFormatError:
                continue
            raw = bytearray()
            for row in rgb_rows:
                for px in row:
                    raw += bytes(px)
            compressed = _zlib.compress(bytes(raw), 6)
            objs.append((next_num,
                        b'<< /Type /XObject /Subtype /Image /Width %d /Height %d '
                        b'/ColorSpace /DeviceRGB /BitsPerComponent 8 '
                        b'/Filter /FlateDecode /Length %d >>\nstream\n%s\nendstream'
                        % (gcols, grows, len(compressed), compressed)))
            image_objs[r.index] = next_num
            next_num += 1
    xobject_dict = (b' /XObject << %s >>' % b' '.join(
                        b'/Im%d %d 0 R' % (idx, n) for idx, n in image_objs.items())
                   if image_objs else b'')

    # LJ6DTP's HP1-HP6 tiling patterns (colour_map is _COLOUR_GRAY_LJ6DTP,
    # non-empty, exactly when the document declares that driver -- same gate
    # as everywhere else this table is consulted). Shared across every page
    # exactly like font_dict/xobject_dict; a page whose own content never
    # selects colour9-14 (every page but 5) references a /Pattern resource
    # dict it never uses, which costs nothing per the PDF spec.
    pattern_objs = {}                                      # colour idx -> obj num
    if colour_map:
        for idx in sorted(_LJ6DTP_HP_PATTERNS):
            w, h, content = _LJ6DTP_HP_PATTERNS[idx]
            objs.append((next_num,
                        b'<< /Type /Pattern /PatternType 1 /PaintType 1'
                        b' /TilingType 1 /BBox [0 0 %d %d] /XStep %d /YStep %d'
                        b' /Resources << >> /Length %d >>\nstream\n%s\nendstream'
                        % (w, h, w, h, len(content), content)))
            pattern_objs[idx] = next_num
            next_num += 1
    pattern_dict = (b' /Pattern << %s >>' % b' '.join(
                        b'/P%d %d 0 R' % (idx, n) for idx, n in pattern_objs.items())
                   if pattern_objs else b'')

    # register b31 E2: /GS0 (Normal) and /GS1 (Darken) ExtGStates, registered
    # per-page exactly like /Pattern just above -- same gate (`colour_map`
    # non-empty, i.e. the document declares the LJ6DTP driver), same "a page
    # that never selects colour1-7 references a resource it never uses,
    # costing nothing" reasoning. /GS0 exists so leaving the colour1-7
    # family can SET Normal back explicitly (`gs` graphics state persists
    # across BT/ET and would otherwise still read Darken from an earlier
    # span on the same page) rather than relying on an assumed initial
    # value once any `gs` operator has ever been written.
    extgstate_objs = {}
    if colour_map:
        objs.append((next_num, b'<< /Type /ExtGState /BM /Normal >>'))
        extgstate_objs['GS0'] = next_num
        next_num += 1
        objs.append((next_num, b'<< /Type /ExtGState /BM /Darken >>'))
        extgstate_objs['GS1'] = next_num
        next_num += 1
    extgstate_dict = (b' /ExtGState << %s >>' % b' '.join(
                          b'/%s %d 0 R' % (name.encode(), n) for name, n in extgstate_objs.items())
                     if extgstate_objs else b'')

    page_nums, content_nums = [], []
    for _ in range(n_pages):
        page_nums.append(next_num); next_num += 1
        content_nums.append(next_num); next_num += 1

    kids = b' '.join(b'%d 0 R' % n for n in page_nums)
    objs.insert(0, (1, b'<< /Type /Catalog /Pages 2 0 R >>'))
    objs.insert(1, (2, b'<< /Type /Pages /Kids [%s] /Count %d >>' % (kids, n_pages)))

    for pnum, cnum, stream in zip(page_nums, content_nums, streams):
        objs.append((pnum,
                     b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] '
                     b'/Resources << /Font << %s >>%s%s%s >> /Contents %d 0 R >>'
                     % (page_w, page_h, font_dict, xobject_dict, pattern_dict,
                        extgstate_dict, cnum)))
        objs.append((cnum, b'<< /Length %d >>\nstream\n%s\nendstream'
                     % (len(stream), stream)))

    objs.sort()
    out = bytearray(b'%PDF-1.4\n')
    offsets = {}
    for num, body in objs:
        offsets[num] = len(out)
        out += b'%d 0 obj\n%s\nendobj\n' % (num, body)
    xref_at = len(out)
    count = max(offsets) + 1
    out += b'xref\n0 %d\n0000000000 65535 f \n' % count
    for n in range(1, count):
        out += b'%010d 00000 n \n' % offsets[n]
    out += (b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
            % (count, xref_at))
    return bytes(out)

emit_pdf.ext = '.pdf'
