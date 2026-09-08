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

TIER SIZE (planning #180 phase 2, "tests expanded", 2026-09-08):
pt.CAPTURED_DOCS carries 261 documents -- the original 18 (pt.
CAPTURED_DOCS_V1V3, v1/v2/v3 captures, the fail-by-name law above applies
to these UNCHANGED) plus 243 from the ws7-prints/v4/ expansion (pt.
CAPTURED_DOCS_V4 -- 291 real captures minus 48 mail-merge files that print
empty by design). The 243 run in a different, deliberately looser bar
(pt.INVENTORY_MODE_DOCS): every one still executes doc_report() and still
PRINTS every named divergence (see the real_bugs branch below), but does
not pytest.fail on them -- untriaged, pending Jon's per-cause ruling. A
manifest DRIFT (a live run disagreeing with the checked-in answer key)
still fails for every document in both sets, unconditionally: this is
inventory, not a suppression -- see that branch's own comment. 64 of the
243 (the private-corpus-group documents: jon-floppies, fixtures-ws5,
ws7-private) are committed as 'source-missing' placeholders in THIS
PUBLIC manifest and therefore SKIP here even when armed (same as any
other source-missing document) -- their real comparison only ever runs
against a locally-armed $CTRLKD_PRIVATE_CORPUS, never lands in this
repo's own committed file, because a real report for one of them can
embed literal document text in `divergences` (see pcl_tolerance.
_v4_private_placeholder's own docstring).

EXCLUSIONS (planning #224/#226, ruled 2026-09-08): 28 more of the 243 are
committed as 'excluded' placeholders (pt.EXCLUDED_V4) -- 3 PostScript-
targeted documents whose typeface IDs the tier's font table has never
classified (planning #224), 21 duplicate/freeze documents excluded so the
same byte-identical content, or a document WordStar itself refuses to
print, isn't judged twice or gated at all (planning #226), and 2 documents
that turn form feeds off (.xl 00), which WS7 prints as multiple pages
overprinted onto one physical sheet -- unrepresentable as PDF pages, a
standing parked issue (planning #15, no new issue opened for this).
Also SKIP here, same as source-missing, but with verdict 'excluded' and a
distinct reason (see the `recorded['verdict'] == 'excluded'` branch below)
so the two skip causes never get confused in the output. The ACTIVE tier
size -- what actually gets a doc_report() and either fails-by-name or runs
in inventory mode -- is 261 - 28 = 233: the 18 original + 215 of the 243
v4 documents. `pt.CAPTURED_DOCS`/`pt.CAPTURED_DOCS_V4` themselves are
UNCHANGED (still 261/243) -- this test still collects and skips-by-name
the 28 excluded cases every run, rather than shrinking the parametrize
list, so a live `pytest -m pcl -rA` always names every excluded document
and its reason. Full detail (sha256, which half of a duplicate pair was
kept) lives in the private corpus repo's ws7-prints/v4/exclusions.json.

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

    if recorded['verdict'] == 'excluded':
        # planning #224/#226 (ruled 2026-09-08): postscript/freeze/duplicate
        # exclusions -- see pt.EXCLUDED_V4's own docstring. Skips BY NAME
        # with the reason every run (visible in `pytest -rA`), never a
        # silent shrink of this parametrize list.
        pytest.skip(f"{doc_name}: {recorded.get('reason', 'excluded (see pt.EXCLUDED_V4)')}")

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
        msg = (f'{doc_name}: {len(real_bugs)} non-font-substitution divergence(s) recorded '
               f'(counts_by_reason={live["counts_by_reason"]}):\n{lines}{tail}')
        # planning #180 phase 2 ("tests expanded", 2026-09-08), Task 6: the v4
        # expansion (243 documents, pt.CAPTURED_DOCS_V4/pt.INVENTORY_MODE_DOCS)
        # runs in INVENTORY mode -- printed (still names every divergent
        # document, still visible in `pytest -rA`/a failed run's captured
        # stdout) but NON-FAILING, until Jon rules on each cause. This is NOT
        # an expected/known-issue/skip suppression (the drift check above
        # still fails loud for these documents same as any other, and this
        # branch still executes doc_report() and inspects every divergence --
        # nothing here is bypassed or hidden) -- it is a deliberately
        # different BAR for a batch that hasn't been triaged yet, same
        # distinction the original 18's own "clean vs divergent, never
        # silently accepted" law draws for font-substitution vs everything
        # else. The original 18 are UNCHANGED: still fail by name here.
        if doc_name in pt.INVENTORY_MODE_DOCS:
            print(f'{doc_name}: INVENTORY (v4 expansion, non-failing pending Jon\'s ruling on '
                  f'each cause) -- {msg}')
        else:
            pytest.fail(msg)
