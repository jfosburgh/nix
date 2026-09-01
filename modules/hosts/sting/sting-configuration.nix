{...}: {
  flake.nixosModules.sting-configuration = {pkgs, ...}: {
    networking.hostName = "sting";

    boot.binfmt.emulatedSystems = ["aarch64-linux"];

    services.displayManager.autoLogin = {
      enable = true;
      user = "james";
    };
    services.displayManager.defaultSession = "hyprland-uwsm";

    services.xserver.enable = true;
    services.desktopManager.gnome.enable = true;

    security.pam.services.login.fprintAuth = true;
    security.pam.services.sudo.fprintAuth = true;
    security.pam.services.sddm.fprintAuth = true;
    security.pam.services.hyprlock.fprintAuth = true;

    # sddm's login PAM stack substacks "login", so the fprintd rule that
    # actually matters for the login screen lives there. Same structure
    # for sudo/hyprlock. fprintd runs first (sufficient) so touching the
    # reader logs in immediately at any time; without a timeout it blocks
    # indefinitely, so a typed password never got checked until the
    # reader was touched. The timeout bounds that: after 5s with no scan,
    # it falls through to the password check.
    security.pam.services.login.rules.auth.fprintd.settings.timeout = 5;
    security.pam.services.sudo.rules.auth.fprintd.settings.timeout = 5;
    security.pam.services.hyprlock.rules.auth.fprintd.settings.timeout = 5;

    users.users.work = {
      isNormalUser = true;
      description = "work";
      extraGroups = ["networkmanager" "wheel"];
      shell = pkgs.zsh;
      initialPassword = "changeme";
    };
  };
}
