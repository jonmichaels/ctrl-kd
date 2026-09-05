"""Suite-wide gates.

A skipped check is not a passing check: a corpus-dependent test that used to
carry `pytest.mark.skipif(not os.path.exists(...))` evaporated from the
totals on any machine without the samples while the suite still reported
success. The `require_sawyer_doc` fixture below FAILS instead, once its
tier is armed.

It is a fixture rather than a module-level raise because a raise at import is a
COLLECTION error, and pytest abandons the entire run on those -- one unarmed
gate would take every unrelated test down with it.

Tier 3's richer suite (Jon's private corpus, Sawyer install-tree byte
parity, cohort census floors) is relocated entirely out of this public repo
(K1 2026-08-26 removal) and tested separately, against this package from
outside it. A handful of tests here also opt into a private per-maintainer
fixture set via `CTRLKD_PRIVATE_CORPUS` (one shape, defined outside this
repo); unset, they skip silently -- deliberately opposite of tier 2's
fail-loud convention, because this data never ships and a stranger's clone
is never expected to have it. Tier 2 (`sawyer` marker) is DESELECTED
entirely (via pyproject.toml's addopts) when `CTRLKD_SAWYER_ARCHIVE` is
unset -- unarmed, its tests never run at all, so there is nothing to fail
or skip.
"""
import pytest

from sawyer_fixture import sawyer_manifest_problem, sawyer_doc_problem, sawyer_doc_path


@pytest.fixture
def require_sawyer_doc():
    """Tier 2 (`sawyer` marker). Returns a callable: `path = require_sawyer_doc('RJS.WS')`.

    Ruled 2026-08-26: tier 2 tests an explicit, committed doc list (see
    tests/SAWYER-CORPUS.md), never a directory sweep. Two checks, in order,
    BOTH fail loud rather than skip -- the marker's own deselection (see
    pyproject.toml addopts) is what makes "unarmed" not reach this fixture
    at all:

      1. sawyer_manifest_problem() -- the archive root exists and its
         version marker matches the release this manifest was generated
         against. Checked once per call so a wrong/stale archive reports
         ONE clear reason.
      2. sawyer_doc_problem(name) -- the specific named document exists and
         its content still matches the committed sha256.
    """
    problem = sawyer_manifest_problem()
    if problem:
        pytest.fail(problem, pytrace=False)

    def _require(name):
        doc_problem = sawyer_doc_problem(name)
        if doc_problem:
            pytest.fail(doc_problem, pytrace=False)
        return sawyer_doc_path(name)

    return _require
