"""planning #264 item 4 (packet rows A3-A6): facing pages in RTF.

THE DEFECT, named by the packet: "GALLEYS.DOT sets 'TITLE' on right-hand
pages and 'ROBERT J. SAWYER' on left-hand ones. The RTF prints 'TITLE' on
every page and the author's name on none." Every fact needed to fix that
was already parsed and read only by the PDF:

  A3  `hf_events_parity` (planning #250) -- which of `.h1o`/`.h1e`/
      `.f1o`/`.f1e` each running-head event came from. RTF gets
      `\\facingp` plus `\\headerr` (odd, the RIGHT-hand page) and
      `\\headerl` (even).
  A4  `header_align`/`footer_align` and their parity siblings (planning
      #255) -- the alignment the `.h#`/`.f#` argument's own embedded style
      sheet declares. RTF gets `\\qr`/`\\qc` on the group's paragraph.
  A5  `.mt`/`.hm`/`.pl`/`.mb`/`.fm` -- RTF gets `\\headery`/`\\footery`,
      computed by the PDF's own formula (`head_base = mt - hm - top_head`
      lines from the top; `mb - fm - 1` lines under the footer).
  A6  `.poe`/`.poo` -- RTF gets `\\margmirror` under `\\facingp`, with
      `\\margl` the odd (inside) offset and `\\margr` the even one.

A5 and A6 are PRINTED ONLY: Modern's page is its own fixed Letter and
Modern carries none of our vertical space (ruling 2026-08-17, "never
Modern"; packet row D9). A3 and A4 are the head's own structure and
content, so they land in both modes.
"""
import pytest

from ctrlkd import core, emit


def _doc(events, parities, page=None, aligns=None, dots=()):
    doc = core.Document(
        blocks=[core.Block('para', lines=[core.Line(spans=[core.Span('body')])])],
        meta={'variant': 'ws5+', 'page': dict(page or {}),
              'dot_positions': [(0, 0, d) for d in dots]})
    doc.hf_events = list(events)
    doc.hf_events_parity = list(parities)
    for kind, lno, txt, _anchor in events:
        (doc.headers if kind == 'H' else doc.footers)[lno] = txt
    for (which, lno, parity), value in (aligns or {}).items():
        if parity is None:
            getattr(doc, '%s_align' % which)[lno] = value
        else:
            getattr(doc, '%s_align_parity' % which).setdefault(lno, {})[parity] = value
    return doc


# ------------------------------------------------- A3: left and right heads

@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_parity_heads_become_headerl_and_headerr(mode):
    out = emit.emit_rtf(_doc([('H', 1, 'TITLE', 0), ('H', 1, 'AUTHOR', 0)],
                             ['O', 'E']), mode=mode)
    assert r'\facingp' in out
    assert r'{\headerr ' in out and 'TITLE' in out
    assert r'{\headerl ' in out and 'AUTHOR' in out


def test_odd_is_the_right_hand_page():
    """WordStar's odd page is the right-hand one, which is `\\headerr`."""
    out = emit.emit_rtf(_doc([('H', 1, 'ODD', 0), ('H', 1, 'EVEN', 0)],
                             ['O', 'E']))
    right = out.index(r'{\headerr ')
    left = out.index(r'{\headerl ')
    assert 'ODD' in out[right:left] and 'EVEN' in out[left:]


def test_a_head_declared_for_one_parity_only_prints_on_that_side():
    out = emit.emit_rtf(_doc([('H', 1, 'ODD ONLY', 0)], ['O']))
    assert r'{\headerr ' in out
    assert r'{\headerl ' not in out


def test_a_plain_head_applies_to_both_sides():
    """A document with no parity variant anywhere keeps the single
    `\\header` group it always had -- and no `\\facingp`."""
    out = emit.emit_rtf(_doc([('H', 1, 'BOTH', 0)], [None]))
    assert r'{\header ' in out
    assert r'\facingp' not in out
    assert r'\headerl' not in out


def test_footers_take_the_same_treatment():
    out = emit.emit_rtf(_doc([('F', 1, 'ODD FOOT', 0), ('F', 1, 'EVEN FOOT', 0)],
                             ['O', 'E']))
    assert r'{\footerr ' in out and r'{\footerl ' in out


# ---------------------------------------------------------- A4: alignment

@pytest.mark.parametrize('align,ctl', [('right', r'\qr'), ('center', r'\qc')])
def test_the_heads_own_alignment_reaches_the_group(align, ctl):
    out = emit.emit_rtf(_doc([('H', 1, 'TITLE', 0)], [None],
                             aligns={('header', 1, None): align}))
    assert (r'{\header \pard\plain %s\f0\fs22 ' % ctl) in out


