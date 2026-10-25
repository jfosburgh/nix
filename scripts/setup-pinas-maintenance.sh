#!/usr/bin/env bash
# Hidden terminal input only. Never generates/replaces existing repository keys.
set -euo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ $# == 1 ]] || { echo 'Usage: setup-pinas-maintenance.sh {critical|media}' >&2; exit 1; }
kind=$1
case "$kind" in
  critical|media)
    [[ $(hostname) == pinas ]] || exit 1
    mountpoint -q /data
    [[ $(findmnt -nro UUID --mountpoint /data) == 0e549dd2-041c-42d1-b760-d42f1bb1d2e8 ]] || exit 1
    repo="/data/restic/blade/$kind"
    [[ $(readlink -e -- "$repo") == "$repo" && -f $repo/config && ! -L $repo/config ]] || exit 1
    base=/var/lib/restic-maintenance
    name="$kind-password"
    prompt="Paste the EXISTING $kind repository encryption password (hidden): "
    ;;
  *) exit 1 ;;
esac
if [[ -e $base || -L $base ]]; then
  [[ -d $base && ! -L $base && $(stat -c '%u:%a' "$base") == 0:700 ]] || {
    echo 'Refusing insecure credential directory.' >&2; exit 1;
  }
else
  install -d -o root -g root -m 0700 "$base"
fi
exec 9>"$base/.setup.lock"
flock -n 9 || exit 1
target="$base/$name"
[[ ! -e $target && ! -L $target ]] || { echo 'Credential already exists; refusing overwrite.' >&2; exit 1; }
tmp=$(mktemp "$base/.credential.XXXXXXXX")
trap 'rm -f -- "$tmp"' EXIT
# /dev/tty avoids reading a secret from shell history, command argv, or a pipe.
IFS= read -r -s -p "$prompt" value < /dev/tty
printf '\n' > /dev/tty
[[ -n $value ]] || { echo 'Empty credential rejected.' >&2; exit 1; }
printf '%s\n' "$value" > "$tmp"
unset value
unset RESTIC_REPOSITORY RESTIC_REPOSITORY_FILE RESTIC_PASSWORD RESTIC_PASSWORD_FILE RESTIC_PASSWORD_COMMAND
restic --no-cache --repo "$repo" --password-file "$tmp" cat config > /dev/null
# Hard-link install fails atomically if target appeared; source remains 0600.
ln -- "$tmp" "$target"
echo 'Existing repository credential validated and installed without displaying it.'
