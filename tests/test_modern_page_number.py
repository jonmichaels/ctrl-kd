r"""M15 (Jon's ruling 2026-09-15): MODERN SHOWS WORDSTAR'S AUTOMATIC PAGE
NUMBER.

Jon: "I think it should in Modern View. Maybe I said something different
previously. But I'm now finding that it looks weird that it suddenly goes
away. Now on Export that's different. There's a flag if people want Page
Number or not, that can be selected."

So the Modern VIEW shows the automatic number wherever Printed does, and
Modern EXPORTS obey `--page-numbers` auto/on/off exactly as Printed does --
the same sentence twice, because the app's Modern view IS this engine's
`auto` Modern PDF. Modern RTF has carried the number since the running-head
round (a `\footer` group of `\chpgn`); Modern PDF was the one paged surface
still dropping it, so switching the app from Printed to Modern made a
document's numbering vanish.

WHETHER IT SHOWS IS THE DOCUMENT'S ANSWER, and the three silencers are
measured, not assumed -- research/2026-09-15_ws7-missing-auto-page-number.md,
308 real WS7 captures, zero counter-examples:

  1. `.op`, with `.pn`/`.pg` turning it back on from where THEY sit.
  2. ANY footer command, with text, bare, or only invisible characters --
     the footer REPLACES the number.
  3. `.mb 0` -- no footer row on the sheet, so nowhere to put one.

WHERE IT SHOWS IS MODERN'S ANSWER ("placed the Modern way"): the row a
Modern footer line 1 rides, centred in Modern's own measure, in the face and
size Modern's running feet already use. Never Printed's `.pc` column, and
never Printed's `pl - mb + fm` row.

Synthetic fixtures only.
"""
import re

import pytest

from ctrlkd import core, emit, pdf

HARD = b'\x0d\x0a'
MODERN_FOOT_Y = 44.0             # the row Modern's own footer line 1 rides


def _ws7(body, dots=b''):
    count = (4 + 16).to_bytes(2, 'little')
    head = b'\x1d' + count + b'\x00' + bytes([0x70]) + bytes(15) + count + b'\x1d'
    return core.parse_ws(head + dots + body)


_TD = re.compile(rb'BT /\S+ [\d.]+ Tf [-\d.]+ Ts ([\d.]+) ([\d.-]+) Td \((.*?)\) Tj ET')


def _streams(out):
    return [s.split(b'\nendstream')[0] for s in out.split(b'>>\nstream\n')[1:]]


def _foot_row(stream):
    """Every drawn (x, text) on Modern's own footer row."""
    return [(float(x), t.decode('latin-1')) for x, y, t in _TD.findall(stream)
            if abs(float(y) - MODERN_FOOT_Y) < 0.05]


def _numbers(doc, **options):
    """The automatic page number drawn on each Modern page, or None --
    a LONE digits-only op on the footer row, centred in Modern's measure."""
    margl, _mt, _mb, width = pdf._modern_geometry(doc)
    centre = margl + width / 2.0
    out = []
    for st in _streams(pdf.emit_pdf(doc, mode='modern', **options)):
        row = _foot_row(st)
        if len(row) == 1 and row[0][1].isdigit() and abs(row[0][0] - centre) < 10.0:
            out.append(row[0][1])
        else:
            out.append(None)
    return out


# a body long enough to fill three Modern pages
_PARA = (b'The quick brown fox jumps over the lazy dog and keeps running '
         b'until the line has to wrap somewhere sensible.' + HARD)
_LONG = _PARA * 60


# ------------------------------------------------------ the stock behaviour

def test_a_plain_document_numbers_every_modern_page():
    nums = _numbers(_ws7(_LONG))
    assert len(nums) > 1
    assert nums == [str(i + 1) for i in range(len(nums))], nums


def test_the_number_sits_on_moderns_own_footer_row_centred():
    doc = _ws7(_LONG)
    margl, _mt, _mb, width = pdf._modern_geometry(doc)
    row = _foot_row(_streams(pdf.emit_pdf(doc, mode='modern'))[0])
    assert len(row) == 1
    x, txt = row[0]
    assert txt == '1'
    assert abs(x - (margl + width / 2.0)) < 10.0, (x, margl, width)


