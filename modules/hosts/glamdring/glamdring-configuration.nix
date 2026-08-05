{ ... }: {
	flake.nixosModules.glamdringConfiguration = { pkgs, ... }: {
		networking.hostName = "glamdring";
	};
}
