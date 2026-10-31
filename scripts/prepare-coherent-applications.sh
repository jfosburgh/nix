#!/usr/bin/env bash
# Consistent PostgreSQL + files per app, with writers stopped for the local copy.
# Unchanged media is hard-linked from the previous generation. No in-place writes.
# Initial/full-comparison captures can still mean substantial downtime.
set -euo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname) == blade ]] || { echo 'Run as root on Blade.' >&2; exit 1; }
mountpoint -q /data || { echo '/data is not mounted.' >&2; exit 1; }
base=/data/backup-staging/coherent-applications
install -d -m 0700 /data/backup-staging "$base"
exec 9>"$base/.lock"
flock -n 9 || { echo 'Another coherent capture/recovery is running.' >&2; exit 1; }
restarts="$base/restart-units"
resume_container() {
  local container=$1 status deadline=$((SECONDS + 300))
  docker start "$container" >/dev/null || return 1
  while (( SECONDS < deadline )); do
    status=$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container") || return 1
    case "$status" in
      'running healthy'|'running none') return 0 ;;
      'running starting'|'running unhealthy'|'restarting '*) sleep 2 ;;
      *) echo "Container did not resume: $container ($status)" >&2; return 1 ;;
    esac
  done
  echo "Timed out waiting for $container health; recovery record retained." >&2
  return 1
}
recover() {
  local entry pending failed=0
  [[ -s $restarts ]] || return 0
  while IFS= read -r entry; do
    case "$entry" in
      container:immich_server|container:bookorbit-app|container:norish-app|container:norish-valkey)
        if ! resume_container "${entry#container:}"; then failed=1; continue; fi
        ;;
      unit:phpfpm-nextcloud.service|unit:nextcloud-cron.timer)
        if ! systemctl start "${entry#unit:}"; then failed=1; continue; fi
        ;;
      *) echo "Unexpected recovery entry: $entry" >&2; failed=1; continue ;;
    esac
    pending=$(mktemp "$base/.recovery.XXXXXXXX")
    grep -Fxv -- "$entry" "$restarts" > "$pending" || [[ $? == 1 ]]
    mv -f -- "$pending" "$restarts"
  done < <(tac "$restarts")
  if [[ $failed == 1 ]]; then echo "RECOVERY REQUIRED: inspect $restarts" >&2; fi
  return "$failed"
}
if [[ ${1:-} == --recover && $# == 1 ]]; then recover; exit; fi
[[ $# == 0 && ! -s $restarts ]] || { echo 'Invalid arguments or pending recovery; use --recover.' >&2; exit 1; }
previous=''
if [[ -L $base/current ]]; then
  previous=$(readlink -e "$base/current")
  [[ ${previous%/*} == "$base" && -d $previous && -f $previous/SHA256SUMS ]] || {
    echo 'Unexpected previous generation; refusing hard-link reuse.' >&2; exit 1;
  }
fi
compare=()
case "${BLADE_BACKUP_FULL_COMPARE:-0}" in
  0) ;;
  1) compare=(--checksum) ;;
  *) echo 'BLADE_BACKUP_FULL_COMPARE must be 0 or 1.' >&2; exit 1 ;;
esac
if [[ -n $previous ]]; then
  echo "Reusing unchanged files from ${previous##*/} with hard links (full comparison: ${BLADE_BACKUP_FULL_COMPARE:-0})"
else
  echo 'No previous generation; full local file copy required.'
fi
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

stop_container() {
  local container=$1 state
  state=$(docker inspect --format '{{.State.Status}}' "$container")
  case "$state" in
    running)
      printf 'container:%s\n' "$container" >> "$restarts"
      docker stop --time 300 "$container" >/dev/null
      ;;
    exited|created) ;;
    *) echo "Unexpected container state: $container ($state)" >&2; return 1 ;;
  esac
}
stop_unit() {
  local unit=$1 state
  state=$(systemctl show --property=ActiveState --value "$unit")
  case "$state" in
    active) printf 'unit:%s\n' "$unit" >> "$restarts"; systemctl stop "$unit" ;;
    inactive) ;;
    *) echo "Unexpected unit state: $unit ($state)" >&2; return 1 ;;
  esac
}

# Fail before downtime if first-generation staging would exhaust the data disk.
needed=$(du -s -B1 /data/immich/media /data/bookorbit /data/norish /data/nextcloud | awk '{s+=$1} END {printf "%.0f",s}')
available=$(df -B1 --output=avail /data | tail -n 1 | tr -d ' ')
(( available > needed + 10737418240 )) || { echo 'Insufficient staging space (need source size plus 10 GiB).' >&2; exit 1; }

