{ ... }: {
	flake.nixosModules.glamdring-configuration = { config, pkgs, ... }: {
		networking.hostName = "glamdring";

		services.greetd.settings.default_session = {
			command = "${config.programs.niri.package}/bin/niri --session --config ${./config.kdl}";
			user = "james";
		};

		# Host-specific extra users 

		# users.users.<username> = {
		# 	isNormalUser = true;
		# 	description = "<username>";
		# 	extraGroups = [ "networkmanager" ];
		# 	shell = pkgs.zsh;
		# };
	};
}
