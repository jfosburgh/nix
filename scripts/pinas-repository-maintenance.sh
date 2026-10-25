#!/usr/bin/env bash
# Non-destructive, local-only Pinas operations. No arbitrary Restic arguments.
set -euo pipefail
umask 077
[[ $(hostname) == pinas ]] || { echo 'Run on Pinas.' >&2; exit 1; }
[[ $# == 2 ]] || { echo 'Usage: pinas-repository-maintenance.sh {critical|media} {check|check-data|retention-preview}' >&2; exit 1; }
repository=$1
operation=$2
case "$repository" in critical|media) ;; *) echo 'Unknown repository.' >&2; exit 1 ;; esac
case "$operation" in
  check|check-data) ;;
  retention-preview) [[ $repository == critical ]] || { echo 'Media retention policy is not selected.' >&2; exit 1; } ;;
  *) echo 'Only check, check-data, and retention-preview are allowed; no deletion operations.' >&2; exit 1 ;;
esac
mountpoint -q /data
[[ $(findmnt -nro UUID --mountpoint /data) == 0e549dd2-041c-42d1-b760-d42f1bb1d2e8 ]] || {
  echo 'Wrong backup filesystem; refusing repository access.' >&2; exit 1;
}
repo="/data/restic/blade/$repository"
[[ $(readlink -e -- "$repo") == "$repo" && -f $repo/config && ! -L $repo/config ]] || {
  echo 'Expected existing local repository, not a symlink or fallback directory.' >&2; exit 1;
}
credential="${CREDENTIALS_DIRECTORY:?Run through the maintenance systemd unit}/repository-password"
[[ -f $credential && ! -L $credential && -s $credential && -r $credential ]] || {
  echo 'Expected private systemd repository-password credential.' >&2; exit 1;
}
# systemd may expose service-owned 0400, or root-owned 0440 with a service
# ACL (root:root on systemd 261) / service group. The enclosing credential
# directory is isolated by PID 1; do not mistake the ACL mask for public access.
case $(stat -c '%u:%g:%a' "$credential") in
  "$EUID:"*":400"|"0:0:440"|"0:$(id -g):440") ;;
  *) echo 'Expected private systemd repository-password credential.' >&2; exit 1 ;;
esac
cache=/var/cache/pinas-restic-maintenance
exec 9>"$cache/.maintenance.lock"
flock -n 9 || { echo 'Another Pinas maintenance operation is active.' >&2; exit 1; }
# Never inherit Blade REST access or alternate password/repository sources.
unset RESTIC_REPOSITORY RESTIC_REPOSITORY_FILE RESTIC_PASSWORD RESTIC_PASSWORD_FILE RESTIC_PASSWORD_COMMAND
unset RESTIC_REST_USERNAME RESTIC_REST_PASSWORD RESTIC_NO_LOCK
args=(--repo "$repo" --password-file "$credential" --cache-dir "$cache")
echo "Starting local $repository $operation UTC: $(date -u --iso-8601=seconds)"
case "$operation" in
  check) restic "${args[@]}" check ;;
  check-data) restic "${args[@]}" check --read-data ;;
  retention-preview)
    # One host group intentionally spans the old and new staging source paths.
    # Untagged smoke/manual snapshots are outside this policy, not deleted.
    restic "${args[@]}" forget --dry-run --tag blade-critical-v1 --group-by host \
      --keep-daily 14 --keep-weekly 8 --keep-monthly 12
    ;;
esac
echo "Completed local $repository $operation UTC: $(date -u --iso-8601=seconds)"
