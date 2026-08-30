{ self, inputs, ... }: let
	dotfilesRoot = "/home/james/nix";

	pkgs = import inputs.nixpkgs {
		system = "x86_64-linux";
		config.allowUnfree = true;
		overlays = [ self.overlays.hyprland-glaze-fix ];
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

		services.home-manager.autoExpire = {
			enable = true;
			frequency = "weekly";
			timestamp = "-5 days";
			store.cleanup = true;
			store.options = "--delete-older-than 5d";
		};
	};

	common = [ base ] ++ (with self.homeModules; [
		zsh
		git
		tmux
		nvim
		devtools
		agents
	]);

	desktopApps = with self.homeModules; [
		ghostty
		zen
		discord
		helium
		vlc
		hyprland
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
		"james@laptop" = mkProfile (common ++ desktopApps);
		"james@desktop" = mkProfile (common ++ desktopApps ++ desktopOnly);
		"james@steammachine" = mkProfile (common ++ desktopApps ++ (with self.homeModules; [ steam ]));
	};
}
