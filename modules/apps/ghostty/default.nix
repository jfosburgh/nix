{ ... }: {
	flake.nixosModules.ghostty = { pkgs, ... }: {
		environment.systemPackages = [ pkgs.ghostty ];
	};

	# TODO: see if this can be fixed
	flake.homeModules.ghostty = { ... }: {
		xdg.configFile."ghostty/config".source = ./config;
		xdg.configFile."ghostty/themes/catppuccin-mocha.conf".source = ./catppuccin-mocha.conf;
	};
}
