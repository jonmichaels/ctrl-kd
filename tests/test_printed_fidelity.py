"""Round 17 ("Printed-fidelity"): RULINGS-LEDGER.md rows 1, 2, 3, 5, 7, 8 —
Jon's GO 2026-08-18, engine side of the 2026-08-17 twelve-point exchange +
follow-on rulings (WordStar-Feature-Decision-Register.md, 2026-08-17 entries).
Fail-first: each test names the ledger row it closes and is written to FAIL
against the pre-round engine, confirmed by running it before its own fix
lands (captured in the commit message, not re-asserted here).

Paged-surface doctrine (register, 2026-08-17): headers/footers/page numbers,
`.pr` landscape, `.sr` roll, vertical space (.lh/.pm/.psa/.psb), and
`.lm`/`.rm` dot-state margins all belong in EVERY paged surface -- Printed
RTF and Printed PDF (Native viewer is sr/Soft Return's own concern, not
ctrl-kd's). Modern must stay untouched throughout (asserted per item).
"""
import copy
import re

from ctrlkd import core, emit, pdf, info

HARD = b'\x0d\x0a'
SOFT = b'\x8d\x0a'


def ws7_block(cmd, content=b''):
    count = (len(content) + 4).to_bytes(2, 'little')
    return b'\x1d' + count + bytes([cmd]) + content + count + b'\x1d'


def _rtf_body_only(r):
    """Strip the control groups (fonttbl/colortbl/stylesheet/info) so a
    content search never accidentally matches boilerplate. Mirrors
    test_modern_lint.py's own helper."""
    body = r
    for grp in (r'\fonttbl', r'\colortbl', r'\stylesheet', r'\info'):
        i = body.find('{' + grp)
        if i == -1:
            continue
        depth = 0
        j = i
        while j < len(body):
            if body[j] == '{':
                depth += 1
            elif body[j] == '}':
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        body = body[:i] + body[j:]
    return body


# --------------------------------------------------------------- ledger row 8
# `.lm`/`.rm` dot-state reaches Printed RTF margins (round 6 flagged, not
# built). `Block.left_margin`/`right_margin` already carry the RESOLVED
# column value (style overrides dot-state, core.py's `_new_block`) -- Printed
# RTF's own li/ri lookup was keyed by STYLE SLOT only (`_rtf_direct_margins`),
# so a WS4 document (no style table at all) or a bare `.lm`/`.rm` with no
# style got li=ri=0 regardless of the running margin state.

def test_lm_rm_dot_state_reaches_printed_rtf_margins():
    doc = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'.lm 11' + HARD + b'.rm 61' + HARD
        + b'A WS4 paragraph with no style table at all.' + HARD)
    assert doc.blocks[0].left_margin == 10.0     # `.lm 11` -> column 11 -> 10 cols offset
    assert doc.blocks[0].right_margin == 61.0    # `.rm 61` unit-less -- already an offset

    r_printed = emit.emit_rtf(doc, mode='printed')
    body = _rtf_body_only(r_printed)
    assert r'\li1440' in body     # 10 cols * 144 twips/col
    assert r'\ri8784' in body     # 61 cols * 144 twips/col

    # Modern stays untouched -- the reader owns presentation, same doctrine
    # as the no-page-width ruling.
    r_modern = emit.emit_rtf(doc, mode='modern')
    assert r'\li1440' not in r_modern
    assert r'\ri8784' not in r_modern


