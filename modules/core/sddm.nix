{ ... }: {
	flake.nixosModules.sddm = { pkgs, ... }: {
		environment.systemPackages = [
			(pkgs.catppuccin-sddm.override {
				flavor = "macchiato";
				accent = "mauve";
				font = "IosevkaTerm Nerd Font";
				fontSize = "14";
				background = "/home/james/.config/backgrounds/default";
			})
			pkgs.catppuccin-cursors.macchiatoMauve
		];

		services.displayManager.sddm = {
			enable = true;
			wayland.enable = true;
			wayland.compositor = "kwin";
			theme = "catppuccin-macchiato-mauve";
			package = pkgs.kdePackages.sddm;
			settings.Theme = {
				CursorTheme = "catppuccin-macchiato-mauve-cursors";
				CursorSize = 24;
			};
		};
	};
}
