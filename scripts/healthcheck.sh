#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
load_env
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health/live
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health/ready
curl --fail --silent --show-error --output /dev/null http://127.0.0.1:3000/login
systemctl is-active nachtlabs-api nachtlabs-worker nachtlabs-web
printf '\nUse the authenticated overview to confirm the worker heartbeat.\n'
