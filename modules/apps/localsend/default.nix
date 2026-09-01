{ ... }: {
	flake.homeModules.localsend = { pkgs, ... }: {
		home.packages = [ pkgs.localsend ];
	};
}
