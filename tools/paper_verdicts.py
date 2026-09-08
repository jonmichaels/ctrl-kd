#!/usr/bin/env python3
"""paper_verdicts.py -- machine-readable verdicts for the paper-scan LOOK
layer (planning #200, Engine-Test-Finalization-Plan Task 5).

WHY THIS EXISTS
---------------
The 69 catalogued M479fdw paper-scan pages (13 documents; see
ws7-prints/paper-scans/README.md in the private corpus) are compared by a
human looking at the real printed page beside our engine's export --
tools/compare-page.py's job, upstream of this repo. Before this file, that
judgment existed only as prose in findings docs and in Jon's head: nothing
enumerated the 69 pages, nothing said which had been looked at, and a page
nobody had reviewed yet was indistinguishable from a defect nobody had
found. See tools/PAPER-VERDICTS.md for the full schema, CLI reference, and
the `paper` pytest tier this file backs (tests/test_paper_verdicts.py).

THE CATALOG COVERS PUBLIC (Sawyer-group) DOCUMENTS ONLY. Planning #243
(2026-09-08, Jon's ruling): a private-corpus document's own name and page
map do not belong in this public repo at all, even alongside already-
public entries -- CATALOG below is the private corpus's own ws7-prints/
paper-scans/README.md filtered to its PUBLIC_SOURCE_GROUPS-member rows
(see tools/pcl_tolerance.py's own PUBLIC_SOURCE_GROUPS); the private-
corpus documents this catalog used to also list are tracked only in the
private corpus's own README now, resolved by the private engine repo's
own tooling. Only the scan PDFs and rendered pages themselves stay
outside this repo either way, reached only through $CTRLKD_PRIVATE_CORPUS
(see tools/fidelity_gate.py's own doc-resolution docstring for the same
discipline).

THE VERDICTS FILE ITSELF is private data (it's keyed to the private
corpus) and is never written into this repo. It lives at
$CTRLKD_PRIVATE_CORPUS/ws7-prints/paper-scans/verdicts.json; this tool
reads/writes whatever path --file (or that default) names.

PILLOW / pdftoppm are required ONLY for --collage -- see _ensure_pil(),
same deferred-import discipline as tools/pcl_render.py (ctrl-kd's own
zero-runtime-dependency rule must not block --init/--status/--set on a
machine with no Pillow installed).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import date as _date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANSWER_KEY_PATH = os.path.join(ROOT, 'tests', 'answer_key.json')
CORPUS_ENV = 'CTRLKD_PRIVATE_CORPUS'
VERDICTS_PATH_ENV = 'CTRLKD_PAPER_VERDICTS'

SCHEMA_VERSION = 1
VERDICTS = ('pass', 'fail', 'font-substitution', 'unreviewed')

# --------------------------------------------------------------- catalog
# (document, scan-pdf key, first page of this document within that PDF,
# page count) -- verbatim from ws7-prints/paper-scans/README.md's own
# per-batch accounting (2026-08-20 M479fdw scan batches; doc87's 4 junk
# trailer pages from the pre-EOF-padding-stripped run are excluded, same
# as every other consumer of this catalog). scan_file = f'm479-scan-{key}.pdf'.
CATALOG = [
    ('LYING', 'doc87', 1, 4),
    ('-SCREEN', 'doc87', 6, 1),
    ('OCAPTAIN', 'doc87', 8, 1),
    ('LJ6DTP', 'doc87', 10, 8),
    ('-README', 'doc88', 1, 14),
    ('BOXES', 'doc88', 15, 3),
    ('PREVIEW', 'doc88', 18, 1),
    ('SAWYER', 'doc88', 19, 4),
    ('SCRIPT', 'doc88', 23, 11),
    ('WARPRAYR', 'doc89', 1, 3),
]
CATALOG_SOURCE = 'ws7-prints/paper-scans/README.md (M479fdw scan batches, 2026-08-20)'


def catalog_pages():
    """Every catalogued (document, page) as a flat list of dicts, in
    catalog order. This is the ONE definition of "the 69 pages" -- the
    skeleton, --status, and the pytest tier's parametrization all walk
    this same list, so they can never enumerate a different set."""
    pages = []
    for document, pdf_key, first, n in CATALOG:
        scan_file = f'm479-scan-{pdf_key}.pdf'
        for page in range(1, n + 1):
            pages.append({
                'document': document,
                'page': page,
                'scan_file': scan_file,
                'scan_page_index': first + page - 1,
            })
    return pages


def total_pages():
    return sum(n for _, _, _, n in CATALOG)


# --------------------------------------------------------------- git / answer-key provenance
def _git(*args):
    return subprocess.check_output(['git', '-C', ROOT, *args], text=True).strip()


def current_engine_commit():
    """(sha, commit_date_iso) for ctrl-kd's own HEAD, or (None, None) if
    this isn't a git checkout (e.g. an extracted sdist) -- callers degrade
    to recording no provenance rather than crashing."""
    try:
        return _git('rev-parse', 'HEAD'), _git('log', '-1', '--format=%cI', 'HEAD')
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None, None


def current_answer_key_ref():
    """tests/answer_key.json's own generator.git_sha, for citation in a
    verdict entry's answer_key_ref -- best-effort, None if the file is
    missing or malformed."""
    try:
        with open(ANSWER_KEY_PATH, encoding='utf-8') as f:
            return json.load(f).get('generator', {}).get('git_sha')
    except (OSError, json.JSONDecodeError):
        return None


def current_answer_key_date():
    """tests/answer_key.json's generator.date -- the reference the `paper`
    tier compares a verdict's engine_commit_date against for staleness.
    Raises (loud, not silent) if the answer key is missing/malformed --
    that is itself a suite-wide problem, not something this tier should
    paper over."""
    with open(ANSWER_KEY_PATH, encoding='utf-8') as f:
        data = json.load(f)
    d = data.get('generator', {}).get('date')
    if not d:
        raise ValueError(f"{ANSWER_KEY_PATH}: no generator.date field")
    return d


# --------------------------------------------------------------- file I/O
def skeleton():
    """A fresh verdicts document: every catalogued page, verdict=unreviewed,
    no review metadata. This is what --init writes."""
    today = _date.today().isoformat()
    pages = []
    for p in catalog_pages():
        entry = dict(p)
        entry.update({
            'verdict': 'unreviewed',
            'region_notes': [],
            'reviewer': None,
            'date': None,
            'engine_commit': None,
            'engine_commit_date': None,
            'answer_key_ref': None,
        })
        pages.append(entry)
    return {
        'schema_version': SCHEMA_VERSION,
        'generator': {'tool': 'tools/paper_verdicts.py', 'date': today},
        'catalog': {'documents': len(CATALOG), 'pages': len(pages), 'source': CATALOG_SOURCE},
        'pages': pages,
    }


def load(path):
    if not os.path.exists(path):
        raise FileNotFoundError(
            f'{path}: no verdicts file -- run `python3 tools/paper_verdicts.py --init '
            f'--out {path}` first')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if data.get('schema_version') != SCHEMA_VERSION:
        raise ValueError(
            f'{path}: schema_version {data.get("schema_version")!r}, this tool understands '
            f'{SCHEMA_VERSION!r}')
    return data


def save(path, data):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write('\n')


def find_entry(data, document, page):
    for entry in data['pages']:
        if entry['document'] == document and entry['page'] == page:
            return entry
    return None


def default_verdicts_path():
    override = os.environ.get(VERDICTS_PATH_ENV)
    if override:
        return override
    corpus = os.environ.get(CORPUS_ENV)
    if corpus:
        return os.path.join(corpus, 'ws7-prints', 'paper-scans', 'verdicts.json')
    return None


# --------------------------------------------------------------- staleness
def staleness_problem(entry):
    """None if `entry` isn't stale relative to the CURRENT answer key;
    otherwise a human-readable reason. Only meaningful for an entry whose
    verdict would otherwise be accepted (pass / properly-reasoned
    font-substitution) -- a `fail` or `unreviewed` page already fails for
    its own reason regardless of staleness."""
    if not entry.get('engine_commit_date'):
        return (f'no engine_commit_date recorded -- this verdict was never actually tied to '
                f'an engine commit; re-review and re-run --set')
    current = current_answer_key_date()
    if entry['engine_commit_date'] < current:
        return (f"stale review: reviewed against engine commit dated "
                f"{entry['engine_commit_date']}, but tests/answer_key.json was last "
                f"regenerated {current} -- the engine has changed since this page was looked "
                f"at; re-review and re-run --set")
    return None


# --------------------------------------------------------------- commands
def cmd_init(args):
    data = skeleton()
    text = json.dumps(data, indent=2, sort_keys=False) + '\n'
    if args.out:
        save(args.out, data)
        print(f'wrote skeleton ({len(data["pages"])} pages, all unreviewed) to {args.out}')
    else:
        sys.stdout.write(text)


def cmd_status(args):
    path = args.file or default_verdicts_path()
    if not path:
        raise SystemExit(f'--file not given and neither {VERDICTS_PATH_ENV} nor {CORPUS_ENV} '
                          f'is set -- nothing to summarize')
    data = load(path)
    counts = Counter(e['verdict'] for e in data['pages'])
    total = len(data['pages'])
    print(f'{path}')
    print(f'  {total} pages catalogued')
    for v in VERDICTS:
        print(f'  {v:<18} {counts.get(v, 0)}')
    unreviewed = [e for e in data['pages'] if e['verdict'] == 'unreviewed']
    if unreviewed:
        print(f'  unreviewed pages ({len(unreviewed)}):')
        for e in unreviewed:
            print(f"    {e['document']} p{e['page']}")


def cmd_set(args):
    path = args.file or default_verdicts_path()
    if not path:
        raise SystemExit(f'--file not given and neither {VERDICTS_PATH_ENV} nor {CORPUS_ENV} '
                          f'is set -- nothing to edit')
    document, page_str, verdict = args.set
    try:
        page = int(page_str)
    except ValueError:
        raise SystemExit(f'PAGE must be an integer, got {page_str!r}')
    if verdict not in VERDICTS:
        raise SystemExit(f'VERDICT must be one of {VERDICTS}, got {verdict!r}')

    note_given = args.reason or args.region or args.what_differs
    if verdict == 'font-substitution' and not args.reason:
        raise SystemExit('verdict=font-substitution must carry --reason '
                          '(the paper tier enforces this too, at test time)')

    data = load(path)
    entry = find_entry(data, document, page)
    if entry is None:
        raise SystemExit(f'{document} p{page}: not in the catalog (see tools/paper_verdicts.py '
                          f'CATALOG) -- check the document name and page number')

    entry['verdict'] = verdict
    entry['reviewer'] = args.reviewer or os.environ.get('USER') or 'unspecified'
    entry['date'] = args.date or _date.today().isoformat()
    sha, commit_date = current_engine_commit()
    entry['engine_commit'] = sha
    entry['engine_commit_date'] = commit_date
    entry['answer_key_ref'] = current_answer_key_ref()
    if note_given:
        entry['region_notes'] = [{
            'region': args.region or 'page',
            'what_differs': args.what_differs or '',
            'reason': args.reason,
        }]

    save(path, data)
    print(f'{document} p{page}: {verdict} (reviewer={entry["reviewer"]}, date={entry["date"]})')


# --------------------------------------------------------------- collage
Image = ImageDraw = ImageFont = None


def _ensure_pil():
    global Image, ImageDraw, ImageFont
    if Image is not None:
        return
    try:
        from PIL import Image as _Image, ImageDraw as _ImageDraw, ImageFont as _ImageFont
    except ImportError:
        print('Pillow is required for --collage: pip install --user Pillow', file=sys.stderr)
        raise
    Image, ImageDraw, ImageFont = _Image, _ImageDraw, _ImageFont


def _pdftoppm_page(pdf_path, page_index, out_prefix):
    subprocess.run(['pdftoppm', '-png', '-r', '100', '-f', str(page_index), '-l',
                     str(page_index), pdf_path, out_prefix], check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    matches = sorted(glob.glob(out_prefix + '*.png'))
    if not matches:
        raise FileNotFoundError(f'pdftoppm produced nothing for {pdf_path} page {page_index}')
    return matches[0]


def _render_pair(corpus_root, entry, tmpdir):
    """(scan_image, engine_image) PIL Images for one catalogued page, or
    None for a side whose source PDF is missing (a partial corpus, e.g.
    while planning #196 is still adding captures) -- callers skip rather
    than crash on one missing document."""
    scan_pdf = os.path.join(corpus_root, 'ws7-prints', 'paper-scans', entry['scan_file'])
    engine_pdf = os.path.join(corpus_root, 'ws7-prints', 'engine-printed',
                               f"{entry['document']}.pdf")
    scan_img = engine_img = None
    tag = f"{entry['document']}-p{entry['page']}"
    if os.path.exists(scan_pdf):
        scan_img = Image.open(
            _pdftoppm_page(scan_pdf, entry['scan_page_index'], os.path.join(tmpdir, f's-{tag}-'))
        ).convert('RGB')
    if os.path.exists(engine_pdf):
        engine_img = Image.open(
            _pdftoppm_page(engine_pdf, entry['page'], os.path.join(tmpdir, f'e-{tag}-'))
        ).convert('RGB')
    return scan_img, engine_img


def _label_for(entry):
    notes = entry.get('region_notes') or []
    if notes:
        detail = '; '.join(f"{n.get('region', 'page')}: {n.get('what_differs', '')}"
                            for n in notes if n.get('what_differs'))
    else:
        detail = ''
    label = f"{entry['document']} p{entry['page']} -- {entry['verdict']}"
    return f'{label} ({detail})' if detail else label


def _build_collage(pairs, out_path, row_h=260):
    """pairs: list of (entry, scan_img_or_None, engine_img_or_None).
    One row per pair: label text, then scan|engine side by side, scaled to
    row_h. Missing sides are drawn as a gray placeholder so the row still
    lines up and the gap itself is visible information."""
    font = ImageFont.load_default()
    rows = []
    for entry, scan_img, engine_img in pairs:
        def _fit(img):
            if img is None:
                return Image.new('RGB', (int(row_h * 0.77), row_h), (90, 90, 90))
            return img.resize((int(img.width * row_h / img.height), row_h))
        s, e = _fit(scan_img), _fit(engine_img)
        rows.append((entry, s, e))
    width = max(s.width + e.width for _, s, e in rows) + 60
    label_h = 22
    total_h = sum(row_h + label_h + 12 for _ in rows) + 20
    canvas = Image.new('RGB', (width, total_h), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)
    y = 10
    for entry, s, e in rows:
        draw.text((10, y), _label_for(entry), fill='white', font=font)
        y += label_h
        draw.text((10, y), 'PAPER SCAN', fill=(200, 200, 200), font=font)
        draw.text((s.width + 30, y), 'ENGINE EXPORT', fill=(200, 200, 200), font=font)
        y += 14
        canvas.paste(s, (0, y))
        canvas.paste(e, (s.width + 30, y))
        y += row_h + 12
    canvas.save(out_path)


def cmd_collage(args):
    _ensure_pil()
    import tempfile

    path = args.file or default_verdicts_path()
    if not path:
        raise SystemExit(f'--file not given and neither {VERDICTS_PATH_ENV} nor {CORPUS_ENV} '
                          f'is set -- nothing to build collages from')
    corpus_root = args.corpus or os.environ.get(CORPUS_ENV)
    if not corpus_root:
        raise SystemExit(f'--corpus not given and {CORPUS_ENV} is not set -- --collage needs '
                          f'the corpus root to find the scan/engine PDFs')

    data = load(path)
    wanted = set(v.strip() for v in args.verdicts.split(','))
    selected = [e for e in data['pages'] if e['verdict'] in wanted]
    if not selected:
        print(f'no pages with verdict in {sorted(wanted)} -- nothing to collage')
        return

    # Group by cause (verdict) first, per the visual-page-review convention
    # (group by cause, then cap total FILES, merging groups to fit rather
    # than dropping findings).
    groups = []
    for v in VERDICTS:
        members = [e for e in selected if e['verdict'] == v]
        if members:
            groups.append((v, members))

    chunks = []  # (label, [entries])
    for label, members in groups:
        for i in range(0, len(members), args.pairs_per_file):
            chunks.append((label, members[i:i + args.pairs_per_file]))

    if len(chunks) > args.max_files:
        head = chunks[:args.max_files - 1]
        tail_labels = sorted({label for label, _ in chunks[args.max_files - 1:]})
        tail_entries = [e for _, ents in chunks[args.max_files - 1:] for e in ents]
        chunks = head + [(' + '.join(tail_labels), tail_entries)]

    os.makedirs(args.out_dir, exist_ok=True)
    outputs = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, (label, entries) in enumerate(chunks, 1):
            pairs = []
            for entry in entries:
                scan_img, engine_img = _render_pair(corpus_root, entry, tmpdir)
                pairs.append((entry, scan_img, engine_img))
            safe_label = label.replace(' ', '_').replace('+', 'and')
            out_path = os.path.join(args.out_dir, f'paper-collage-{idx:02d}-{safe_label}.png')
            _build_collage(pairs, out_path)
            outputs.append(out_path)

    print(f'{len(outputs)} collage file(s) (<= {args.max_files}), '
          f'{len(selected)} page(s) across {len(groups)} verdict group(s):')
    for o in outputs:
        print(f'  {o}')


# --------------------------------------------------------------- CLI
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--init', action='store_true', help='write a fresh unreviewed skeleton')
    p.add_argument('--status', action='store_true', help='summarize an existing verdicts file')
    p.add_argument('--set', nargs=3, metavar=('DOC', 'PAGE', 'VERDICT'),
                    help='record one page\'s verdict')
    p.add_argument('--collage', action='store_true', help='build review collages')

    p.add_argument('--out', help='--init: path to write the skeleton to (default: stdout)')
    p.add_argument('--file', help=f'verdicts.json path (default: ${VERDICTS_PATH_ENV} or '
                                   f'${CORPUS_ENV}/ws7-prints/paper-scans/verdicts.json)')
    p.add_argument('--corpus', help=f'--collage: corpus root (default: ${CORPUS_ENV})')
    p.add_argument('--out-dir', default='.', help='--collage: directory for the output PNGs')
    p.add_argument('--verdicts', default='fail,font-substitution',
                    help='--collage: comma-separated verdicts to include (default: %(default)s)')
    p.add_argument('--max-files', type=int, default=8,
                    help='--collage: max output files (default: %(default)s, Jon\'s 8-image cap)')
    p.add_argument('--pairs-per-file', type=int, default=6,
                    help='--collage: max page-pairs per file (default: %(default)s)')

    p.add_argument('--reason', help='--set: region-note reason (required for font-substitution)')
    p.add_argument('--region', help='--set: region-note region label (default: "page")')
    p.add_argument('--what-differs', help='--set: region-note description')
    p.add_argument('--reviewer', help='--set: reviewer name (default: $USER)')
    p.add_argument('--date', help='--set: review date YYYY-MM-DD (default: today)')

    args = p.parse_args(argv)

    actions = [a for a in (args.init, args.status, bool(args.set), args.collage) if a]
    if len(actions) != 1:
        p.error('exactly one of --init / --status / --set / --collage is required')

    if args.init:
        cmd_init(args)
    elif args.status:
        cmd_status(args)
    elif args.set:
        cmd_set(args)
    elif args.collage:
        cmd_collage(args)


if __name__ == '__main__':
    main()
