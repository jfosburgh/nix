{ ... }: {
	flake.nixosModules.greetd-autologin = { sessionCommand, ... }: {
		services.greetd.restart = true;

		services.greetd.settings.initial_session.command = sessionCommand;
	};
}
