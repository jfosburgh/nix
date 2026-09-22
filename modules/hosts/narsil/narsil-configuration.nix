{self, ...}: {
  flake.nixosModules.narsil-configuration = {
    pkgs,
    lib,
    ...
  }: {
    imports = [self.nixosModules.vt-fast-switch];

    _module.args.dotfilesRoot = "/home/james/nix";

    networking.hostName = "narsil";

    boot.binfmt.emulatedSystems = ["aarch64-linux"];

    # Autologin to Hyprland for james; work picks GNOME manually from the
    # greeter after any later logout.
    services.greetd.settings.initial_session = {
      command = "${lib.getExe' pkgs.uwsm "uwsm"} start -e -D Hyprland hyprland.desktop";
      user = "james";
    };

    services.xserver.enable = true;
    services.desktopManager.gnome.enable = true;

    users.users.work = {
      isNormalUser = true;
      description = "work";
      extraGroups = ["networkmanager" "wheel"];
      shell = pkgs.zsh;
      initialPassword = "changeme";
    };
  };
}
