{ ... }: {
	flake.nixosModules.narsil-configuration = { pkgs, ... }: {
		_module.args.dotfilesRoot = "/home/james/nix";

		networking.hostName = "narsil";

		services.displayManager.autoLogin = {
			enable = true;
			user = "james";
		};
		services.displayManager.defaultSession = "hyprland-uwsm";

		# Host-specific extra users 
		users.users.resin = {
			isNormalUser = true;
			description = "resin";
			extraGroups = [ "networkmanager" ];
			shell = pkgs.zsh;
			initialPassword = "changeme";
		};
	};
}
