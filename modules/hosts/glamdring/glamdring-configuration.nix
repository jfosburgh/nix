{...}: {
  flake.nixosModules.glamdring-configuration = {
    pkgs,
    lib,
    ...
  }: {
    _module.args.dotfilesRoot = "/home/james/nix";

    networking.hostName = "glamdring";

    services.greetd.settings.initial_session = {
      command = "${lib.getExe' pkgs.uwsm "uwsm"} start -e -D Hyprland hyprland.desktop";
      user = "james";
    };

    services.logind.settings.Login.HandlePowerKeyLongPress = "hibernate";
  };
}
