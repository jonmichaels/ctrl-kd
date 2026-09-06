"""Locating and validating the Sawyer WS7 archive (tier 2 -- opt-in, but
PUBLICLY AVAILABLE: Robert J. Sawyer's own WordStar 7 archive,
https://www.sfwriter.com/ws7.htm). See tests/SAWYER-CORPUS.md for the full
account of what this tier is and why.

RULED 2026-08-26 (Jon, mid-K1-build): unlike Jon's private corpus (tested
separately, outside this repo), this repo carries an
EXPLICIT, COMMITTED list of the documents this tier tests -- never a
directory sweep of the whole archive (it holds ~180 files; the suite has no
opinion on most of them). Revealing these filenames/paths is explicitly
fine, because the archive itself is public. The list lives in
sawyer_manifest.json alongside a SHA-256 per document, computed against
archive release 1.5 (the same session verified the zip's own sha256 against
the coordinator's report before trusting it -- see the commit that added
this file).

Two failure MODES, and neither is a skip (2026-08-24 rule, scoped here to
"once armed"):

  1. The archive isn't there at all, or doesn't look like release 1.5 (the
     version-marker check below) -- sawyer_manifest_problem().
  2. The archive is there and looks right, but one LISTED document is
     missing or its content has drifted from the committed hash --
     sawyer_doc_problem(name).

One name, one shape, everywhere: CTRLKD_SAWYER_ARCHIVE (D3, 2026-09-03) --
the archive's own top-level directory. Its presence arms the whole
`sawyer` marker (see pyproject.toml's addopts). An earlier, now-retired
alias name is no longer honoured.
"""
import hashlib
import json
import os

ARCHIVE_ENV = 'CTRLKD_SAWYER_ARCHIVE'

_MANIFEST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sawyer_manifest.json')
with open(_MANIFEST_PATH) as _f:
    _MANIFEST = json.load(_f)

ARCHIVE_RELEASE = _MANIFEST['archive_release']
ARCHIVE_SOURCE_URL = _MANIFEST['source_url']
ARCHIVE_ZIP_SHA256 = _MANIFEST['zip_sha256']
VERSION_MARKER = _MANIFEST['version_marker']       # {'path': ..., 'sha256': ...}
SAWYER_DOCS = _MANIFEST['docs']                    # name -> {'path', 'sha256', 'size'}

# Single source of truth for the two "can't fully test this one" carve-outs
# out of the 252 manifest entries (see tests/test_sawyer_corpus.py's module
# docstring for the full reasoning). Used by both tools/answer_key.py (which
# entries get the full format x mode grid vs. a recorded failure reason) and
# tests/test_sawyer_corpus.py (which entries get which test). Previously
# duplicated by hand across tools/gen_sawyer_oracle.py and this test file --
# consolidated here 2026-09 (Task 3, one shared answer key) so there is one
# place to update, not two to keep in sync.
NON_DOCUMENT_ASSETS = {'WORDSTAR.PIX'}
KNOWN_NONCONVERTIBLE = {
    'CVWP/WP_WP_US.QRS': "not a convertible file (detected: binary -- 82% text but no structure)",
    'CVWP/WP{WPC}.QKL': "not a convertible file (detected: binary -- 59% text but no structure)",
    'DEFAULT/APP/03670464.CRT/05200120.CRT': "not a convertible file (detected: binary -- 46% text but no structure)",
    'DEFAULT/APP/03670464.CRT/08120072.CRT': "not a convertible file (detected: binary -- 45% text but no structure)",
    'DEFAULT/APP/03670464.CRT/14240124.CRT': "not a convertible file (detected: binary -- 42% text but no structure)",
    'DEFAULT/APP/03670464.CRT/15240104.CRT': "not a convertible file (detected: binary -- 44% text but no structure)",
    'HIJAAK/ISI0.TMP': "not a convertible file (detected: binary -- 77% text but no structure)",
    'HIJAAK/ISI2.TMP': "not a convertible file (detected: binary -- 78% text but no structure)",
    'MANUALS/WordStar Manuals Index/index1.idx': "not a convertible file (detected: binary -- 40% text but no structure)",
    'WFW/UNC0819.DAT': "not a convertible file (detected: binary -- 69% text but no structure)",
}


