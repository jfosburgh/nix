{...}: {
  flake.nixosModules.power = {
    lib,
    pkgs,
    ...
  }: {
    services = {
      power-profiles-daemon.enable = true;
      upower.enable = true;
    };

    services.logind.settings.Login.HandlePowerKey = lib.mkDefault "suspend-then-hibernate";

    # gvfsd-fuse mounts (Nautilus network shares, MTP phones) can block in
    # uninterruptible sleep during the kernel's pre-suspend process freeze,
    # silently failing suspend. Lazy-unmount them first, then restart gvfs
    # after wake to bring the mounts back.
    environment.etc."systemd/system-sleep/unmount-fuse".source = pkgs.writeShellScript "unmount-fuse" ''
      case "$1" in
        pre)
          while IFS=' ' read -r _ mountpoint fstype _; do
            case "$fstype" in
              fuse.gvfsd-fuse)
                mountpoint=$(printf '%b' "$mountpoint")
                ${pkgs.fuse3}/bin/fusermount3 -uz "$mountpoint" 2>/dev/null \
                  || ${pkgs.fuse}/bin/fusermount -uz "$mountpoint" 2>/dev/null \
                  || true
                ;;
            esac
          done < /proc/mounts
          ;;
        post)
          # Run in the background: user.slice is still frozen at this point,
          # so a synchronous restart would block the thaw for up to 90s.
          (
            sleep 5
            for uid_dir in /run/user/*; do
              uid=$(basename "$uid_dir")
              if [ -S "$uid_dir/bus" ]; then
                ${pkgs.sudo}/bin/sudo -u "#$uid" env \
                  DBUS_SESSION_BUS_ADDRESS="unix:path=$uid_dir/bus" \
                  XDG_RUNTIME_DIR="$uid_dir" \
                  ${pkgs.systemd}/bin/systemctl --user restart gvfs-daemon.service 2>/dev/null || true
              fi
            done
          ) &
          ;;
      esac
    '';
  };
}
