{ ... }: {
  imports = [
    ./hardware.nix
    ../../modules/nixos/core.nix
    ../../modules/nixos/users.nix
    ../../modules/nixos/nvidia-1080ti.nix
    ../../modules/nixos/wm/niri.nix
  ];

  networking.hostName = "glamdring";

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  system.stateVersion = "26.05"; 
}
