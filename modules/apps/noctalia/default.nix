{ inputs, ... }: {
	flake.homeModules.noctalia = { ... }: {
		imports = [ inputs.noctalia.homeModules.default ];

		programs.noctalia = {
			enable = true;
			settings = {
				theme = {
					mode = "dark";
					source = "builtin";
					builtin = "Catppuccin";
				};

				# TODO: fix config
				wallpaper = {
					enabled = true;
					default.path = ./wallpaper.jpg;
				};
			};
		};
	};
}
