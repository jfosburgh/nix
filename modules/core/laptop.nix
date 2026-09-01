{self, ...}: {
  flake.nixosModules.laptop = {...}: {
    imports = with self.nixosModules; [graphical];

    hardware.acpilight.enable = true;
    powerManagement.enable = true;
    services.fprintd.enable = true;

    services.logind.settings.Login = {
      HandleLidSwitch = "suspend-then-hibernate";
      HandleLidSwitchExternalPower = "suspend-then-hibernate";
    };
  };
}
