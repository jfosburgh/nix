#!/usr/bin/env bash
# Manual-only controller. Never run while Blade is uploading or RAID is syncing.
set -euo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname) == pinas ]] || { echo 'Run as root on Pinas.' >&2; exit 1; }
runtime=/run/pinas-restic-retention
blocked="$runtime/blocked"
state="$runtime/restore-state"
units=(restic-rest-server.socket restic-rest-server.service)
recover() {
  rm -f -- "$runtime/password"
  if [[ ! -f $state ]]; then
    [[ ! -e $blocked ]] || { echo 'Blocked endpoint without saved state; manual recovery required.' >&2; return 1; }
    return 0
  fi
  local previous
  previous=$(< "$state")
  [[ $previous == active || $previous == inactive ]] || return 1
  rm -f -- "$blocked"
  systemctl start restic-rest-server.socket || return 1
  if [[ $previous == active ]]; then systemctl start restic-rest-server.service || return 1; fi
  rm -f -- "$state"
  echo 'Restored original endpoint availability.'
}
if [[ ${1:-} == --recover && $# == 1 ]]; then
  # ExecStopPost belongs to this invocation. A separate/manual recovery must
  # never reopen ingress while another invocation is still pruning.
  active=$(systemctl show -p ActiveState --value pinas-restic-critical-retention.service)
  invocation=$(systemctl show -p InvocationID --value pinas-restic-critical-retention.service)
  if [[ $active == active || $active == activating || $active == deactivating ]]; then
    [[ -n ${INVOCATION_ID:-} && $INVOCATION_ID == "$invocation" ]] || {
      echo 'Retention still running; refusing independent endpoint recovery.' >&2; exit 1;
    }
  fi
  recover
  exit
fi
[[ $# == 0 && -n ${INVOCATION_ID:-} ]] || { echo 'Start pinas-restic-critical-retention.service; no direct arguments.' >&2; exit 1; }
[[ ! -e $state && ! -e $blocked ]] || { echo 'Pending endpoint recovery; refusing maintenance.' >&2; exit 1; }
mountpoint -q /data
[[ $(findmnt -nro UUID --mountpoint /data) == 0e549dd2-041c-42d1-b760-d42f1bb1d2e8 ]] || exit 1
device=$(findmnt -nro MAJ:MIN --mountpoint /data)
[[ $device =~ ^[0-9]+:[0-9]+$ ]] || exit 1
md="/sys/dev/block/$device/md"
raid_ready() {
  [[ -d $md && $(< "$md/level") == raid1 && $(< "$md/raid_disks") == 2 && $(< "$md/degraded") == 0 && $(< "$md/sync_action") == idle && $(< "$md/resync_start") == none ]] || {
    echo 'RAID must be healthy, fully synced two-disk RAID1 and idle (no resync/check/recovery).' >&2; return 1;
  }
}
raid_ready
repo=/data/restic/blade/critical
[[ $(readlink -e "$repo") == "$repo" && -f $repo/config && ! -L $repo/config ]] || exit 1
credential="${CREDENTIALS_DIRECTORY:?Missing systemd credential}/repository-password"
[[ -f $credential && ! -L $credential && -s $credential && -r $credential ]] || exit 1
cache=/var/cache/pinas-restic-maintenance
as_restic() { setpriv --reuid=restic --regid=restic --init-groups "$@"; }
# Open the same inode as check jobs, creating it as restic if necessary.
# shellcheck disable=SC2016
as_restic bash -c 'umask 077; : >> "$1"' _ "$cache/.maintenance.lock"
exec 9<>"$cache/.maintenance.lock"
flock -n 9 || { echo 'Another maintenance job is active.' >&2; exit 1; }
no_locks() {
  local group directory
  for group in critical media; do
    directory="/data/restic/blade/$group"
    [[ ! -e $directory ]] && continue
    [[ $(readlink -e "$directory") == "$directory" && -d $directory/locks && ! -L $directory/locks ]] || return 1
    [[ -z $(find "$directory/locks" -mindepth 1 -maxdepth 1 -print -quit) ]] || {
      echo "Repository locks exist in $group; no automatic unlock. Refusing maintenance." >&2; return 1;
    }
  done
}
no_locks
[[ $(systemctl show -p ActiveState --value restic-rest-server.socket) == active ]] || exit 1
previous=$(systemctl show -p ActiveState --value restic-rest-server.service)
[[ $previous == active || $previous == inactive ]] || exit 1
for unit in "${units[@]}"; do
  [[ $(systemctl show -p Conditions --value "$unit") == *"$blocked"* ]] || {
    echo 'Endpoint maintenance guard not deployed; refusing maintenance.' >&2; exit 1;
  }
done
cleanup() {
  local status=$?
  trap - EXIT
  if ! recover; then echo 'Endpoint recovery failed; saved state retained for operator recovery.' >&2; status=1; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '%s\n' "$previous" > "$runtime/.restore-state.new"
mv -f -- "$runtime/.restore-state.new" "$state"
# Negative ConditionPathExists guards both units against reactivation, including
# socket activation. Unlike runtime masks this also works with NixOS /etc units.
: > "$blocked"
systemctl stop "${units[@]}"
for unit in "${units[@]}"; do
  [[ $(systemctl show -p ActiveState --value "$unit") == inactive ]] || exit 1
done
no_locks  # Detect an upload that raced the first check; never delete its locks.
# Repeat the RAID gate immediately before repository operations.
raid_ready
install -o restic -g restic -m 0400 "$credential" "$runtime/password"
install -d -o restic -g restic -m 0700 /var/cache/pinas-restic-retention/worker
unset RESTIC_REPOSITORY RESTIC_REPOSITORY_FILE RESTIC_PASSWORD RESTIC_PASSWORD_FILE RESTIC_PASSWORD_COMMAND
unset RESTIC_REST_USERNAME RESTIC_REST_PASSWORD RESTIC_NO_LOCK
args=(--repo "$repo" --password-file "$runtime/password" --cache-dir /var/cache/pinas-restic-retention/worker)
as_restic restic "${args[@]}" check
as_restic restic "${args[@]}" snapshots --json > "$runtime/snapshots.json"
as_restic restic "${args[@]}" forget --dry-run --json --tag blade-critical-v1 --group-by host \
  --keep-daily 14 --keep-weekly 8 --keep-monthly 12 > "$runtime/policy.json"
"${PINAS_RETENTION_PLANNER:?Missing packaged planner}" "$runtime/snapshots.json" "$runtime/policy.json" > "$runtime/remove-ids"
mapfile -t remove < "$runtime/remove-ids"
if (( ${#remove[@]} == 0 )); then
  echo 'No eligible expired snapshots; skipping forget and prune.'
else
  printf 'Forgetting explicitly selected expired snapshot: %s\n' "${remove[@]}"
  raid_ready
  as_restic restic "${args[@]}" forget "${remove[@]}"
  raid_ready
  as_restic restic "${args[@]}" prune --max-repack-size 10G --max-unused 5%
  as_restic restic "${args[@]}" check
fi
echo 'Critical retention completed; restoring endpoint.'
