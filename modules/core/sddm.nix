{ ... }: {
	flake.nixosModules.sddm = { pkgs, ... }: {
		environment.systemPackages = [
			(pkgs.catppuccin-sddm.override {
				flavor = "macchiato";
				accent = "mauve";
				font = "IosevkaTerm Nerd Font";
				fontSize = "14";
			})
		];

		services.displayManager.sddm = {
			enable = true;
			wayland.enable = true;
			theme = "catppuccin-macchiato-mauve";
			package = pkgs.kdePackages.sddm;
		};
	};
}
