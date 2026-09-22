{self, ...}: {
  flake.nixosModules.sting-configuration = {pkgs, ...}: let
    # SDDM's per-user "remember last session" (via AccountsService) isn't
    # reliable here -- it silently launched hyprland for work's login
    # despite weeks of correctly remembering gnome. Rather than depend on
    # that, make session choice deterministic: a single "Auto" entry that
    # always launches the right desktop for whoever just authenticated,
    # set as the default so the greeter's session dropdown becomes
    # irrelevant as long as it's left untouched.
    sessionDispatch = pkgs.writeShellApplication {
      name = "session-dispatch";
      runtimeInputs = [pkgs.uwsm pkgs.gnome-session pkgs.systemd];
      text = ''
        # The real per-DE session files (gnome.desktop, hyprland-uwsm.desktop)
        # set DesktopNames to the right value so DE-aware apps recognize their
        # environment; this shared entry can't vary that per user, so set
        # XDG_CURRENT_DESKTOP/XDG_SESSION_DESKTOP by hand instead. Both the
        # exported vars (for anything that inherits our env directly) and the
        # systemd --user set-environment call (for anything gnome-shell
        # launches via a systemd scope instead) are covered, since it's not
        # guaranteed which path a given app takes.
        set_desktop() {
          export XDG_CURRENT_DESKTOP="$1"
          export XDG_SESSION_DESKTOP="$2"
          systemctl --user set-environment \
            XDG_CURRENT_DESKTOP="$1" XDG_SESSION_DESKTOP="$2" || true
        }

        case "$(whoami)" in
          work)
            set_desktop "GNOME:Unity" "GNOME"
            exec gnome-session
            ;;
          *)
            set_desktop "Hyprland" "Hyprland"
            exec uwsm start -e -D Hyprland hyprland.desktop
            ;;
        esac
      '';
    };

    autoSession = pkgs.runCommand "auto-session" {passthru.providedSessions = ["auto"];} ''
      mkdir -p $out/share/wayland-sessions
      cat > $out/share/wayland-sessions/auto.desktop <<EOF
      [Desktop Entry]
      Name=Auto
      Comment=Launches Hyprland for james, GNOME for work
      Exec=${sessionDispatch}/bin/session-dispatch
      Type=Application
      DesktopNames=auto
      EOF
    '';
  in {
    imports = [self.nixosModules.vt-fast-switch];

    networking.hostName = "sting";

    boot.binfmt.emulatedSystems = ["aarch64-linux"];

    services.displayManager.sessionPackages = [autoSession];
    services.displayManager.defaultSession = "auto";

    # Base noctalia-greeter setup lives in modules/core/graphical.nix.
    services.displayManager.noctalia-greeter.settings.session.default = "Auto";

    services.xserver.enable = true;
    services.desktopManager.gnome.enable = true;

    # noctalia-greeter's own PAM stack isn't wired to fprintd yet -- password
    # only there for now.
    security.pam.services.login.fprintAuth = true;
    security.pam.services.sudo.fprintAuth = true;
    security.pam.services.hyprlock.fprintAuth = true;

    # Without a timeout, fprintd blocks indefinitely and a typed password
    # never gets checked until the reader is touched.
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
