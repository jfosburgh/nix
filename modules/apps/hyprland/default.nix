{
  self,
  inputs,
  ...
}: {
  flake.overlays.hyprland-glaze-fix = final: prev: {
    hyprland = prev.hyprland.override {
      glaze = prev.glaze.overrideAttrs (_: {
        version = "7.2.0";
        src = prev.fetchFromGitHub {
          owner = "stephenberry";
          repo = "glaze";
          tag = "v7.2.0";
          hash = "sha256-f3NVRi3SXKo42hn0WCw7JsOK3EkdOVJIcuzhPorKjFY=";
        };
      });
    };
  };

  flake.nixosModules.hyprland = {
    pkgs,
    lib,
    config,
    ...
  }: {
    nixpkgs.overlays = [self.overlays.hyprland-glaze-fix];

    programs.hyprland.enable = true;
    programs.hyprland.withUWSM = true;

    xdg.portal.extraPortals = [pkgs.xdg-desktop-portal-gtk];

    services.gvfs.enable = true;

    nix.settings = {
      extra-substituters = ["https://noctalia.cachix.org"];
      extra-trusted-public-keys = ["noctalia.cachix.org-1:pCOR47nnMEo5thcxNDtzWpOxNFQsBRglJzxWPp3dkU4="];
    };

    environment.etc."xdg/autostart/ibus-daemon.desktop" =
      lib.mkIf
      (config.i18n.inputMethod.enable && config.i18n.inputMethod.type == "ibus")
      {
        text = ''
          [Desktop Entry]
          Name=IBus
          Type=Application
          Exec=${config.i18n.inputMethod.package}/bin/ibus-daemon --daemonize --xim
          NotShowIn=GNOME;KDE;Hyprland;
        '';
      };
  };

  flake.homeModules.hyprland = {
    pkgs,
    config,
    dotfilesRoot,
    ...
  }: {
    imports = [inputs.noctalia.homeModules.default];

    programs.noctalia = {
      enable = true;
      systemd.enable = true;

      settings = {
        theme = {
          mode = "dark";
          source = "builtin";
          builtin = "Catppuccin";
        };

        wallpaper = {
          enabled = true;
          default.path = "${config.home.homeDirectory}/.config/backgrounds/default";
        };
      };
    };

    home.packages = with pkgs; [
      nautilus

      inputs.hyprland-preview-share-picker.packages.x86_64-linux.default

      nerd-fonts.iosevka-term
      nerd-fonts.symbols-only

      (writeShellApplication {
        name = "launch-floating-terminal";
        runtimeInputs = [ghostty];
        text = builtins.readFile ./scripts/launch-floating-terminal;
      })

      (writeShellApplication {
        name = "launch-floating-terminal-keepalive";
        runtimeInputs = [ghostty uwsm];
        text = builtins.readFile ./scripts/launch-floating-terminal-keepalive;
      })

      (writeShellApplication {
        name = "hyprpolkitagent";
        text = "exec ${hyprpolkitagent}/libexec/hyprpolkitagent";
      })

      (writeShellApplication {
        name = "nix-search-shell";
        runtimeInputs = [nix-search-tv fzf];
        text = builtins.readFile ./scripts/nix-search-shell;
      })

      # Driven by theme.templates.user.keyboard_backlight's post_hook in
      # noctalia-settings.toml.
      (writeShellApplication {
        name = "keyboard-backlight-sync";
        runtimeInputs = [config.programs.noctalia.package];
        text = builtins.readFile ./scripts/keyboard-backlight-sync;
      })
    ];

    fonts.fontconfig.enable = true;

    home.pointerCursor = {
      enable = true;
      package = pkgs.bibata-cursors;
      name = "Bibata-Original-Classic";
      size = 16;
      hyprcursor.enable = true;
    };

    xdg.configFile.hypr.source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/config";

    xdg.configFile."backgrounds/default".source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/backgrounds/default";

    xdg.configFile."noctalia/templates/keyboard-backlight-mode.tmpl".source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/keyboard-backlight-mode.tmpl";

    xdg.stateFile."noctalia/settings.toml".source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/noctalia-settings.toml";
  };
}