def test_the_number_is_not_at_printeds_own_column():
    """Printed anchors it at `.po + .pc` columns (`_auto_pageno_x_pt`);
    Modern centres it in its own measure. The two only coincide by
    accident, and this document is not that accident."""
    doc = _ws7(_LONG, dots=b'.po 20' + HARD)
    row = _foot_row(_streams(pdf.emit_pdf(doc, mode='modern'))[0])
    assert len(row) == 1
    assert abs(row[0][0] - pdf._auto_pageno_x_pt(doc)) > 10.0


def test_the_number_starts_where_pn_says():
    nums = _numbers(_ws7(_LONG, dots=b'.pn 7' + HARD))
    assert nums[0] == '7'
    assert nums[1] == '8'


# --------------------------------------------------- silencer 1: `.op`/`.pn`

def test_op_silences_the_modern_number():
    assert set(_numbers(_ws7(_LONG, dots=b'.op' + HARD))) == {None}


def test_pn_after_op_turns_it_back_on():
    doc = _ws7(b'Opening.' + HARD + b'.pn 3' + HARD + _LONG, dots=b'.op' + HARD)
    nums = _numbers(doc)
    assert any(n is not None for n in nums), nums


# ---------------------------------------------------- silencer 2: the footer

def test_a_bare_fo_silences_the_modern_number():
    """"That holds whether the footer has text, is bare, or contains only
    invisible characters" -- research 2026-09-15, rule 2."""
    assert set(_numbers(_ws7(_LONG, dots=b'.fo' + HARD))) == {None}


def test_a_footer_with_text_silences_the_modern_number():
    nums = _numbers(_ws7(_LONG, dots=b'.fo Chapter one' + HARD))
    assert set(nums) == {None}


def test_a_footer_typed_after_the_last_block_still_silences_it():
    """`sawyer/REF/BUGS.WS`'s own shape: a `.fo` anchored past the
    document's last block. It never reaches the Modern FLOW at all
    (`layout.modern_flow` walks `enumerate(doc.blocks)`), so the page's
    own `cur_f` snapshot cannot see it -- the decision reads the event's
    anchor directly for exactly this case."""
    doc = _ws7(b'Body text.' + HARD + b'.fo' + HARD)
    assert getattr(doc, 'hf_events', None), 'fixture lost its footer event'
    assert set(_numbers(doc)) == {None}


# ------------------------------------------------------- silencer 3: `.mb 0`

def test_mb_zero_silences_the_modern_number():
    """"No bottom margin -- there is no footer line on the sheet at all,
    so there is nowhere to put a number" (research, rule 3). In the
    archive that is the label/Rolodex/mail-merge stock."""
    assert set(_numbers(_ws7(_LONG, dots=b'.mb 0' + HARD))) == {None}


def test_the_row_test_is_the_one_printed_uses():
    """One definition, two readers: Printed draws at this y, Modern only
    asks whether it is None."""
    assert pdf._auto_pageno_row_y(792, 66, 8, 2, 12) == 60.0
    assert pdf._auto_pageno_row_y(72, 6, 0, 0, 12) is None


def test_the_row_steps_by_a_page_line_not_the_documents_lh():
    """Planning #274: `.pl`/`.mb`/`.fm` count PAGE lines -- WordStar's
    fixed 6-LPI grid -- and the row used to be multiplied by the
    document's own `.lh` instead. Identical whenever `.lh` is the default
    12pt, which is why it went unseen; a document that sets `.lh` higher
    had the row pushed down by (lh - 12) x ~60 lines and lost its number.
    `sawyer/REF/SUB-SUPE.TST` (`.lh` 24pt, `.pl 66 .mb 8 .fm 2`) is the
    case: real WS7 prints its number 732pt from the top of the sheet, the
    row this arithmetic gives at 6 LPI and nowhere near the 1452pt a
    24pt step would."""
    assert pdf._auto_pageno_row_y(792, 66, 8, 2, 12) == 792 - 60 * 12 - 12


