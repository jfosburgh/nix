{...}: {
  flake.nixosModules.blade-backups = {config, lib, pkgs, ...}: let
    cfg = config.services.bladeBackupPreparation;
    prepare = pkgs.writeShellApplication {
      name = "prepare-postgresql-backups";
      runtimeInputs = [
        pkgs.coreutils
        pkgs.util-linux
        pkgs.docker
        config.services.postgresql.package
      ];
      text = builtins.readFile ../../../scripts/prepare-postgresql-backups.sh;
    };
    captureMachine = pkgs.writeScriptBin "capture-machine-recovery"
      ("#!${pkgs.python3}/bin/python3\n" + builtins.readFile ../../../scripts/capture-machine-recovery.py);
    prepareState = pkgs.writeShellApplication {
      name = "prepare-application-state";
      runtimeInputs = [pkgs.coreutils pkgs.findutils pkgs.gnugrep pkgs.util-linux pkgs.rsync pkgs.sqlite pkgs.systemd pkgs.python3 pkgs.openssh];
      text = ''
        export BLADE_CAPTURE_MACHINE_RECOVERY=${lib.getExe captureMachine}
        export BLADE_SSH_HOST_KEYS=${lib.escapeShellArg (builtins.toJSON (map (key: builtins.toString key.path) config.services.openssh.hostKeys))}
      '' + builtins.readFile ../../../scripts/prepare-application-state.sh;
    };
    prepareCoherent = pkgs.writeShellApplication {
      name = "prepare-coherent-applications";
      runtimeInputs = [pkgs.coreutils pkgs.findutils pkgs.gnugrep pkgs.gawk pkgs.util-linux pkgs.rsync pkgs.docker pkgs.systemd pkgs.inetutils config.services.postgresql.package];
      text = builtins.readFile ../../../scripts/prepare-coherent-applications.sh;
    };
    resticClient = pkgs.writeShellApplication {
      name = "pinas-restic";
      runtimeInputs = [pkgs.coreutils pkgs.inetutils pkgs.restic];
      text = builtins.readFile ../../../scripts/pinas-restic.sh;
    };
    uploadCritical = pkgs.writeShellApplication {
      name = "upload-critical";
      runtimeInputs = [pkgs.coreutils pkgs.findutils pkgs.util-linux pkgs.inetutils pkgs.bash];
      text = builtins.readFile ../../../scripts/upload-critical.sh;
    };
    finishStaging = pkgs.writeShellApplication {
      name = "finish-critical-staging";
      runtimeInputs = [pkgs.coreutils pkgs.findutils pkgs.util-linux pkgs.inetutils];
      text = builtins.readFile ../../../scripts/finish-critical-staging.sh;
    };
    backupCritical = pkgs.writeShellApplication {
      name = "backup-critical";
      runtimeInputs = [pkgs.coreutils pkgs.util-linux pkgs.inetutils pkgs.bash];
      text = ''
        export BLADE_PREPARE_STATE=${lib.getExe prepareState}
        export BLADE_PREPARE_COHERENT=${lib.getExe prepareCoherent}
        export BLADE_RESTIC=${lib.getExe resticClient}
        export BLADE_UPLOAD_CRITICAL=${lib.getExe uploadCritical}
        export BLADE_FINISH_STAGING=${lib.getExe finishStaging}
      '' + builtins.readFile ../../../scripts/backup-critical.sh;
    };
    recoverAll = pkgs.writeShellScript "recover-backup-applications" ''
      status=0
      ${lib.getExe prepareState} --recover || status=1
      ${lib.getExe prepareCoherent} --recover || status=1
      exit "$status"
    '';
  in {
    options.services.bladeBackupPreparation.enable = lib.mkEnableOption
      "manual-only database and application-state preparation (no timers or off-host backup)";

    config = lib.mkIf cfg.enable {
      systemd.services.blade-backup-critical = {
        description = "Capture coherent application state and upload critical backup to Pinas";
        after = ["docker.service" "postgresql.service"];
        requisite = ["docker.service" "postgresql.service"];
        unitConfig.RequiresMountsFor = ["/data"];
        serviceConfig = {
          Type = "oneshot";
          User = "root";
          UMask = "0077";
          ExecStart = lib.getExe backupCritical;
          ExecStopPost = recoverAll;
          CacheDirectory = "blade-restic";
          CacheDirectoryMode = "0700";
          StateDirectory = "blade-backup-status";
          StateDirectoryMode = "0700";
          Environment = ["RESTIC_CACHE_DIR=/var/cache/blade-restic"];
          TimeoutStartSec = "2d";
          TimeoutStopSec = "10min";
          KillMode = "control-group";
          PrivateTmp = true;
          ProtectHome = "read-only";
        };
      };
      systemd.services.blade-prepare-coherent-applications = {
        description = "Stage coordinated PostgreSQL application databases and files";
        after = ["docker.service" "postgresql.service"];
        requisite = ["docker.service" "postgresql.service"];
        unitConfig.RequiresMountsFor = ["/data"];
        serviceConfig = {
          Type = "oneshot";
          User = "root";
          UMask = "0077";
          ExecStart = lib.getExe prepareCoherent;
          ExecStopPost = "${lib.getExe prepareCoherent} --recover";
          TimeoutStartSec = "8h";
          TimeoutStopSec = "10min";
          KillMode = "control-group";
          PrivateTmp = true;
          ProtectHome = "read-only";
        };
      };
      systemd.services.blade-prepare-application-state = {
        description = "Stage quiesced application state and validate SQLite databases";
        after = ["audiobookshelf.service" "vaultwarden.service" "headscale.service" "jellyfin.service"];
        unitConfig.RequiresMountsFor = ["/data"];
        serviceConfig = {
          Type = "oneshot";
          User = "root";
          UMask = "0077";
          ExecStartPre = "${pkgs.util-linux}/bin/mountpoint -q /data";
          ExecStart = lib.getExe prepareState;
          # Runs even on start failure or timeout, after remaining processes die.
          ExecStopPost = "${lib.getExe prepareState} --recover";
          TimeoutStartSec = "30min";
          TimeoutStopSec = "5min";
          KillMode = "control-group";
          PrivateTmp = true;
          ProtectHome = true;
        };
      };
      systemd.services.blade-prepare-postgresql-backups = {
        description = "Prepare and validate logical PostgreSQL backup dumps";
        after = ["docker.service" "postgresql.service"];
        # Do not start applications/databases implicitly just to back them up.
        requisite = ["docker.service" "postgresql.service"];
        unitConfig.RequiresMountsFor = ["/data"];
        path = [pkgs.coreutils pkgs.util-linux pkgs.docker config.services.postgresql.package];
        serviceConfig = {
          Type = "oneshot";
          User = "root";
          UMask = "0077";
          ExecStartPre = "${pkgs.util-linux}/bin/mountpoint -q /data";
          ExecStart = lib.getExe prepare;
          TimeoutStartSec = "1h";
          KillMode = "control-group";
          Nice = 10;
          IOSchedulingClass = "best-effort";
          IOSchedulingPriority = 7;
          PrivateTmp = true;
          ProtectHome = true;
        };
      };
    };
  };
}
