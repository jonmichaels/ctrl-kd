#!/usr/bin/env python3
"""Catch fixtures that encode an INVENTED file format.

WHY THIS EXISTS
---------------
The Swift port's vectors use synthetic inputs, built byte by byte. That is the
right call -- real documents are personal and never enter a public repo, and a
hand-built input can isolate one behaviour exactly.

But synthetic CONTENT and invented STRUCTURE are different things, and the
distinction was lost. `job-005`'s footnote fixture carried 17 zero bytes where a
real WordStar note has a 5-byte header and nested sub-blocks. It was not a
malformed note; it was not shaped like a note at all. The expected output was
then whatever ctrl-kd 1.1.3's looser parser happened to scavenge out of it, and
that got frozen as ground truth.

The damage is subtle: such a fixture cannot fail usefully. When the parser was
later rewritten against 86 real WS7 documents and correctly found no note there,
the fixture read as a REGRESSION -- and the temptation was to "fix" working code
to satisfy a fabrication. A fixture that tests an imaginary format is worse than
no fixture, because it argues back.

WHAT THIS CHECKS
----------------
Structure only, never content. Text can be as synthetic as you like.

  * every 0x1D symmetric block's declared length lands inside the data
  * a block whose command is a NOTE kind (3-6) actually yields note text

The second is the real test, and it is a round-trip: build a note, parse it, get
the text back. A block that parses to empty text is not a note, whatever its
command byte says.

USAGE
    tools/audit_fixtures.py <vectors-dir> [...]

Directories are searched recursively for *.json. Exit 0 = clean.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from ctrlkd import core                                          # noqa: E402

NOTE_KINDS = {3, 4, 5, 6}

# A byte ramp (00 01 02 ... ff) is a DELIBERATE binary blob for detection tests.
# Any 0x1D in it is incidental and its "block" will of course overrun -- that is
# the point of the fixture, so it is not a finding.
def _is_byte_ramp(data):
    return len(data) >= 32 and all(b == i % 256 for i, b in enumerate(data))


def _blocks(data):
    """Walk 0x1D symmetric blocks the same way `_symmetric_blocks` does."""
    i, out = 0, []
    while i < len(data):
        if data[i] == 0x1D and i + 3 <= len(data):
            jump = int.from_bytes(data[i + 1:i + 3], 'little')
            end = i + 3 + jump
            blk = data[i + 1:end]
            out.append({
                'off': i,
                'cmd': blk[2] if len(blk) > 2 else -1,
                'overruns': end > len(data),
            })
            i = end
        else:
            i += 1
    return out


def _inputs(obj, trail=''):
    """Every input_hex anywhere in a vector file, with a readable path."""
    if isinstance(obj, dict):
        if 'input_hex' in obj:
            name = obj.get('name', '')
            yield (trail + ('/' + name if name else ''), obj['input_hex'])
        for k, v in obj.items():
            yield from _inputs(v, trail + '/' + k)
    elif isinstance(obj, list):
        for n, v in enumerate(obj):
            yield from _inputs(v, trail + '[%d]' % n)


def audit(path):
    findings = []
    with open(path) as fh:
        doc = json.load(fh)
    for case, hexstr in _inputs(doc):
        try:
            data = bytes.fromhex(hexstr)
        except ValueError:
            findings.append((case, 'input_hex is not valid hex'))
            continue
        if _is_byte_ramp(data):
            continue
        blocks = _blocks(data)
        if not blocks:
            continue
        for b in blocks:
            if b['overruns']:
                findings.append((case, 'block at %d declares a length past end of data'
                                 % b['off']))
        if any(b['cmd'] in NOTE_KINDS for b in blocks):
            notes = core.parse_ws(data).notes
            if not notes:
                findings.append((case, 'note-kind block present but no note parsed'))
            else:
                empty = sum(1 for n in notes if not n.text.strip())
                if empty:
                    findings.append((case, '%d note(s) parse to EMPTY text -- the block '
                                     'is not shaped like a real WordStar note' % empty))
    return findings


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    files = []
    for root in argv:
        if os.path.isfile(root):
            files.append(root)
            continue
        for dirpath, _dirs, names in os.walk(root):
            files += [os.path.join(dirpath, n) for n in sorted(names)
                      if n.endswith('.json')]
    if not files:
        print('no vector files found', file=sys.stderr)
        return 2

    total = 0
    for path in sorted(files):
        findings = audit(path)
        if findings:
            total += len(findings)
            print(os.path.basename(path))
            for case, why in findings:
                print('  %-44s %s' % (case[:44], why))
    if total:
        print()
        print('%d fabricated-format fixture(s). These cannot fail usefully: they '
              'assert what a\nlenient parser once scavenged from bytes no WordStar '
              'ever wrote. Rebuild them\nwith real framing (synthetic TEXT is fine; '
              'invented STRUCTURE is not).' % total)
        return 1
    print('fixture audit clean: every 0x1D block is well-formed and every note parses')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
