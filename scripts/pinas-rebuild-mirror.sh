#!/usr/bin/env bash
# DESTRUCTIVE, ONE-TIME procedure for the two explicitly approved Pinas disks.
# Do not run until migration and the single-copy risk have been accepted.
set -euo pipefail
export LC_ALL=C
fail() { echo "STOP: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail 'Run as root.'
[[ $(hostname) == pinas ]] || fail 'This procedure is only for pinas.'
[[ $# == 1 && $1 == --erase-pinas-data ]] || fail 'Requires --erase-pinas-data.'
for tool in lsblk findmnt mountpoint readlink pvs lvs lvremove vgremove pvremove wipefs mdadm mkfs.ext4 mount umount systemctl blkid awk sort modprobe; do
  command -v "$tool" >/dev/null || fail "Missing tool: $tool"
done

disk1=/dev/disk/by-id/ata-ST6000VN001-2BB186_ZR10H976
disk2=/dev/disk/by-id/ata-ST6000VN001-2BB186_ZR13TWBJ
array=/dev/md/pinas-backup
[[ -b $disk1 && -b $disk2 ]] || fail 'Expected disk identifiers are missing.'
[[ $(readlink -f "$disk1") != "$(readlink -f "$disk2")" ]] || fail 'Disk identifiers resolve to the same disk.'
for spec in "$disk1:ZR10H976" "$disk2:ZR13TWBJ"; do
  disk=${spec%:*}; serial=${spec##*:}
  [[ $(lsblk -dnro SERIAL "$disk" | awk '{$1=$1;print}') == "$serial" ]] || fail "Serial mismatch: $disk"
  [[ $(lsblk -dnro TYPE "$disk") == disk ]] || fail "Not a whole disk: $disk"
  [[ $(lsblk -bdnro SIZE "$disk") == 6001175126016 ]] || fail "Unexpected disk size: $disk"
  while IFS= read -r target; do
    [[ -z $target || $target == /data ]] || fail "Unexpected mount on $disk: $target"
  done < <(lsblk -nrpo MOUNTPOINTS "$disk")
done
[[ ! -e $array ]] || fail "$array already exists; this procedure is not resumable."
mountpoint -q /data || fail '/data is not mounted in its expected old layout.'
[[ $(readlink -f "$(findmnt -nro SOURCE /data)") == "$(readlink -f /dev/data-vg/data-lv)" ]] || fail 'Unexpected /data source.'
[[ $(findmnt -Rnr -o TARGET /data | wc -l) == 1 ]] || fail '/data has nested mounts.'
[[ $(lvs --noheadings -o lv_name data-vg | awk '{$1=$1;print}') == data-lv ]] || fail 'Unexpected logical volumes in data-vg.'
actual_pvs=$(pvs --noheadings -o pv_name --select vg_name=data-vg | awk '{$1=$1;print}' | sort)
expected_pvs=$(printf '%s\n' "$(readlink -f "$disk1")" "$(readlink -f "$disk2")" | sort)
[[ $actual_pvs == "$expected_pvs" ]] || fail 'data-vg does not contain exactly the two approved disks.'

# Verify kernel RAID1 support before removing the existing storage.
modprobe raid1

printf '\nWILL ERASE BOTH DISKS AND ALL OLD /data BACKUPS:\n%s\n%s\n' "$disk1" "$disk2"
printf 'Blade has no independent backup during this rebuild. The SD-card OS is NOT a target.\n'
read -r -p 'Type ERASE PINAS BACKUPS to proceed: ' confirmation < /dev/tty
[[ $confirmation == 'ERASE PINAS BACKUPS' ]] || fail 'Confirmation did not match.'

# Do not automatically undo or retry a partially completed storage rebuild.
trap 'echo "Rebuild stopped. Do not rerun blindly or reboot; report the failed command and current lsblk output." >&2' ERR
# Prevent the old writable share from coming back before endpoint hardening.
systemctl mask --runtime --now samba-smbd.service
# A busy mount fails here, before any LVM deletion. Never use force/lazy unmount.
umount /data
lvremove --yes /dev/data-vg/data-lv
vgremove --yes data-vg
pvremove --yes "$disk1" "$disk2"
wipefs --all "$disk1" "$disk2"

# Whole-disk RAID members are intentional; neither the SD card nor its partitions
# is referenced by any destructive command. No --force or --assume-clean.
mdadm --create "$array" --metadata=1.2 --level=1 --raid-devices=2 \
  --bitmap=internal --name=pinas-backup --run "$disk1" "$disk2"
mkfs.ext4 -L pinas-backup -m 1 "$array"
mount "$array" /data
chmod 0755 /data

printf '\nNew filesystem identifiers:\n'
blkid "$array"
printf '\nNew array state and UUID:\n'
mdadm --detail "$array"
printf '\nMount state:\n'
findmnt /data
printf '\nNEXT: record UUIDs, configure NixOS RAID assembly/mount, and let initial sync finish.\n'
printf 'DO NOT REBOOT or rebuild with the old LVM mount configuration.\n'
printf 'Samba is runtime-masked only; persistent removal is still required.\n'
