{...}: {
  flake.nixosModules.blade-hardware = {lib, modulesPath, ...}: {
    imports = [
      (modulesPath + "/installer/scan/not-detected.nix")
    ];

    boot.initrd.availableKernelModules = [
      "xhci_pci" "ahci" "usbhid" "usb_storage" "sd_mod"
      "mmc_block" "sdhci" "sdhci_pci" "sdhci_acpi"
    ];
    boot.kernelModules = ["kvm-intel"];

    # Only the internal eMMC is managed here. Do not add the SATA data
    # disks until NixOS is installed and their storage layout is decided.
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
