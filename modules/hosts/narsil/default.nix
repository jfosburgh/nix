{ inputs, self, ... }: {
	flake.nixosConfigurations.narsil = inputs.nixpkgs.lib.nixosSystem {
		system = "x86_64-linux";
		modules = with self.nixosModules; [
			graphical
			narsil-configuration
			narsil-hardware
			amd-gpu
			james
			steam
			ai
			greetd-autologin
			greetd-tuigreet
		];
	};
}
