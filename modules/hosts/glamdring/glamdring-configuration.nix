{...}: {
  flake.nixosModules.glamdring-configuration = {pkgs, ...}: {
    _module.args.dotfilesRoot = "/home/james/nix";

    networking.hostName = "glamdring";

    services.displayManager.autoLogin = {
      enable = true;
      user = "james";
    };
    services.displayManager.defaultSession = "hyprland-uwsm";

    services.logind.settings.Login.HandlePowerKeyLongPress = "hibernate";
  };
}
