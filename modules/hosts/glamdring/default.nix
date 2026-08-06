{ inputs, self, ... }: {
	flake.nixosConfigurations.glamdring = inputs.nixpkgs.libs.nixosSystem {
		modules = with self.nixosModules; [
			graphical
			glamdring-configuration
			nvidia-1080ti
			james
			./hardware-configuration.nix
		];
	};
}
