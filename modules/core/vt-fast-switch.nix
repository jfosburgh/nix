{...}: {
  # For hosts with two users sharing a seat (james, work): a second greeter
  # on VT2 runs alongside the primary one on VT1, so each user's session
  # lives on its own VT permanently -- switching is a chvt, never a logout.
  flake.nixosModules.vt-fast-switch = {
    pkgs,
    lib,
    config,
    ...
  }: {
    environment.systemPackages = [
      (pkgs.writeShellApplication {
        name = "switch-session";
        runtimeInputs = [pkgs.systemd pkgs.gawk pkgs.coreutils];
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
            case "$(cat /sys/class/tty/tty0/active)" in
              tty1) chvt 2 ;;
              *) chvt 1 ;;
            esac
          fi
        '';
      })
    ];

    # loginctl activate needs no privilege escalation (polkit's allow_active);
    # chvt does. CAP_SYS_TTY_CONFIG for the VT-switch ioctl, CAP_DAC_OVERRIDE
    # to open /dev/tty0 (mode 0600, root:root).
    security.wrappers.chvt = {
      owner = "root";
      group = "root";
      capabilities = "cap_sys_tty_config,cap_dac_override+ep";
      source = "${pkgs.kbd}/bin/chvt";
    };

    # Mirrors NixOS's own greetd service (nixos/modules/services/
    # display-managers/greetd.nix) but for tty2 instead of the hardcoded
    # tty1, and without initial_session (autologin, if any, is VT1-only).
    systemd.services."autovt@tty2".enable = false;
    systemd.services.greetd-vt2 = {
      unitConfig = {
        Wants = ["systemd-user-sessions.service"];
        # After greetd.service (not just Wants): starting both greeters at
        # the same instant races them for the initially-active VT, which has
        # been observed to leave greetd-vt2's greeter client dead with no
        # self-recovery (session paused mid-init, PAM conversation broken).
        After = ["systemd-user-sessions.service" "getty@tty2.service" "greetd.service"];
        Conflicts = ["getty@tty2.service"];
      };
      serviceConfig = {
        ExecStart = let
          toml = pkgs.formats.toml {};
          settings =
            (builtins.removeAttrs config.services.greetd.settings ["initial_session"])
            // {terminal.vt = 2;};
        in "${lib.getExe config.services.greetd.package} --config ${toml.generate "greetd-vt2.toml" settings}";
        Restart = "on-success";
        IgnoreSIGPIPE = false;
        SendSIGHUP = true;
        TimeoutStopSec = "30s";
        KeyringMode = "shared";
        Type = "idle";
      };
      restartIfChanged = false;
      wantedBy = ["graphical.target"];
    };

    # Logging out doesn't otherwise return focus anywhere -- it just leaves
    # you on that VT's now-empty greeter. Watch for a session ending and, if
    # exactly one graphical session is left, activate it.
    systemd.services.vt-switch-on-logout = {
      after = ["dbus.service"];
      wantedBy = ["graphical.target"];
      serviceConfig = {
        ExecStart = pkgs.writeShellScript "vt-switch-on-logout" ''
          ${lib.getExe' pkgs.dbus "dbus-monitor"} --system \
              "type='signal',interface='org.freedesktop.login1.Manager',member='SessionRemoved'" \
            | grep --line-buffered "member=SessionRemoved" \
            | while read -r _; do
                remaining=$(${lib.getExe' pkgs.systemd "loginctl"} list-sessions --no-legend \
                  | ${lib.getExe pkgs.gawk} '$6 == "user" { print $1 }')
                if [ "$(printf '%s\n' "$remaining" | grep -c .)" = "1" ]; then
                  ${lib.getExe' pkgs.systemd "loginctl"} activate "$remaining"
                fi
              done
        '';
        Restart = "always";
        RestartSec = "1s";
      };
    };
  };
}
