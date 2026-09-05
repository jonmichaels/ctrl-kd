"""Locating the maintainer's private corpus (tier 3) -- one var, one shape,
per D3 (2026-09-03): CTRLKD_PRIVATE_CORPUS names the corpus clone's own
root; every consumer reaches into a KNOWN subdirectory under that root
rather than being handed a pre-shaped path of its own. See tests/conftest.py
for the skip-silently convention this tier uses (opposite of tier 2's
fail-loud convention) -- this data never ships and a stranger's clone is
never expected to have it.

The handful of tests in this repo that opt into real fixtures read a flat
directory of individually-named WordStar files (NOTES.TST, -ATTRIB.TST,
etc.) under the corpus root's own `fixtures-ws5/` subdirectory -- an
earlier version of these tests pointed a now-retired, dedicated env var
directly at that subdirectory instead of composing it from the corpus
root, which was exactly the "one name, several shapes" overload D3 exists
to remove.
"""
import os

CORPUS_ENV = 'CTRLKD_PRIVATE_CORPUS'


def private_fixtures_root():
    """Absolute path to the private fixtures-ws5/ subdirectory, or None if
    CTRLKD_PRIVATE_CORPUS is unset. Callers skip silently on None -- see
    module docstring."""
    root = os.environ.get(CORPUS_ENV)
    return os.path.join(root, 'fixtures-ws5') if root else None
