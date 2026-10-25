#!/usr/bin/env bash
# Provision local credentials only. Does NOT initialize repositories or run backups.
set -euo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run as root on Blade.' >&2; exit 1; }
[[ $(hostname) == blade ]] || { echo 'This setup is only for Blade.' >&2; exit 1; }
parent=/var/lib/restic-secrets
target="$parent/pinas"
[[ ! -e $target && ! -L $target ]] || {
  echo "Refusing to overwrite $target. Existing encryption keys must never be replaced casually." >&2
  exit 1
}
install -d -o root -g root -m 0700 "$parent"
work=$(mktemp -d "$parent/.pinas-incomplete.XXXXXXXX")
cleanup() {
  status=$?
  trap - EXIT
  [[ -z ${work:-} ]] || rm -rf -- "$work"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf 'Enter the REST authentication password already configured on Pinas.\n'
IFS= read -r -s -p 'REST password: ' password < /dev/tty
printf '\n'
IFS= read -r -s -p 'Repeat REST password: ' repeated < /dev/tty
printf '\n'
[[ -n $password && $password == "$repeated" ]] || {
  echo 'Passwords were empty or did not match; nothing provisioned.' >&2
  exit 1
}
printf '%s\n' "$password" > "$work/rest-password"
unset password repeated
for repository in critical media; do
  # 256 random bits from the kernel CSPRNG, encoded as a 64-character hex string.
  od -An -N32 -v -tx1 /dev/urandom | tr -d ' \n' > "$work/$repository-password"
  printf '\n' >> "$work/$repository-password"
  [[ $(wc -c < "$work/$repository-password") == 65 ]] || exit 1
done
chmod 0600 "$work/"*
mv -T -- "$work" "$target"
work=''
printf '\nCredentials created in %s (root-only). No repository initialized.\n' "$target"
printf 'Save BOTH encryption passwords and the REST password in independent recovery storage before init.\n'
printf 'Never paste them into chat or replace them by rerunning setup.\n'
