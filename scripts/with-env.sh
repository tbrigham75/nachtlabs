#!/usr/bin/env bash
# Source the generated environment, then run whatever was asked for.
#
# Compose's env_file cannot be used for the generated configuration: it is
# resolved on the host when the file is parsed, which is before the init
# container has written anything. The file only exists inside the config volume,
# so the load happens here instead.
set -euo pipefail
set -a
# NACHTLABS_ENV_FILE is an absolute path inside the config volume. Accepting a
# bare name too costs nothing and avoids the doubled-path failure below.
if [[ "${NACHTLABS_ENV_FILE}" = /* ]]; then
  env_file="${NACHTLABS_ENV_FILE}"
else
  env_file="/etc/nachtlabs/${NACHTLABS_ENV_FILE}"
fi
# shellcheck disable=SC1090
source "$env_file"
set +a
exec "$@"
