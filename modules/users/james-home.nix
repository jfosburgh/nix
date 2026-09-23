{
  self,
  inputs,
  ...
}: let
  dotfilesRoot = "/home/james/nix";

  mkPkgs = system: self.legacyPackages.${system};

  base = {...}: {
    home.username = "james";
    home.homeDirectory = "/home/james";
    home.stateVersion = "26.05";
    programs.home-manager.enable = true;

    home.sessionVariables = {
      EDITOR = "nvim";
      VISUAL = "nvim";
      PAGER = "less";
    };

    services.home-manager.autoExpire = {
      enable = true;
      frequency = "weekly";
      timestamp = "-5 days";
      store.cleanup = true;
      store.options = "--delete-older-than 5d";
    };
  };

  common =
    [base]
    ++ (with self.homeModules; [
      zsh
      git
      tmux
      nvim
      devtools
      agents
      direnv
      yazi
    ]);

  desktopApps =
    (with self.homeModules; [
      ghostty
      zen
      discord
      helium
      vlc
      imv
      hyprland
      localsend
      beancount
    ])
    ++ [
      ({...}: {
        # Without this, opening an image (e.g. from yazi or a file manager)
        # falls through to whichever .desktop file claims image/* first --
        # here that was helium (the browser), not an actual image viewer.
        xdg.mimeApps = {
          enable = true;
          defaultApplications = let
            imv = "imv.desktop";
            imageMimeTypes = [
              "image/avif"
              "image/bmp"
              "image/gif"
              "image/heif"
              "image/jpeg"
              "image/jxl"
              "image/png"
              "image/qoi"
              "image/svg+xml"
              "image/tiff"
              "image/webp"
            ];
          in
            builtins.listToAttrs (map (mime: {
                name = mime;
                value = imv;
              })
              imageMimeTypes);
        };
      })
    ];

  desktopOnly = with self.homeModules; [
    vintagestory
  ];

  mkProfile = {
    modules,
    system ? "x86_64-linux",
  }:
    inputs.home-manager.lib.homeManagerConfiguration {
      pkgs = mkPkgs system;
      inherit modules;
      extraSpecialArgs = {inherit dotfilesRoot;};
    };
in {
  flake.homeConfigurations = {
    "james@headless" = mkProfile {modules = common;};
    "james@pinas" = mkProfile {
      modules = common;
      system = "aarch64-linux";
    };
    "james@laptop" = mkProfile {modules = common ++ desktopApps;};
    "james@desktop" = mkProfile {modules = common ++ desktopApps ++ desktopOnly;};
    "james@steammachine" = mkProfile {modules = common ++ desktopApps ++ (with self.homeModules; [steam]);};
  };
}
