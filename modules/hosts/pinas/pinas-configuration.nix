{ ... }: {
	flake.nixosModules.pinas-configuration = { pkgs, ... }: {
		boot.loader.grub.enable = false;
		boot.loader.generic-extlinux-compatible.enable = true;

		networking.hostName = "pinas";

		networking.useNetworkd = true;
		systemd.network.enable = true;
		systemd.network.networks."10-wired" = {
			matchConfig.Name = "eth*";
			networkConfig.DHCP = "yes";
		};

		services.openssh = {
			enable = true;
			settings = {
				PasswordAuthentication = true;
				PermitRootLogin = "no";
			};
		};

		zramSwap.enable = true;
		systemd.oomd.enable = true;

		fileSystems."/data" = {
			device = "/dev/data-vg/data-lv";
			fsType = "ext4";
			options = [ "defaults" "nofail" ];
		};

		services.samba = {
			enable = true;
			nmbd.enable = false;
			openFirewall = true;
			settings = {
				global = {
					"server string" = "pinas";
					"server role" = "standalone server";
				};
				backups = {
					path = "/data/backups";
					browseable = "yes";
					"read only" = "no";
					"guest ok" = "no";
					"valid users" = "james";
					"create mask" = "0664";
					"directory mask" = "0775";
				};
			};
		};

		systemd.tmpfiles.rules = [ "d /data/backups 0775 james users -" ];

		environment.systemPackages = with pkgs; [
			git
			vim
			rsync
			restic
		];

		nix.settings.trusted-users = [ "root" "james" ];

		services.journald.extraConfig = "SystemMaxUse=50M";

		system.stateVersion = "25.11";
	};
}
