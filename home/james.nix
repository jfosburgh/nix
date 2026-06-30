{ pkgs, ... }: {
  home.stateVersion = "26.05"; 

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
  ];

  home.sessionVariables = {
    EDITOR = "nvim";
    VISUAL = "nvim";
	TERMINAL = "fallback-terminal-or-tmux";
    PAGER = "less";
  };

  programs.git = {
    enable = true;
    userName = "James Fosburgh";
    userEmail = "jwfosburgh@gmail.com";

    extraConfig = {
      init.defaultBranch = "main";
      pull.rebase = true;
    };
  };

  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;

    shellAliases = {
      ll = "eza -l --icons --git";
      la = "eza -la --icons --git";
      cat = "bat";
      g = "git";
    };

    initExtra = ''
    '';
  };

  programs.starship = {
    enable = true;
    enableZshIntegration = true;
    settings = {
      add_newline = false;
      line_break.disabled = true;
    };
  };

  programs.home-manager.enable = true;
}
