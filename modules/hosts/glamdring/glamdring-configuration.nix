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
	};
}