for spec in 'immich:immich_server:immich_postgres:postgres:immich' 'bookorbit:bookorbit-app:bookorbit-db:bookorbit:bookorbit' 'norish:norish-app:norish-db:norish:norish'; do
  IFS=: read -r app writer database_container user database <<< "$spec"
  install -d -m 0700 "$work/$app"
  echo "Stopping $app writers for database and file capture"
  downtime_start=$SECONDS
  stop_container "$writer"
  # Persist and quiesce Norish's job queue too; recover starts it before the app.
  if [[ $app == norish ]]; then stop_container norish-valkey; fi
  docker exec -u postgres "$database_container" pg_dump -U "$user" -d "$database" --format=custom > "$work/$app/database.dump"
  docker exec -u postgres "$database_container" pg_dumpall -U "$user" --globals-only > "$work/$app/globals.sql"
  docker exec -u postgres "$database_container" pg_dump --version > "$work/$app/version.txt"
  docker inspect --format '{{.Config.Image}}' "$writer" "$database_container" > "$work/$app/images.txt"
  if [[ $app == immich ]]; then
    links=()
    [[ -z $previous ]] || links=("--link-dest=$previous/immich")
    rsync -a --stats --numeric-ids "${compare[@]}" "${links[@]}" /data/immich/media "$work/$app/"
    install -m 0600 /var/lib/immich/environment "$work/$app/environment"
  else
    links=()
    [[ -z $previous || ! -d $previous/$app/files ]] || links=("--link-dest=$previous/$app/files")
    rsync -a --numeric-ids "${compare[@]}" "${links[@]}" --exclude=/postgres/ "/data/$app/" "$work/$app/files/"
  fi
  recover
  echo "Resumed previously running $app after $((SECONDS - downtime_start))s capture/startup window"
  docker exec -i -u postgres "$database_container" pg_restore --list < "$work/$app/database.dump" >/dev/null
done

# Refuse to race setup/upgrade operations. With FPM and scheduled cron stopped,
# the configured Nextcloud writers are quiesced without toggling maintenance state.
for unit in nextcloud-setup.service nextcloud-update-db.service; do
  state=$(systemctl show --property=ActiveState --value "$unit")
  [[ $state == inactive ]] || { echo "Refusing capture while $unit is $state" >&2; exit 1; }
done
stop_unit nextcloud-cron.timer
while :; do
  state=$(systemctl show --property=ActiveState --value nextcloud-cron.service)
  case "$state" in
    inactive) break ;;
    active|activating|deactivating) sleep 1 ;;
    *) echo "Unexpected Nextcloud cron state: $state" >&2; exit 1 ;;
  esac
done
downtime_start=$SECONDS
stop_unit phpfpm-nextcloud.service
install -d -m 0700 "$work/nextcloud"
runuser -u postgres -- pg_dump -d nextcloud --format=custom > "$work/nextcloud/database.dump"
runuser -u postgres -- pg_dumpall --globals-only > "$work/nextcloud/globals.sql"
pg_dump --version > "$work/nextcloud/version.txt"
links=()
[[ -z $previous ]] || links=("--link-dest=$previous/nextcloud/files")
rsync -a --numeric-ids "${compare[@]}" "${links[@]}" --exclude=/redis/ --exclude=/tmp/ /data/nextcloud/ "$work/nextcloud/files/"
# Keep generated config content recoverable without its old Nix store path.
rsync -aL --numeric-ids /data/nextcloud/config/ "$work/nextcloud/files/config/"
recover
echo "Resumed previously running Nextcloud writers after $((SECONDS - downtime_start))s capture window"
pg_restore --list "$work/nextcloud/database.dump" >/dev/null

# Copy deployment material into the same immutable generation. Dereference only
# explicit generated /etc files; retain repository symlinks as symlinks.
install -d -m 0700 "$work/configuration"
rsync -a --exclude='result*' /home/james/nix/ "$work/configuration/nix/"
for path in /etc/immich/compose.yaml /etc/bookorbit/compose.yaml /etc/norish/compose.yaml /etc/headscale/config.yaml; do
  destination="$work/configuration$path"
  install -d -m 0700 "${destination%/*}"
  install -m 0600 "$path" "$destination"
done
for app in immich bookorbit norish nextcloud; do
  [[ -s $work/$app/database.dump && -s $work/$app/globals.sql ]] || exit 1
done
printf 'Completed UTC: %s\nEach application captured separately; writers stopped for database and files.\nFull source checksum comparison: %s\nUnchanged files may share hard links with older generations; NEVER edit staging files in place.\n' \
  "$(date -u --iso-8601=seconds)" "${BLADE_BACKUP_FULL_COMPARE:-0}" > "$work/README.txt"
echo 'Computing staged SHA-256 manifest; application writers have already resumed.'
(cd "$work" && find immich bookorbit norish nextcloud configuration README.txt -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
generation="$(date -u +%Y%m%dT%H%M%SZ)-${work##*.}"
mv -- "$work" "$base/$generation"
work=''
ln -s "$generation" "$base/.current-$generation"
mv -Tf -- "$base/.current-$generation" "$base/current"
echo "Prepared $base/$generation"
