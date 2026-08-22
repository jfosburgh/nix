{ ... }: {
	flake.nixosModules.greetd-tuigreet = { sessionCommand, pkgs, ... }: {
		services.greetd = {
			useTextGreeter = true;

			settings.default_session.command =
				"${pkgs.tuigreet}/bin/tuigreet --time --remember --remember-session --cmd '${sessionCommand}'";
		};
	};
}
