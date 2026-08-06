{ ... }: {
	flake.nixosModules.discord = { pkgs, ... }: {
		environment.systemPackages = [
			(pkgs.discord.override { withVencord = true; })
		];
	};
}
