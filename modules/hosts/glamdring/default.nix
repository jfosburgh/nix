{ inputs, self, ... }: {
	flake.nixosConfigurations.glamdring = inputs.nixpkgs.lib.nixosSystem {
		system = "x86_64-linux";
		modules = with self.nixosModules; [
			graphical
			hyprland
			glamdring-configuration
			glamdring-hardware
			nvidia-1080ti
			james
			steam
			ai
		] ++ [
			inputs.jovian.nixosModules.default
		];
	};
}
