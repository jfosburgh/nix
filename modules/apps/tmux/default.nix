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

    # TPM itself only manages plugins; fetching the plugins tmux.conf declares
    # (catppuccin/tmux, vim-tmux-navigator) is normally a manual `prefix + I`
    # keypress inside a running tmux session. Run its non-interactive
    # installer here too so the actual theme is there after a switch, not
    # just the manager -- without this, tmux quietly falls back to its stock
    # (bright green) status line as if unthemed.
    home.activation.installTmuxPlugins = lib.hm.dag.entryAfter ["installTpm"] ''
      PATH="${pkgs.tmux}/bin:${pkgs.git}/bin:${pkgs.gawk}/bin:${pkgs.gnugrep}/bin:${pkgs.gnused}/bin:${pkgs.coreutils}/bin:$PATH" \
      	"$HOME/.tmux/plugins/tpm/bin/install_plugins" || true
    '';
  };
}
