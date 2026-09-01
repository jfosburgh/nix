{...}: {
  flake.nixosModules.narsil-configuration = {pkgs, ...}: {
    _module.args.dotfilesRoot = "/home/james/nix";

    networking.hostName = "narsil";

    boot.binfmt.emulatedSystems = ["aarch64-linux"];

    services.displayManager.autoLogin = {
      enable = true;
      user = "james";
    };
    services.displayManager.defaultSession = "hyprland-uwsm";

    # GNOME session, for the work user (see users.users.work below). james
    # stays on Hyprland via the autologin default session above; SDDM's
    # session picker lets work choose GNOME at login.
    services.xserver.enable = true;
    services.desktopManager.gnome.enable = true;

    # Host-specific extra users
    users.users.work = {
      isNormalUser = true;
      description = "work";
      extraGroups = ["networkmanager" "wheel"];
      shell = pkgs.zsh;
      initialPassword = "changeme";
    };
  };
}
