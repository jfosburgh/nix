{ inputs, self, ... }: {
	flake.nixosConfigurations.glamdring = inputs.nixpkgs.lib.nixosSystem {
		system = "x86_64-linux";
		modules = with self.nixosModules; [
			graphical
			glamdring-configuration
			glamdring-hardware
			amd-gpu
			james
			vintagestory
			steam
			ai
			greetd-autologin
			greetd-tuigreet
		];
	};
}
