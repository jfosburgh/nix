{...}: {
  flake.nixosModules.power = {lib, ...}: {
    services = {
      power-profiles-daemon.enable = true;
      upower.enable = true;
    };

    services.logind.settings.Login.HandlePowerKey = lib.mkDefault "suspend-then-hibernate";
  };
}
