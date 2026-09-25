#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
command -v gitleaks >/dev/null || { echo 'Install a pinned gitleaks binary before scanning.' >&2; exit 1; }
gitleaks dir . --redact --config config/gitleaks.toml
