{self, ...}: {
  flake.nixosModules.narsil-strata-mode = {pkgs, lib, ...}: let
    common = builtins.readFile ./scripts/mode-common.sh;
    stopManual = pkgs.writeScriptBin "stop-manual-strata" ''
      #!${pkgs.python312}/bin/python3
      ${builtins.readFile ./scripts/stop-manual-strata.py}
    '';
    worker = pkgs.writeShellApplication {
      name = "narsil-mode-switch";
      runtimeInputs = with pkgs; [coreutils util-linux systemd gawk curl jq stopManual];
      text = common + "\n" + builtins.readFile ./scripts/mode-worker.sh;
    };
    command = pkgs.writeShellApplication {
      name = "narsil-mode";
      # Privilege escalation uses NixOS's /run/wrappers/bin/sudo explicitly;
      # pkgs.sudo is the unprivileged store binary, not the setuid wrapper.
      runtimeInputs = with pkgs; [coreutils systemd];
      text = common + "\n" + builtins.readFile ./scripts/mode-command.sh;
    };
    shortcut = mode: pkgs.writeShellApplication {
      name = "narsil-${mode}";
      text = ''exec ${lib.getExe command} ${mode} "$@"'';
    };
  in {
    environment.systemPackages = [command (shortcut "headless") (shortcut "desktop")];
    environment.etc."narsil-mode".text = lib.mkDefault "desktop\n";

    # Identical in parent and child, so activation never replaces the worker
    # performing the switch. It is not owned by the graphical terminal/session.
    systemd.services."narsil-mode-switch@" = {
      description = "Switch Narsil to %i mode without rebooting";
      unitConfig.IgnoreOnIsolate = true;
      serviceConfig = {
        Type = "oneshot";
        User = "root";
        ExecStart = "${lib.getExe worker} %i";
        TimeoutStartSec = "15min";
        UMask = "0077";
      };
    };

    # Inherit the ordinary system, but offer a separate boot entry. Nothing in
    # the normal desktop generation starts Strata or Narsil's upstream proxy.
    specialisation.strata-server.configuration = {lib, ...}: {
      imports = [self.nixosModules.strata-server];

      system.nixos.tags = ["strata-server"];
      environment.etc."narsil-mode".text = lib.mkForce "headless\n";
      systemd.defaultUnit = "multi-user.target";

      services.displayManager.noctalia-greeter.enable = lib.mkForce false;
      services.greetd.enable = lib.mkForce false;
      services.xserver.enable = lib.mkForce false;
      services.desktopManager.gnome.enable = lib.mkForce false;
      programs.hyprland.enable = lib.mkForce false;
      programs.uwsm.enable = lib.mkForce false;
      systemd.services.greetd.enable = lib.mkForce false;
      systemd.services.greetd-vt2.enable = lib.mkForce false;
      systemd.services.vt-switch-on-logout.enable = lib.mkForce false;

      services.ollama.enable = lib.mkForce false;
      services.pipewire.enable = lib.mkForce false;
      services.pipewire.wireplumber.enable = lib.mkForce false;
      # Keep paired Bluetooth keyboards/mice usable on the headless text console.
      # BlueZ and the adapter power-on retry run independently of the desktop.
      hardware.bluetooth.enable = lib.mkForce true;
      hardware.bluetooth.powerOnBoot = lib.mkForce true;
      services.upower.enable = lib.mkForce false;
      services.power-profiles-daemon.enable = lib.mkForce false;

      # Keep a server awake, but allow the physical button to shut it down.
      services.logind.settings.Login = {
        IdleAction = "ignore";
        HandlePowerKey = lib.mkForce "poweroff";
      };
      systemd.sleep.settings.Sleep = {
        AllowSuspend = false;
        AllowHibernation = false;
        AllowHybridSleep = false;
        AllowSuspendThenHibernate = false;
      };
    };
  };
}
