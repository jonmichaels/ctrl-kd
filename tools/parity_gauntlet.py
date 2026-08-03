#!/usr/bin/env python3
"""Printed-mode parity gauntlet: our render of a WordStar DOCUMENT versus
WordStar's OWN printout of the same document.

WHY THIS EXISTS
---------------
Printed mode's whole job is to reproduce what WordStar put on paper. For a
corpus of period documents one may have both halves of that: the `.WS` source AND
the print-to-disk output made from it at the time. The printstream is not our
opinion of correct — it is the 1992 printer's own answer, and it is the only
ground truth available for questions the manuals do not settle (how `.ls`
interacts with page capacity; whether `.mt` blanks double under double spacing;
where `.cp` measures from).

This is the same instrument that made ctrl-kd land right the first time, and
whose absence is why the Mac app needed three sessions to find one bug.

WHAT IT COMPARES, AND WHAT IT DELIBERATELY DOES NOT
---------------------------------------------------
Compared:
  * the LINE STREAM  - the sequence of rendered lines, blanks included,
                       ignoring page boundaries
  * PAGINATION       - by two routes. (a) form feeds, when present. (b) for a
                       DOUBLE-SPACED printstream, boundaries recovered from
                       WordStar's own filler suppression — see derived_breaks().
                       Route (b) is what makes a real-world corpus usable at all:
                       ONLY when the printstream actually carries form feeds
                       (0x0C). Measured 2026-08-03: not one printstream in the
                       corpus tested does — WordStar's print-to-disk wrote a
                       continuous stream and let the printer form-feed. So for
                       that corpus the pagination question is NOT ANSWERABLE
                       here, and the tool says so instead of inventing a
                       verdict. Answering it needs a DOSBox head-to-head.

Deliberately NOT compared:
  * the LEFT OFFSET. `.po` was consumed by the print driver and never entered
    the printstream, so a printstream cannot tell us what it was. Our WS4 render
    uses the file's own `.po` (documented default 8 columns = 0.8in) and is the
    more faithful of the two. Comparing x would report a difference that is not
    an error.

Separating stream from pagination is the point: it says WHICH thing is wrong.
A stream match with a pagination mismatch is a capacity bug; a stream mismatch
is a parsing or line-breaking bug.

USAGE
-----
    python3 tools/parity_gauntlet.py <pairs-dir> [-v]

`<pairs-dir>` holds two subdirectories:
    doc/  the WordStar documents      (.WS / extensionless)
    out/  the matching printstreams, SAME FILENAME

REAL DOCUMENTS NEVER ENTER THIS REPO. The path is an argument for exactly that
reason; keep the corpus outside the checkout.
"""
from __future__ import annotations

import sys
import os
import difflib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ctrlkd import core                     # noqa: E402
from ctrlkd.pdf import _doc_to_pagelines    # noqa: E402


def render(data: bytes, printstream: bool):
    """(line stream, page-break line indices, page count) for one file.

    For a PRINTSTREAM the machine top margin is physically present as blank
    lines at the head of every page; for a DOCUMENT it is not (`.mt` is a dot
    command the emitter turns into paper margin). Comparing the two raw would
    diff a difference of representation, not of content — so the machine margin
    is removed from pages 2+ of a printstream. Page 1 is left alone: that is
    where an author's deliberate chapter-drop lives, and it must stay visible to
    the comparison.
    """
    doc = (core.parse_printstream if printstream else core.parse_ws)(data)
    pages = _doc_to_pagelines(doc, True)
    if printstream and len(pages) > 1:
        machine = min(_leading(pg) for pg in pages[1:])
        pages = [pages[0]] + [pg[machine:] for pg in pages[1:]]
    stream, breaks, n = [], [], 0
    for page in pages:
        for line in page:
            stream.append(''.join(t for t, _ in line).rstrip())
        n += len(page)
        breaks.append(n)
    return stream, breaks[:-1], len(pages)


