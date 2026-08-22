{ ... }: {
	flake.nixosModules.greetd-autologin = { config, ... }: {
		services.greetd.restart = true;

		services.greetd.settings.initial_session.command =
			"${config.programs.niri.package}/bin/niri --session --config /etc/niri/config.kdl";
	};
}
