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

          # Template enablement (theme.templates.*) deliberately isn't set
          # here: it lives in the live-editable noctalia-settings.toml below
          # instead, alongside everything else Settings -> Templates toggles.
          # GTK/Qt templates in particular can't be enabled from either
          # place: gtk.enable manages ~/.config/gtk-3.0 as Nix-store
          # symlinks, which a template can't write into (Noctalia's own
          # docs call this out). hyprland.lua's require("noctalia") and
          # modules/apps/ghostty/config's `theme` line are pre-wired to
          # match what the hyprland/ghostty templates would write on first
          # run, so enabling those two lands as a no-op instead of an
          # out-of-band diff to a git-tracked file.
        };

        # Set explicitly rather than left to noctalia's directory-scanning
        # wallpaper picker: that picker (and its thumbnailer) only recognizes
        # files with a known image extension, and this repo's background
        # asset is stored suffix-less (see backgrounds/default) -- it's a
        # real JPEG, just an extensionless one, so the picker can't find it
        # even though direct loading-by-path (used here) doesn't care about
        # the extension at all.
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
    ];

    fonts.fontconfig.enable = true;

    gtk.enable = true;
    gtk.font.name = "IosevkaTerm Nerd Font";

    home.pointerCursor = {
      enable = true;
      package = pkgs.bibata-cursors;
      name = "Bibata-Original-Classic";
      size = 24;
      gtk.enable = true;
      hyprcursor.enable = true;
    };

    xdg.configFile.hypr.source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/config";

    xdg.configFile."backgrounds/default".source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/backgrounds/default";

    # Noctalia's own GUI-writable state -- Settings changes, template
    # enablement, bar/widget layout, lockscreen widget positions -- rather
    # than the declarative programs.noctalia.settings above (which only
    # covers what has no GUI equivalent, e.g. wallpaper path). An
    # out-of-store symlink so Settings keeps writing straight into this
    # repo's copy instead of a Nix-store-immutable one.
    xdg.stateFile."noctalia/settings.toml".source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/noctalia-settings.toml";
  };
}
