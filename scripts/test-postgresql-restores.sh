#!/usr/bin/env bash
# Replay restored dumps only into new, disposable, network-isolated containers.
# No production mounts/ports/connections and no global-role SQL replay.
set -euo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname) == blade ]] || { echo 'Run as root on Blade.' >&2; exit 1; }
[[ $# == 1 ]] || { echo 'Usage: test-postgresql-restores.sh RESTORED_COHERENT_GENERATION' >&2; exit 1; }
source=$(readlink -e -- "$1")
case "$source" in /data/restore-tests/*/data/backup-staging/coherent-applications/*) ;; *) echo 'Expected a restored generation under /data/restore-tests, never live/staging data.' >&2; exit 1 ;; esac
[[ -d $source && ! -L $1 ]] || exit 1

get_image() {
  local app=$1
  local -a images
  mapfile -t images < "$source/$app/images.txt"
  [[ ${#images[@]} == 2 && ${images[1]} =~ ^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$ ]] || {
    echo "Missing/invalid pinned database image for $app" >&2; return 1;
  }
  printf '%s\n' "${images[1]}"
}
get_version() {
  local app=$1 program product version
  read -r program product version _ < "$source/$app/version.txt"
  [[ $program == pg_dump && $product == '(PostgreSQL)' && $version =~ ^[0-9]+\.[0-9]+$ ]] || {
    echo "Unexpected dump version record for $app" >&2; return 1;
  }
  printf '%s\n' "$version"
}
immich_image=$(get_image immich)
bookorbit_image=$(get_image bookorbit)
# Nextcloud was native PG18.6. Reuse the already-cached PG18.6 BookOrbit image
# as an isolated SQL engine, verifying the exact server version before restoring.
# This tests dump replay, NOT native service configuration or application startup.
for app in immich bookorbit nextcloud; do
  [[ -s $source/$app/database.dump ]] || { echo "Missing dump for $app" >&2; exit 1; }
  get_version "$app" >/dev/null
done
docker image inspect "$immich_image" >/dev/null
docker image inspect "$bookorbit_image" >/dev/null
containers=()
cleanup() {
  status=$?
  trap - EXIT
  for id in "${containers[@]}"; do
    if ! docker rm --force --volumes "$id" >/dev/null; then
      echo "Cleanup failed for test container $id; remove ONLY that test container after inspection." >&2
      status=1
    fi
  done
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
token=$(od -An -N6 -v -tx1 /dev/urandom | tr -d ' \n')

for app in immich bookorbit nextcloud; do
  if [[ $app == immich ]]; then image=$immich_image; else image=$bookorbit_image; fi
  expected=$(get_version "$app")
  echo "Testing $app dump in disposable PostgreSQL $expected container"
  # create first, record ID, then start: even startup failure can be cleaned up.
  id=$(docker create --pull=never --name "backup-restore-test-$app-$token" \
    --label "backup-restore-test=$token" --network none --shm-size=256m \
    --memory=2g --cpus=2 --security-opt=no-new-privileges:true \
    --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_USER=postgres \
    --env POSTGRES_DB=restore_test --env DB_STORAGE_TYPE=HDD "$image")
  [[ $id =~ ^[a-f0-9]{64}$ ]] || { echo 'Unexpected container ID; inspect test container by its generated name.' >&2; exit 1; }
  containers+=("$id")
  docker start "$id" >/dev/null
  ready=false
  for (( attempt=0; attempt<150; attempt++ )); do
    # Use the final TCP listener on loopback inside the isolated network namespace.
    # The entrypoint's temporary initialization server normally has no TCP listener.
    if docker exec -u postgres "$id" pg_isready -h 127.0.0.1 -U postgres -d restore_test >/dev/null 2>&1; then
      ready=true; break
    fi
    [[ $(docker inspect --format '{{.State.Running}}' "$id") == true ]] || {
      echo "Test container for $app exited during startup; no production service touched." >&2; exit 1;
    }
    sleep 2
  done
  [[ $ready == true ]] || { echo "Timed out starting $app test database." >&2; exit 1; }
  actual=$(docker exec -u postgres "$id" psql -X -U postgres -d restore_test -Atc 'SHOW server_version;')
  [[ ${actual%% *} == "$expected" ]] || { echo "Version mismatch: expected $expected, got $actual" >&2; exit 1; }
  docker exec -i -u postgres "$id" pg_restore -U postgres -d restore_test \
    --clean --if-exists --no-owner --no-privileges --exit-on-error < "$source/$app/database.dump"
  tables=$(docker exec -u postgres "$id" psql -X -v ON_ERROR_STOP=1 -U postgres -d restore_test -Atc \
    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%';")
  [[ $tables =~ ^[0-9]+$ && $tables -gt 0 ]] || { echo "No user tables restored for $app." >&2; exit 1; }
  docker exec -u postgres "$id" psql -X -v ON_ERROR_STOP=1 -U postgres -d restore_test -c ANALYZE >/dev/null
  echo "PASS: $app dump replayed without errors; $tables user tables; server $actual"
  docker rm --force --volumes "$id" >/dev/null
  containers=()
done
printf '\nAll three database dumps replayed successfully. Test containers/anonymous volumes removed.\n'
printf 'Original roles/ACLs, application startup, and omitted Immich media still require separate tests.\n'
