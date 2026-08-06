{ self, ... }: {
	flake.nixosModules.laptop = { ... }: {
		imports = with self.nixosModules; [ graphical ];

		services.logind.settings.Login = {
			HandleLidSwitch = "suspend";
			HandleLidSwitchExternalPower = "suspend";
			HandlePowerKey = "suspend";
		};
	};
}
