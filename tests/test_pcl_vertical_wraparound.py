"""planning #234: WS7's own LaserJet driver's internal ESC&a#V vertical-
position accumulator overflows past 2**15 (32768) decipoints and wraps
back to a small value WHILE STILL ON THE SAME LOGICAL PAGE (no 0x0C
between) -- confirmed by raw byte inspection of the real captured
ground truth, sawyer/REF/-PATCHES.WS page 19 (a `.pl0`, i.e. no-
automatic-page-break, continuously-flowing logical page): its ESC&a#V
values climb ..., 32520, 32760, then the VERY NEXT command in the
stream is the literal ASCII bytes "232" -- the wrapped value is baked
into WS7's own emitted bytes, not something either decoder misreads.
Un-handled, this inflated the baseline-shift divergence bucket by 1366
(41% of the corpus-wide total) on that one document/page alone, all of
it spurious: residuals of exactly +-3276.80pt or +-6553.60pt (2**15/10
and 2**16/10 decipoints), a dead giveaway of an unhandled power-of-two
wrap, not a real placement defect (`2026-09-08_placement-triage.md`,
exclusion E1).

Ruled out the alternative hypothesis (this issue's own question): is
WS7 using a RELATIVE move (ESC&a+nV) that the decoder's accumulator
stores/truncates in a 16-bit-ish way? No -- grepping the raw capture's
ESC&a#V fields around both wraps on page 19 found only unsigned
(absolute-form) values on both sides of the drop (no '+'/'-' prefix
anywhere near it); the wrap is genuinely in the absolute value WS7's
own driver emitted, matching the worked example encoded below.

Fix (both decoders, identically): apply_axis()/handle_field() now
detect a fresh ABSOLUTE value that would move the cursor backward by
more than half the wrap modulus (WRAP_HALF_DECIPT = 16384 decipoints =
22.75in -- already far larger than any real physical page, so this
never misfires on a genuine same-page backward move such as a footer
set below a full page of body text) and correct it by adding
WRAP_MODULUS_DECIPT (32768), repeated for a hypothetical multi-wrap
case, keeping the corrected position monotonically climbing with the
page instead of falling back near zero. The wrap-offset accumulator
resets to 0 at every real page eject (0x0C), same as cursor_x/cursor_y.

Confirmed against the real corpus (2026-09-08): re-decoding
sawyer/REF/-PATCHES.WS page 19 with both fixed decoders now yields a
monotonically non-decreasing y-position sequence (480 -> 97704
decipoints, two wraps corrected, zero backward jumps), and regenerating
that document's ground-truth measurements.json with the fixed
tools/pcl_render.py and re-running the fidelity gate turns its verdict
from divergent (1366 baseline-shift + 37 extra-word-in-engine + 33
word-unmatched, all cascading from the same wrap) to fully clean.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

import pcl_text                                                # noqa: E402
import pcl_render as pr                                        # noqa: E402


def _preamble(x=576, y=480):
    return f'\x1b&a{x}H\x1b&a{y}V'.encode('ascii')


def _move_v(y):
    return f'\x1b&a{y}V'.encode('ascii')


def _synthetic_wrap_stream():
    """Mirrors the REAL sawyer/REF/-PATCHES.WS page 19 worked example: a
    vertical position climbs in 120-decipoint steps up to 32760 (one step
    short of the 32768 wrap modulus), then WS7's own driver emits the
    wrapped value 232 (32760 + 240 - 32768) as the very next absolute
    command, followed by more climbing -- twice, matching the two real
    wraps found on that page."""
    out = _preamble(y=32520)
    out += b'before-wrap-1'
    out += _move_v(32760)
    out += b'at-wrap-1'
    out += _move_v(232)  # WS7's own wrapped byte, not a decoder misread
    out += b'after-wrap-1'
    out += _move_v(32752)
    out += b'before-wrap-2'
    out += _move_v(224)  # second wrap, same shape
    out += b'after-wrap-2'
    return out


def _run_pcl_text(data):
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 1
    return pages[0]


def _run_pcl_render(data):
    pages, unhandled, recognized_not_rendered, meta = pr.parse_pcl_extended(data)
    assert len(pages) == 1
    return [c for c in pages[0] if c.get('type', 'text') == 'text']


def test_wraparound_stays_monotonic_pcl_text():
    runs = _run_pcl_text(_synthetic_wrap_stream())
    ys = [r['y_decipoints'] for r in runs]
    assert ys == sorted(ys), f"expected non-decreasing y sequence, got {ys}"
    # the two wraps must have been corrected, not just clamped/dropped
    assert ys[-1] > 65536, f"expected the second wrap to be fully unwound, got {ys}"


def test_wraparound_exact_values_pcl_text():
    runs = _run_pcl_text(_synthetic_wrap_stream())
    by_text = {r['text']: r['y_decipoints'] for r in runs}
    assert by_text['before-wrap-1'] == 32520
    assert by_text['at-wrap-1'] == 32760
    # 232 unwrapped: raw 232 + one modulus (32768) = 33000, continuing the
    # +240/line climb from 32760 (32760 + 240 = 33000) -- not the raw 232.
    assert by_text['after-wrap-1'] == 33000
    # 32752 + one modulus (32768) = 65520 -- still only one wrap applied
    # (this value, on its own, is not a backward jump from 33000).
    assert by_text['before-wrap-2'] == 65520
    # second wrap: raw 224 + two moduli (65536) = 65760.
    assert by_text['after-wrap-2'] == 65760


def test_real_page_eject_resets_wrap_state_pcl_text():
    """A genuine 0x0C page eject must reset the wrap-offset accumulator,
    the same way it resets cursor_x/cursor_y -- otherwise a wrap on one
    page would corrupt every later page's positions too."""
    data = _preamble(y=32700) + b'p1'
    data += _move_v(32760) + b'p1b'
    data += b'\x0c'  # real page eject
    data += _preamble(y=100) + b'p2'
    pages = pcl_text.parse_pcl(data)
    assert len(pages) == 2
    assert pages[1][0]['y_decipoints'] == 100  # not 100 + 32768


