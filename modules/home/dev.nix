{ config, pkgs, ... }:
let dot = "${config.home.homeDirectory}/dotfiles"; in
{
  home.packages = with pkgs; [
    # TUIs
    neovim
    lazygit
    claude-code

    # Compilers / toolchains
    clang
    llvm

    # LSPs
    lua-language-server
    tree-sitter
	nixd

    # Docs
    man-pages
    man-db

	# Nix Utils
	devenv
  ];

  xdg.configFile."nvim".source =
    config.lib.file.mkOutOfStoreSymlink "${dot}/nvim/.config/nvim";
}
