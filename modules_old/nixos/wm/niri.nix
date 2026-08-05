{ pkgs, config, inputs, ... }: {
  nixpkgs.overlays = [ inputs.niri.overlays.niri ];

  programs.niri = {
    enable = true;
	package = pkgs.niri-stable;
  };

  xdg.portal = {
    enable = true;
    config.common.default = [ "gnome" "wlr" ];
    extraPortals = with pkgs; [
      xdg-desktop-portal-gnome
      xdg-desktop-portal-wlr
    ];
  };

  services.greetd = {
    enable = true;
    settings = {
      default_session = {
        command = "${config.programs.niri.package}/bin/niri-session";
        user = "james";
      };
    };
  };

  environment.systemPackages = with pkgs; [
	xwayland-satellite
  ];

  systemd.user.services.niri.enableDefaultPath = false;
}
