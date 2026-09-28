#!/usr/bin/env bash
# Source after common.sh. Caller supplies die(). Never infer stopped from an error.
require_unit() {
  local loaded
  loaded="$(systemctl show "$1" --property=LoadState --value)" || die "cannot inspect $1"
  [[ "$loaded" == loaded ]] || die "$1 is not installed"
}

require_stopped() {
  local unit state pid
  for unit in "$@"; do
    require_unit "$unit"
    state="$(systemctl show "$unit" --property=ActiveState --value)" || die "cannot inspect $unit"
    pid="$(systemctl show "$unit" --property=MainPID --value)" || die "cannot inspect $unit PID"
    [[ "$state" == inactive || "$state" == failed ]] || die "$unit is not stopped ($state)"
    [[ "$pid" == 0 ]] || die "$unit still has a process"
  done
}

lock_maintenance() {
  command -v flock >/dev/null || die "flock is required"
  install -d -m 0700 /var/lib/nachtlabs-maintenance
  exec 8>/var/lib/nachtlabs-maintenance/maintenance.lock
  flock -n 8 || die "another maintenance operation is running"
}

lock_stopped_executor() {
  local jobs
  require_stopped nachtlabs-executor
  # Same lock as the broker and reconcile-executor.py. Keep it until exit so a
  # manually started broker cannot claim a job during maintenance.
  [[ -d /var/lib/nachtlabs-executor ]] || die "executor state directory is missing"
  exec 9>/var/lib/nachtlabs-executor/broker.lock
  flock -n 9 || die "the executor broker or reconciliation is still running"
  jobs="$(systemctl list-units --all --plain --no-legend --no-pager 'nachtlabs-job-*.service')" || die "cannot inspect execution units"
  [[ -z "$jobs" ]] || die "execution units remain; stop and reconcile them first"
  [[ ! -e /var/lib/nachtlabs-executor/active.json ]] || die "executor recovery is required (active.json remains)"
}
