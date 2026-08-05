{ ... }: {
  imports = [
    ./hardware.nix
    ../../modules/nixos/core.nix
    ../../modules/nixos/desktop.nix
    ../../modules/nixos/gaming.nix
    ../../modules/nixos/users.nix
    ../../modules/nixos/nvidia-1080ti.nix
    ../../modules/nixos/kanata.nix
	# ../../modules/nixos/keyd.nix
    ../../modules/nixos/wm/niri.nix
  ];

  networking.hostName = "glamdring";
}
