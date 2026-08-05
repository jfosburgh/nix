{ inputs, ... }: {
	perSystem = { system, ... }: {
		_module.args.unfreePkgs = import inputs.nixpkgs {
			inherit system;
			config.allowUnfree = true;
		};
	};

	flake.nixosModules.nix = {
		...
	}: {
		nix = {
			gc = {
				automatic = true;
				dates = "weekly";
				options = "--delete-older-than 14d";
			};

			optimise.automatic = true;

			registry.nixpkgs.flake = inputs.nixpkgs;

			settings = {
				experimental-features = [
					"nix-command"
					"flakes"
				];
				auto-optimise-store = true;
			};
		};

		nixpkgs = {
			config = {
				allowUnfree = true;
				packageOverrides = pkgs: {
					unstable = import inputs.nixpkgs-unstable {
						config = {
							allowUnfree = true;
						};
					};
				};
			};
		};
	};
}
