"""The `pcl` pytest tier: tools/fidelity_gate.py's coordinate comparison
against real WS7 LaserJet PCL captures, wired into pytest and checked
against a committed answer key (tests/pcl_fidelity_manifest.json).

Armed by $CTRLKD_PRIVATE_CORPUS (data lives at its own ws7-prints/v1/
subdirectory; see tools/fidelity_gate.py's own doc-resolution docstring).
Unarmed, `pcl`-marked tests are DESELECTED by pyproject.toml's addopts --
same convention as the `sawyer` tier -- so a bare `pytest` never collects
them at all. If someone explicitly runs `pytest -m pcl` unarmed anyway,
each test still SKIPS by its own doc name (never silently, never a fake
pass) rather than raising a collection error, because $CTRLKD_SAWYER_ARCHIVE
also gates a few of these docs independently (see below) and the two
unarmed states need to read differently in the output.

WHAT A FAILURE MEANS. Per the finalization plan: any residual beyond its
font-class tolerance is a NAMED divergence, and any divergence whose
reason isn't one of tools/pcl_tolerance.py's own FONT_SUBSTITUTION_REASONS
(mechanism I: CG-Times/Univers drift beyond the modelled tolerance -- see
that module's reason-vocabulary block) is a bug -- so this test FAILS BY
NAME (one parametrized case per document) whenever the checked-in manifest
records a real (non-font-substitution) divergence for that document. A
document whose ONLY divergences are font-substitution PASSES -- the count
is still printed, never silently dropped. That is intentional: a document
with a known, unfixed placement bug stays visibly red in this suite until
the bug is fixed or the manifest's classification of it is corrected with
evidence -- it does not go green just because the number was written down
once (see tests/conftest.py's "a skipped check is not a passing check"
doctrine, same spirit applied to a failing one).

The test also fails if a LIVE run's divergence set has drifted from the
manifest -- regenerate with `python3 tools/pcl_tolerance.py --record` and
review the diff (never regenerate inside the test itself: a test that can
rewrite its own answer key can never fail).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'tools'))
import pcl_tolerance as pt  # noqa: E402

pytestmark = pytest.mark.pcl

MANIFEST = pt.load_manifest()


def _armed():
    return bool(os.environ.get('CTRLKD_PRIVATE_CORPUS'))


@pytest.mark.parametrize('doc_name', pt.CAPTURED_DOCS)
def test_pcl_fidelity(doc_name):
    if not _armed():
        pytest.skip(f'{doc_name}: CTRLKD_PRIVATE_CORPUS not set -- the pcl tier needs the '
                    f'private WS7 LaserJet PCL corpus (see tools/pcl_tolerance.py)')

    recorded = MANIFEST['documents'].get(doc_name)
    if recorded is None:
        pytest.fail(f'{doc_name}: not present in tests/pcl_fidelity_manifest.json -- '
                    f'regenerate with `python3 tools/pcl_tolerance.py --record` and commit '
                    f'the reviewed diff')

    if recorded['verdict'] == 'source-missing':
        pytest.skip(f"{doc_name}: {recorded.get('reason', 'source not available')}")

    live = pt.doc_report(doc_name)

    # A live 'source-missing' the manifest does NOT record as such means an
    # environment gap (most likely $CTRLKD_SAWYER_ARCHIVE unset for a
    # sawyer-group document), not a real drift -- skip, don't fail.
    if live['verdict'] == 'source-missing':
        pytest.skip(f"{doc_name}: {live.get('reason', 'source not available')}")

    if live != recorded:
        live_counts = live['counts_by_reason']
        recorded_counts = recorded['counts_by_reason']
        pytest.fail(
            f'{doc_name}: live divergence set has drifted from the checked-in manifest.\n'
            f'  recorded counts_by_reason: {recorded_counts}\n'
            f'  live counts_by_reason:     {live_counts}\n'
            f'Regenerate with `python3 tools/pcl_tolerance.py --record` and review the diff '
            f'before committing -- this test never regenerates its own answer key.')

    font_sub_counts = {r: c for r, c in live['counts_by_reason'].items()
                       if pt.is_font_substitution_reason(r)}
    if font_sub_counts:
        print(f'{doc_name}: {sum(font_sub_counts.values())} accepted font-substitution '
              f'divergence(s), by reason: {font_sub_counts}')

    real_bugs = [d for d in live['divergences'] if not pt.is_font_substitution_reason(d['reason'])]
    if real_bugs:
        lines = '\n'.join(
            f"  [{d['reason']}] page {d['page']} words={d['words']} "
            f"ws7={d['ws7_pos']} pdf={d['pdf_pos']} font_class={d['font_class']} -- {d['detail']}"
            for d in real_bugs[:15])
        more = len(real_bugs) - 15
        tail = f'\n  ... and {more} more (see tests/pcl_fidelity_manifest.json)' if more > 0 else ''
        pytest.fail(
            f'{doc_name}: {len(real_bugs)} non-font-substitution divergence(s) recorded '
            f'(counts_by_reason={live["counts_by_reason"]}):\n{lines}{tail}')
