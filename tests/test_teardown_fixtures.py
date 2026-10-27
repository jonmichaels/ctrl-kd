"""The `teardowns` tier: this engine against real WordStar's own runs.

Arm with `CTRLKD_TEARDOWNS` = the WordStar teardowns checkout. Unarmed, the
`teardowns` marker is DESELECTED (pyproject.toml's addopts), the same shape
as `sawyer`; armed, every converter fixture's reading part is one test, read
in place from the checkout (nothing is copied here), and a missing or
wrong-schema manifest FAILS rather than skips.

What is compared, and how, is `tools/teardown_fixtures.py`'s docstring. A
part passes when its mismatches are exactly the ones
`tests/teardown_fixtures_known.json` names for it, kind by kind and count
by count, each with its reason. A new mismatch, or a known one that has gone
away, fails: the second means the known list is stale and must shrink in
the same change.
"""
import json
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import teardown_fixtures as tf  # noqa: E402

pytestmark = pytest.mark.teardowns

_KNOWN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'teardown_fixtures_known.json')


def _known():
    with open(_KNOWN_PATH) as f:
        return json.load(f)['parts']


def pytest_generate_tests(metafunc):
    if 'teardown_part' not in metafunc.fixturenames:
        return
    if tf.manifest_problem():
        metafunc.parametrize('teardown_part', [None], ids=['unarmed'])
        return
    cases = tf.parts()
    metafunc.parametrize('teardown_part', cases, ids=[c[0] for c in cases])


def test_install_is_the_engine_factory_default():
    problem = tf.manifest_problem()
    if problem:
        pytest.fail(problem, pytrace=False)
    for s in tf.SETS:
        ip = tf.install_problem(s, tf.load_manifest(s))
        if ip:
            pytest.fail(ip, pytrace=False)


def test_fixture_part(teardown_part):
    problem = tf.manifest_problem()
    if problem:
        pytest.fail(problem, pytrace=False)
    case, set_name, fixture, _i, part = teardown_part
    found = tf.check_part(set_name, fixture, part)
    got = Counter(m['kind'] for m in found)
    known = _known().get(case, {}).get('kinds', {})
    if dict(got) != known:
        lines = [f'{case}: {fixture["claim"]}',
                 f'  cite: {", ".join(fixture.get("cite", []))}',
                 f'  mismatches by kind: {dict(got)}; known: {known}']
        lines += ['    ' + json.dumps(m, ensure_ascii=False) for m in found[:12]]
        pytest.fail('\n'.join(lines), pytrace=False)


def test_known_list_names_only_real_parts():
    problem = tf.manifest_problem()
    if problem:
        pytest.fail(problem, pytrace=False)
    ids = {c[0] for c in tf.parts()}
    stale = sorted(set(_known()) - ids)
    assert not stale, f'teardown_fixtures_known.json names parts that do not exist: {stale}'
    unreasoned = sorted(k for k, v in _known().items() if not v.get('reason'))
    assert not unreasoned, f'known mismatches without a reason: {unreasoned}'