def test_style_margin_still_wins_over_dot_state_in_printed_rtf():
    """A style's OWN left_margin_hmi/right_margin_hmi takes precedence over
    whatever `.lm`/`.rm` is running -- core.py's own `_new_block` already
    encodes this precedence (`style_fmt.get(..., fmt.get(...))`); the
    Printed RTF fix must read the SAME resolved value, not bypass it."""
    rec = _style_record_with_margins(left_hmi=3600, right_hmi=3600)
    lib = _style_library([('WordStar Defaults', None),
                          ('WordStar Defaults', None),
                          ('Wide Quote', rec)])
    body = (b'.lm 5' + HARD + b'.rm 70' + HARD
            + _style_ref(2) + b'A paragraph under its own wide style margins.' + HARD)
    doc = core.parse_ws(_doc_with_style_library(body, lib))
    assert doc.blocks[0].left_margin == 20.0     # the STYLE's own HMI, not `.lm 5`
    r_printed = emit.emit_rtf(doc, mode='printed')
    body_only = _rtf_body_only(r_printed)
    assert r'\li2880' in body_only               # 3600 hmi / 1800 * 1440


# --------------------------------------------------------------- ledger row 3
# `.sr` sub/superscript roll: `state['sub_super_roll_48']` was parsed and
# recorded but never read -- PDF hardcoded rise 3 (sup) / -2 (sub) regardless
# of the file's own `.sr`; RTF carried no explicit rise override at all
# (`\super`/`\sub` alone, a reader's own default). WSFORMAT.TXT: "[.SR] The
# increments (in 1/48ths of an inch) which the carriage is to roll up or down
# for subscript and superscript printing. Default is 3."

def _sup_sub_doc(sr_line=b''):
    return core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + sr_line
        + b'Water' + b'\x14' + b'2' + b'\x14' + b'O and CO' + b'\x16' + b'2' + b'\x16'
        + b' gas.' + HARD)


def test_sr_roll_drives_printed_pdf_rise():
    doc = _sup_sub_doc(b'.sr 10' + HARD)
    assert doc.meta['formatting']['sub_super_roll_48'] == 10.0
    out = pdf.emit_pdf(doc, mode='printed')
    rises = {int(x) for x in re.findall(rb'(-?\d+) Ts', out)}
    # 10/48in * 1.5 pt/48in-unit = 15pt, symmetric per WSFORMAT's own text
    assert 15 in rises and -15 in rises
    assert 3 not in rises and -2 not in rises   # the old hardcoded pair is gone


def test_sr_absent_uses_the_wsformat_default_not_the_old_hardcode():
    doc = _sup_sub_doc()
    assert 'sub_super_roll_48' not in doc.meta['formatting']
    out = pdf.emit_pdf(doc, mode='printed')
    rises = {int(x) for x in re.findall(rb'(-?\d+) Ts', out)}
    # WSFORMAT's own stated default (3/48in = 4.5pt, rounds to 4) -- NOT the
    # emitter's old, spec-unrelated fixed 3/-2 pair.
    assert 4 in rises and -4 in rises


def test_sr_roll_drives_printed_rtf_up_dn_alongside_super_sub():
    doc = _sup_sub_doc(b'.sr 10' + HARD)
    r = emit.emit_rtf(doc, mode='printed')
    body = _rtf_body_only(r)
    assert r'\super' in body and r'\sub' in body   # semantic tag still present
    assert r'\up30 ' in body    # 10 * 3 half-points/48in-unit
    assert r'\dn30 ' in body


def test_sr_roll_never_reaches_modern_rtf_or_pdf():
    """Modern must remain untouched -- the reader owns presentation, same
    doctrine as every other Printed-only vertical-space item."""
    doc = _sup_sub_doc(b'.sr 10' + HARD)
    r_modern = emit.emit_rtf(doc, mode='modern')
    assert r'\up30' not in r_modern and r'\dn30' not in r_modern
    assert r'\super' in r_modern and r'\sub' in r_modern   # semantic tag intact

    out_modern = pdf.emit_pdf(doc, mode='modern')
    rises = {int(x) for x in re.findall(rb'(-?\d+) Ts', out_modern)}
    # Modern PDF keeps the exact prior fixed pair, unaffected by `.sr 10`
    assert 3 in rises and -2 in rises
    assert 15 not in rises and -15 not in rises


