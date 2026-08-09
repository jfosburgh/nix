{ self, ... }: {
	flake.nixosModules.graphical = { pkgs, ... }: {
		imports = with self.nixosModules; [
			core
			power
			audio
			bluetooth
			kanata
			niri
			# noctalia
			fonts
			ghostty
			zen
			discord
		];

		environment.systemPackages = [ 
			pkgs.chromium
			pkgs.vlc
		];
	};
}