def test_the_row_keeps_fractional_page_lines():
    """`.mb 1.8`/`.fm 1.14` are ordinary corpus values
    (`sawyer/REF/PS-FONTS.REF`, `sawyer/REF/ADVANCE.DOT`) and truncating
    them to integers moved the row by most of an inch."""
    assert pdf._auto_pageno_row_y(792, 66.0, 1.8, 2.0, 12) == \
        pytest.approx(792 - 66.2 * 12 - 12, abs=1e-9)


def test_the_row_is_returned_even_when_it_falls_past_the_paper():
    """Real WS7 does not clamp: with `.mb 1.8 .fm 2` on a 66-line page it
    commands the number 806.4pt from the top of a 792pt sheet -- 14.4pt
    past the bottom edge -- and the printer clips it. The engine does the
    same and lets the page clip it, instead of dropping the row. A blanket
    "must be on the paper" guard used to do the dropping, and it was
    standing in for the `.mb 0` rule below."""
    y = pdf._auto_pageno_row_y(792, 66.0, 1.8, 2.0, 12)
    assert y is not None and y < 0


def test_no_bottom_margin_means_no_row_at_all():
    """Research 2026-09-15 rule 3, 24 captures and no counter-example: no
    bottom margin means there is no footer line on the sheet, so there is
    nowhere to put a number. `MAILLIST/LABELA` is `.pl 6 .mb 0 .fm 0`."""
    assert pdf._auto_pageno_row_y(72, 6, 0, 0, 12) is None
    assert pdf._auto_pageno_row_y(792, 0.0, 0.0, 2.0, 12) is None


# ------------------------------------------------------------- the flag

def test_page_numbers_off_silences_a_numbering_document():
    assert set(_numbers(_ws7(_LONG), page_numbers='off')) == {None}


def test_page_numbers_on_forces_it_over_op():
    nums = _numbers(_ws7(_LONG, dots=b'.op' + HARD), page_numbers='on')
    assert nums[0] == '1'


def test_page_numbers_on_cannot_conjure_a_row_that_is_not_there():
    """`on` overrides the DOCUMENT'S CHOICE (`.op`). It does not override
    what WordStar itself does: a sheet with no footer row has nowhere to
    put a number, and a footer already occupies the row."""
    assert set(_numbers(_ws7(_LONG, dots=b'.mb 0' + HARD),
                        page_numbers='on')) == {None}
    assert set(_numbers(_ws7(_LONG, dots=b'.fo' + HARD),
                        page_numbers='on')) == {None}


# ------------------------------------- Modern PDF and Modern RTF agree again

def test_modern_rtf_and_modern_pdf_agree_about_numbering():
    """The 2026-08-05 ruling: Modern PDF is the printed form of the Modern
    RTF. The RTF said `\\chpgn` while the PDF drew nothing -- that is the
    defect M15 closes, stated as an equality."""
    for dots, numbered in ((b'', True), (b'.op' + HARD, False),
                           (b'.fo' + HARD, False)):
        doc = _ws7(_LONG, dots=dots)
        rtf = emit.emit_rtf(doc, mode='modern')
        assert (r'\chpgn' in rtf) is numbered, dots
        assert (_numbers(doc)[0] is not None) is numbered, dots


def _rtf_auto_footer(rtf):
    r"""True when the RTF carries WordStar's AUTOMATIC number -- a
    `\footer` group whose whole content is `\chpgn`. A `#` the author
    typed into a real head or foot also renders as `\chpgn`, so a bare
    substring test would answer a different question."""
    return bool(re.search(r'\\footer [^{}]*\{\\chpgn \}\\par\}', rtf))


def test_a_bare_fo_silences_the_rtf_number_in_both_modes():
    r"""M15 follow-up, and the same rule the PDF's own 2026-09-12 triage
    fixed: "any footer command -- with text, bare, or carrying only
    invisible characters" silences the automatic number.
    `emit._hf_slots` drops an event with no text at all, so a document
    whose ONLY footer is a bare `.fo` used to read as "no footer in use"
    and RTF printed a number both PDFs did not. Five archive documents are
    that shape and their `rtf.printed` and `rtf.modern` move with this."""
    bare = _ws7(_LONG, dots=b'.fo' + HARD)
    for mode in ('printed', 'modern'):
        assert not _rtf_auto_footer(emit.emit_rtf(bare, mode=mode)), mode
    plain = _ws7(_LONG)
    for mode in ('printed', 'modern'):
        assert _rtf_auto_footer(emit.emit_rtf(plain, mode=mode)), mode


