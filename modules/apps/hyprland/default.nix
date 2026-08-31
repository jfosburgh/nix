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

	flake.nixosModules.hyprland = { pkgs, lib, config, ... }: {
		nixpkgs.overlays = [ self.overlays.hyprland-glaze-fix ];

		programs.hyprland.enable = true;
		programs.hyprland.withUWSM = true;

		programs.hyprlock.enable = true;

		xdg.portal.extraPortals = [ pkgs.xdg-desktop-portal-gtk ];

		services.gvfs.enable = true;
		services.udev.packages = [ pkgs.swayosd ];

		# GNOME/KDE launch ibus themselves; other desktops (including Hyprland) get it
		# via this XDG autostart entry, which nags about not being a "real" desktop
		# session under Wayland. Shadow it (earlier in XDG_CONFIG_DIRS than the
		# package-provided one) to skip it under Hyprland too.
		environment.etc."xdg/autostart/ibus-daemon.desktop" = lib.mkIf
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

	flake.homeModules.hyprland = { pkgs, config, dotfilesRoot, ... }: {
		home.packages = with pkgs; [
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

			(writeShellApplication {
				name = "hyprpolkitagent";
				text = "exec ${hyprpolkitagent}/libexec/hyprpolkitagent";
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
