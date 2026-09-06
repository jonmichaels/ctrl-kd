"""The `paper` pytest tier: one parametrized test per catalogued paper-scan
page, over the verdicts file tools/paper_verdicts.py reads/writes (planning
#200, Engine-Test-Finalization-Plan Task 5). See tools/PAPER-VERDICTS.md for
the schema and CLI.

Armed by $CTRLKD_PRIVATE_CORPUS -- unarmed, `paper`-marked tests are
DESELECTED by pyproject.toml's addopts, same convention as `sawyer`/`pcl`,
so a bare `pytest` never collects them. The actual verdicts.json path
defaults to $CTRLKD_PRIVATE_CORPUS/ws7-prints/paper-scans/verdicts.json but
can be overridden independently with $CTRLKD_PAPER_VERDICTS -- this is what
lets the tier be exercised against a scratch skeleton (straight out of
`--init`) without a populated private corpus tree; see tools/PAPER-VERDICTS.md
("The `paper` pytest tier" section) for the documented demo command.

WHAT A FAILURE MEANS. A page absent from the file, or verdict `unreviewed`,
fails BY NAME: "go review this page" (a skipped review is not a passing
one -- tests/conftest.py's "a skipped check is not a passing check"
doctrine, applied to review coverage rather than corpus availability).
verdict `fail` fails by name: a real, unexplained divergence. verdict
`font-substitution` fails if it carries no reason (an unreasoned
"acceptable" is not a review). verdict `pass` or a properly-reasoned
`font-substitution` fails anyway if the review is STALE -- its
engine_commit_date predates tests/answer_key.json's current generator.date,
meaning the engine changed since a human last looked at this page.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'tools'))
import paper_verdicts as pv  # noqa: E402

pytestmark = pytest.mark.paper

CATALOG_PAGES = pv.catalog_pages()
PARAMS = [(p['document'], p['page']) for p in CATALOG_PAGES]
IDS = [f"{p['document']}-p{p['page']}" for p in CATALOG_PAGES]


def _armed():
    return bool(os.environ.get(pv.CORPUS_ENV))


@pytest.mark.parametrize('document,page', PARAMS, ids=IDS)
def test_paper_verdict(document, page):
    if not _armed():
        pytest.skip(f'{document} p{page}: {pv.CORPUS_ENV} not set -- the paper tier needs the '
                     f'private paper-scan verdicts file (see tools/PAPER-VERDICTS.md)')

    path = pv.default_verdicts_path()
    try:
        data = pv.load(path)
    except FileNotFoundError as exc:
        pytest.fail(str(exc), pytrace=False)

    entry = pv.find_entry(data, document, page)
    if entry is None:
        pytest.fail(f'{document} p{page}: missing from {path} entirely -- regenerate the '
                     f'skeleton with `python3 tools/paper_verdicts.py --init` and merge', pytrace=False)

    verdict = entry['verdict']

    if verdict == 'unreviewed':
        pytest.fail(f'{document} p{page}: unreviewed -- run the paper-scan look-first review '
                     f'and record a verdict with `tools/paper_verdicts.py --set`', pytrace=False)

    if verdict == 'fail':
        notes = entry.get('region_notes') or []
        detail = '; '.join(
            f"{n.get('region', 'page')}: "
            f"{(n.get('what_differs') + ' ') if n.get('what_differs') else ''}"
            f"({n.get('reason', 'no reason recorded')})"
            for n in notes)
        pytest.fail(f'{document} p{page}: verdict=fail -- {detail or "no region notes recorded"}',
                    pytrace=False)

    if verdict == 'font-substitution':
        reasons = [n.get('reason') for n in (entry.get('region_notes') or []) if n.get('reason')]
        if not reasons:
            pytest.fail(f'{document} p{page}: verdict=font-substitution but no region-note '
                         f'reason recorded -- an unreasoned "acceptable" is not a review',
                        pytrace=False)
    elif verdict != 'pass':
        pytest.fail(f'{document} p{page}: unknown verdict {verdict!r}', pytrace=False)

    problem = pv.staleness_problem(entry)
    if problem:
        pytest.fail(f'{document} p{page}: {problem}', pytrace=False)
