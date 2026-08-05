{ inputs, self, ... }: {
	flake.nixosConfigurations.glamdring = inputs.nixpkgs.libs.nixosSystem {
		modules = with self.nixosModules; [
			core
			glamdring-configuration
			nvidia-1080ti
		];
	};
}
