#!/usr/bin/env bash
# Consistent logical dumps, NOT a coordinated application-files backup.
# Requires root, a real /data mount, and pg_dump/pg_dumpall/pg_restore in PATH.
set -euo pipefail
umask 077

[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
mountpoint -q /data || { echo '/data is not mounted; refusing staging.' >&2; exit 1; }

base=/data/backup-staging/postgresql
install -d -m 0700 /data/backup-staging "$base"
exec 9>"$base/.lock"
flock -n 9 || { echo 'Another database preparation is running.' >&2; exit 1; }
work=$(mktemp -d "$base/.incomplete.XXXXXXXX")
cleanup() {
  status=$?
  trap - EXIT
  [[ -z ${work:-} ]] || rm -rf -- "$work"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Fail closed if an expected database/container is unavailable. Do not start,
# stop, or otherwise change application services here.
for spec in 'immich:immich_postgres:postgres:immich' 'bookorbit:bookorbit-db:bookorbit:bookorbit' 'norish:norish-db:norish:norish'; do
  IFS=: read -r app container user database <<< "$spec"
  echo "Preparing $app PostgreSQL dump"
  docker exec -u postgres "$container" pg_dump -U "$user" -d "$database" --format=custom > "$work/$app.dump"
  docker exec -u postgres "$container" pg_dumpall -U "$user" --globals-only > "$work/$app-globals.sql"
  # Validate using the same major version that produced this archive.
  docker exec -i -u postgres "$container" pg_restore --list < "$work/$app.dump" > /dev/null
  docker exec -u postgres "$container" pg_dump --version > "$work/$app-version.txt"
done

echo 'Preparing nextcloud PostgreSQL dump'
runuser -u postgres -- pg_dump -d nextcloud --format=custom > "$work/nextcloud.dump"
runuser -u postgres -- pg_dumpall --globals-only > "$work/nextcloud-globals.sql"
pg_restore --list "$work/nextcloud.dump" > /dev/null
pg_dump --version > "$work/nextcloud-version.txt"

for app in immich bookorbit norish nextcloud; do
  [[ -s $work/$app.dump && -s $work/$app-globals.sql ]] || {
    echo "Missing/empty dump for $app" >&2
    exit 1
  }
done
{
  printf 'Completed UTC: %s\n' "$(date -u --iso-8601=seconds)"
  printf 'Host: %s\n' "$(hostname)"
  printf '%s\n' 'Logical database dumps only. Application files are NOT captured or quiesced.'
  printf '%s\n' 'Archive listing validated; actual restore tests are still required.'
} > "$work/README.txt"
(cd "$work" && sha256sum -- *.dump *-globals.sql *-version.txt > SHA256SUMS)

# Publish only when every dump and check succeeded. Keep the previous complete
# generation; do not automatically delete older generations before off-host
# backups and retention are implemented.
generation="$(date -u +%Y%m%dT%H%M%SZ)-${work##*.}"
mv -- "$work" "$base/$generation"
work=''
link="$base/.current-$generation"
ln -s "$generation" "$link"
mv -Tf -- "$link" "$base/current"
echo "Prepared $base/$generation"
