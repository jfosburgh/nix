{ ... }: {
	flake.homeModules.browsers = { pkgs, ... }: {
		home.packages = [
			pkgs.chromium
			pkgs.vlc
		];
	};
}
