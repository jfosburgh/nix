{ ... }: {
	flake.nixosModules.kanata = { ... }: {
		boot.kernelModules = [ "uinput" ];

		hardware.uinput.enable = true;

		services.udev.extraRules = ''
			KERNEL=="uinput", MODE="0660", GROUP="uinput", OPTIONS+="static_node=uinput"
		'';

		users.groups.uinput = {};

		systemd.services.kanata-internalKeyboard.serviceConfig = {
			SupplementaryGroups = [
				"input"
				"uinput"
			];
		};

		services.kanata = {
			enable = true;
		};
	};
}
