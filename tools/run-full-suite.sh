#!/usr/bin/env bash
# Run the FULL suite with every corpus gate satisfied.
#
# WHY THIS EXISTS. `pytest tests/` alone runs ONLY tier 1 (K1, 2026-08-26):
# tier 2 (`sawyer`) is DESELECTED by pyproject.toml's addopts whenever its
# arming variable is unset, so a bare run never silently drops a corpus
# check -- there is nothing to drop, because those checks were never
# collected in the first place. This script is how you run BOTH tiers
# together, with the gate armed, exactly what a stranger running
# `pytest -m sawyer` against the public Sawyer archive would see.
#
# (Jon's own private corpus is tested more fully from a separate, private
# repo against this package from outside it -- no test files or markers for
# that live here. A handful of tests in this repo also opt into a private
# per-maintainer fixture set via CTRLKD_PRIVATE_CORPUS; unset, they skip
# silently rather than failing loud, since that data never ships and a
# stranger's clone is never expected to have it -- unlike tier 2, below.)
#
# A reduced number was quoted through an entire release round on 2026-08-24
# before anyone set the variable -- the reason the tier-2 gate fails loud
# rather than skipping once armed.
#
#   CTRLKD_SAWYER_ARCHIVE  tier 2 (public): Robert J. Sawyer's WS7 archive
#                          root (see tests/SAWYER-CORPUS.md) -- the
#                          committed manifest documents are checked BY NAME,
#                          never a directory sweep.
#
#   CTRLKD_PRIVATE_CORPUS  `pcl` tier (2026-09-05, planning #197): the
#                          coordinate-level fidelity gate against real WS7
#                          LaserJet PCL captures (tests/test_pcl_fidelity.py,
#                          tools/pcl_tolerance.py). Unlike the rest of the
#                          CTRLKD_PRIVATE_CORPUS-gated tests, this tier is
#                          DESELECTED (not silently skipped) when unarmed --
#                          same convention as `sawyer` -- and, once armed,
#                          FAILS BY NAME on any recorded divergence that
#                          isn't accepted font-substitution drift. That is
#                          not a bug in the script: a document with a real,
#                          unfixed placement bug is SUPPOSED to show red
#                          here until the bug is fixed or the manifest's
#                          classification of it is corrected with evidence
#                          (see tests/pcl_fidelity_manifest.json and
#                          `python3 tools/pcl_tolerance.py --record`).
#
#                          Also selects `paper` (2026-09-06, planning #200):
#                          the 69 M479fdw paper-scan verdicts
#                          (tests/test_paper_verdicts.py, tools/paper_verdicts.py).
#                          PARKED BY RULING 2026-09-14: every page now skips
#                          with the register citation instead of failing on an
#                          unreviewed/failing/unreasoned/stale verdict. It is
#                          reported as "parked by ruling", never as a red and
#                          never as a bare skip (see tools/PAPER-VERDICTS.md
#                          and paper_verdicts.PARKED_BY_RULING).
#
# USAGE.
#
#   CTRLKD_SAWYER_ARCHIVE=/path/to/sawyer/WS  tools/run-full-suite.sh
#
# This path is not stored here. CTRLKD_SAWYER_ARCHIVE is public -- Sawyer's
# own download -- but still an external path nothing in this repo should
# hardcode.
#
# IF YOUR CORPUS LIVES ON A READ-ONLY ARCHIVE, and it very likely does,
# point this variable at your OWN COPY, never at the archive itself: a
# test that writes beside its fixture would be writing into material you
# cannot replace.
set -euo pipefail
cd "$(dirname "$0")/.."

# The privacy audit is part of the suite, not a thing to remember. It was
# committed, wired to nothing, and never run -- and was sitting on two real
# leaks the whole time.
echo "== privacy audit =="
tools/audit_private.sh
echo

