#!/usr/bin/env bash
# Secret scan, over the working tree and the whole history.
#
# Two modes because they catch different things. `dir` reads the checked-out
# tree, which is where an untracked, generated or ignored-but-inspected secret
# would be. `git` reads every commit, so a secret that was committed and later
# removed is still found; `dir` cannot see it, because by then the file is gone
# and the value is still in the history anyone can clone. Running only one of
# the two leaves a real gap, and the gap is the history case, which is the one
# that keeps being a problem.
#
# Ignored files (.env, credentials, build output) are intentionally not scanned:
# they are not committed, and a credential that is only on this disk is not a
# disclosure. What matters is what a clone would contain.
source "$(dirname -- "$0")/common.sh"
command -v gitleaks >/dev/null || { echo 'Install a pinned gitleaks binary before scanning.' >&2; exit 1; }
printf '== gitleaks: working tree ==\n'
gitleaks dir . --redact --config config/gitleaks.toml
printf '== gitleaks: history ==\n'
gitleaks git . --redact --config config/gitleaks.toml
