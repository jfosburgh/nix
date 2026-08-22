{ self, ... }: {
	flake.nixosModules.graphical = { ... }: {
		imports = with self.nixosModules; [
			core
			power
			audio
			bluetooth
			kanata
			niri
			fonts
		];
	};
}