# --------------------------------------------------------------- ledger row 2
# `.pr or=l` landscape: `state['orientation']` was parsed, never consumed --
# a landscape document always rendered portrait, no diagnostic. WSFORMAT/the
# archive's real syntax: `.pr or=l` / `.pr or=p`.

def _landscape_doc(orientation=b'l'):
    return core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'.pr or=' + orientation + HARD
        + b'A landscape-declared paragraph of body text.' + HARD)


def test_pr_landscape_flips_printed_pdf_mediabox():
    doc = _landscape_doc()
    assert doc.meta['formatting']['orientation'] == 'landscape'
    out = pdf.emit_pdf(doc, mode='printed')
    m = re.search(rb'/MediaBox \[0 0 (\d+) (\d+)\]', out)
    assert m is not None
    w, h = int(m.group(1)), int(m.group(2))
    assert (w, h) == (792, 612)     # wider than tall -- the swap landed


def test_pr_portrait_explicit_keeps_the_ordinary_mediabox():
    doc = _landscape_doc(orientation=b'p')
    assert doc.meta['formatting']['orientation'] == 'portrait'
    out = pdf.emit_pdf(doc, mode='printed')
    m = re.search(rb'/MediaBox \[0 0 (\d+) (\d+)\]', out)
    assert (int(m.group(1)), int(m.group(2))) == (612, 792)


def test_pr_landscape_flips_printed_rtf_paper_and_sets_landscape_keyword():
    doc = _landscape_doc()
    r = emit.emit_rtf(doc, mode='printed')
    assert r'\landscape' in r
    m = re.search(r'\\paperw(\d+)\\paperh(\d+)', r)
    assert m is not None
    paperw, paperh = int(m.group(1)), int(m.group(2))
    assert paperw > paperh                    # 11in wide, 8.5in tall, in twips
    assert paperw == 15840 and paperh == 12240


def test_pr_landscape_never_reaches_modern_pdf_or_rtf():
    """Modern must remain untouched -- its own fixed Letter page regardless
    of the document's declared orientation, same doctrine as every other
    Printed-only geometry item."""
    doc = _landscape_doc()
    out_modern = pdf.emit_pdf(doc, mode='modern')
    m = re.search(rb'/MediaBox \[0 0 (\d+) (\d+)\]', out_modern)
    assert (int(m.group(1)), int(m.group(2))) == (612, 792)

    r_modern = emit.emit_rtf(doc, mode='modern')
    assert r'\landscape' not in r_modern


# --------------------------------------------------------------- ledger row 1
# Headers/footers/page numbers in ALL paged surfaces + toggle flag. Pre-round
# state (register B1/B2): renders in Printed PDF + Modern RTF only; Printed
# RTF (the one RTF style that never got them) was the gap; no flag existed
# at all.

def _headed_doc(h1=b'Sawyer / Old Times / #'):
    return core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'.h1 ' + h1 + HARD
        + b'Body text of the document, long enough to paginate sensibly.' + HARD)


def test_printed_rtf_gains_header_footer_destinations_with_chpgn():
    doc = _headed_doc()
    assert doc.headers == {1: 'Sawyer / Old Times / #'}
    r = emit.emit_rtf(doc, mode='printed')
    assert r'{\header' in r
    assert r'\chpgn' in r          # `#` became RTF's own page-number field
    assert 'Sawyer' in r and 'Old Times' in r


def test_headers_flag_off_suppresses_printed_rtf_header():
    doc = _headed_doc()
    r = emit.emit_rtf(doc, mode='printed', headers=False)
    assert r'{\header' not in r and 'Sawyer' not in r


def test_headers_flag_off_suppresses_printed_pdf_running_content():
    doc = _headed_doc()
    on = pdf.emit_pdf(doc, mode='printed', headers=True)
    off = pdf.emit_pdf(doc, mode='printed', headers=False)
    assert b'Sawyer' in on
    assert b'Sawyer' not in off


