{ pkgs, config, inputs, ... }:
  let dot = "${config.home.homeDirectory}/dotfiles"; in
{
  imports = [
    inputs.noctalia.homeModules.default
  ];

  home.packages = with pkgs; [
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

  xdg.configFile = {
    "niri".source = config.lib.file.mkOutOfStoreSymlink "${dot}/niri/.config/niri";
  };

  programs.noctalia = {
	enable = true;
	settings = {
	  theme = {
	    mode = "dark";
		source = "builtin";
		buildin = "Catppuccin";
	  };

	  wallpaper = {
	    enabled = true;
		default.path = "/home/james/.config/backgrounds/default";
	  };
	};
  };
}
