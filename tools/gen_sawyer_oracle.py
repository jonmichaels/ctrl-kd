#!/usr/bin/env python3
"""Regenerate tests/sawyer_oracle.json -- the tier-2 full-manifest oracle.

WHY THIS EXISTS
----------------
tests/test_sawyer_corpus.py runs EVERY document listed in
tests/sawyer_manifest.json (the full identified-document set reconciled
against archive release 1.5 -- see tests/SAWYER-CORPUS.md) through a real
conversion: parse the source bytes, emit `text` (mode=modern) and `layout`
JSON, and check each output's SHA-256 against a committed expectation here.
Same pattern as tools/gen_samples_oracle.py / tests/samples_oracle.json:
hashes only, no content, so the file stays compact across ~240 documents x
2 formats instead of carrying every document's full converted text.

A handful of manifest documents are known NOT to parse as WordStar prose at
all -- structured non-prose data (font/cartridge tables, WordPerfect-
conversion keystroke data, HiJaak intermediate files, a search-index blob)
that the vault catalog itself already describes as "non-prose, binary-
shaped content" even though an earlier, separate classification pass
(classify_sawyer.py) corroborated them as ws4/ws5+ by a looser structural
test than this engine's own core.detect()/core.parse() applies. Those are
NOT in this oracle -- see KNOWN_NONCONVERTIBLE in test_sawyer_corpus.py,
which asserts they fail exactly this way instead of silently excluding them.
WORDSTAR.PIX (an Inset image asset, not a WordStar document) is excluded
here for the same reason it was never one of the catalog's 251 documents.

INPUTS ARE FROZEN relative to the archive: this script never modifies the
Sawyer archive, only recomputes hashes of THIS engine's own output for the
documents named in sawyer_manifest.json. A diff after a run should be
explainable by a deliberate emitter change (or a manifest update); an
unexplained diff is a regression this oracle exists to catch.

USAGE
    CTRLKD_SAWYER_ARCHIVE=/path/to/WS python3 tools/gen_sawyer_oracle.py
    CTRLKD_SAWYER_ARCHIVE=/path/to/WS python3 tools/gen_sawyer_oracle.py --check
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from ctrlkd import core, emit                                     # noqa: E402
from sawyer_fixture import (ARCHIVE_ENV, LEGACY_ARCHIVE_ENV, SAWYER_DOCS,   # noqa: E402
                             sawyer_manifest_problem, sawyer_doc_path)

ORACLE_PATH = os.path.join(ROOT, 'tests', 'sawyer_oracle.json')

# Kept out of the oracle -- see this file's docstring and
# test_sawyer_corpus.py's KNOWN_NONCONVERTIBLE / NON_DOCUMENT_ASSETS.
NON_DOCUMENT_ASSETS = {'WORDSTAR.PIX'}
KNOWN_NONCONVERTIBLE = {
    'CVWP/WP_WP_US.QRS', 'CVWP/WP{WPC}.QKL',
    'DEFAULT/APP/03670464.CRT/05200120.CRT',
    'DEFAULT/APP/03670464.CRT/08120072.CRT',
    'DEFAULT/APP/03670464.CRT/14240124.CRT',
    'DEFAULT/APP/03670464.CRT/15240104.CRT',
    'HIJAAK/ISI0.TMP', 'HIJAAK/ISI2.TMP',
    'MANUALS/WordStar Manuals Index/index1.idx',
    'WFW/UNC0819.DAT',
}


def _render(name):
    path = sawyer_doc_path(name)
    doc = core.parse(open(path, 'rb').read())
    text_out = emit.emit_text(doc, mode='modern').encode('utf-8')
    layout_out = emit.get_emitter('layout')['fn'](doc, mode='modern').encode('utf-8')
    return text_out, layout_out


def build():
    oracle = {}
    for name, entry in sorted(SAWYER_DOCS.items()):
        rel = entry['path']
        if name in NON_DOCUMENT_ASSETS or rel in KNOWN_NONCONVERTIBLE:
            continue
        text_out, layout_out = _render(name)
        oracle[name] = {
            'text': {'sha256': hashlib.sha256(text_out).hexdigest(), 'size': len(text_out)},
            'layout': {'sha256': hashlib.sha256(layout_out).hexdigest(), 'size': len(layout_out)},
        }
    return oracle


def main():
    problem = sawyer_manifest_problem()
    if problem:
        print('archive not armed/correct: %s' % problem)
        print('set %s (or legacy %s) to the Sawyer WS7 archive root.' % (ARCHIVE_ENV, LEGACY_ARCHIVE_ENV))
        return 1

    check = '--check' in sys.argv
    fresh = build()
    if check:
        if not os.path.exists(ORACLE_PATH):
            print('no existing oracle to check against'); return 1
        current = json.load(open(ORACLE_PATH))
        if current != fresh:
            print('sawyer_oracle.json is STALE -- rerun without --check')
            return 1
        print('sawyer_oracle.json matches current engine output (%d docs)' % len(fresh))
        return 0
    with open(ORACLE_PATH, 'w') as f:
        json.dump(fresh, f, indent=2, sort_keys=True)
        f.write('\n')
    print('wrote %s (%d docs)' % (ORACLE_PATH, len(fresh)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
