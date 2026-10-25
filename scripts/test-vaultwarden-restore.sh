#!/usr/bin/env bash
# Runtime-only restored-vault sandbox. Never load production environment/config.
set -euo pipefail
[[ $EUID -eq 0 && $(hostname) == blade ]] || { echo 'Run as root on Blade.' >&2; exit 1; }
app=vaultwarden-restore-test.service
proxy=vaultwarden-restore-proxy.service
socket=vaultwarden-restore-proxy.socket
marker='# Managed by test-vaultwarden-restore.sh'
units=/run/systemd/system
state=/var/lib/vaultwarden-restore-test
sandbox=/data/restore-tests/vaultwarden-sandbox
tlsdir="$sandbox/tls"
create_tls() {
  command -v openssl >/dev/null || { echo 'openssl is required for the test certificate.' >&2; return 1; }
  [[ ! -e $tlsdir ]] || { echo 'Existing TLS material preserved; refusing overwrite.' >&2; return 1; }
  install -d -m 0700 "$tlsdir"
  openssl req -x509 -newkey rsa:2048 -noenc -sha256 -days 7 \
    -subj '/CN=localhost/O=Vaultwarden Restore Test ONLY' \
    -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1' \
    -addext 'basicConstraints=critical,CA:FALSE' \
    -addext 'extendedKeyUsage=serverAuth' \
    -keyout "$tlsdir/key.pem" -out "$tlsdir/cert.pem" 2>/dev/null
  chmod 0600 "$tlsdir/key.pem" "$tlsdir/cert.pem"
}
tls_settings() {
  printf '%s\n' "LoadCredential=tls-cert:$tlsdir/cert.pem" "LoadCredential=tls-key:$tlsdir/key.pem"
  printf '%s\n' "Environment='ROCKET_TLS={certs=\"/run/credentials/$app/tls-cert\",key=\"/run/credentials/$app/tls-key\"}'"
}
if [[ $# == 1 && $1 == --enable-https ]]; then
  [[ -f $units/$app && $(head -n 1 "$units/$app") == "$marker" ]] || { echo 'No recognized test unit.' >&2; exit 1; }
  grep -Fxq 'Environment=DOMAIN=http://localhost:18222' "$units/$app" || {
    echo 'Expected the original HTTP test unit; refusing unexpected edits.' >&2; exit 1;
  }
  create_tls
  temporary=$(mktemp "$units/.vaultwarden-restore-tls.XXXXXXXX")
  while IFS= read -r line; do
    if [[ $line == 'Environment=DOMAIN=http://localhost:18222' ]]; then
      printf '%s\n' 'Environment=DOMAIN=https://localhost:18222'
      tls_settings
    else
      printf '%s\n' "$line"
    fi
  done < "$units/$app" > "$temporary"
  install -m 0644 "$temporary" "$units/$app"
  rm -- "$temporary"
  systemctl stop "$socket" "$proxy" "$app"
  systemd-analyze verify "$units/$app" "$units/$proxy" "$units/$socket"
  systemctl daemon-reload
  systemctl start "$app" "$socket"
  openssl x509 -in "$tlsdir/cert.pem" -noout -fingerprint -sha256
  echo 'Test instance upgraded to https://localhost:18222; production untouched.'
  exit
fi
if [[ $# == 1 && $1 == --stop ]]; then
  for unit in "$socket" "$proxy" "$app"; do
    [[ -f $units/$unit && $(head -n 1 "$units/$unit") == "$marker" ]] || {
      echo "Refusing to touch unrecognized unit $unit" >&2; exit 1;
    }
  done
  systemctl stop "$socket" "$proxy" "$app"
  rm -- "$units/$socket" "$units/$proxy" "$units/$app"
  systemctl daemon-reload
  echo 'Restored-vault test units removed; private sandbox/reference data retained.'
  exit
fi
[[ $# == 4 && $1 == --start ]] || {
  echo 'Usage: test-vaultwarden-restore.sh --start RESTORED_VAULT_DIR VAULTWARDEN_BINARY WEB_VAULT_FOLDER | --enable-https | --stop' >&2; exit 1;
}
source=$(readlink -e -- "$2")
binary=$(readlink -e -- "$3")
webvault=$(readlink -e -- "$4")
[[ $source =~ ^/data/restore-tests/[a-zA-Z0-9/_-]+/vaultwarden$ ]] || { echo 'Use only a restored vault directory.' >&2; exit 1; }
[[ $binary =~ ^/nix/store/[a-z0-9]{32}-vaultwarden-[a-zA-Z0-9._+-]+/bin/vaultwarden$ && -x $binary ]] || exit 1
[[ $webvault =~ ^/nix/store/[a-z0-9]{32}-vaultwarden-webvault-[a-zA-Z0-9._+-]+/share/vaultwarden/vault$ && -s $webvault/index.html ]] || exit 1
[[ -s $source/db.sqlite3 ]] || { echo 'Missing restored database.' >&2; exit 1; }
[[ ! -e $state && ! -L $state && ! -e $sandbox && ! -L $sandbox ]] || { echo 'Existing sandbox/state preserved; refusing overwrite.' >&2; exit 1; }
for unit in "$app" "$proxy" "$socket"; do
  [[ ! -e $units/$unit && $(systemctl show --property=LoadState --value "$unit") == not-found ]] || {
    echo "Unit already exists: $unit" >&2; exit 1;
  }
done
proxy_binary=$(readlink -e /run/current-system/systemd/lib/systemd/systemd-socket-proxyd)
[[ -x $proxy_binary ]] || exit 1
install -d -m 0700 "$sandbox" "$state"
create_tls
install -d -m 0755 "$sandbox/root" "$sandbox/root/nix/store" "$sandbox/root/var/lib"
# Keep DB/WAL/keys/attachments coherent, but deliberately omit admin JSON config:
# it can override env settings with production domain, SMTP, push and file paths.
rsync -a --exclude=/config.json --exclude=/.env --exclude=/restore-test-config.json "$source/" "$state/"
cat > "$units/$app" <<EOF
$marker
[Unit]
Description=Isolated restored Vaultwarden (NOT production)
RequiresMountsFor=$sandbox $state

[Service]
Type=exec
DynamicUser=yes
StateDirectory=vaultwarden-restore-test
StateDirectoryMode=0700
RootDirectory=$sandbox/root
MountAPIVFS=yes
BindReadOnlyPaths=/nix/store
WorkingDirectory=$state
ExecStart=$binary
Environment=DATA_FOLDER=$state
Environment=DATABASE_URL=$state/db.sqlite3
Environment=CONFIG_FILE=$state/restore-test-config.json
Environment=WEB_VAULT_ENABLED=true
Environment=WEB_VAULT_FOLDER=$webvault
Environment=DOMAIN=https://localhost:18222
$(tls_settings)
Environment=ROCKET_ADDRESS=127.0.0.1
Environment=ROCKET_PORT=8222
Environment=SIGNUPS_ALLOWED=false
Environment=INVITATIONS_ALLOWED=false
Environment=PUSH_ENABLED=false
Environment=DISABLE_ICON_DOWNLOAD=true
PrivateNetwork=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=yes
ProtectProc=invisible
NoNewPrivileges=yes
CapabilityBoundingSet=
RestrictSUIDSGID=yes
UMask=0077
TimeoutStopSec=60
EOF
cat > "$units/$proxy" <<EOF
$marker
[Unit]
Description=Local browser proxy into restored Vaultwarden network namespace
Requires=$app
After=$app
JoinsNamespaceOf=$app
BindsTo=$app

[Service]
Type=exec
ExecStart=$proxy_binary 127.0.0.1:8222
DynamicUser=yes
PrivateNetwork=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
CapabilityBoundingSet=
EOF
cat > "$units/$socket" <<EOF
$marker
[Unit]
Description=Localhost-only restored-vault browser access

[Socket]
ListenStream=127.0.0.1:18222
Service=$proxy
EOF
systemd-analyze verify "$units/$app" "$units/$proxy" "$units/$socket"
systemctl daemon-reload
trap 'systemctl stop "$socket" "$proxy" "$app" || true; echo "Sandbox startup failed; inspect ONLY test-unit logs. Production untouched." >&2' ERR
systemctl start "$app" "$socket"
openssl x509 -in "$tlsdir/cert.pem" -noout -fingerprint -sha256
echo 'Restored vault sandbox started: https://localhost:18222 through an SSH tunnel.'
echo 'Short-lived self-signed localhost certificate: verify fingerprint before accepting its browser warning.'
echo 'Use a private browser window, NEVER reconfigure your normal extension or clients.'
echo 'No outbound network/SMTP/push; existing origin-bound passkeys may not work at localhost.'
echo 'Stop with: sudo bash scripts/test-vaultwarden-restore.sh --stop'
