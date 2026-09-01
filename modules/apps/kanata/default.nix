{...}: {
  flake.nixosModules.kanata = {...}: {
    boot.kernelModules = ["uinput"];

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
      Restart = "on-failure";
      RestartSec = "5s";
    };

    services.kanata = {
      enable = true;

      keyboards.internalKeyboard = {
        devices = [];
        configFile = ./kanata.kbd;
      };
    };
  };
}
