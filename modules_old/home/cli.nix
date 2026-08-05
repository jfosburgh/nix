{ config, pkgs, ... }:
# let dot = "${config.home.homeDirectory}/dotfiles"; in
{
  home.packages = with pkgs; [
    ripgrep
    fd
    fzf
    htop
    eza
    bat

    # Utilities
    tmux
    rsync
    jq
    btop
	nvtopPackages.full
  ];

  # home.file.".local/bin" = {
  #   source    = config.lib.file.mkOutOfStoreSymlink "${dot}/bin/.local/bin";
  #   recursive = true;
  # };
}