# Compile every shipped module with warnings as errors. tests/
# test_no_syntax_warnings.py does the same thing in-process and is the real
# gate; this runs the literal command, so the recipe written down in that
# file's own docstring is itself guarded and cannot rot.
#
# WHY IT IS NOT ENOUGH TO IMPORT THE PACKAGE. A SyntaxWarning fires when a
# module is COMPILED, not imported: once __pycache__ holds a current .pyc,
# every later import is silent. A developer's checkout compiled each module
# once, long ago; only a user meets a cold cache -- a fresh pip or brew
# install, byte-compiled at install time. ctrl-kd 4.9.0 therefore greeted
# every new Homebrew user with an invalid-escape warning naming a path inside
# our own package, ahead of `ctrl-kd --version`'s own output, while every
# suite here ran clean. `-f` forces recompilation regardless of the cache,
# which is the whole point.
echo "== compile with warnings as errors =="
python3 -W error::SyntaxWarning -m compileall -q -f src/ctrlkd
echo "all modules compile silently"
echo

SAWYER="${CTRLKD_SAWYER_ARCHIVE:-}"

sawyer_status="not armed"
[ -n "$SAWYER" ] && sawyer_status="armed"

private_status="not armed"
[ -n "${CTRLKD_PRIVATE_CORPUS:-}" ] && private_status="armed"

pcl_status="not armed"
[ -n "${CTRLKD_PRIVATE_CORPUS:-}" ] && pcl_status="armed"

# PARKED BY RULING 2026-09-14 (tools/paper_verdicts.py's PARKED_BY_RULING).
# The tier is still collected when armed -- every page skips with the
# register citation, which is what "parked by ruling" has to look like in a
# run: named, cited, and impossible to mistake for a tier nobody ran. The
# status word therefore says PARKED whether or not the corpus is present,
# because arming it no longer gates anything.
paper_status="parked by ruling (RULINGS-LEDGER 2026-09-14), corpus not armed"
[ -n "${CTRLKD_PRIVATE_CORPUS:-}" ] && paper_status="parked by ruling (RULINGS-LEDGER 2026-09-14)"

# Clear addopts' default tier filter (-m "not sawyer and not pcl and not
# paper") so tier 2, the pcl tier, and the paper tier all run alongside
# tier 1 when armed, in one invocation, in one report. An unarmed tier's
# own fixtures still fail loud (sawyer) or skip by name (pcl, paper) with a
# clear message rather than silently vanishing, if something manages to
# select one of its tests anyway.
#
# set +e around the run: pytest's own exit code must reach the arming
# status line and this script's own exit, not kill the script here under
# -e (which would print no status line at all on a red run -- exactly the
# kind of silent gap this whole script exists to prevent).
set +e
python3 -m pytest tests/ -q -rs -o addopts="" "$@"
status=$?
set -e

public_line=$(python3 -m pytest tests/ --collect-only -q -m "not sawyer" 2>/dev/null | tail -1)
public_count=$(echo "$public_line" | grep -oE '^[0-9]+')

# Full-denominator discipline (per Jon's rule): this line names every tier's
# state every run, not just the ones that happen to be armed today.
echo
echo "public: ${public_count} ran / sawyer: ${sawyer_status} / private (CTRLKD_PRIVATE_CORPUS): ${private_status}, richer suite tested separately / pcl fidelity tier: ${pcl_status} / paper verdicts tier: ${paper_status}"
if [ "$pcl_status" = "armed" ]; then
    echo "  (pcl per-document verdicts are in the -rs output above; regenerate the answer key with"
    echo "   \`python3 tools/pcl_tolerance.py --record\` -- a FAILED pcl case names a real, unfixed"
    echo "   coordinate divergence, not a broken test)"
fi
echo "  (paper: PARKED BY RULING -- the per-page skips in the -rs output above each carry"
echo "   the register citation; they are an intentional exclusion, not unrun checks. The"
echo "   scans, the catalog and \`python3 tools/paper_verdicts.py --status/--set/--collage\`"
echo "   are all untouched -- un-parking is deleting PARKED_BY_RULING in that file.)"

exit "$status"