def test_headers_flag_default_is_on():
    """Ruled default (register, 'Flag UI + defaults' entry): headers ON."""
    doc = _headed_doc()
    r = emit.emit_rtf(doc, mode='printed')       # no explicit headers= at all
    assert r'{\header' in r
    out = pdf.emit_pdf(doc, mode='printed')
    assert b'Sawyer' in out


def test_headers_flag_never_disables_body_text():
    doc = _headed_doc()
    r = emit.emit_rtf(doc, mode='printed', headers=False)
    assert 'Body text of the document' in r


# --------------------------------------------------------------- ledger row 5
# PDF vertical space: `.pm` first-line indent + `.psa`/`.psb` spacing extend
# round 6's RTF work to pdf.py, same relative-computation rules, Printed only.

def test_pm_shifts_printed_pdf_first_line_start_x():
    doc = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'.pm 10' + HARD
        + b'Some paragraph text without a typed indent at all.' + HARD)
    # `.pm 10` is a COLUMN NUMBER (1-based, same frame as `.lm`/`.po`) --
    # normalised to 9.0 offset columns, same as `.lm` (b26 fix; this
    # assertion previously read 10.0, the dormant pre-normalization bug).
    assert doc.blocks[0].para_margin == 9.0
    out = pdf.emit_pdf(doc, mode='printed')
    m = re.search(rb'BT /\S+ \d+ Tf \d+ Ts ([\d.]+) ([\d.]+) Td', out)
    baseline = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'Some paragraph text without a typed indent at all.' + HARD)
    out_base = pdf.emit_pdf(baseline, mode='printed')
    m_base = re.search(rb'BT /\S+ \d+ Tf \d+ Ts ([\d.]+) ([\d.]+) Td', out_base)
    assert round(float(m.group(1)) - float(m_base.group(1)), 6) == 64.8   # 9 cols * 7.2pt/col


def test_pm_column_normalization_matches_lm_flush_left():
    """b26: `.pm` lives in the SAME absolute column frame as `.lm`/`.po`
    (emit.py `_rtf_pm_fi_twips` docstring) and is 1-based like `.lm`, so
    `.pm 1` -- column 1, the left edge itself -- must normalize to a ZERO
    first-line indent, landing the first line flush on the `.po`-derived
    left margin, not one column right of it."""
    doc = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'.pm 1' + HARD + b'.lm 16' + HARD + b'.po 8' + HARD
        + b'A paragraph whose .pm column equals the left edge itself.' + HARD)
    assert doc.blocks[0].para_margin == 0.0    # `.pm 1` -> column 1 -> 0 offset
    out = pdf.emit_pdf(doc, mode='printed')
    m = re.search(rb'BT /\S+ \d+ Tf \d+ Ts ([\d.]+) ([\d.]+) Td', out)
    assert float(m.group(1)) == 57.6           # `.po 8` flush left, 8*12*0.6pt
    # Pre-fix this landed at 64.8pt (57.6 + 1 unnormalized `.pm` column *
    # 7.2pt/col) -- one column right of the file's own bytes.


def test_psa_psb_add_printed_pdf_vertical_space():
    doc = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'.PSB 1' + HARD + b'.PSA 2' + HARD
        + b'First paragraph line one.' + HARD + HARD
        + b'Second paragraph after a blank line.' + HARD)
    assert doc.meta['space_before_lines'] == 1.0
    assert doc.meta['space_after_lines'] == 2.0
    assert doc.meta['producer'] == 'wordtsar'

    baseline = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'First paragraph line one.' + HARD + HARD
        + b'Second paragraph after a blank line.' + HARD)

    def gap(d):
        out = pdf.emit_pdf(d, mode='printed')
        ys = [float(y) for _, y in re.findall(rb'([\d.]+) ([\d.]+) Td', out)]
        return ys[0] - ys[1]

    # +1 line before (12pt) + 2 lines after (24pt) = 36pt more than baseline
    assert gap(doc) - gap(baseline) == 36.0


