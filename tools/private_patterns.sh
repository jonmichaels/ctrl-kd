#!/usr/bin/env bash
# THE deny pattern. One definition, sourced by tools/audit_private.sh and by
# the pre-commit / pre-push hooks, so the three can never drift apart.
#
# WHY THIS FILE EXISTS. Private material reached this public repo repeatedly,
# and each fix added one more literal to one more copy of a list. That guard
# could only ever catch the leak that had already happened: hooks installed on
# 2026-08-20 passed a private repo path straight through on 2026-08-23, because
# the path was a NEW SHAPE, not a listed word.
#
# So the rule is now about shape, not vocabulary. Category 2 is the one that
# does the work; category 1 is history, kept because it costs nothing.
#
# Sensitive literals are written with bracketed single-char classes -- they
# match identically while keeping this public file from carrying the strings
# it exists to reject. Files that legitimately contain the patterns (this one
# and the audit) are excluded by the scanners, not by weakening the pattern.

# 1. Named private things. Historical; grows only after a leak.
PAT_NAMES='(/mnt/md[0]|hum[u]ng|jmw[o]rk|old-files-pr[o]ject|/CEL[E]B/|/W[O]RK/[A-Z]|fl[o]ppy-[a-z])'

# 2. The SHAPE of every leak so far: a filesystem location on somebody's
#    machine. A public repo never needs one -- corpus roots come from the
#    environment. Anchored to a following name char so "~3px" is not a hit.
PAT_SHAPE='(~/[A-Za-z]|/home/[A-Za-z]|/Users/[A-Za-z]|/mnt/[A-Za-z]|/root/[A-Za-z])'

# 3. Machine names, including in commit author/committer fields -- a hostname
#    in metadata is exactly as public as one in a file (learned 2026-08-22,
#    after `worker@<host>` sat in 319 commits unnoticed).
PAT_HOSTS='(hum[u]ng\.us|chon[k]y|borg[c]ube|noi[s]y|hea[r]th|grogn[a]rd)'

PAT="($PAT_NAMES|$PAT_SHAPE|$PAT_HOSTS)"

# Files that carry the patterns by definition. Scanners must skip these rather
# than the pattern being softened to accommodate them.
PAT_SELF_EXCLUDE='^tools/(private_patterns|audit_private)\.sh$'
