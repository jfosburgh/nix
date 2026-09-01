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
  };
}
