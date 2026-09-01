{self, ...}: {
  flake.nixosModules.core = {pkgs, ...}: let
    modules = with self.nixosModules; [
      bootloader
      locale
      network
      nix
    ];
  in {
    imports = modules;

    environment.systemPackages = with pkgs; [
      bash
      curl
      git
      home-manager
      pciutils
      vim
      wget
    ];

    system.stateVersion = "26.05";

    # Compressed swap in RAM. zstd averages around 3:1, so even a full device
    # occupies roughly a third of RAM. Sized to all of RAM so reclaim never
    # has to spill to a slower disk swap.
    zramSwap = {
      enable = true;
      algorithm = "zstd";
      memoryPercent = 100;
      priority = 100;
    };
  };
}
