{ inputs, ... }: {
	flake.nixosModules.niri = {
		pkgs, ...
	}: {
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

		services.greetd.enable = true;

		environment.sessionVariables = {
			NIXOS_OZONE_WL = "1";
			MOZ_ENABLE_WAYLAND = "1";
			XDG_CURRENT_DESKTOP = "niri";
			XDG_SESSION_TYPE = "wayland";
			TERMINAL = "ghostty";
		};

		environment.systemPackages = with pkgs; [
			xwayland-satellite
			wl-clipboard
		];

		systemd.user.services.niri.enableDefaultPath = false;
	};
}
