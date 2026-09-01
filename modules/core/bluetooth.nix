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
      after = ["bluetooth.service"];
      requires = ["bluetooth.service"];
      wantedBy = ["bluetooth.target"];
      serviceConfig.Type = "oneshot";
      script = ''
        for i in $(seq 1 30); do
        	if ${pkgs.bluez}/bin/bluetoothctl show | grep -q "Powered: yes"; then
        		exit 0
        	fi
        	${pkgs.bluez}/bin/bluetoothctl power on
        	sleep 2
        done
      '';
    };
  };
}
