{ self, ... }: {
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

	flake.nixosModules.hyprland = { pkgs, ... }: {
		nixpkgs.overlays = [ self.overlays.hyprland-glaze-fix ];

		programs.hyprland.enable = true;
		programs.hyprland.withUWSM = true;

		xdg.portal.extraPortals = [ pkgs.xdg-desktop-portal-gtk ];

		services.greetd.enable = true;
		services.gvfs.enable = true;
		services.udev.packages = [ pkgs.swayosd ];

		environment.sessionVariables = {
			NIXOS_OZONE_WL = "1";
			MOZ_ENABLE_WAYLAND = "1";
			XDG_CURRENT_DESKTOP = "Hyprland";
			XDG_SESSION_TYPE = "wayland";
			TERMINAL = "ghostty";
		};
	};

	flake.homeModules.hyprland = { pkgs, config, dotfilesRoot, ... }: {
		home.packages = with pkgs; [
			hypridle
			hyprlock
			hyprpaper
			hyprsunset
			hyprshot
			rofi
			waybar
			swayosd
			mako
			nautilus
			cliphist
			wl-clipboard
			bluetui
			wiremix
			pamixer

			nerd-fonts.iosevka-term
			nerd-fonts.symbols-only

			(writeShellApplication {
				name = "launch-floating-terminal";
				runtimeInputs = [ ghostty ];
				text = builtins.readFile ./scripts/launch-floating-terminal;
			})

			(writeShellApplication {
				name = "launch-floating-terminal-keepalive";
				runtimeInputs = [ ghostty uwsm ];
				text = builtins.readFile ./scripts/launch-floating-terminal-keepalive;
			})
		];

		fonts.fontconfig.enable = true;

		gtk.enable = true;

		home.pointerCursor = {
			enable = true;
			package = pkgs.catppuccin-cursors.macchiatoMauve;
			name = "catppuccin-macchiato-mauve-cursors";
			size = 24;
			gtk.enable = true;
			hyprcursor.enable = true;
		};

		xdg.configFile.hypr.source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/config";

		xdg.configFile."backgrounds/default".source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/backgrounds/default";

		xdg.configFile.rofi.source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/rofi";

		xdg.configFile.waybar.source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/waybar";

		xdg.configFile.mako.source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/hyprland/mako";
	};
}
