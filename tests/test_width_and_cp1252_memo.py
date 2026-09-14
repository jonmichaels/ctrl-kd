"""Perf (planning #271 M7): two pure per-string/per-character answers are
memoized instead of recomputed tens of thousands of times per document.

Both memos are caches over PURE functions of their arguments -- the AFM
width tables and the cp1252 repertoire are module-level and never rebuilt --
so the only thing worth testing is that the cache never changes an answer,
including across its own eviction boundary.
"""
from ctrlkd import afm, pdf


# -------------------------------------------------------------- string widths

def test_a_memoized_width_is_the_width_it_always_was():
    for text, font in (('Chapter One', 'Times-Roman'),
                       ('Chapter One', 'Helvetica-Bold'),
                       ('', 'Times-Roman'),
                       (' ', 'Courier'),
                       ('fi—’', 'Times-Italic'),
                       ('ΘΩ', 'Symbol')):
        afm._WIDTH_MEMO.clear()
        cold = afm.string_width_1000(text, font)
        warm = afm.string_width_1000(text, font)
        assert cold == warm
        # and the memo did not swallow the second call's answer
        afm._WIDTH_MEMO.clear()
        assert afm.string_width_1000(text, font) == cold


def test_the_width_memo_keys_on_the_font_as_well_as_the_text():
    afm._WIDTH_MEMO.clear()
    times = afm.string_width_1000('Chapter One', 'Times-Roman')
    courier = afm.string_width_1000('Chapter One', 'Courier')
    assert times != courier
    assert afm.string_width_1000('Chapter One', 'Times-Roman') == times


def test_an_unknown_face_still_falls_back_to_courier_through_the_memo():
    afm._WIDTH_MEMO.clear()
    assert (afm.string_width_1000('abc', 'No-Such-Face')
            == afm.string_width_1000('abc', 'Courier'))


def test_a_full_memo_clears_rather_than_growing_without_bound():
    afm._WIDTH_MEMO.clear()
    cap = afm._WIDTH_MEMO_CAP
    try:
        afm._WIDTH_MEMO_CAP = 4
        widths = [afm.string_width_1000('w%d' % i, 'Courier') for i in range(12)]
        assert len(afm._WIDTH_MEMO) <= 4
        # every answer survives the eviction unchanged
        assert [afm.string_width_1000('w%d' % i, 'Courier')
                for i in range(12)] == widths
    finally:
        afm._WIDTH_MEMO_CAP = cap
        afm._WIDTH_MEMO.clear()


# ------------------------------------------------------------ cp1252 verdicts

def test_the_cp1252_verdict_is_the_verdict_encode_gives():
    pdf._CP1252_OK_MEMO.clear()
    for ch in ('A', ' ', '—', '’', '€',
               'Θ', '─', '☺', 'π'):
        try:
            ch.encode('cp1252')
            expected = True
        except UnicodeEncodeError:
            expected = False
        assert pdf._cp1252_ok(ch) is expected
        assert pdf._cp1252_ok(ch) is expected          # again, from the memo


def test_both_verdicts_are_cached_not_just_the_true_one():
    """A memo that stores only `True` would re-raise for every Greek letter
    in a symbol chart -- exactly the case this exists for."""
    pdf._CP1252_OK_MEMO.clear()
    pdf._cp1252_ok('Θ')
    assert pdf._CP1252_OK_MEMO['Θ'] is False
    pdf._cp1252_ok('A')
    assert pdf._CP1252_OK_MEMO['A'] is True
