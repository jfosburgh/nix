{ inputs, ... }: {
	flake.nixosModules.noctalia = { ... }: {
		imports = [ inputs.noctalia.nixosModules.default ];

		programs.noctalia.enable = true;
	};

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

				wallpaper = {
					enabled = true;
					default.path = ./wallpaper.jpg;
				};
			};
		};
	};
}
