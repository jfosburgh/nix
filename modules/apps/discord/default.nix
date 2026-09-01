{ ... }: {
	flake.homeModules.discord = { pkgs, ... }: {
		home.packages = [
			(pkgs.discord.override { withVencord = true; })
		];
	};
}