def test_ordinary_backward_move_is_not_miscorrected_pcl_text():
    """A real same-page backward move (e.g. a footer set above a tall body)
    must NOT be treated as a wrap: the drop here (9000 -> 700) is nowhere
    near WRAP_HALF_DECIPT (16384), so it must pass through unchanged."""
    data = _preamble(y=9000) + b'body'
    data += _move_v(700) + b'footer'
    runs = pcl_text.parse_pcl(data)[0]
    by_text = {r['text']: r['y_decipoints'] for r in runs}
    assert by_text['footer'] == 700


def test_wraparound_stays_monotonic_pcl_render():
    chunks = _run_pcl_render(_synthetic_wrap_stream())
    ys = [c['y_decipoints'] for c in chunks]
    assert ys == sorted(ys), f"expected non-decreasing y sequence, got {ys}"
    assert ys[-1] > 65536, f"expected the second wrap to be fully unwound, got {ys}"


def test_wraparound_exact_values_pcl_render():
    chunks = _run_pcl_render(_synthetic_wrap_stream())
    by_text = {c['text']: c['y_decipoints'] for c in chunks}
    assert by_text['before-wrap-1'] == 32520
    assert by_text['at-wrap-1'] == 32760
    assert by_text['after-wrap-1'] == 33000
    assert by_text['before-wrap-2'] == 65520
    assert by_text['after-wrap-2'] == 65760


def test_real_page_eject_resets_wrap_state_pcl_render():
    data = _preamble(y=32700) + b'p1'
    data += _move_v(32760) + b'p1b'
    data += b'\x0c'
    data += _preamble(y=100) + b'p2'
    pages, unhandled, recognized_not_rendered, meta = pr.parse_pcl_extended(data)
    assert len(pages) == 2
    p2_text = [c for c in pages[1] if c.get('type', 'text') == 'text']
    assert p2_text[0]['y_decipoints'] == 100


def test_ordinary_backward_move_is_not_miscorrected_pcl_render():
    data = _preamble(y=9000) + b'body'
    data += _move_v(700) + b'footer'
    chunks = _run_pcl_render(data)
    by_text = {c['text']: c['y_decipoints'] for c in chunks}
    assert by_text['footer'] == 700
