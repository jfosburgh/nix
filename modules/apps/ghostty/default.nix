{ ... }: {
	flake.homeModules.ghostty = { pkgs, config, dotfilesRoot, ... }: {
		home.packages = [ pkgs.ghostty ];

		xdg.configFile."ghostty/config".source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/ghostty/config";
		xdg.configFile."ghostty/themes/catppuccin-mocha.conf".source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/ghostty/catppuccin-mocha.conf";
	};
}
