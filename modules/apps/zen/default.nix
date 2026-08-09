{ moduleWithSystem, ... }: {
	flake.nixosModules.zen = moduleWithSystem ({ inputs', ... }: {
		environment.systemPackages = [
			inputs'.zen-browser.packages.default
		];
	});
}
