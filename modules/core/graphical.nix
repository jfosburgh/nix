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
			helium
			discord
		];

		environment.systemPackages = [ pkgs.vlc ];
	};
}