def test_an_invisible_only_footer_silences_it_too():
    """LJ6DTP.WS's own `.f1` is two print-control bytes and renders
    nothing visible; it was already read as "in use" because it carries
    text. Pinned so the fix above cannot be narrowed back to it."""
    doc = _ws7(_LONG, dots=b'.fo \x0f\x0f' + HARD)
    assert not _rtf_auto_footer(emit.emit_rtf(doc, mode='modern'))
    assert _numbers(doc)[0] is None


# ------------------------------------------- `--headers off` reaches Modern
#
# `--headers` governs the RUNNING HEADS AND FEET on every paged surface
# (register, "Flag UI + defaults"; ruled again 2026-09-14, planning #264
# R7). Printed PDF and both RTF modes have honoured it since `722b877`;
# Modern PDF was the one paged surface still drawing its heads under
# `off`, so `sr -t pdf --mode modern --headers off` on `REF/BOOKLET.WS`
# kept all three of that document's running heads. M5 ("Modern keeps
# running heads", ruled 2026-08-06) is the DEFAULT this flag turns off,
# never a refusal of the flag.

_HEAD_AND_FOOT = b'.h1 Running Head' + HARD + b'.f1 Running Foot' + HARD


def _drawn(doc, **options):
    """Every string Modern's first page draws, in the order it draws it."""
    st = _streams(pdf.emit_pdf(doc, mode='modern', **options))[0]
    return [t.decode('latin-1') for _x, _y, t in _TD.findall(st)]


def test_headers_off_drops_moderns_running_heads_and_feet():
    doc = _ws7(_LONG, dots=_HEAD_AND_FOOT)
    on = _drawn(doc, headers=True)
    assert 'Head' in on and 'Foot' in on
    off = _drawn(doc, headers=False)
    assert 'Head' not in off and 'Foot' not in off


def test_headers_off_never_touches_moderns_body():
    """The flag reaches the margin zones and nothing else."""
    doc = _ws7(_LONG, dots=_HEAD_AND_FOOT)
    body_on = [t for t in _drawn(doc, headers=True) if t not in ('Running', 'Head', 'Foot')]
    body_off = [t for t in _drawn(doc, headers=False) if t != 'Running']
    assert body_off == body_on and body_on[:3] == ['The', 'quick', 'brown']


def test_headers_off_keeps_moderns_automatic_number():
    """Two flags, two subjects: `--page-numbers` governs WordStar's own
    automatic number ALONE, so it survives `--headers off` exactly as it
    does in Printed (`test_printed_fidelity.py`'s own twin)."""
    doc = _ws7(_LONG, dots=b'.h1 Running Head' + HARD)
    for headers in (True, False):
        assert _numbers(doc, headers=headers)[0] == '1'
        assert _numbers(doc, headers=headers, page_numbers='off')[0] is None
    assert 'Head' not in _drawn(doc, headers=False)


def test_a_declared_footer_still_pre_empts_moderns_number_with_headers_off():
    """"In use" is a property of the DOCUMENT, not of the flag -- the same
    hazard `722b877` pinned on the Printed side. Suppressing a footer's
    DRAWING must not conjure a number the document never had."""
    for dots in (b'.fo' + HARD, b'.f1 Running Foot' + HARD):
        doc = _ws7(_LONG, dots=dots)
        for headers in (True, False):
            assert _numbers(doc, headers=headers)[0] is None, (dots, headers)


def test_the_modern_footer_row_keeps_the_number_when_its_head_is_suppressed():
    """The number rides Modern's own footer row. A document with a head
    and no footer declared keeps that row's number under `--headers off`,
    centred where it always was."""
    doc = _ws7(_LONG, dots=b'.h1 Running Head' + HARD)
    margl, _mt, _mb, width = pdf._modern_geometry(doc)
    row = _foot_row(_streams(pdf.emit_pdf(doc, mode='modern', headers=False))[0])
    assert len(row) == 1
    x, txt = row[0]
    assert txt == '1'
    assert abs(x - (margl + width / 2.0)) < 10.0, (x, margl, width)
