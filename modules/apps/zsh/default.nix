{...}: {
  flake.nixosModules.zsh = {pkgs, ...}: {
    programs.zsh.enable = true;

    # /etc/zshrc otherwise runs a second, full compinit on top of the cached
    # one home-manager installs, costing ~0.12s per shell. enableCompletion
    # stays on so /share/zsh keeps being linked into the system profile.
    programs.zsh.enableGlobalCompInit = false;
  };

  flake.homeModules.zsh = {pkgs, ...}: {
    programs.zsh = {
      enable = true;

      # Full compinit rescans ~3100 completion files, audits them and rewrites
      # the dump on every start; -C trusts the existing dump and skips all of
      # it. The age test's glob qualifier needs extended_glob, so it runs in an
      # anonymous function that scopes the option -- without that the qualifier
      # is literal text, the test is always true, and the slow path always
      # wins. Rescan at most daily so newly installed completions still appear.
      completionInit = ''
        autoload -Uz compinit
        _zc=''${XDG_CACHE_HOME:-$HOME/.cache}/zsh/zcompdump
        if () { emulate -L zsh -o extended_glob; [[ -f $_zc && -z ''${_zc}(#qN.mh+24) ]] }; then
          compinit -C -d $_zc
        else
          [[ -d ''${_zc:h} ]] || mkdir -p ''${_zc:h}
          compinit -d $_zc
          zcompile -R -- $_zc 2>/dev/null
        fi
        unset _zc
      '';

      plugins = [
        {
          name = "zsh-autosuggestions";
          src = pkgs.zsh-autosuggestions;
          file = "share/zsh-autosuggestions/zsh-autosuggestions.zsh";
        }
        {
          name = "fast-syntax-highlighting";
          src = pkgs.zsh-fast-syntax-highlighting;
          file = "share/zsh/site-functions/fast-syntax-highlighting.plugin.zsh";
        }
      ];

      history = {
        size = 10000;
        save = 10000;
        share = true;
      };

      initContent = ''
        source ${./envs}
        source ${./aliases}
        source ${./functions}
        source ${./interactive}
      '';
    };

    programs.starship = {
      enable = true;
      enableZshIntegration = true;
    };

    programs.zoxide = {
      enable = true;
      enableZshIntegration = true;
    };

    programs.fzf = {
      enable = true;
      enableZshIntegration = true;
    };
  };
}