def test_pm_psa_psb_never_reach_modern_pdf():
    """Modern must remain untouched -- the reader owns presentation, same
    doctrine as every other Printed-only vertical-space item."""
    doc = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'.pm 10' + HARD + b'.PSB 1' + HARD + b'.PSA 2' + HARD
        + b'First paragraph.' + HARD + HARD
        + b'Second paragraph.' + HARD)
    baseline = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15))
        + b'First paragraph.' + HARD + HARD
        + b'Second paragraph.' + HARD)
    out_modern = pdf.emit_pdf(doc, mode='modern')
    out_modern_base = pdf.emit_pdf(baseline, mode='modern')
    # Modern reflows anyway, but the point stands: .pm/.psa/.psb make zero
    # difference to Modern's own byte output.
    assert out_modern == out_modern_base


# --------------------------------------------------------------- ledger row 5/6
# `.ul` (continuous underline of inter-word blanks), `.sb` (suppress blank
# lines at page top), `.l#` (line-number gutter). Register C8/C11/C21.

def test_ul_honest_default_breaks_underline_at_spaces():
    """WS3.3 Reference Manual ch.7 "Underscoring": "^PS does not underline
    blank spaces." Absent `.ul`, the honest default underlines characters
    only -- confirmed empirically pre-round: `.ul on`/`.ul off`/absent all
    produced byte-identical PDF underline output (always continuous)."""
    body = b'\x13AA BB\x13 plain.' + HARD
    doc = core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)
    assert 'underline_blanks' not in doc.meta['formatting']
    out = pdf.emit_pdf(doc, mode='printed')
    rules = re.findall(rb'0\.6 w ([\d.]+) [\d.]+ m ([\d.]+) [\d.]+ l S', out)
    assert len(rules) == 2      # "AA" and "BB" underlined separately

    r = emit.emit_rtf(doc, mode='printed')
    assert r.count(r'\ul ') == 2


def test_ul_on_draws_one_continuous_rule():
    body = b'.ul on' + HARD + b'\x13AA BB\x13 plain.' + HARD
    doc = core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)
    assert doc.meta['formatting']['underline_blanks'] is True
    out = pdf.emit_pdf(doc, mode='printed')
    rules = re.findall(rb'0\.6 w ([\d.]+) [\d.]+ m ([\d.]+) [\d.]+ l S', out)
    assert len(rules) == 1

    r = emit.emit_rtf(doc, mode='printed')
    assert r.count(r'\ul ') == 1


def test_ul_never_reaches_modern_pdf_or_rtf():
    body = b'.ul on' + HARD + b'\x13AA BB\x13 plain.' + HARD
    doc = core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)
    import hashlib
    baseline = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15)) + b'\x13AA BB\x13 plain.' + HARD)
    assert (hashlib.sha256(pdf.emit_pdf(doc, mode='modern')).hexdigest()
            == hashlib.sha256(pdf.emit_pdf(baseline, mode='modern')).hexdigest())
    r_modern = emit.emit_rtf(doc, mode='modern')
    r_modern_base = emit.emit_rtf(baseline, mode='modern')
    assert r_modern == r_modern_base


def test_sb_suppresses_leading_blank_lines_at_page_top():
    body = HARD + HARD + b'Actual content starts here.' + HARD
    doc_default = core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)
    doc_sb = core.parse_ws(
        ws7_block(0x00, bytes([0x70]) + bytes(15)) + b'.sb on' + HARD + body)
    assert doc_sb.meta['formatting']['suppress_blanks'] is True

    def content_y(d):
        out = pdf.emit_pdf(d, mode='printed')
        m = re.search(rb'([\d.]+) ([\d.]+) Td \(Actual', out)
        return float(m.group(2))

    # UPDATED 2026-08-20 (round 26 wave 3, WS7 ground truth): top offset is
    # now (.mt+.hm)*12 = 60pt for a headerless doc (was 36pt .mt-only) --
    # see _printed_top's docstring.
    assert content_y(doc_default) == 696.0    # top 60 + two 12pt blanks + 12pt lead
    assert content_y(doc_sb) == 720.0          # suppressed -- starts right at top+lead


