{ self, ... }: {
	flake.nixosModules.core = {
		pkgs,
		...
	}: let
		modules = with self.nixosModules; [
			boot
			locale
			network
			nix
			power
		];
	in {
		imports = 
			[
				/etc/nixos/hardware-configuration.nix
			]
			++ modules;

		services = {
		};

		environment.systemPackages = with pkgs; [
			bash
			curl
			git
			home-manager
			vim
			wget
		];

		system.stateVersion = "26.05"; 
	};
}
