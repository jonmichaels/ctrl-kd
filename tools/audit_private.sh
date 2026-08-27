#!/usr/bin/env bash
# Refuse to let anything personal into this PUBLIC repo.
#
# The rule (CLAUDE.md): the development corpus is personal and must never enter
# this repository -- not as a fixture, not as a path, not as a filename in a
# comment or a commit message. Synthetic fixtures only.
#
# This exists because the check kept being hand-rolled at the point of commit
# and kept being WRONG in both directions: a pattern like `WORK/[A-Z]` matched
# the shell variable `$WORK` and blocked a clean commit, while an earlier run
# printed HITS and committed anyway because the gate was chained with `&&` off
# the wrong command. An audit that is retyped each time is not an audit.
#
#   tools/audit_private.sh          # working tree
#   tools/audit_private.sh --log R  # also every commit message in range R
#
# Exit 0 = clean. Non-zero = do not publish.
set -uo pipefail
cd "$(dirname "$0")/.."

# The pattern lives in ONE place, shared with the git hooks.
. "$(dirname "$0")/private_patterns.sh"

fail=0

# Audit what git TRACKS, not what happens to be on disk. The question is "what
# would be published", and that is exactly the tracked set -- scanning the
# filesystem instead flagged untracked virtualenvs full of absolute paths that
# were never going anywhere.
hits=$(git ls-files -z \
       | grep -zZvE -e "$PAT_SELF_EXCLUDE" \
       | xargs -0r grep -nIE "$PAT" 2>/dev/null)
if [ -n "$hits" ]; then
    echo "PRIVATE MATERIAL IN TRACKED FILES:"; echo "$hits"; fail=1
fi

if [ "${1:-}" = "--log" ] && [ -n "${2:-}" ]; then
    msgs=$(git log --format='%h %B' "$2" 2>/dev/null | grep -nIE "$PAT")
    if [ -n "$msgs" ]; then
        echo "PRIVATE MATERIAL IN COMMIT MESSAGES:"; echo "$msgs"; fail=1
    fi
fi

# Positive control: a check that has never returned a hit has not been tested.
# If the scanner cannot find a string we KNOW is present, it is not reading the
# files and its silence means nothing.
if ! git ls-files -z | xargs -0r grep -qIE 'WordStar' 2>/dev/null; then
    echo "AUDIT IS NOT READING FILES -- its 'clean' result is meaningless"; fail=1
fi

[ "$fail" -eq 0 ] && echo "audit clean: no personal corpus material found"
exit "$fail"
