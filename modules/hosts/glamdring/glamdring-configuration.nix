{ ... }: {
	flake.nixosModules.glamdring-configuration = { pkgs, ... }: {
		_module.args.dotfilesRoot = "/home/james/nix";

		networking.hostName = "glamdring";

		jovian.steam = {
			enable = true;
			autoStart = true;
			user = "james";
			desktopSession = "hyprland-uwsm";
		};

		services.logind.settings.Login.HandlePowerKeyLongPress = "hibernate";

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
