{...}: {
  flake.homeModules.git = {pkgs, ...}: {
    home.packages = [pkgs.forgejo-cli];

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

    programs.lazygit.enable = true;
  };
}
