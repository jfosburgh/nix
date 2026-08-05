{ ... }: {
	flake.nixosModules.nvidia-1080ti = { config, ... }: {
		hardware = {
			environment.sessionVariables = {
				ELECTRON_OZONE_PLATFORM_HINT = "wayland";
			};

			graphics = {
				enable = true;
				enable32Bit = true;
			};

			nvidia = {
				modesetting.enable = true;
				open = false;
				nvidiaSettings = true;
				package = config.boot.kernelPackages.nvidiaPackages.legacy_580;
			};
		};
	};
}
