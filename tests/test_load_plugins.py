"""load_plugins() must work on both the 3.9 and 3.10+ importlib.metadata
shapes of entry_points() (planning #203).

Python 3.10+ entry_points() returns a SelectableGroups object with a
.select(group=...) method. Python 3.9's entry_points() returns a plain
dict keyed by group name and has no .select. pyproject's requires-python
is >=3.9, so ctrlkd.emit.load_plugins() must branch on which shape it got
rather than assume the 3.10+ API unconditionally (CI run 34011057595
failed 19 tests on 3.9 before this fix).

These tests monkeypatch importlib.metadata.entry_points itself (not
ctrlkd.emit.entry_points -- load_plugins does a local `from
importlib.metadata import entry_points` at call time, so it always picks
up whatever is bound on the module at call time) with tiny stand-ins for
each shape, run load_plugins() against an isolated registry, and check
the discovered emitter landed correctly either way.
"""
import importlib.metadata

from ctrlkd import emit


class _FakeEntryPoint:
    def __init__(self, name, fn):
        self.name = name
        self._fn = fn

    def load(self):
        return self._fn


def _fake_emitter(doc, mode='printed', **options):
    return 'fake output'


def _isolate_registry(monkeypatch):
    """Give load_plugins a scratch registry so the test can't leak a fake
    emitter into the real one (or collide with an already-loaded one)."""
    fake_registry = {}
    monkeypatch.setattr(emit, '_REGISTRY', fake_registry)
    return fake_registry


def test_load_plugins_py310_selectable_shape(monkeypatch):
    """3.10+: entry_points() returns an object with .select(group=...)."""
    registry = _isolate_registry(monkeypatch)
    fake_ep = _FakeEntryPoint('fakefmt', _fake_emitter)

    class _FakeSelectable:
        def select(self, group=None):
            assert group == 'ctrlkd.emitters'
            return [fake_ep]

    monkeypatch.setattr(importlib.metadata, 'entry_points', lambda: _FakeSelectable())

    emit.load_plugins()

    assert 'fakefmt' in registry
    assert registry['fakefmt']['fn'] is _fake_emitter
    assert registry['fakefmt']['ext'] == '.fakefmt'


def test_load_plugins_py39_dict_shape(monkeypatch):
    """3.9: entry_points() returns a plain dict keyed by group name, with
    no .select and no group= support at all."""
    registry = _isolate_registry(monkeypatch)
    fake_ep = _FakeEntryPoint('fakefmt', _fake_emitter)

    fake_dict = {'ctrlkd.emitters': [fake_ep]}
    monkeypatch.setattr(importlib.metadata, 'entry_points', lambda: fake_dict)

    emit.load_plugins()

    assert 'fakefmt' in registry
    assert registry['fakefmt']['fn'] is _fake_emitter
    assert registry['fakefmt']['ext'] == '.fakefmt'


def test_load_plugins_py39_dict_shape_missing_group(monkeypatch):
    """3.9 shape with no 'ctrlkd.emitters' key at all (no plugins installed)
    must not raise -- .get(group, []) is the whole point of the guard."""
    registry = _isolate_registry(monkeypatch)
    monkeypatch.setattr(importlib.metadata, 'entry_points', lambda: {})

    emit.load_plugins()

    assert registry == {}


def test_load_plugins_does_not_overwrite_existing_registration(monkeypatch):
    """A name already in the registry (e.g. a built-in emitter) wins over
    a same-named plugin -- unchanged behaviour, exercised on the 3.10+
    shape since that's the CI-default interpreter here."""
    registry = _isolate_registry(monkeypatch)
    sentinel = object()
    registry['fakefmt'] = {'fn': sentinel, 'ext': '.fakefmt'}
    fake_ep = _FakeEntryPoint('fakefmt', _fake_emitter)

    class _FakeSelectable:
        def select(self, group=None):
            return [fake_ep]

    monkeypatch.setattr(importlib.metadata, 'entry_points', lambda: _FakeSelectable())

    emit.load_plugins()

    assert registry['fakefmt']['fn'] is sentinel
