{...}: {
  flake.homeModules.nvim = {
    pkgs,
    lib,
    config,
    dotfilesRoot,
    ...
  }: {
    programs.neovim.enable = true;

    # nvim-treesitter compiles its own parsers, so it needs a compiler.
    # Everything else project-specific (LSPs, formatters, toolchains) comes
    # from devenv and is enabled per-repo via exrc. The exceptions below are
    # for filetypes commonly edited outside of any devenv repo (including
    # this nix config itself).
    home.packages = with pkgs; [
      tree-sitter
      gcc

      lua-language-server
      stylua

      nil
      alejandra

      vscode-langservers-extracted # jsonls
      yaml-language-server
      marksman

      bash-language-server
      shellcheck
      shfmt

      hyprls

      prettier
    ];

    xdg.configFile.nvim.source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/nvim/config";

    xdg.configFile."nvim/init.lua".enable = lib.mkForce false;
  };
}
