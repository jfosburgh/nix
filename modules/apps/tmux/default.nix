{...}: {
  flake.homeModules.tmux = {
    lib,
    pkgs,
    config,
    dotfilesRoot,
    ...
  }: {
    home.packages = [
      pkgs.tmux

      (pkgs.writeShellApplication {
        name = "tmux-sessionizer";
        runtimeInputs = [pkgs.fzf pkgs.tmux];
        text = builtins.readFile ./tmux-sessionizer;
      })
    ];

    home.file.".tmux.conf".source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/tmux/tmux.conf";

    # tmux-plugins/tpm isn't packaged declaratively -- clone it once so
    # `run '~/.tmux/plugins/tpm/tpm'` in tmux.conf has something to run.
    home.activation.installTpm = lib.hm.dag.entryAfter ["writeBoundary"] ''
      if [ ! -d "$HOME/.tmux/plugins/tpm" ]; then
      	${pkgs.git}/bin/git clone \
      		https://github.com/tmux-plugins/tpm \
      		"$HOME/.tmux/plugins/tpm"
      fi
    '';
  };
}
