#!/usr/bin/env bash
# Read-only backup/storage inventory. Run with sudo for complete results.
# Does not read application secrets, start tests, or modify storage/services.
set -euo pipefail
export LC_ALL=C

section() { printf '\n== %s ==\n' "$1"; }
optional() {
  if command -v "$1" >/dev/null 2>&1; then
    "$@" || printf 'WARNING: command failed: %s\n' "$*" >&2
  else
    printf 'Not installed: %s\n' "$1"
  fi
}

section 'Host'
hostname
if [[ $EUID -ne 0 ]]; then
  printf 'WARNING: run with sudo for complete disk and application inventory.\n' >&2
fi
section 'Physical disks and mounts'
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL
if mountpoint -q /data; then
  findmnt /data
  df -hT /data
  section 'Top-level data usage'
  optional du -xhd1 /data
else
  printf 'WARNING: /data is NOT a mount point.\n' >&2
fi
section 'LVM'
optional pvs
optional vgs
optional lvs -a -o +devices,segtype
section 'Software RAID'
if [[ -r /proc/mdstat ]]; then
  # Avoid interactive shell aliases (for example cat -> bat).
  while IFS= read -r line; do printf '%s\n' "$line"; done < /proc/mdstat
else
  printf '/proc/mdstat is absent; the md driver may not be loaded.\n'
fi
section 'Disk SMART reports (no self-tests started)'
while read -r disk type; do
  [[ $type == disk ]] || continue
  # Skip SD/eMMC system storage; smartctl targets SATA/SAS/USB/NVMe disks.
  case "$disk" in /dev/sd*|/dev/nvme*) optional smartctl -x "$disk" ;; esac
done < <(lsblk -dnpo NAME,TYPE)
section 'Application state sizes (not file contents)'
for path in /var/lib /var/backup; do
  if [[ -d $path ]]; then optional du -xhd1 "$path"; fi
done
section 'Running containers (no environment variables)'
optional docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
