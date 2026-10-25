{...}: {
  flake.nixosModules.pinas-backups = {config, lib, pkgs, ...}: let
    root = "/data/restic";
    address = "100.64.0.6";
    blade = "100.64.0.1";
    port = 8000;
    storage = "pinas-backup-storage.service";
    credentials = "/var/lib/restic-server/htpasswd";
    maintenance = pkgs.writeShellApplication {
      name = "pinas-repository-maintenance";
      runtimeInputs = [pkgs.coreutils pkgs.util-linux pkgs.inetutils pkgs.restic];
      text = builtins.readFile ../../../scripts/pinas-repository-maintenance.sh;
    };
    setupMaintenance = pkgs.writeShellApplication {
      name = "setup-pinas-maintenance";
      runtimeInputs = [pkgs.coreutils pkgs.util-linux pkgs.inetutils pkgs.restic];
      text = builtins.readFile ../../../scripts/setup-pinas-maintenance.sh;
    };
    retentionRuntime = "/run/pinas-restic-retention";
    retentionPlanner = pkgs.writeScriptBin "plan-critical-retention"
      ("#!${pkgs.python3}/bin/python3\n" + builtins.readFile ../../../scripts/plan-critical-retention.py);
    retention = pkgs.writeShellApplication {
      name = "apply-critical-retention";
      runtimeInputs = [pkgs.coreutils pkgs.findutils pkgs.util-linux pkgs.inetutils pkgs.systemd pkgs.restic pkgs.bash];
      text = ''
        export PINAS_RETENTION_PLANNER=${lib.getExe retentionPlanner}
      '' + builtins.readFile ../../../scripts/apply-critical-retention.sh;
    };
    maintenanceJobs = [
      {repo = "critical"; operation = "check";}
      {repo = "critical"; operation = "check-data";}
      {repo = "critical"; operation = "retention-preview";}
      {repo = "media"; operation = "check";}
      {repo = "media"; operation = "check-data";}
    ];
  in {
    assertions = [{
      assertion = !config.networking.nftables.enable;
      message = "Pinas Restic ingress rules currently require the iptables firewall backend.";
    }];

    services.restic.server = {
      enable = true;
      listenAddress = "${address}:${toString port}";
      dataDir = root;
      appendOnly = true;
      htpasswd-file = "/run/credentials/restic-rest-server.service/htpasswd";
      # Pass the flag directly: upstream privateRepos also creates an htpasswd
      # via global tmpfiles, which could write onto the OS disk without /data.
      extraFlags = ["--private-repos"];
    };
    users.users.restic.createHome = lib.mkForce false;
    environment.systemPackages = [setupMaintenance];
    systemd.tmpfiles.rules = [
      "d /var/cache/pinas-restic-maintenance 0700 restic restic -"
    ];

    # Deliberately no wantedBy/timer. Refuses resync/degradation and locks.
    systemd.services.pinas-restic-critical-retention = {
      description = "Manual critical snapshot retention and pruning (endpoint offline)";
      unitConfig.RequiresMountsFor = ["/data"];
      bindsTo = ["data.mount"];
      serviceConfig = {
        Type = "oneshot";
        User = "root";
        Group = "restic";
        ExecStart = lib.getExe retention;
        ExecStopPost = "${lib.getExe retention} --recover";
        LoadCredential = ["repository-password:/var/lib/restic-maintenance/critical-password"];
        RuntimeDirectory = "pinas-restic-retention";
        RuntimeDirectoryMode = "0750";
        RuntimeDirectoryPreserve = "yes";
        CacheDirectory = "pinas-restic-retention";
        CacheDirectoryMode = "0750";
        UMask = "0077";
        TimeoutStartSec = "12h";
        TimeoutStopSec = "5min";
        KillMode = "control-group";
        Nice = 10;
        IOSchedulingClass = "idle";
        NoNewPrivileges = true;
        CapabilityBoundingSet = ["CAP_CHOWN" "CAP_DAC_OVERRIDE" "CAP_FOWNER" "CAP_SETGID" "CAP_SETUID"];
        AmbientCapabilities = ["CAP_SETGID" "CAP_SETUID"];
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateNetwork = true;
        RestrictAddressFamilies = ["AF_UNIX"];
        ReadOnlyPaths = [root];
        ReadWritePaths = ["${root}/blade/critical" "/var/cache/pinas-restic-maintenance"];
      };
    };

    systemd.services.pinas-restic-critical-retention-recover = {
      description = "Recover endpoint after failed critical retention (no pruning)";
      serviceConfig = {
        Type = "oneshot";
        User = "root";
        Group = "restic";
        ExecStart = "${lib.getExe retention} --recover";
        RuntimeDirectory = "pinas-restic-retention";
        RuntimeDirectoryMode = "0750";
        RuntimeDirectoryPreserve = "yes";
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateNetwork = true;
        NoNewPrivileges = true;
        CapabilityBoundingSet = "";
        RestrictAddressFamilies = ["AF_UNIX"];
      };
    };

    # Manual-only, non-destructive jobs: no wantedBy, timers, endpoint restart,
    # or permission to modify repository data/snapshots. Only lock files are RW.
    imports = map (job: {
      systemd.services."pinas-restic-${job.repo}-${job.operation}" = {
        description = "Local Restic ${job.repo} ${job.operation} (non-destructive)";
        unitConfig.RequiresMountsFor = ["/data"];
        bindsTo = ["data.mount"];
        serviceConfig = {
          Type = "oneshot";
          User = "restic";
          Group = "restic";
          ExecStart = "${lib.getExe maintenance} ${job.repo} ${job.operation}";
          LoadCredential = ["repository-password:/var/lib/restic-maintenance/${job.repo}-password"];
          CacheDirectory = "pinas-restic-maintenance";
          CacheDirectoryMode = "0700";
          UMask = "0077";
          TimeoutStartSec = "12h";
          Nice = 10;
          IOSchedulingClass = "idle";
          NoNewPrivileges = true;
          CapabilityBoundingSet = "";
          PrivateTmp = true;
          PrivateNetwork = true;
          ProtectHome = true;
          ProtectSystem = "strict";
          ReadOnlyPaths = [root];
          ReadWritePaths = ["${root}/blade/${job.repo}/locks"];
          ProtectKernelTunables = true;
          ProtectKernelModules = true;
          ProtectControlGroups = true;
          RestrictAddressFamilies = ["AF_UNIX"];
          RestrictSUIDSGID = true;
          LockPersonality = true;
        };
      };
    }) maintenanceJobs;

    systemd.services.pinas-backup-storage = {
      description = "Verify backup filesystem and prepare repository directories";
      unitConfig.RequiresMountsFor = ["/data"];
      serviceConfig = {
        Type = "oneshot";
        # Re-run checks on every start of the endpoint, not just once per boot.
        UMask = "0077";
      };
      script = ''
        set -eu
        ${pkgs.util-linux}/bin/mountpoint -q /data
        test "$(${pkgs.util-linux}/bin/findmnt -nro UUID --mountpoint /data)" = 0e549dd2-041c-42d1-b760-d42f1bb1d2e8
        ${pkgs.coreutils}/bin/install -d -o restic -g restic -m 0700 ${root} ${root}/blade
      '';
    };

    systemd.services.restic-rest-server = {
      unitConfig.ConditionPathExists = "!${retentionRuntime}/blocked";
      requires = [storage];
      after = [storage];
      bindsTo = ["data.mount"];
      unitConfig.RequiresMountsFor = ["/data"];
      serviceConfig = {
        LoadCredential = ["htpasswd:${credentials}"];
        ExecStartPre = ["${pkgs.util-linux}/bin/mountpoint -q /data"];
      };
    };
    systemd.sockets.restic-rest-server = {
      # This socket needs late services. Default socket dependencies would put
      # it before sockets.target/basic.target, creating an ordering cycle with
      # storage preparation and tailscaled (both after basic.target).
      wantedBy = lib.mkForce ["multi-user.target"];
      requires = [storage "tailscaled.service"];
      after = [storage "tailscaled.service"];
      bindsTo = ["data.mount"];
      before = ["shutdown.target"];
      conflicts = ["shutdown.target"];
      unitConfig = {
        DefaultDependencies = false;
        ConditionPathExists = "!${retentionRuntime}/blocked";
        RequiresMountsFor = ["/data"];
      };
      socketConfig.BindToDevice = "tailscale0";
    };

    networking.firewall.interfaces.tailscale0.allowedTCPPorts = [port];
    # Tailscale can install ACCEPT rules ahead of the ordinary NixOS filter.
    # Enforce the source restriction in raw PREROUTING, before those rules.
    # Only this IPv4 endpoint is matched; nothing listens on LAN/WAN/IPv6.
    networking.firewall.extraCommands = ''
      iptables -w -t raw -N pinas-restic 2>/dev/null || true
      iptables -w -t raw -F pinas-restic
      iptables -w -t raw -A pinas-restic -i tailscale0 -s ${blade}/32 -j RETURN
      iptables -w -t raw -A pinas-restic -j DROP
      iptables -w -t raw -C PREROUTING -d ${address}/32 -p tcp --dport ${toString port} -j pinas-restic 2>/dev/null || \
        iptables -w -t raw -A PREROUTING -d ${address}/32 -p tcp --dport ${toString port} -j pinas-restic
    '';
    networking.firewall.extraStopCommands = ''
      iptables -w -t raw -D PREROUTING -d ${address}/32 -p tcp --dport ${toString port} -j pinas-restic 2>/dev/null || true
      iptables -w -t raw -F pinas-restic 2>/dev/null || true
      iptables -w -t raw -X pinas-restic 2>/dev/null || true
    '';
  };
}
