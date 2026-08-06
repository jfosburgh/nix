{ ... }: {
	flake.homeModules.git = { ... }: {
		programs.git = {
			enable = true;
			settings = {
				user = {
					name = "James Fosburgh";
					email = "jwfosburgh@gmail.com";
				};

				extraConfig = {
					init.defaultBranch = "main";
					pull.rebase = true;
				};
			};
		};

		programs.lazygit.enable = true;
	};
}
