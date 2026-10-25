#!/usr/bin/env bash
# Read-only bind views in a NEW private mount namespace give Restic stable paths.
set -euo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname) == blade ]] || { echo 'Run as root on Blade.' >&2; exit 1; }
[[ $# == 2 ]] || { echo 'Usage: upload-critical.sh STATE_GENERATION COHERENT_GENERATION' >&2; exit 1; }
mountpoint -q /data || exit 1
staging=/data/backup-staging
# Pin both groups against standalone preparation/pruning during the upload.
exec 5>"$staging/application-state/.lock"
exec 6>"$staging/coherent-applications/.lock"
if ! flock -sn 5 || ! flock -sn 6; then
  echo 'Preparation/pruning is active; refusing upload.' >&2
  exit 1
fi
state=$(readlink -e -- "$1")
coherent=$(readlink -e -- "$2")
for spec in "$state:application-state" "$coherent:coherent-applications"; do
  generation=${spec%:*}; group=${spec##*:}
  [[ ${generation%/*} == "$staging/$group" && -f $generation/SHA256SUMS ]] || {
    echo 'Expected complete immutable generation.' >&2; exit 1;
  }
  [[ ${generation##*/} =~ ^[0-9]{8}T[0-9]{6}Z-[a-zA-Z0-9]{8}$ ]] || exit 1
  published="$staging/$group/published"
  [[ ! -L $published ]] || exit 1
  install -d -m 0700 "$published"
  [[ -z $(find "$published" -mindepth 1 -maxdepth 1 -print -quit) ]] || {
    echo "Expected empty host-side bind target: $published" >&2; exit 1;
  }
done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
client=${BLADE_RESTIC:-$script_dir/pinas-restic.sh}
# No mounts are added to the host namespace. The kernel releases these views
# when this process subtree exits, including on failure. No host umount cleanup.
# Expansion is intentionally performed by the child shell after unshare.
# shellcheck disable=SC2016
exec unshare --mount --propagation private bash -c '
  set -euo pipefail
  state=$1; coherent=$2; client=$3; staging=$4
  state_view="$staging/application-state/published"
  coherent_view="$staging/coherent-applications/published"
  mount --bind "$state" "$state_view"
  mount -o remount,bind,ro "$state_view"
  mount --bind "$coherent" "$coherent_view"
  mount -o remount,bind,ro "$coherent_view"
  bash "$client" critical backup "$state_view" "$coherent_view" \
    --ignore-ctime --tag blade-critical-v1 --tag stable-staging-v2
' _ "$state" "$coherent" "$client" "$staging"
