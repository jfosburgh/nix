#!/usr/bin/env bash
# Browser-accessible restored Audiobookshelf, isolated from live data/network.
set -euo pipefail
[[ $EUID -eq 0 && $(hostname) == blade ]] || { echo 'Run as root on Blade.' >&2; exit 1; }
app=audiobookshelf-restore-test.service
proxy=audiobookshelf-restore-proxy.service
socket=audiobookshelf-restore-proxy.socket
marker='# Managed by test-audiobookshelf-restore.sh'
units=/run/systemd/system
state=/var/lib/audiobookshelf-restore-test
sandbox=/data/restore-tests/audiobookshelf-sandbox

if [[ $# == 1 && $1 == --stop ]]; then
  for unit in "$socket" "$proxy" "$app"; do
    [[ -f $units/$unit && $(head -n 1 "$units/$unit") == "$marker" ]] || {
      echo "Refusing to touch unrecognized unit $unit" >&2; exit 1;
    }
  done
  systemctl stop "$socket" "$proxy" "$app"
  rm -- "$units/$socket" "$units/$proxy" "$units/$app"
  systemctl daemon-reload
  echo 'Test units stopped/removed. Sandbox state retained; production untouched.'
  exit
fi
[[ $# == 3 && $1 == --start ]] || {
  echo 'Usage: test-audiobookshelf-restore.sh --start RESTORED_ABS_DIRECTORY /nix/store/.../bin/audiobookshelf | --stop' >&2; exit 1;
}
source=$(readlink -e -- "$2")
binary=$(readlink -e -- "$3")
[[ $source =~ ^/data/restore-tests/[a-zA-Z0-9/_-]+/audiobookshelf$ ]] || { echo 'Use only a restored Audiobookshelf directory.' >&2; exit 1; }
[[ $binary =~ ^/nix/store/[a-z0-9]{32}-audiobookshelf-[a-zA-Z0-9._+-]+/bin/audiobookshelf$ && -x $binary ]] || { echo 'Expected an existing Nix-store Audiobookshelf executable.' >&2; exit 1; }
[[ -s $source/config/absdatabase.sqlite && -d $source/metadata ]] || exit 1
[[ ! -e $state && ! -L $state && ! -e $sandbox && ! -L $sandbox ]] || { echo 'Existing sandbox/state preserved; refusing overwrite.' >&2; exit 1; }
for unit in "$app" "$proxy" "$socket"; do
  [[ ! -e $units/$unit && $(systemctl show --property=LoadState --value "$unit") == not-found ]] || {
    echo "Unit already exists: $unit" >&2; exit 1;
  }
done
proxy_binary=$(readlink -e /run/current-system/systemd/lib/systemd/systemd-socket-proxyd)
[[ -x $proxy_binary ]] || exit 1
install -d -m 0700 "$sandbox" "$state"
install -d -m 0755 "$sandbox/root" "$sandbox/root/nix/store" "$sandbox/root/var/lib" "$sandbox/root/data"
# Restored settings retain absolute paths (notably the native backup folder).
# Inside the chroot, this alias resolves ONLY to the sandbox StateDirectory,
# never to the host's /data/audiobookshelf.
ln -s "$state" "$sandbox/root/data/audiobookshelf"
# A writable COPY: the restored reference databases remain unchanged.
rsync -a "$source/config" "$source/metadata" "$state/"

cat > "$units/$app" <<EOF
$marker
[Unit]
Description=Isolated restored Audiobookshelf (NOT production)
RequiresMountsFor=$sandbox $state

[Service]
Type=exec
DynamicUser=yes
StateDirectory=audiobookshelf-restore-test
StateDirectoryMode=0700
RootDirectory=$sandbox/root
MountAPIVFS=yes
BindReadOnlyPaths=/nix/store
WorkingDirectory=$state
ExecStart=$binary --host 127.0.0.1 --port 8000 --config $state/config --metadata $state/metadata
Environment=TZ=UTC
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
Description=Local browser proxy into restored Audiobookshelf network namespace
Requires=$app
After=$app
JoinsNamespaceOf=$app
BindsTo=$app

[Service]
Type=exec
ExecStart=$proxy_binary 127.0.0.1:8000
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
Description=Localhost-only restored Audiobookshelf browser access

[Socket]
ListenStream=127.0.0.1:18000
Service=$proxy
EOF
# Only runtime units: no boot enablement, nginx routes, or production unit changes.
systemd-analyze verify "$units/$app" "$units/$proxy" "$units/$socket"
systemctl daemon-reload
trap 'systemctl stop "$socket" "$proxy" "$app" || true; echo "Sandbox startup failed; inspect test-unit logs. Reference restore preserved." >&2' ERR
systemctl start "$app" "$socket"
echo 'Sandbox started: http://127.0.0.1:18000 (use SSH local forwarding from your workstation).'
echo 'Outbound network and live application paths are inaccessible. Original library media is NOT mounted.'
echo 'Verify existing login, libraries, listening progress and bookmarks; do not run production scans/imports.'
echo 'Stop with: sudo bash scripts/test-audiobookshelf-restore.sh --stop'
