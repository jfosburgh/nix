{ self, ... }: {
	flake.nixosModules.james = { pkgs, ... }: {
		imports = with self.nixosModules; [
			zsh
		];

		users.users.james = {
			isNormalUser = true;
			description = "James";
			extraGroups = [ "networkmanager" "wheel" "video" "audio" "render" ];
			shell = pkgs.zsh;
		};
	};
}
