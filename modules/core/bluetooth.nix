{ ... }: {
	flake.nixosModules.bluetooth = { ... }: {
		hardware.bluetooth = {
			enable = true;
			powerOnBoot = true;
			settings.General.Experimental = true;
		};

		hardware.xpadneo.enable = true;

		services.blueman.enable = true;
	};
}