def test_alignment_is_per_parity():
    out = emit.emit_rtf(_doc([('H', 1, 'ODD', 0), ('H', 1, 'EVEN', 0)], ['O', 'E'],
                             aligns={('header', 1, 'O'): 'right'}))
    assert r'{\headerr \pard\plain \qr' in out
    assert r'{\headerl \pard\plain \f0' in out          # left, as declared


def test_an_undeclared_alignment_writes_nothing():
    out = emit.emit_rtf(_doc([('H', 1, 'TITLE', 0)], [None]))
    assert r'{\header \pard\plain \f0\fs22 ' in out


# ------------------------------------------------- A5: head and foot distance

def test_headery_and_footery_follow_the_pdfs_own_formula():
    """`.mt 7 .hm 3` with one head line: head_base = 7 - 3 - 1 = 3 lines.
    `.pl 66 .mb 8 .fm 2`: 8 - 2 - 1 = 5 lines under the footer."""
    out = emit.emit_rtf(_doc([('H', 1, 'TITLE', 0)], [None],
                             page={'mt_lines': 7, 'hm_lines': 3,
                                   'pl_lines': 66, 'mb_lines': 8, 'fm_lines': 2}),
                        mode='printed')
    assert r'\headery720' in out                       # 3 * 240
    assert r'\footery1200' in out                      # 5 * 240


def test_the_distance_never_goes_negative():
    out = emit.emit_rtf(_doc([('H', 1, 'T', 0)], [None],
                             page={'mt_lines': 1, 'hm_lines': 3,
                                   'mb_lines': 1, 'fm_lines': 3}),
                        mode='printed')
    assert r'\headery0' in out and r'\footery0' in out


def test_modern_carries_no_head_foot_distance():
    """Ruling 2026-08-17: Modern's page is its own; the reader's gap
    stands, exactly as the reader's leading does."""
    out = emit.emit_rtf(_doc([('H', 1, 'TITLE', 0)], [None],
                             page={'mt_lines': 7, 'hm_lines': 3}),
                        mode='modern')
    assert r'\headery' not in out and r'\footery' not in out


# ------------------------------------------------ A6: mirrored binding margin

def test_poe_and_poo_mirror_the_margins():
    """`.poo` is the odd (right-hand) page's own left offset, which under
    `\\margmirror` is `\\margl`; `.poe` is the even page's, `\\margr`."""
    out = emit.emit_rtf(_doc([], [], dots=['.poe 1.35i', '.poo 5.8125i']),
                        mode='printed')
    assert r'\facingp' in out and r'\margmirror' in out
    assert r'\margl8370' in out                        # 58.125 cols * 144
    assert r'\margr1944' in out                        # 13.5 cols * 144


def test_modern_keeps_its_own_fixed_page():
    out = emit.emit_rtf(_doc([], [], dots=['.poe 1.35i', '.poo 5.8125i']),
                        mode='modern')
    assert r'\margmirror' not in out


def test_a_document_without_poe_poo_is_unmirrored():
    out = emit.emit_rtf(_doc([], []), mode='printed')
    assert r'\margmirror' not in out


# ---------------------------------------------------- the real corpus (tier 2)

@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_galleys_prints_both_of_its_heads(require_sawyer_doc, mode):
    """The packet's own example."""
    with open(require_sawyer_doc('REF/GALLEYS.DOT'), 'rb') as fh:
        doc = core.parse(fh.read())
    out = emit.emit_rtf(doc, mode=mode)
    assert r'\facingp' in out
    assert r'{\headerr \pard\plain \qr' in out and 'TITLE' in out
    assert r'{\headerl ' in out and 'ROBERT J. SAWYER' in out


@pytest.mark.sawyer
def test_galleys_geometry(require_sawyer_doc):
    """`.mt 1.25i` (7.5 lines) `.hm .20i` (1.2) one head line -> 5.3 lines;
    `.mb 1.50i` (9.0) `.fm .19i` (1.14) -> 6.86 lines. `.poo 5.8125i` /
    `.poe 1.35i` mirror."""
    with open(require_sawyer_doc('REF/GALLEYS.DOT'), 'rb') as fh:
        doc = core.parse(fh.read())
    out = emit.emit_rtf(doc, mode='printed')
    assert r'\headery1272' in out and r'\footery1646' in out
    assert r'\margl8370\margr1944' in out
    assert r'\margmirror' in out


@pytest.mark.sawyer
@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_a_single_sided_document_is_unchanged(require_sawyer_doc, mode):
    """-README.WS declares one plain `.h1` and must keep the single
    `\\header` group, with no facing pages anywhere."""
    with open(require_sawyer_doc('-README.WS (root)'), 'rb') as fh:
        doc = core.parse(fh.read())
    out = emit.emit_rtf(doc, mode=mode)
    assert r'{\header ' in out
    assert r'\facingp' not in out and r'\margmirror' not in out
