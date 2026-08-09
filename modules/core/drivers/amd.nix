{ ... }: {
	flake.nixosModules.amd-gpu = { config, pkgs, ... }: {
		environment.sessionVariables = {
			ELECTRON_OZONE_PLATFORM_HINT = "wayland";
		};

		hardware = {
			graphics = {
				enable = true;
				enable32Bit = true;
			};
		};
	};
}
