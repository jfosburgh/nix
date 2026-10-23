{...}: {
  flake.nixosModules.pinas-configuration = {pkgs, ...}: {
    boot.loader.grub.enable = false;
    boot.loader.generic-extlinux-compatible.enable = true;

    networking.hostName = "pinas";

    networking.useNetworkd = true;
    systemd.network.enable = true;
    systemd.network.networks."10-wired" = {
      matchConfig.Name = "eth*";
      networkConfig.DHCP = "yes";
    };

    services.openssh = {
      enable = true;
      settings = {
        PasswordAuthentication = true;
        PermitRootLogin = "no";
      };
    };

    zramSwap.enable = true;
    systemd.oomd.enable = true;

    boot.swraid = {
      enable = true;
      mdadmConf = ''
        ARRAY /dev/md/pinas-backup metadata=1.2 UUID=6cb48734:a83974e0:7525ec7e:07af97ca
        PROGRAM ${pkgs.writeShellScript "pinas-raid-notify" ''
          exec ${pkgs.util-linux}/bin/logger -t mdadm -- "$@"
        ''}
      '';
    };

    fileSystems."/data" = {
      device = "/dev/disk/by-uuid/0e549dd2-041c-42d1-b760-d42f1bb1d2e8";
      fsType = "ext4";
      # Keep remote administration available if the backup array cannot mount.
      # Backup services must separately require and verify the real /data mount.
      options = ["defaults" "nofail" "x-systemd.device-timeout=60s"];
    };

    # No writable file share on the dedicated backup target.
    services.samba.enable = false;

    services.smartd = {
      enable = true;
      autodetect = false;
      # Monitor health only: do not schedule self-tests during initial RAID sync.
      devices = map (serial: {
        device = "/dev/disk/by-id/ata-ST6000VN001-2BB186_${serial}";
        options = "-a -n standby,q";
      }) ["ZR10H976" "ZR13TWBJ"];
    };

    environment.systemPackages = with pkgs; [
      git
      vim
      rsync
      restic
      mdadm
      smartmontools
    ];

    nix.settings.trusted-users = ["root" "james"];

    services.journald.settings.Journal.SystemMaxUse = "50M";

    system.stateVersion = "25.11";
  };
}
