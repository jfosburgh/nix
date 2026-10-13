{...}: {
  flake.nixosModules.blade-hardware = {lib, pkgs, modulesPath, ...}: {
    imports = [
      (modulesPath + "/installer/scan/not-detected.nix")
    ];

    boot.initrd.availableKernelModules = [
      "xhci_pci" "ahci" "usbhid" "usb_storage" "sd_mod"
      "mmc_block" "sdhci" "sdhci_pci" "sdhci_acpi"
    ];
    boot.kernelModules = ["kvm-intel"];

    boot.swraid = {
      enable = true;
      mdadmConf = ''
        ARRAY /dev/md/data metadata=1.2 UUID=145fcc4c:b0c74ad6:75a2ada2:a85849b2
        PROGRAM ${pkgs.writeShellScript "raid-notify" ''
          exec ${pkgs.util-linux}/bin/logger -t mdadm -- "$@"
        ''}
      '';
    };

    fileSystems."/data" = {
      device = "/dev/disk/by-uuid/ac33548a-fcbe-46be-a6e7-b7e277a0b846";
      fsType = "ext4";
    };

    # Disko manages only the OS disk; the existing RAID1 is assembled above.
    disko.devices.disk.emmc = {
      type = "disk";
      device = "/dev/mmcblk0";
      content = {
        type = "gpt";
        partitions = {
          ESP = {
            size = "512M";
            type = "EF00";
            content = {
              type = "filesystem";
              format = "vfat";
              mountpoint = "/boot";
              mountOptions = ["fmask=0022" "dmask=0022"];
            };
          };
          root = {
            size = "100%";
            content = {
              type = "filesystem";
              format = "ext4";
              mountpoint = "/";
            };
          };
        };
      };
    };

    swapDevices = [];
    nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
  };
}
