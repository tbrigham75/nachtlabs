#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
[[ $EUID -eq 0 ]] || { echo 'Run installation as a Linux administrator.' >&2; exit 1; }
[[ "$(realpath "$NACHTLABS_ROOT")" == /opt/nachtlabs ]] || { echo 'Install the source at /opt/nachtlabs before service installation.' >&2; exit 1; }
getent group nachtlabs-secrets >/dev/null || groupadd --system nachtlabs-secrets
for service in api worker web; do
 id "nachtlabs-$service" >/dev/null 2>&1 || useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin "nachtlabs-$service"
 install -d -o "nachtlabs-$service" -g "nachtlabs-$service" -m 0750 "/var/lib/nachtlabs/$service"
 install -m 0644 "systemd/nachtlabs-$service.service" "/etc/systemd/system/nachtlabs-$service.service"
done
usermod -aG nachtlabs-secrets nachtlabs-api
usermod -aG nachtlabs-secrets nachtlabs-worker
install -d -o root -g nachtlabs-secrets -m 0750 /etc/nachtlabs /etc/nachtlabs/credentials
chown -R root:root /opt/nachtlabs
chmod -R go-w /opt/nachtlabs
install -d -o root -g root -m 0700 /var/lib/nachtlabs-executor
install -m 0644 systemd/nachtlabs-executor.service /etc/systemd/system/nachtlabs-executor.service
systemctl daemon-reload
printf '%s\n' 'Units installed, not started. Configure credentials, database grants, and TLS before starting services.'