def derived_breaks(stream):
    """Page boundaries recovered from a double-spaced printstream.

    The printstreams tested carry no form feed, so at first glance
    it records no page boundaries. It does, in a side effect: under `.ls > 1`
    the printed pattern is strictly text/blank/text/blank, and WordStar "always
    suppresses soft blank lines at the top of a page when they are created by a
    line spacing greater than one" (WS7 Reference, Page Layout). So every place
    the alternation BREAKS is a page top. WordStar's own suppression is the
    record of where its pages fell.

    ⚠️ CORRECTED 2026-08-03 — THIS DOES NOT WORK, and is retained only so the
    mistake is not made again. Checked against the RAW bytes of a real 1992
    print stream: it holds 0 form feeds, one leading blank run, 225 single
    blanks, and just 2 text-text adjacencies in 458 lines. It records NO page
    boundaries. The six "boundaries" this function appeared to recover were
    manufactured by _doc_to_pagelines' own trailing-blank stripper, which drops
    the last blank of each page and so butts one page's last text line against
    the next page's first. The uniform "pitch 33" seen across several documents
    was simply our own 66-line capacity divided by two.

    A print stream whose margins do not travel in-band cannot tell you how it
    was paginated. Verify against raw bytes before believing any structure a
    processed stream appears to show.

    Returns None when the stream is not double-spaced, else the indices where
    two text lines sit adjacent.
    """
    text = [bool(l.strip()) for l in stream]
    if len(text) < 20:
        return None
    # double-spaced == most text lines are followed by a blank
    followed = sum(1 for i in range(len(text) - 1) if text[i] and not text[i + 1])
    if not text.count(True) or followed / text.count(True) < 0.8:
        return None
    return [i for i in range(1, len(text)) if text[i] and text[i - 1]]


def text_lines_before(stream, idx):
    """How many text-bearing lines precede `idx` — the unit that survives blank
    suppression, so ours and WordStar's are comparable even though our streams
    contain a different number of blanks."""
    return sum(1 for l in stream[:idx] if l.strip())


def _leading(page):
    n = 0
    while n < len(page) and not ''.join(t for t, _ in page[n]).strip():
        n += 1
    return n


def trim_lead(stream):
    """Drop leading blanks and say how many there were.

    A printstream carries WordStar's machine top margin as real blank lines; a
    document does not (`.mt` is a dot command the emitter applies as paper
    margin). So the counts legitimately differ and are reported, not diffed.
    """
    n = 0
    while n < len(stream) and not stream[n].strip():
        n += 1
    return stream[n:], n