def sawyer_classify():
    """(convertible_names, known_nonconvertible_names, non_document_asset_names),
    each sorted, partitioning ALL_NAMES = sorted(SAWYER_DOCS) into the three
    disjoint groups tools/answer_key.py and test_sawyer_corpus.py both need."""
    all_names = sorted(SAWYER_DOCS)
    non_document = sorted(n for n in all_names if n in NON_DOCUMENT_ASSETS)
    nonconvertible = sorted(n for n in all_names if SAWYER_DOCS[n]['path'] in KNOWN_NONCONVERTIBLE)
    convertible = sorted(n for n in all_names
                          if n not in NON_DOCUMENT_ASSETS
                          and SAWYER_DOCS[n]['path'] not in KNOWN_NONCONVERTIBLE)
    return convertible, nonconvertible, non_document


def sawyer_archive():
    """The archive root directory, or None if the tier is not armed."""
    return os.environ.get(ARCHIVE_ENV) or None


def sawyer_armed():
    return sawyer_archive() is not None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sawyer_manifest_problem():
    """The one-time sanity check: is the archive root even there, and does
    it look like release 1.5 (the version this manifest's hashes were
    computed against)? None if fine. Checked once per test via the
    require_sawyer_doc fixture (conftest.py) before any per-doc check --
    a stale/wrong archive should report ONE clear reason, not N confusing
    per-file mismatches."""
    root = sawyer_archive()
    if not root:
        return '%s is not set -- the sawyer tier is not armed.' % (ARCHIVE_ENV,)
    if not os.path.isdir(root):
        return '%s=%s is not a directory.' % (ARCHIVE_ENV, root)
    marker_path = os.path.join(root, VERSION_MARKER['path'])
    if not os.path.isfile(marker_path):
        return ('version marker %s not found under %s -- this does not look '
                 'like the Sawyer WS7 archive at all.' % (VERSION_MARKER['path'], root))
    got = _sha256(marker_path)
    if got != VERSION_MARKER['sha256']:
        return (
            'version marker %s does not match archive release %s '
            '(expected sha256 %s, got %s). This manifest was generated '
            'against release %s (%s) -- point %s at that release, or '
            'regenerate sawyer_manifest.json against the archive you have.'
            % (VERSION_MARKER['path'], ARCHIVE_RELEASE, VERSION_MARKER['sha256'],
               got, ARCHIVE_RELEASE, ARCHIVE_SOURCE_URL, ARCHIVE_ENV))
    return None


def sawyer_doc_path(name):
    """Absolute path to a manifest-listed document. Never raises at import
    time: returns a sentinel path when unarmed so a stray direct read fails
    obviously rather than resolving somewhere unexpected."""
    root = sawyer_archive()
    rel = SAWYER_DOCS[name]['path']
    if not root:
        return os.path.join('<%s-unset>' % ARCHIVE_ENV, rel)
    return os.path.join(root, rel)


def sawyer_doc_problem(name):
    """Why a manifest-listed doc can't be used, or None if it's fine. Call
    ONLY after sawyer_manifest_problem() has returned None -- see
    require_sawyer_doc in conftest.py, which always does both in order."""
    entry = SAWYER_DOCS[name]
    path = sawyer_doc_path(name)
    if not os.path.isfile(path):
        return 'manifest doc %r (%s) not found under the archive.' % (name, entry['path'])
    got = _sha256(path)
    if got != entry['sha256']:
        return (
            'manifest doc %r (%s) does not match its committed sha256 '
            '(expected %s, got %s) -- archive content has drifted from '
            'release %s.' % (name, entry['path'], entry['sha256'], got, ARCHIVE_RELEASE))
    return None
