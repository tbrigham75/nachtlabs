#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
load_env
: "${NACHTLABS_RESTORE_ARCHIVE:?Set encrypted archive path}"
: "${NACHTLABS_RESTORE_IDENTITY:?Set age identity path}"
: "${NACHTLABS_RESTORE_DATABASE:?Set an empty alternate database ending _restore}"
: "${NACHTLABS_RESTORE_KEY_OUTPUT:?Set a new master-key output path}"
: "${NACHTLABS_RESTORE_PREVIOUS_KEYS_OUTPUT:?Set a new previous-keys JSON output path}"
.venv/bin/python scripts/snapshot.py restore --archive "$NACHTLABS_RESTORE_ARCHIVE" --identity "$NACHTLABS_RESTORE_IDENTITY" --target-database "$NACHTLABS_RESTORE_DATABASE" --key-output "$NACHTLABS_RESTORE_KEY_OUTPUT" --previous-keys-output "$NACHTLABS_RESTORE_PREVIOUS_KEYS_OUTPUT"
