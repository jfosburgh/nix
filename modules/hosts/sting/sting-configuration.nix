{ ... }: {
	flake.nixosModules.sting-configuration = { pkgs, ... }: {
		networking.hostName = "sting";

		boot.binfmt.emulatedSystems = [ "aarch64-linux" ];

		services.displayManager.autoLogin = {
			enable = true;
			user = "james";
		};
		services.displayManager.defaultSession = "hyprland-uwsm";

		services.xserver.enable = true;
		services.desktopManager.gnome.enable = true;

		security.pam.services.login.fprintAuth = true;
		security.pam.services.sudo.fprintAuth = true;
		security.pam.services.sddm.fprintAuth = true;
		security.pam.services.hyprlock.fprintAuth = true;

		users.users.work = {
			isNormalUser = true;
			description = "work";
			extraGroups = [ "networkmanager" "wheel" ];
			shell = pkgs.zsh;
			initialPassword = "changeme";
		};
	};
}
