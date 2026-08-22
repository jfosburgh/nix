{ ... }: {
	flake.nixosModules.glamdring-configuration = { pkgs, ... }: {
		_module.args.dotfilesRoot = "/home/james/nix";
		_module.args.sessionCommand = "${pkgs.uwsm}/bin/uwsm start -e -D Hyprland hyprland.desktop";

		networking.hostName = "glamdring";

		services.greetd.settings.initial_session.user = "james";

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
