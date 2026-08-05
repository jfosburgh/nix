{ config, pkgs, inputs, ... }:
let
  dot    = "${config.home.homeDirectory}/dotfiles";
  system = pkgs.stdenv.hostPlatform.system;
in
{
  home.packages = with pkgs; [
    # Browsers
    inputs.helium.packages.${system}.default
    chromium

	# Terminal Emulators
    ghostty

	# CLI Utilities
    wiremix
    bluetui

    # GUI Applications
    vlc
    (discord.override {
        withVencord = true;
    })
  ];

  xdg.configFile = {
    "ghostty".source     = config.lib.file.mkOutOfStoreSymlink "${dot}/ghostty/.config/ghostty";
    "backgrounds".source = config.lib.file.mkOutOfStoreSymlink "${dot}/backgrounds/.config/backgrounds";
  };
}
