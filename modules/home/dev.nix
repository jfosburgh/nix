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
    pyright
    ruff
    rust-analyzer
    tree-sitter
    glslang
    shader-slang
	nixd

    # Docs
    man-pages
    man-db
  ];

  xdg.configFile."nvim".source =
    config.lib.file.mkOutOfStoreSymlink "${dot}/nvim/.config/nvim";
}
