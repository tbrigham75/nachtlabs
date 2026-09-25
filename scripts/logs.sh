#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
journalctl -u nachtlabs-api -u nachtlabs-worker -u nachtlabs-web --since '30 minutes ago' --no-pager