def test_l_hash_gutter_numbers_every_nth_line_printed_pdf_and_rtf():
    body = (b'.l# 2' + HARD
            + HARD.join(b'Line %d text.' % i for i in range(1, 7)) + HARD)
    doc = core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)
    assert doc.meta['line_numbering'] == 2

    out = pdf.emit_pdf(doc, mode='printed')
    nums = re.findall(rb'BT /\S+ \d+ Tf 0 Ts [\d.]+ [\d.]+ Td \((\d+)\) Tj ET', out)
    assert nums == [b'2', b'4', b'6']

    r = emit.emit_rtf(doc, mode='printed')
    assert r'2\tab' in r and r'4\tab' in r and r'6\tab' in r
    assert r'1\tab' not in r and r'3\tab' not in r and r'5\tab' not in r


def test_line_numbers_flag_off_suppresses_the_gutter():
    body = (b'.l# 1' + HARD + b'One line only.' + HARD)
    doc = core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)
    out_off = pdf.emit_pdf(doc, mode='printed', line_numbers=False)
    assert not re.findall(rb'BT /\S+ \d+ Tf 0 Ts [\d.]+ [\d.]+ Td \(\d+\) Tj ET', out_off)
    r_off = emit.emit_rtf(doc, mode='printed', line_numbers=False)
    assert r'\tab' not in r_off


def test_line_numbers_never_reach_modern():
    body = (b'.l# 1' + HARD + b'One line only.' + HARD)
    doc = core.parse_ws(ws7_block(0x00, bytes([0x70]) + bytes(15)) + body)
    r_modern = emit.emit_rtf(doc, mode='modern')
    assert r'\tab' not in r_modern


# --------------------------------------------------------------- ledger row 7
# DIAGNOSE surfacing: `document_info()` (the library home of `--diagnose`)
# never read `doc.meta['formatting']` at all -- the internal Document object
# always carried `.pr`/`.sr`/`.ul`/`.sb`/`.ps`, but the actual diagnose
# SURFACE showed none of it. Standing discoverability rule (register):
# "everything these flags govern surfaces in Info/Diagnose regardless of
# flag state."

def _diag(body_after_header):
    data = (ws7_block(0x00, bytes([0x70]) + bytes(15)) + body_after_header)
    return info.document_info(data)


def test_diagnose_surfaces_formatting_dict():
    d = _diag(b'.pr or=l' + HARD + b'.sr 10' + HARD + b'.ul on' + HARD
              + b'Body text.' + HARD)
    assert d['formatting']['orientation'] == 'landscape'
    assert d['formatting']['sub_super_roll_48'] == 10.0
    assert d['formatting']['underline_blanks'] is True


def test_diagnose_omits_formatting_key_when_nothing_was_set():
    d = _diag(b'Plain body text, no dot commands at all.' + HARD)
    assert 'formatting' not in d


def test_diagnose_flags_ps_as_superseded():
    d = _diag(b'.ps on' + HARD + b'Body text.' + HARD)
    assert 'ps_note' in d and 'superseded' in d['ps_note']
    assert d['formatting']['proportional'] is True


def test_diagnose_surfaces_headers_footers_declared():
    d = _diag(b'.h1 Sawyer / Old Times / #' + HARD + b'Body text.' + HARD)
    assert d['headers'] == {1: 'Sawyer / Old Times / #'}
    assert 'footers' not in d


def test_diagnose_surfaces_line_numbering_interval():
    d = _diag(b'.l# 5' + HARD + b'Body text.' + HARD)
    assert d['line_numbering'] == 5


