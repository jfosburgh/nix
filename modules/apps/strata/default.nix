{...}: {
  # Opt-in: imported only by narsil's headless boot specialisation.
  # Uses the already-installed engine/model; never downloads or loads at build time.
  flake.nixosModules.strata-server = {
    config,
    pkgs,
    lib,
    ...
  }: let
    root = "/home/james/dev/Strata";
    data = "/home/james/dev/Strata-data";
    rocm = pkgs.symlinkJoin {
      name = "strata-rocm";
      paths = with pkgs.rocmPackages; [
        clr
        hipcc
        hipblas
        hipblas-common
        hipblaslt
        rocblas
        rocm-core
        rocm-device-libs
        rocm-toolchain
      ];
    };
    serverConfig = pkgs.writeText "strata-server.json" (builtins.toJSON {
      exe = "${root}/engine/strata";
      cwd = root;
      tokenizer = "${data}/packs/coder-iq1_m/tokenizer";
      model_name = "qwen3.8-flash-next-coder-iq1_m";
      backend = "hip";
      host = "127.0.0.1";
      port = 8080;
      open_browser = false;
      allowed_hosts = ["strata.threegoldenhairs.me"];
      log = "/var/log/strata/engine.log";
      lib_dirs = ["${rocm}/lib"];
      env = {
        STRATA_HIPBLASLT_TUNING = "${root}/tools/hip/gfx1201-hipblaslt-100202.txt";
        STRATA_RESIDENT_PIN = "0";
        STRATA_RESIDENT_HEADROOM_GIB = "6";
        STRATA_HIP_WMMA = "1";
      };
      args = [
        "--pack"
        "${data}/packs/coder-iq1_m"
        "--native"
        "${data}/models/coder-IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf"
        "--ple-gguf"
        "${data}/models/coder-IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf"
        "--expert-profile"
        "${root}/data/expert-profile-coder.bin"
        "--expert-cache"
        "auto"
        "--prefill"
        "auto"
        "--spec"
        "4"
        "--spec-min-p"
        "0.5"
        "--mtp"
        "${data}/mtp/rt"
        "--max-context"
        "262144"
        "--kv"
        "int8"
        "--kv-resident"
        "32768"
        "--resident-experts"
        "--vram-reserve-mib"
        "1024"
      ];
    });
  in
    lib.mkIf (!(config.services.narsilInference.enable or false)) {
      # Root the interpreter and runtime libraries in the system generation; the
      # local venv and installed engine remain owned/maintained by james.
      system.extraDependencies = [pkgs.python312];
      environment.etc."strata/server.json".source = serverConfig;

      systemd.services.strata = {
        description = "Strata Coder (256K, headless)";
        # ExecStart names a stable /etc path; restart when its generated content changes.
        restartTriggers = [serverConfig];
        wantedBy = ["multi-user.target"];
        after = ["network.target"];
        unitConfig = {
          RequiresMountsFor = [root data];
          StartLimitIntervalSec = 600;
          StartLimitBurst = 3;
        };
        environment = {
          ROCM_PATH = "${rocm}";
          HIP_PATH = "${rocm}";
          LD_LIBRARY_PATH =
            "/run/opengl-driver/lib:"
            + lib.makeLibraryPath [
              rocm
              pkgs.stdenv.cc.cc.lib
              pkgs.zlib
              pkgs.numactl
            ];
          # Never use nix-shell's transient TMPDIR for a long-lived HIP process.
          TMPDIR = "/run/strata";
          TMP = "/run/strata";
          TEMP = "/run/strata";
          TEMPDIR = "/run/strata";
          XDG_CACHE_HOME = "/var/cache/strata";
          PYTHONUNBUFFERED = "1";
        };
        serviceConfig = {
          Type = "simple";
          User = "james";
          SupplementaryGroups = ["render" "video"];
          WorkingDirectory = root;
          ExecStartPre = "${pkgs.coreutils}/bin/test -x ${root}/engine/strata";
          ExecStart = "${root}/.venv/bin/python ${root}/serve/server.py --engine strata --config /etc/strata/server.json --port 8080";
          Restart = "on-failure";
          RestartSec = "15s";
          TimeoutStopSec = "120s";
          KillSignal = "SIGTERM";
          RuntimeDirectory = "strata";
          RuntimeDirectoryMode = "0700";
          CacheDirectory = "strata";
          LogsDirectory = "strata";
          UMask = "0077";
          NoNewPrivileges = true;
          PrivateTmp = true;
          ProtectSystem = "strict";
          ProtectHome = "read-only";
          ProtectKernelTunables = true;
          ProtectKernelModules = true;
          ProtectControlGroups = true;
          RestrictSUIDSGID = true;
          # PrivateDevices must stay off: HIP needs /dev/kfd and /dev/dri.
        };
      };

      # Strata stays loopback-only. This second, source-restricted hop accepts
      # requests only from Blade over Tailscale; clients use Blade's HTTPS vhost.
      services.nginx = {
        enable = true;
        recommendedProxySettings = true;
        virtualHosts.strata-upstream = {
          listen = [
            {
              addr = "0.0.0.0";
              port = 8081;
            }
          ];
          locations."/" = {
            proxyPass = "http://127.0.0.1:8080";
            proxyWebsockets = true;
            extraConfig = ''
              allow 100.64.0.1;
              deny all;
              client_max_body_size 128m;
              proxy_buffering off;
              proxy_request_buffering off;
              proxy_read_timeout 3600s;
              proxy_send_timeout 3600s;
            '';
          };
        };
      };
      networking.firewall.interfaces.tailscale0.allowedTCPPorts = [8081];
    };
}
