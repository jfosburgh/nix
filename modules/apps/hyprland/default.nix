{
  self,
  inputs,
  ...
}: let
  # Catppuccin Macchiato. Single source of truth for hyprlock, Hyprland window
  # borders, waybar, and mako -- generated into ~/.config/theme/ in several
  # formats since each consumer's config format has its own (or no) include
  # mechanism. Order matches the upstream palette listing.
  macchiato = [
    {
      name = "rosewater";
      hex = "f4dbd6";
    }
    {
      name = "flamingo";
      hex = "f0c6c6";
    }
    {
      name = "pink";
      hex = "f5bde6";
    }
    {
      name = "mauve";
      hex = "c6a0f6";
    }
    {
      name = "red";
      hex = "ed8796";
    }
    {
      name = "maroon";
      hex = "ee99a0";
    }
    {
      name = "peach";
      hex = "f5a97f";
    }
    {
      name = "yellow";
      hex = "eed49f";
    }
    {
      name = "green";
      hex = "a6da95";
    }
    {
      name = "teal";
      hex = "8bd5ca";
    }
    {
      name = "sky";
      hex = "91d7e3";
    }
    {
      name = "sapphire";
      hex = "7dc4e4";
    }
    {
      name = "blue";
      hex = "8aadf4";
    }
    {
      name = "lavender";
      hex = "b7bdf8";
    }
    {
      name = "text";
      hex = "cad3f5";
    }
    {
      name = "subtext1";
      hex = "b8c0e0";
    }
    {
      name = "subtext0";
      hex = "a5adcb";
    }
    {
      name = "overlay2";
      hex = "939ab7";
    }
    {
      name = "overlay1";
      hex = "8087a2";
    }
    {
      name = "overlay0";
      hex = "6e738d";
    }
    {
      name = "surface2";
      hex = "5b6078";
    }
    {
      name = "surface1";
      hex = "494d64";
    }
    {
      name = "surface0";
      hex = "363a4f";
    }
    {
      name = "base";
      hex = "24273a";
    }
    {
      name = "mantle";
      hex = "1e2030";
    }
    {
      name = "crust";
      hex = "181926";
    }
  ];
in {
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

    programs.hyprlock.enable = true;

    xdg.portal.extraPortals = [pkgs.xdg-desktop-portal-gtk];

    services.gvfs.enable = true;
    services.udev.packages = [pkgs.swayosd];

    # GNOME/KDE launch ibus themselves; other desktops (including Hyprland) get it
    # via this XDG autostart entry, which nags about not being a "real" desktop
    # session under Wayland. Shadow it (earlier in XDG_CONFIG_DIRS than the
    # package-provided one) to skip it under Hyprland too.
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
    lib,
    config,
    dotfilesRoot,
    ...
  }: let
    color = name: (lib.findFirst (c: c.name == name) null macchiato).hex;
  in {
    home.packages = with pkgs; [
      hyprpaper
      hyprsunset
      hyprshot
      waybar
      swayosd
      mako
      nautilus
      cliphist
      wl-clipboard
      bluetui
      wiremix
      pamixer
      quickshell

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
    ];

    fonts.fontconfig.enable = true;

    # bluetui and wiremix are TUI-only tools nixpkgs ships with no .desktop
    # file, so they're invisible to anything reading DesktopEntries (like the
    # quickshell launcher). terminal = true gets them the floating-terminal
    # treatment shell.qml gives Terminal=true entries.
    xdg.desktopEntries.bluetui = {
      name = "Bluetui";
      genericName = "Bluetooth Manager";
      exec = "bluetui";
      terminal = true;
      categories = ["System" "Network"];
    };

    xdg.desktopEntries.wiremix = {
      name = "Wiremix";
      genericName = "Audio Mixer";
      exec = "wiremix";
      terminal = true;
      categories = ["System" "AudioVideo"];
    };

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

    xdg.configFile.quickshell.source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/quickshell";

    xdg.configFile.waybar.source =
      config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/waybar";

    xdg.configFile."theme/macchiato.conf".text =
      lib.concatMapStringsSep "\n" (c: "\$${c.name} = rgb(${c.hex})\n\$${c.name}Alpha = ${c.hex}\n") macchiato;

    xdg.configFile."theme/macchiato.lua".text =
      "return {\n"
      + lib.concatMapStringsSep "\n" (c: "  ${c.name} = \"rgb(${c.hex})\",") macchiato
      + "\n}\n";

    xdg.configFile."theme/macchiato.css".text =
      lib.concatMapStringsSep "\n" (c: "@define-color ${c.name} #${c.hex};") macchiato
      + "\n";

    # mako's config format has no include directive, so it's fully generated
    # rather than templated in place like the others.
    xdg.configFile."mako/config".text = ''
      # Colors
      background-color=#${color "base"}
      text-color=#${color "text"}
      border-color=#${color "mauve"}
      border-radius=4
      progress-color=over #${color "surface0"}

      default-timeout=5000

      [urgency=high]
      border-color=#${color "peach"}
    '';
  };
}
