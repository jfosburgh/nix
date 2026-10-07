{...}: {
  flake.nixosModules.bluetooth = {pkgs, ...}: {
    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
      settings.General.Experimental = true;
    };

    hardware.xpadneo.enable = true;
    # xpadneo doesn't blacklist the in-kernel xpad driver on its own; without
    # this, xpad and xpadneo race to bind Xbox controllers, which is what
    # causes them to show up in Steam but hang mid-connect.
    boot.blacklistedKernelModules = ["xpad"];

    services.blueman.enable = true;

    systemd.services.bluetooth-poweron-retry = {
      description = "Retry powering on the Bluetooth adapter";
			after = ["bluetooth.service" "systemd-rfkill.service"];
			wants = ["systemd-rfkill.service"];
			requires = ["bluetooth.service"];
			wantedBy = ["bluetooth.target"];
			serviceConfig = {
				Type = "oneshot";
				TimeoutStartSec = "5min";
			};
			script = ''
				for i in $(seq 1 30); do
					# Restore our power-on-boot policy without touching Wi-Fi. Repeat
					# for adapters that appear late and have saved rfkill state restored.
					${pkgs.util-linux}/bin/rfkill unblock bluetooth || true
					# NixOS scripts use set -e: transient failures must not end the loop.
					${pkgs.coreutils}/bin/timeout 3s ${pkgs.bluez}/bin/bluetoothctl power on || true
					if ${pkgs.coreutils}/bin/timeout 3s ${pkgs.bluez}/bin/bluetoothctl show | grep -q "Powered: yes"; then
						exit 0
					fi
					sleep 2
				done
				echo "Bluetooth adapter did not power on after 30 attempts" >&2
				exit 1
			'';
    };
  };
}