def test_diagnose_tags_psa_psb_as_wordtsar_origin():
    d = _diag(b'.PSB 1' + HARD + b'.PSA 2' + HARD + b'Body text.' + HARD)
    assert d['vertical_spacing'] == {
        'space_before_lines': 1.0, 'space_after_lines': 2.0, 'origin': 'wordtsar'}
    assert d['producer'] == 'wordtsar'


def test_diagnose_counts_pm_blocks():
    d = _diag(b'.pm 5' + HARD + b'First paragraph.' + HARD + HARD
              + b'Second paragraph, no .pm reset.' + HARD)
    assert d['pm_blocks'] >= 1


def test_diagnose_output_is_json_serializable():
    import json
    d = _diag(b'.pr or=l' + HARD + b'.sr 10' + HARD + b'.ul on' + HARD
              + b'.ps on' + HARD + b'.l# 3' + HARD + b'.pm 5' + HARD
              + b'.h1 Title / #' + HARD + b'.PSB 1' + HARD + b'.PSA 2' + HARD
              + b'Body text.' + HARD)
    json.dumps(d)   # must not raise


# ---------------------------------------------------- style-library helpers
# Trimmed local copies -- see test_modern_lint.py's own `_style_record`/
# `_style_library`/`_doc_with_style_library` for the field-by-field
# rationale (WordStar 7.0 file format spec, validated corpus-wide).

def _style_record_with_margins(left_hmi=1800, right_hmi=None, just=0, attrs_on=0):
    rec = bytearray(102)

    def put(off, b):
        rec[off:off + len(b)] = b
    put(0, (0xFFFF).to_bytes(2, 'little'))            # font: inherited
    put(10, left_hmi.to_bytes(2, 'little'))
    put(12, (right_hmi if right_hmi is not None else 0xFFFE).to_bytes(2, 'little'))
    put(14, (0xFFFE).to_bytes(2, 'little'))           # para margin: inherited
    rec[18] = 0xFF
    rec[19] = 0xFF                                    # tabs: inherited
    rec[86] = just % 256
    rec[87] = 1                                       # wrap on
    put(88, (0xFFFF).to_bytes(2, 'little'))           # line height: inherit
    rec[90] = 0xFF
    put(91, attrs_on.to_bytes(2, 'little'))
    rec[95] = 0xFF
    return bytes(rec)


def _style_library(entries):
    n = len(entries)
    items = b''
    records = b''
    rec_base = 13 + 5 + 33 * n
    for name, rec in entries:
        if name is None:
            items += b'\x3f' * 24 + b'\x00' * 9
            continue
        nm = name.encode().ljust(24, b' ')
        if rec is not None:
            items += (nm + b'\x02' + b'\x00' * 4
                      + (rec_base + len(records)).to_bytes(4, 'little'))
            records += rec
        else:
            items += nm + b'\x00' + b'\x00' * 8
    head = (b'\x1a\x55' + (1).to_bytes(2, 'little') + b'\x01'
            + n.to_bytes(2, 'little') + (102).to_bytes(2, 'little')
            + (13).to_bytes(4, 'little'))
    return head + bytes([n]) + b'\x00' * 4 + items + records


def _style_ref(slot):
    payload = ((0x0200 | slot).to_bytes(2, 'little') + (0x0201).to_bytes(2, 'little')
              + (0x0300).to_bytes(2, 'little') + (0x0201).to_bytes(2, 'little'))
    return ws7_block(0x11, payload)


def _doc_with_style_library(body, library, header=None):
    header = header if header is not None else bytes([0x70]) + bytes(15)
    doc = bytearray(ws7_block(0x00, header) + body)
    base = ((len(doc) + 127) // 128) * 128
    while len(doc) < base:
        doc.append(0x1a)
    doc += library
    base_bytes = base.to_bytes(4, 'little')
    doc[4 + 12:4 + 16] = base_bytes
    return bytes(doc)
