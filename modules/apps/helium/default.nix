{ inputs, ... }: {
	flake.homeModules.helium = { ... }: {
		home.packages = [
			inputs.helium.packages.x86_64-linux.default
		];
	};
}
