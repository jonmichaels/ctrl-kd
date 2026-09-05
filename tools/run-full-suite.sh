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

SAWYER="${CTRLKD_SAWYER_ARCHIVE:-}"

sawyer_status="not armed"
[ -n "$SAWYER" ] && sawyer_status="armed"

private_status="not armed"
[ -n "${CTRLKD_PRIVATE_CORPUS:-}" ] && private_status="armed"

# Clear addopts' default tier filter (-m "not sawyer") so tier 2 runs
# alongside tier 1 when armed, in one invocation, in one report. An unarmed
# tier's own fixtures still fail loud with a clear message rather than
# silently vanishing, if something manages to select one of its tests
# anyway.
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
echo "public: ${public_count} ran / sawyer: ${sawyer_status} / private (CTRLKD_PRIVATE_CORPUS): ${private_status}, richer suite tested separately"

exit "$status"
