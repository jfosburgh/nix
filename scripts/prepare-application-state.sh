#!/usr/bin/env bash
# Briefly quiesce each service for a local state copy. No off-host backup.
set -euo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
mountpoint -q /data || { echo '/data is not mounted; refusing staging.' >&2; exit 1; }
base=/data/backup-staging/application-state
install -d -m 0700 /data/backup-staging "$base"
exec 9>"$base/.lock"
flock -n 9 || { echo 'Another state preparation/recovery is running.' >&2; exit 1; }
restarts="$base/restart-units"

recover() {
  local unit pending failed=0
  [[ -s $restarts ]] || return 0
  # Reverse stop order: application first, then its timer.
  while IFS= read -r unit; do
    case "$unit" in
      audiobookshelf.service|vaultwarden.service|headscale.service|jellyfin.service|backup-vaultwarden.timer) ;;
      *) echo "Unexpected recovery unit: $unit" >&2; failed=1; continue ;;
    esac
    if systemctl start "$unit"; then
      pending=$(mktemp "$base/.recovery.XXXXXXXX")
      # grep returns 1 when no records remain.
      grep -Fxv -- "$unit" "$restarts" > "$pending" || [[ $? == 1 ]]
      mv -f -- "$pending" "$restarts"
    else
      echo "RECOVERY REQUIRED: could not start $unit" >&2
      failed=1
    fi
  done < <(tac "$restarts")
  return "$failed"
}

if [[ ${1:-} == --recover && $# == 1 ]]; then
  recover
  exit
fi
[[ $# == 0 ]] || { echo 'Usage: prepare-application-state [--recover]' >&2; exit 1; }
[[ ! -s $restarts ]] || {
  echo 'Pending service recovery: run with --recover before preparing more state.' >&2
  exit 1
}
work=$(mktemp -d "$base/.incomplete.XXXXXXXX")
cleanup() {
  status=$?
  trap - EXIT
  if ! recover; then status=1; fi
  [[ -z ${work:-} ]] || rm -rf -- "$work"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

stop_if_active() {
  local unit=$1 state
  state=$(systemctl show --property=ActiveState --value "$unit")
  case "$state" in
    active)
      # Record before stopping, so failure/interruption still triggers recovery.
      printf '%s\n' "$unit" >> "$restarts"
      systemctl stop "$unit"
      ;;
    inactive) ;;
    *) echo "Refusing transitional/failed unit $unit ($state)" >&2; return 1 ;;
  esac
}

# Capture identity/recovery files before any application downtime. No network
# daemon is stopped; the Tailscale file backend atomically replaces its state.
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
machine_capture=${BLADE_CAPTURE_MACHINE_RECOVERY:-$script_dir/capture-machine-recovery.py}
python3 "$machine_capture" "$work/machine-recovery"

for app in audiobookshelf vaultwarden headscale jellyfin; do
  echo "Staging $app state"
  case "$app" in
    audiobookshelf)
      sources=(/data/audiobookshelf/config /data/audiobookshelf/metadata)
      excludes=(--exclude=/metadata/tmp/)
      database=config/absdatabase.sqlite
      ;;
    vaultwarden)
      sources=(/var/lib/vaultwarden/)
      excludes=(--exclude=/icon_cache/)
      database=db.sqlite3
      stop_if_active backup-vaultwarden.timer
      # Let any already-running native backup finish; never cancel it mid-copy.
      while :; do
        backup_state=$(systemctl show --property=ActiveState --value backup-vaultwarden.service)
        case "$backup_state" in
          inactive|failed) break ;;
          active|activating|deactivating) sleep 1 ;;
          *) echo "Unknown Vaultwarden backup state: $backup_state" >&2; exit 1 ;;
        esac
      done
      ;;
    headscale)
      sources=(/var/lib/headscale/)
      excludes=()
      database=db.sqlite
      ;;
    jellyfin)
      sources=(/data/jellyfin/)
      excludes=(--exclude=/cache/ --exclude=/log/)
      database=data/jellyfin.db
      ;;
  esac
  for source in "${sources[@]}"; do
    [[ -d $source ]] || { echo "Missing source directory: $source" >&2; exit 1; }
  done
  stop_if_active "$app.service"
  install -d -m 0700 "$work/$app"
  rsync -a --numeric-ids "${excludes[@]}" "${sources[@]}" "$work/$app/"
  # Resume immediately after copying, before checking the offline copy.
  recover
  [[ -s $work/$app/$database ]] || { echo "Missing staged database for $app" >&2; exit 1; }
  [[ $(sqlite3 "$work/$app/$database" 'PRAGMA quick_check;') == ok ]] || {
    echo "SQLite quick_check failed for $app" >&2; exit 1;
  }
done

{
  printf 'Completed UTC: %s\n' "$(date -u --iso-8601=seconds)"
  printf 'Host: %s\n' "$(hostname)"
  printf '%s\n' 'Services captured individually, not as one simultaneous snapshot.'
  printf '%s\n' 'Includes a root-only machine-recovery bundle; keep independent Restic recovery keys.'
  printf '%s\n' 'Does not include bulk audiobook/movie content, general home files, ACME state, or PostgreSQL services.'
} > "$work/README.txt"
# Include all copied files, including any WALs and persistent identity keys.
(cd "$work" && find audiobookshelf vaultwarden headscale jellyfin machine-recovery README.txt -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
generation="$(date -u +%Y%m%dT%H%M%SZ)-${work##*.}"
mv -- "$work" "$base/$generation"
work=''
ln -s "$generation" "$base/.current-$generation"
mv -Tf -- "$base/.current-$generation" "$base/current"
echo "Prepared $base/$generation"