def compare(name, doc_bytes, out_bytes, verbose=False):
    d_stream, d_breaks, d_pages = render(doc_bytes, printstream=False)
    o_stream, o_breaks, o_pages = render(out_bytes, printstream=True)
    # A printstream with no form feed carries no page boundaries of its own —
    # the pages we give it are OUR arithmetic, so comparing them to our other
    # arithmetic proves nothing. Only compare pagination when WordStar actually
    # recorded where the pages fell.
    paginable = b'\x0c' in out_bytes

    d_body, d_lead = trim_lead(d_stream)
    o_body, o_lead = trim_lead(o_stream)

    same = d_body == o_body
    ratio = difflib.SequenceMatcher(None, d_body, o_body).ratio()

    status = 'MATCH' if same else f'{ratio * 100:5.1f}%'
    print(f'{name:12} stream {status:>7}  '
          f'lines {len(d_body):4}/{len(o_body):<4}  '
          f'pages {d_pages:2}/{o_pages:<2}  '
          f'lead {d_lead}/{o_lead}')

    if not same:
        # first divergence, which is what you actually act on
        for i, (a, b) in enumerate(zip(d_body, o_body)):
            if a != b:
                print(f'{"":12}   first diff at body line {i}:')
                print(f'{"":12}     ours {a[:66]!r}')
                print(f'{"":12}     ws   {b[:66]!r}')
                break
        else:
            print(f'{"":12}   identical for {min(len(d_body), len(o_body))} '
                  f'lines, then one stream ends')
        if verbose:
            for ln in list(difflib.unified_diff(
                    o_body, d_body, 'wordstar', 'ours', lineterm='', n=1))[:40]:
                print(f'{"":12}   {ln}')

    # Page boundaries recovered from the printstream's own suppression pattern.
    # Compared in TEXT LINES, not raw indices: the two streams hold a different
    # number of blanks, and text-lines-so-far is the quantity both agree on.
    ours_ok = True
    # DISABLED 2026-08-03. derived_breaks() does not measure WordStar -- see its
    # docstring. Documenting that was not enough: left running it kept printing a
    # confident "PAGES DIFFER" verdict whose numbers were our own capacity
    # reflected back (33 when we paginated at 66, 55 when we paginated at 55).
    # An instrument that reports a wrong answer with authority is worse than one
    # that abstains, so it abstains. Re-enable only against a stream whose page
    # boundaries are verified present in its RAW bytes.
    derived = None
    if derived:
        ws_at = [text_lines_before(o_body, i) for i in derived]
        our_at = [text_lines_before(d_body, i) for i in d_breaks]
        gaps = [ws_at[i + 1] - ws_at[i] for i in range(len(ws_at) - 1)]
        pitch = f'{gaps[0]}' if gaps and len(set(gaps)) == 1 else f'{gaps}'
        if ws_at == our_at:
            print(f'{"":12}   pages MATCH — {len(ws_at) + 1} pages, '
                  f'WordStar pitch {pitch} text lines')
        else:
            ours_ok = False
            print(f'{"":12}   PAGES DIFFER (derived from suppressed filler):')
            print(f'{"":12}     wordstar breaks after text lines {ws_at}')
            print(f'{"":12}     ours              after text lines {our_at}')
            print(f'{"":12}     wordstar pitch {pitch}; we make '
                  f'{len(our_at) + 1} pages, WordStar made {len(ws_at) + 1}')
    elif not paginable:
        if verbose:
            print(f'{"":12}   pagination not comparable (no form feeds, and the '
                  f'printstream is not double-spaced)')
    elif paginable and d_pages != o_pages:
        print(f'{"":12}   PAGINATION differs (form feeds): we make {d_pages}, '
              f'WordStar made {o_pages}')

    return same and ours_ok and (not paginable or d_pages == o_pages)


def main(argv):
    verbose = '-v' in argv
    argv = [a for a in argv if a != '-v']
    if len(argv) != 2:
        print(__doc__.strip().split('USAGE')[-1].strip(), file=sys.stderr)
        return 2
    root = argv[1]
    docs, outs = os.path.join(root, 'doc'), os.path.join(root, 'out')
    if not (os.path.isdir(docs) and os.path.isdir(outs)):
        print(f'expected {docs}/ and {outs}/', file=sys.stderr)
        return 2

    # A pair is ground truth only if the document was not edited AFTER it was
    # printed. Record known post-print edits here rather than silently tolerating
    # a diff — the gauntlet must never learn to shrug.
    known = {}
    kpath = os.path.join(root, 'KNOWN-DIFFS.txt')
    if os.path.isfile(kpath):
        for row in open(kpath):
            row = row.split('#', 1)[0].strip()
            if ':' in row:
                k, v = row.split(':', 1)
                known[k.strip()] = v.strip()

    names = sorted(n for n in os.listdir(docs)
                   if os.path.isfile(os.path.join(outs, n)))
    if not names:
        print('no matched pairs found — same filename must exist in both dirs',
              file=sys.stderr)
        return 2

    print(f'PRINTED-MODE PARITY GAUNTLET — {len(names)} matched pairs')
    print(f'{"":12} {"stream":>14}  {"lines ours/ws":>13}  '
          f'{"pages":>8}  lead')
    print(f'{"":12} (page column is raw count; boundaries are COMPARED via '
          f'form feeds or recovered filler)\n')
    passed = 0
    for n in names:
        ok = compare(n,
                     open(os.path.join(docs, n), 'rb').read(),
                     open(os.path.join(outs, n), 'rb').read(),
                     verbose)
        if not ok and n in known:
            print(f'{"":12}   KNOWN, not a defect: {known[n]}')
            ok = True
        passed += ok
    print(f'\n{passed}/{len(names)} pairs match on BOTH stream and pagination.')
    return 0 if passed == len(names) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
