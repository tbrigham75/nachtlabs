#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
load_env
.venv/bin/python scripts/snapshot.py backup
