#!/usr/bin/env bash
# Manual critical backup: coherent local staging first, network upload afterward.
set -euo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname) == blade ]] || { echo 'Run as root on Blade.' >&2; exit 1; }
[[ $# == 0 ]] || { echo 'This job takes no arguments.' >&2; exit 1; }
mountpoint -q /data || { echo '/data is not mounted.' >&2; exit 1; }
install -d -m 0700 /data/backup-staging
exec 8>/data/backup-staging/.critical.lock
flock -n 8 || { echo 'Another critical backup is running.' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
prepare_state=${BLADE_PREPARE_STATE:-$script_dir/prepare-application-state.sh}
prepare_coherent=${BLADE_PREPARE_COHERENT:-$script_dir/prepare-coherent-applications.sh}
restic_client=${BLADE_RESTIC:-$script_dir/pinas-restic.sh}
upload=${BLADE_UPLOAD_CRITICAL:-$script_dir/upload-critical.sh}
finish=${BLADE_FINISH_STAGING:-$script_dir/finish-critical-staging.sh}
cleanup() {
  status=$?
  trap - EXIT
  if ! bash "$prepare_state" --recover; then status=1; fi
  if ! bash "$prepare_coherent" --recover; then status=1; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Check credentials/connectivity before interrupting any application.
bash "$restic_client" critical snapshots >/dev/null
bash "$prepare_state"
# Resolve the actual immutable generation, NOT its symlink (Restic won't follow it).
state=$(readlink -e /data/backup-staging/application-state/current)
bash "$prepare_coherent"
coherent=$(readlink -e /data/backup-staging/coherent-applications/current)
[[ -d $state && -f $state/SHA256SUMS && -d $coherent && -f $coherent/SHA256SUMS ]] || exit 1
# Both paths are complete generations. All application writers have been resumed.
bash "$upload" "$state" "$coherent"
# Only a successful off-host snapshot permits local staging retention/receipt.
bash "$finish" "$state" "$coherent"
printf 'Critical backup completed UTC: %s\n' "$(date -u --iso-8601=seconds)"
