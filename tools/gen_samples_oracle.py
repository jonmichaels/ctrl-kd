#!/usr/bin/env python3
"""Regenerate tests/samples_oracle.json -- the tier-1 public-fixture oracle.

WHY THIS EXISTS
----------------
tests/test_samples.py is the suite's tier-1 (always-run, zero-corpus-needed)
coverage: it converts every bundled samples/*.WS document across every output
format and both modes, and checks the result against a committed SHA-256 per
(doc, mode, format). Hashes, not full text, because five formats times two
modes times four documents is a lot of bytes to carry in the repo for what a
regression test actually needs -- a change in the byte output. A failing hash
tells you WHAT changed (which cell); this generator is how you re-derive the
new expectation once you have confirmed the change is deliberate.

INPUTS ARE FROZEN, same discipline as tools/gen_vectors.py -- this script
NEVER edits samples/*.WS, only recomputes hashes of THIS engine's own output
for those frozen inputs. A diff in samples_oracle.json after a run should be
explainable by a specific commit to the emitters; a diff you can't explain is
a regression this oracle exists to catch, not a stale expectation to paper
over by re-running this script.

USAGE
    python3 tools/gen_samples_oracle.py             # rewrite in place
    python3 tools/gen_samples_oracle.py --check     # report only, exit 1 on diff
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from ctrlkd import core, emit                                     # noqa: E402
from ctrlkd.pdf import emit_pdf                                   # noqa: E402

SAMPLES_DIR = os.path.join(ROOT, 'samples')
ORACLE_PATH = os.path.join(ROOT, 'tests', 'samples_oracle.json')

DOCS = ['LYING.WS', 'OCAPTAIN.WS', 'TWAINLET.WS', 'WARPRAYR.WS']
MODES = ['printed', 'modern']
FORMATS = ['text', 'markdown', 'html', 'rtf', 'pdf']


def render(doc, mode, fmt):
    if fmt == 'pdf':
        out = emit_pdf(doc, mode=mode)          # bytes
    else:
        out = emit.get_emitter(fmt)['fn'](doc, mode=mode)   # str
        out = out.encode('utf-8')
    return hashlib.sha256(out).hexdigest(), len(out)


def build():
    oracle = {}
    for name in DOCS:
        data = open(os.path.join(SAMPLES_DIR, name), 'rb').read()
        doc = core.parse(data)
        oracle[name] = {}
        for mode in MODES:
            oracle[name][mode] = {}
            for fmt in FORMATS:
                digest, size = render(doc, mode, fmt)
                oracle[name][mode][fmt] = {'sha256': digest, 'size': size}
    return oracle


def main():
    check = '--check' in sys.argv
    fresh = build()
    if check:
        if not os.path.exists(ORACLE_PATH):
            print('no existing oracle to check against'); return 1
        current = json.load(open(ORACLE_PATH))
        if current != fresh:
            print('samples_oracle.json is STALE -- rerun without --check')
            return 1
        print('samples_oracle.json matches current engine output')
        return 0
    with open(ORACLE_PATH, 'w') as f:
        json.dump(fresh, f, indent=2, sort_keys=True)
        f.write('\n')
    print(f'wrote {ORACLE_PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
