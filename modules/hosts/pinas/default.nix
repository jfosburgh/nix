{ inputs, self, ... }: {
	flake.nixosConfigurations.pinas = inputs.nixpkgs.lib.nixosSystem {
		system = "aarch64-linux";
		modules = with self.nixosModules; [
			locale
			nix
			james
			tailscale
			pinas-configuration
			pinas-hardware
		];
	};
}
