{ ... }: {
	flake.nixosModules.greetd-tuigreet = { config, pkgs, ... }: {
		services.greetd = {
			useTextGreeter = true;

			settings.default_session.command =
				"${pkgs.tuigreet}/bin/tuigreet --time --remember --remember-session --cmd '${config.programs.niri.package}/bin/niri --session --config /etc/niri/config.kdl'";
		};
	};
}
