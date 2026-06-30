{ pkgs, inputs, ... }: {
  imports = [
    inputs.niri.homeModules.niri
  ];

  home.packages = with pkgs; [
    ghostty
    fuzzel
    waybar
    mako
    swaybg
    wl-clipboard
  ];

  home.sessionVariables = {
    NIXOS_OZONE_WL = "1";
    MOZ_ENABLE_WAYLAND = "1";
    XDG_CURRENT_DESKTOP = "niri";
    XDG_SESSION_TYPE = "wayland";
    TERMINAL = "ghostty";
  };

  programs.niri.enable = true;
  programs.niri.settings = {
    input = {
      keyboard.xkb.layout = "us";
      touchpad = {
        tap = true;
        dwt = true; 
      };
    };

    layout = {
      gaps = 12;
      default-column-width = { proportion = 0.5; };
      struts = {
        top = 40; 
      };
    };

    spawn-at-startup = [
      { command = [ "waybar" ]; }
      { command = [ "mako" ]; }
      { command = [ "swaybg" "-m" "fill" "-i" "/path/to/your/wallpaper.jpg" ]; } 
    ];

    binds = with programs.niri.settings.actions; {
      "Mod+Return" = spawn "ghostty";
      "Mod+D" = spawn "fuzzel";
      "Mod+Q" = close-window;
      "Mod+Shift+E" = quit;

      "Mod+H" = focus-column-left;
      "Mod+L" = focus-column-right;
      "Mod+J" = focus-window-or-workspace-down;
      "Mod+K" = focus-window-or-workspace-up;

      "Mod+Shift+H" = move-column-left;
      "Mod+Shift+L" = move-column-right;
      "Mod+Shift+J" = move-window-down-or-workspace-down;
      "Mod+Shift+K" = move-window-up-or-workspace-up;

      "Mod+R" = switch-preset-column-width;
      "Mod+F" = maximize-column;
      "Mod+Shift+F" = fullscreen-window;
    };

    window-rules = [
      {
        matches = [{ app-id = "firefox"; }];
        open-maximized = true;
      }
    ];
  };

  programs.ghostty = {
    enable = true;
    enableZshIntegration = true;
    settings = {
      theme = "catppuccin-macchiato";
      font-family = "monospace";
      font-size = 11;
      window-background-opacity = 0.95;
      window-padding-x = 8;
      window-padding-y = 8;
      gtk-titlebar = false;
    };
  };
}
