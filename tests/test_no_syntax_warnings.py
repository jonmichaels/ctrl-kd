"""Every module must compile silently -- no invalid escape sequences.

WHAT SHIPPED. ctrl-kd 4.9.0, installed from Homebrew onto Python 3.12,
printed this before its own output::

    $ ctrl-kd --version
    .../pdf.py:10002: SyntaxWarning: invalid escape sequence '\\m'
    ctrl-kd 4.9.0

`_modern_geometry`'s docstring cites RTF's `\\margr` control word inside a
PLAIN (non-raw) triple-quoted string, so Python read `\\m` as an escape
sequence, found no such escape, and warned. Nothing was broken -- the
docstring still said what it meant -- but the first thing a new user saw was
an interpreter warning naming a file path inside our own package, which reads
like a crash.

WHY NO TEST CAUGHT IT, AND WHY THIS ONE IS SHAPED THE WAY IT IS. The warning
fires when a module is COMPILED, not when it is imported: once `__pycache__`
holds a current `.pyc`, every later import is silent. A developer's checkout
compiles each module once, months ago, and never warns again; the full suite
imports everything and sees nothing. The only machine that reliably meets a
cold cache is a user's -- a fresh `pip install` or `brew install`, byte-
compiled at install time or on first run. So the check cannot be "import the
package and listen"; it has to compile the SOURCE, unconditionally, every
time.

This is the test form of the command the fix was verified with::

    python3 -W error::SyntaxWarning -m compileall -q -f src/ctrlkd

compiled in-process instead of shelled out for two reasons: it writes no
bytecode into the source tree, and `compileall` stops at the first bad file,
while a reviewer wants EVERY offending line at once. `tools/run-full-suite.sh`
runs the command itself as well, so the documented recipe is guarded too.

WARNINGS ARE ERRORS FOR EVERY CATEGORY, not just `SyntaxWarning`. Compilation
is also where a `DeprecationWarning` about invalid escapes arrives on some
versions (it was a `DeprecationWarning` before 3.12 and becomes a
`SyntaxError` in a future release), and where `assert (a, b)`-shaped mistakes
are reported. Nothing in this package intends to emit anything at compile
time, so the correct budget is zero.

Tier 1: no corpus, no environment variables, no network.
"""
import pathlib
import warnings

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / 'src' / 'ctrlkd'


def _modules():
    """Every module in the shipped package, found by walking rather than
    listed, so a file added tomorrow is covered the day it lands."""
    return sorted(SRC.rglob('*.py'))


def test_the_package_has_modules_to_check():
    """A guard on the guard: a path typo here would make every check below
    pass over an empty list and report success forever."""
    names = {p.name for p in _modules()}
    assert len(names) >= 5, f'only found {names} under {SRC}'
    assert {'core.py', 'pdf.py', 'emit.py'} <= names


def test_every_module_compiles_without_a_single_warning():
    """The whole package at once, so a failure names every offending line
    rather than only the first file that trips.

    A hit is almost always one of three fixes, in this order of preference:
    make the docstring raw (`r\"\"\"...\"\"\"`) when it quotes RTF/PCL control
    words, double the backslash when the string is really about one
    character, or reword. Raw is preferred for prose because it keeps the
    text a reader sees identical to the text in the file.
    """
    failures = []
    for path in _modules():
        source = path.read_text(encoding='utf-8')
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            try:
                compile(source, str(path), 'exec')
            except SyntaxWarning as exc:
                # Raised as an error, so the line number rides on the
                # exception rather than on a warning record.
                failures.append(f'{path.name}:{exc.lineno}: {exc.msg}')
            except SyntaxError as exc:
                failures.append(f'{path.name}:{exc.lineno}: {exc.msg}')
            except Warning as exc:                    # any other category
                failures.append(f'{path.name}: {type(exc).__name__}: {exc}')
    assert not failures, (
        'modules must compile silently -- a user installing from PyPI or '
        'Homebrew compiles them on a COLD cache and sees every one of these '
        'printed before our own output:\n  ' + '\n  '.join(failures))


@pytest.mark.parametrize('path', _modules(), ids=lambda p: p.name)
def test_each_module_compiles_without_a_single_warning(path):
    """The same check per module, so the suite reports WHICH file regressed
    in its own test id instead of one opaque aggregate failure."""
    source = path.read_text(encoding='utf-8')
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        compile(source, str(path), 'exec')
