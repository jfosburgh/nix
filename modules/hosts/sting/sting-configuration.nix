{...}: {
  flake.nixosModules.sting-configuration = {pkgs, ...}: let
    # If the other user (james <-> work) already has a live session on this
    # seat, jump straight to it -- no greeter, no re-auth. Otherwise fall
    # back to handing the seat to the SDDM greeter. loginctl activate is
    # authorized for any locally-active user (polkit's allow_active), so
    # this needs no privilege escalation.
    switchSession = pkgs.writeShellApplication {
      name = "switch-session";
      runtimeInputs = [pkgs.systemd pkgs.dbus pkgs.gawk];
      text = ''
        other=""
        case "$(whoami)" in
          james) other=work ;;
          work) other=james ;;
        esac

        session=""
        if [[ -n $other ]]; then
          session=$(loginctl list-sessions --no-legend \
            | awk -v u="$other" '$3 == u && $6 == "user" { print $1; exit }')
        fi

        if [[ -n $session ]]; then
          loginctl activate "$session"
        else
          dbus-send --system --print-reply \
            --dest=org.freedesktop.DisplayManager \
            /org/freedesktop/DisplayManager/Seat0 \
            org.freedesktop.DisplayManager.Seat.SwitchToGreeter
        fi
      '';
    };

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
      Name=Auto (per-user)
      Comment=Launches Hyprland for james, GNOME for work
      Exec=${sessionDispatch}/bin/session-dispatch
      Type=Application
      DesktopNames=auto
      EOF
    '';
  in {
    networking.hostName = "sting";

    # Stable path (unlike the store path, survives generation switches)
    # for both james's Hyprland keybind and work's GNOME custom shortcut
    # to invoke.
    environment.systemPackages = [switchSession];

    boot.binfmt.emulatedSystems = ["aarch64-linux"];

    services.displayManager.sessionPackages = [autoSession];
    services.displayManager.defaultSession = "auto";

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
