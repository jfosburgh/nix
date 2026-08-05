{ moduleWithSystem, ... }: {
	flake.nixosModules.vintagestory = moduleWithSystem ({
		pkgs, ...
	}: {
		environment.systemPackages = [
			pkgs.vintagestory
		];
	});
}
