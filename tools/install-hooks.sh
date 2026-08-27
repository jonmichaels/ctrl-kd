#!/usr/bin/env bash
# Point this clone's git hooks at the tracked set in tools/githooks/.
#
# WHY. The privacy hooks used to live only in .git/hooks -- untracked, and so
# absent from every fresh clone and invisible to review. Their deny list is now
# in tools/private_patterns.sh, which carries no secrets (sensitive literals are
# written as bracketed char classes), so the hooks themselves can be tracked,
# reviewed, and versioned like any other code.
#
# Run once per clone:   tools/install-hooks.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git config core.hooksPath tools/githooks
chmod +x tools/githooks/*
echo "hooks installed: core.hooksPath -> tools/githooks"
echo "active:" && ls tools/githooks
