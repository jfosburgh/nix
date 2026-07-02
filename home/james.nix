{ pkgs, config, ... }: {
  home.stateVersion = "26.05"; 

  imports = [
  ];

  home.packages = with pkgs; [
  ];

  home.sessionVariables = {
    EDITOR = "nvim";
    VISUAL = "nvim";
    PAGER = "less";
  };

  programs.git = {
    enable = true;
    settings = {
        user = {
            name = "James Fosburgh";
            email = "jwfosburgh@gmail.com";
        };

        extraConfig = {
            init.defaultBranch = "main";
            pull.rebase = true;
        };
    };
  };

  programs.home-manager.enable = true;

  nixpkgs.config.allowUnfree = true;
}
