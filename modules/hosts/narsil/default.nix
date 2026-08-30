{ inputs, self, ... }: {
	flake.nixosConfigurations.narsil = inputs.nixpkgs.lib.nixosSystem {
		system = "x86_64-linux";
		modules = with self.nixosModules; [
			graphical
			hyprland
			narsil-configuration
			narsil-hardware
			amd-gpu
			james
			steam
			llama-cpp
			agents
		];
	};
}
