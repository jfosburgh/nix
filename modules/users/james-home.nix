{ self, inputs, ... }: let
	dotfilesRoot = "/home/james/nix";

	pkgs = import inputs.nixpkgs {
		system = "x86_64-linux";
		config.allowUnfree = true;
		overlays = [ inputs.niri.overlays.niri ];
	};

	base = { ... }: {
		home.username = "james";
		home.homeDirectory = "/home/james";
		home.stateVersion = "26.05";
		programs.home-manager.enable = true;

		home.sessionVariables = {
			EDITOR = "nvim";
			VISUAL = "nvim";
			PAGER = "less";
		};
	};

	common = [ base ] ++ (with self.homeModules; [
		zsh
		git
		tmux
		nvim
		devtools
		ai
	]);

	graphical = with self.homeModules; [
		noctalia
		ghostty
		niri
		zen
		discord
		browsers
	];

	desktopOnly = with self.homeModules; [
		vintagestory
	];

	mkProfile = modules: inputs.home-manager.lib.homeManagerConfiguration {
		inherit pkgs modules;
		extraSpecialArgs = { inherit dotfilesRoot; };
	};
in {
	flake.homeConfigurations = {
		"james@headless" = mkProfile common;
		"james@laptop" = mkProfile (common ++ graphical);
		"james@desktop" = mkProfile (common ++ graphical ++ desktopOnly);
	};
}
