{ self, inputs, ... }: {
	flake.nixosModules.james = { pkgs, ... }: {
		imports = [ inputs.home-manager.nixosModules.home-manager ] ++ (with self.nixosModules; [
			zsh
		]);

		users.users.james = {
			isNormalUser = true;
			description = "James";
			extraGroups = [ "networkmanager" "wheel" "video" "audio" "render" ];
			shell = pkgs.zsh;
		};

		home-manager = {
			# useGlobalPkgs = true;
			useUserPackages = true;

			users.james = {
				imports = with self.homeModules; [
					zsh
					noctalia
					tmux
					git
					nvim
					devtools
				];

				home.stateVersion = "26.05";

				home.sessionVariables = {
					EDITOR = "nvim";
					VISUAL = "nvim";
					PAGER = "less";
				};

				programs.home-manager.enable = true;

				nixpkgs.config.allowUnfree = true;
			};
		};
	};
}
