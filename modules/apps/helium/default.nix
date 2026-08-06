{ moduleWithSystem, ... }: {
	flake.nixosModules.helium = moduleWithSystem ({ inputs', ... }: {
		environment.systemPackages = [
			inputs'.helium.packages.default
		];
	});
}
