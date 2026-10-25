#!/usr/bin/env bash
# Root-only Restic access to a fixed Pinas repository. No embedded credentials.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root on Blade.' >&2; exit 1; }
[[ $(hostname) == blade ]] || { echo 'This helper is only for Blade.' >&2; exit 1; }
[[ $# -ge 2 ]] || { echo 'Usage: pinas-restic.sh {critical|media} RESTIC_COMMAND [ARGS...]' >&2; exit 1; }
repository=$1
shift
case "$repository" in critical|media) ;; *) echo 'Unknown repository.' >&2; exit 1 ;; esac
secrets=/var/lib/restic-secrets/pinas
for directory in /var/lib/restic-secrets "$secrets"; do
  [[ ! -L $directory && $(stat -c '%u:%a' "$directory") == 0:700 ]] || {
    echo "Expected root-owned mode-0700 directory: $directory" >&2; exit 1;
  }
done
for file in "$secrets/rest-password" "$secrets/$repository-password"; do
  [[ -f $file && ! -L $file && $(stat -c '%u:%a' "$file") == 0:600 && -s $file ]] || {
    echo "Expected nonempty root-owned mode-0600 credential: $file" >&2; exit 1;
  }
done
# Avoid inherited alternative password/repository sources. Explicit CLI options
# still work for deliberate administrator operations; use this helper carefully.
unset RESTIC_REPOSITORY_FILE RESTIC_PASSWORD RESTIC_PASSWORD_COMMAND
export RESTIC_REPOSITORY="rest:http://100.64.0.6:8000/blade/$repository/"
export RESTIC_PASSWORD_FILE="$secrets/$repository-password"
export RESTIC_REST_USERNAME=blade
RESTIC_REST_PASSWORD=$(< "$secrets/rest-password")
export RESTIC_REST_PASSWORD
exec restic "$@"
