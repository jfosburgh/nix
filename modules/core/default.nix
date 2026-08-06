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
		];
	in {
		imports = modules;

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
