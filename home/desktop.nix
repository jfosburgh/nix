{ pkgs, ... }: {
  imports = [
    ./james.nix
    ../modules/home/wm/niri.nix
    ../modules/home/cli.nix
	../modules/home/desktop-common.nix
	../modules/home/dev.nix
	../modules/home/fonts.nix
	../modules/home/shell.nix
  ];
}
