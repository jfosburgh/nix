{ ... }: {
	flake.nixosModules.bluetooth = { ... }: {
		hardware.bluetooth = {
			enable = true;
			powerOnBoot = true;
			settings.General.Experimental = true;
		};

		hardware.xpadneo.enable = true;
		# xpadneo doesn't blacklist the in-kernel xpad driver on its own; without
		# this, xpad and xpadneo race to bind Xbox controllers, which is what
		# causes them to show up in Steam but hang mid-connect.
		boot.blacklistedKernelModules = [ "xpad" ];

		services.blueman.enable = true;
	};
}
