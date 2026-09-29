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

    # GTK walks the selected icon theme's full Inherits chain on every
    # window open. Papirus-Dark inherits breeze-dark, a 40MB tree that
    # ships no icon-theme.cache, so each miss became a directory scan --
    # ~1.4s per ghostty window. Adwaita inherits only hicolor.
    dconf.settings."org/gnome/desktop/interface".icon-theme = "Adwaita";

    home.packages = with pkgs; [
      wl-clipboard

      # Kept for noctalia's "papirus-icons" theme template, not for GTK --
      # GTK's icon-theme is Adwaita (see dconf.settings above). Selecting
      # Papirus-Dark here drags in its breeze-dark inherit and costs ~1.4s
      # per window; it is also the only theme installed that carries
      # "starred", which GTK apps now render as a missing icon.
      papirus-icon-theme

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

      (writeShellApplication {
        name = "rbw-menu";
        runtimeInputs = [rbw fzf wl-clipboard];
        text = builtins.readFile ./scripts/rbw-menu;
      })

      # Driven by theme.templates.user.keyboard_backlight's post_hook in
      # noctalia-settings.toml.
      (writeShellApplication {
        name = "keyboard-backlight-sync";
        runtimeInputs = [config.programs.noctalia.package];
        text = builtins.readFile ./scripts/keyboard-backlight-sync;
      })

      # Driven by theme.templates.user.gtk_dark_mode's post_hook in
      # noctalia-settings.toml.
      (writeShellApplication {
        name = "gtk-dark-mode-sync";
        text = builtins.readFile ./scripts/gtk-dark-mode-sync;
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

    xdg.configFile."noctalia/templates/gtk-dark-mode.tmpl".source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/gtk-dark-mode.tmpl";

    xdg.stateFile."noctalia/settings.toml".source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/noctalia-settings.toml";
  };
}
