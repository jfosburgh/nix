#!/usr/bin/env bash
# Call ONLY after successful Restic upload. Never deletes unconfirmed generations.
set -euo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname) == blade ]] || { echo 'Run as root on Blade.' >&2; exit 1; }
[[ $# == 2 ]] || { echo 'Usage: finish-critical-staging.sh STATE_GENERATION COHERENT_GENERATION' >&2; exit 1; }
mountpoint -q /data || exit 1
staging=/data/backup-staging
state=$(readlink -e -- "$1")
coherent=$(readlink -e -- "$2")
# Also exclude concurrent standalone preparation/recovery while pruning.
exec 5>"$staging/application-state/.lock"
exec 6>"$staging/coherent-applications/.lock"
if ! flock -n 5 || ! flock -n 6; then
  echo 'Preparation still active; refusing cleanup.' >&2
  exit 1
fi
for spec in "$state:application-state" "$coherent:coherent-applications"; do
  generation=${spec%:*}; group=${spec##*:}
  [[ ${generation%/*} == "$staging/$group" && -d $generation && -f $generation/SHA256SUMS ]] || exit 1
  [[ ${generation##*/} =~ ^[0-9]{8}T[0-9]{6}Z-[a-zA-Z0-9]{8}$ ]] || exit 1
  current=$(readlink -e "$staging/$group/current")
  [[ ${current%/*} == "$staging/$group" && -f $current/SHA256SUMS ]] || exit 1
done
for spec in "$state:application-state" "$coherent:coherent-applications"; do
  generation=${spec%:*}; group=${spec##*:}
  base="$staging/$group"
  ledger="$base/.uploaded"
  [[ ! -L $ledger ]] || exit 1
  install -d -m 0700 "$ledger"
  printf 'Successful critical upload UTC: %s\n' "$(date -u --iso-8601=seconds)" > "$ledger/${generation##*/}"
  current=$(readlink -e "$base/current")
  kept=0
  while IFS= read -r name; do
    [[ $name =~ ^[0-9]{8}T[0-9]{6}Z-[a-zA-Z0-9]{8}$ ]] || continue
    candidate="$base/$name"
    [[ -f $ledger/$name && ! -L $ledger/$name && ! -L $candidate ]] || continue
    kept=$((kept + 1))
    # Keep two newest confirmed uploads, current, and this job's selected source.
    if (( kept <= 2 )) || [[ $candidate == "$current" || $candidate == "$generation" ]]; then continue; fi
    if mountpoint -q "$candidate"; then echo "Refusing mounted generation: $candidate" >&2; exit 1; fi
    echo "Removing old uploaded local staging generation: $candidate"
    rm -rf --one-file-system -- "$candidate"
    rm -- "$ledger/$name"
  done < <(find "$base" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -r)
done
# This is an operational status receipt, not a substitute for snapshot checks.
status=/var/lib/blade-backup-status
install -d -m 0700 "$status"
receipt=$(mktemp "$status/.last-success.XXXXXXXX")
printf '%s\n' "$(date +%s)" > "$receipt"
mv -f -- "$receipt" "$status/last-success"
