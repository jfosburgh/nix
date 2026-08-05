{ config, pkgs, lib, ... }:
let dot = "${config.home.homeDirectory}/dotfiles"; in
{
  home.packages = [ pkgs.tmux ];

  home.file.".tmux.conf".source =
    config.lib.file.mkOutOfStoreSymlink "${dot}/tmux/.tmux.conf";

  home.activation.installTpm = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    if [ ! -d "$HOME/.tmux/plugins/tpm" ]; then
      ${pkgs.git}/bin/git clone \
        https://github.com/tmux-plugins/tpm \
        "$HOME/.tmux/plugins/tpm"
    fi
  '';

  programs.zsh = {
    enable = true;

    oh-my-zsh = {
      enable  = true;
      theme   = "robbyrussell";
      plugins = [ "git" "sudo" "copyfile" "copybuffer" ];
    };

    plugins = [
      {
        name = "zsh-autosuggestions";
        src  = pkgs.zsh-autosuggestions;
        file = "share/zsh-autosuggestions/zsh-autosuggestions.zsh";
      }
      {
        name = "fast-syntax-highlighting";
        src  = pkgs.zsh-fast-syntax-highlighting;
        file = "share/zsh/site-functions/fast-syntax-highlighting.plugin.zsh";
      }
    ];

    history = {
      size  = 10000;
      save  = 10000;
      share = true;
    };

    initContent = ''
      source ${dot}/zsh/.config/zsh/envs
      source ${dot}/zsh/.config/zsh/aliases
      source ${dot}/zsh/.config/zsh/functions
    '';
  };

  programs.starship = {
    enable              = true;
    enableZshIntegration = true;
  };

  programs.zoxide = {
    enable              = true;
    enableZshIntegration = true;
  };

  programs.fzf = {
    enable              = true;
    enableZshIntegration = true;
  };
}
