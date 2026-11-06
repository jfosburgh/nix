{
  self,
  inputs,
  ...
}: {
  # Normal Narsil inference service; preserves the tuned backend profiles.
  flake.nixosModules.inference-coordinator = {
    config,
    lib,
    pkgs,
    ...
  }: let
    cfg = config.services.narsilInference;
    headless = config.environment.etc."narsil-mode".text == "headless\n";
    context =
      if headless
      then 262144
      else 131072;
    root = "/home/james/dev/Strata";
    data = "/home/james/dev/Strata-data";
    device = "/sys/bus/pci/devices/0000:08:00.0";
    python = pkgs.python3.withPackages (p: [p.aiohttp]);
    coordinatorSource = lib.cleanSourceWith {
      src = ./coordinator;
      filter = path: type: builtins.baseNameOf path != "__pycache__" && !(lib.hasSuffix ".pyc" path);
    };
    package =
      pkgs.runCommand "narsil-inference-coordinator" {
        nativeBuildInputs = [pkgs.makeWrapper];
      } ''
        mkdir -p "$out/lib" "$out/bin"
        cp -R ${coordinatorSource} "$out/lib/coordinator"
        makeWrapper ${python}/bin/python "$out/bin/narsil-inference-runtime" \
          --prefix PYTHONPATH : "$out/lib" --set PYTHONDONTWRITEBYTECODE 1 \
          --set PYTHONUNBUFFERED 1 --add-flags "-m coordinator.personal"
      '';
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
    strataConfig =
      pkgs.writeText "strata-coordinated-${
        if headless
        then "headless"
        else "desktop"
      }.json" (builtins.toJSON {
        exe = "${root}/engine/strata";
        cwd = root;
        tokenizer = "${data}/packs/coder-iq1_m/tokenizer";
        model_name = "qwen3.8-flash-next-coder-iq1_m";
        backend = "hip";
        host = "127.0.0.1";
        port = 18081;
        lazy_load = true;
        open_browser = false;
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
          (toString context)
          "--kv"
          "int8"
          "--kv-resident"
          "32768"
          "--resident-experts"
          "--vram-reserve-mib"
          (
            if headless
            then "1024"
            else "3072"
          )
        ];
      });
    serviceConfig = pkgs.writeText "narsil-inference.json" (builtins.toJSON {
      version = 1;
      profile =
        if headless
        then "headless"
        else "desktop";
      token_file = "/run/credentials/inference-coordinator.service/client";
      admin_token_file = "/run/credentials/inference-coordinator.service/admin";
      limits = {
        max_queue = 16;
        # 256K code histories can exceed 1 MiB even before JSON/tool schemas.
        max_queue_bytes = 16777216;
        max_body = 4194304;
        max_connections = 16;
        max_discovery_bytes = 1048576;
        lifecycle_timeout = 300;
        inference_timeout = 900;
        body_timeout = 30;
        # Measured Ornith 256K cold prefill takes ~214s before first output.
        stream_idle = 600;
        queue_timeout = 1800;
        discovery_timeout = 10;
        admin_timeout = 900;
        count_timeout = 5;
      };
      backends = [
        {
          id = "strata";
          adapter = "strata";
          priority = 0;
          upstream = "http://127.0.0.1:18081";
          resources = ["narsil-gpu"];
          model = "qwen3.8-flash-next-coder-iq1_m";
          inherit context;
          inherit (cfg.memoryBudgets.strata) cold resident;
        }
        {
          id = "ollama";
          adapter = "ollama";
          priority = 1;
          upstream = "http://127.0.0.1:12434";
          resources = ["narsil-gpu"];
          expected_version = "0.40.11";
          input_policy = "native-reject";
          models."gemma4:12b" = {
            catalog_name = "gemma4:12b";
            resident_name = "gemma4:12b";
            context = 65536;
            output = 8192;
            inherit (cfg.memoryBudgets.ollama) cold resident;
          };
          models."ornith-1.5:9b" = {
            catalog_name = "ornith-1.5:9b";
            resident_name = "ornith-1.5:9b";
            context = 262144;
            output = 8192;
            inherit (cfg.memoryBudgets.ornith) cold resident;
          };
          models."nemotron-3.5-bolt:e4b" = {
            catalog_name = "nemotron-3.5-bolt:e4b";
            resident_name = "nemotron-3.5-bolt:e4b";
            context = 65536;
            output = 8192;
            inherit (cfg.memoryBudgets.bolt) cold resident;
          };
        }
      ];
    });
    operator = pkgs.writeShellApplication {
      name = "narsil-inference";
      text = ''exec ${package}/bin/narsil-inference-runtime "$@"'';
    };
  in {
    options.services.narsilInference = {
      enable = (lib.mkEnableOption "personal-use local inference routing") // {default = true;};
      memoryBudgets = lib.mkOption {
        type = lib.types.attrs;
        # Desktop cold values came from the successful local measurements.
        # These are admission estimates, not full-context/worst-case guarantees.
        # Headless retains the larger floor; that profile needs separate live testing.
        default = {
          strata = {
            cold = {
              ram_available =
                24606584832
                + (
                  if headless
                  then 4294967296
                  else 0
                );
              vram_free = 14616551424;
            };
            resident = {
              ram_available =
                if headless
                then 6442450944
                else 2147483648;
              vram_free = 536870912;
            };
          };
          # Live desktop: Ornith 256K / 254K prompt, >=2.44 GiB VRAM free;
          # Bolt 64K / 57K prompt, >=7.40 GiB VRAM free. Conservative cold
          # admission estimates; headless and worst-case use remain unmeasured.
          ornith = {
            cold = {
              ram_available = 17179869184;
              vram_free = 15032385536;
            };
            resident = {
              ram_available = 6442450944;
              vram_free = 536870912;
            };
          };
          bolt = {
            cold = {
              ram_available = 12884901888;
              vram_free = 10737418240;
            };
            resident = {
              ram_available = 6442450944;
              vram_free = 536870912;
            };
          };
          # Qwen 27B is intentionally not served: safe offload measured below
          # the user's 20-token/s generation floor. Use Strata for stronger work.
          # Gemma 64K: live 56K-token prompt fits with >5 GiB VRAM free.
          # Conservative cold estimates, not a worst-case memory guarantee.
          ollama = {
            cold = {
              ram_available = 12884901888;
              vram_free = 15032385536;
            };
            resident = {
              ram_available = 6442450944;
              vram_free = 536870912;
            };
          };
        };
        description = "Per-profile cold/resident free RAM and VRAM admission estimates, in bytes.";
      };
    };
    config = lib.mkIf cfg.enable {
      assertions = [
        {
          assertion = pkgs.ollama-rocm.version == "0.40.11";
          message = "Native rejection policy requires Ollama 0.40.11";
        }
      ];
      environment.systemPackages = [operator];
      environment.etc."narsil-inference-coordinator".text = "mode switches require coordinated backend lifecycle integration\n";
      system.extraDependencies = [package serviceConfig];
      users.groups.inference-coordinator = {};
      users.users.inference-coordinator = {
        isSystemUser = true;
        group = "inference-coordinator";
      };
      systemd.tmpfiles.rules = ["d /var/lib/inference-coordinator-secrets 0700 root root -"];
      # No privileged HTTP service/helper. Only this account can request restart
      # of these two exact units; it cannot manage other units or change policy.
      security.polkit.extraConfig = ''
        polkit.addRule(function(action, subject) {
          if (subject.user === "inference-coordinator" &&
              action.id === "org.freedesktop.systemd1.manage-units" &&
              action.lookup("verb") === "restart" &&
              (action.lookup("unit") === "ollama.service" || action.lookup("unit") === "strata.service")) {
            return polkit.Result.YES;
          }
        });
      '';
      networking.firewall.interfaces.tailscale0.allowedTCPPorts = [8081];
      services.ollama = {
        enable = lib.mkForce true;
        host = lib.mkForce "127.0.0.1";
        port = lib.mkForce 12434;
        openFirewall = lib.mkForce false;
        loadModels = lib.mkForce [];
        environmentVariables = {
          OLLAMA_NUM_PARALLEL = "1";
          OLLAMA_MAX_LOADED_MODELS = "1";
          OLLAMA_CONTEXT_LENGTH = "8192";
          OLLAMA_KEEP_ALIVE = "-1";
          OLLAMA_FLASH_ATTENTION = "1";
          OLLAMA_KV_CACHE_TYPE = "q8_0";
          OLLAMA_NO_CLOUD = "1";
        };
      };
      systemd.services.ollama.serviceConfig = {
        Restart = lib.mkForce "no";
        KillMode = "control-group";
        SendSIGKILL = true;
        FinalKillSignal = "SIGKILL";
        TimeoutStopSec = 90;
      };
      systemd.services.strata = {
        description = "Lazy managed Strata (${toString context}, coordinated local inference)";
        restartTriggers = [strataConfig];
        wantedBy = ["multi-user.target"];
        after = ["network.target"];
        unitConfig.RequiresMountsFor = [root data];
        environment = {
          ROCM_PATH = "${rocm}";
          HIP_PATH = "${rocm}";
          LD_LIBRARY_PATH = "/run/opengl-driver/lib:" + lib.makeLibraryPath [rocm pkgs.stdenv.cc.cc.lib pkgs.zlib pkgs.numactl];
          TMPDIR = "/run/strata";
          TMP = "/run/strata";
          TEMP = "/run/strata";
          TEMPDIR = "/run/strata";
          XDG_CACHE_HOME = "/var/cache/strata";
          PYTHONUNBUFFERED = "1";
          PYTHONDONTWRITEBYTECODE = "1";
        };
        serviceConfig = {
          Type = "exec";
          User = "james";
          SupplementaryGroups = ["render" "video"];
          WorkingDirectory = root;
          ExecStartPre = "${pkgs.coreutils}/bin/test -x ${root}/engine/strata";
          ExecStart = "${root}/.venv/bin/python ${root}/serve/server.py --engine strata --config ${strataConfig} --port 18081 --lazy";
          Restart = "no";
          KillMode = "control-group";
          SendSIGKILL = true;
          TimeoutStopSec = "120s";
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
        };
      };
      systemd.services.inference-credentials = {
        description = "Create or validate local inference credentials";
        before = ["inference-coordinator.service"];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          UMask = "0077";
          ExecStart = "${package}/bin/narsil-inference-runtime credentials";
          ProtectSystem = "strict";
          ReadWritePaths = ["/var/lib/inference-coordinator-secrets"];
          ProtectHome = true;
          NoNewPrivileges = true;
        };
      };
      systemd.services.inference-coordinator = {
        description = "Personal-use inference router (reset backends on startup)";
        wantedBy = ["multi-user.target"];
        after = ["strata.service" "ollama.service" "inference-credentials.service" "polkit.service"];
        wants = ["strata.service" "ollama.service" "polkit.service"];
        requires = ["inference-credentials.service"];
        restartTriggers = [serviceConfig];
        unitConfig = {
          StartLimitIntervalSec = 300;
          StartLimitBurst = 3;
        };
        serviceConfig = {
          Type = "exec";
          User = "inference-coordinator";
          Group = "inference-coordinator";
          ExecStart = "${package}/bin/narsil-inference-runtime serve --config ${serviceConfig} --device ${device} --systemctl ${pkgs.systemd}/bin/systemctl";
          LoadCredential = ["client:/var/lib/inference-coordinator-secrets/client" "admin:/var/lib/inference-coordinator-secrets/admin"];
          Restart = "on-failure";
          RestartSec = 5;
          TimeoutStopSec = 35;
          KillMode = "control-group";
          MemoryMax = "512M";
          TasksMax = 32;
          UMask = "0077";
          NoNewPrivileges = true;
          PrivateTmp = true;
          PrivateDevices = true;
          ProtectSystem = "strict";
          ProtectHome = true;
          ProtectKernelTunables = true;
          ProtectKernelModules = true;
          ProtectControlGroups = true;
          RestrictNamespaces = true;
          RestrictSUIDSGID = true;
          CapabilityBoundingSet = [];
          RestrictAddressFamilies = ["AF_UNIX" "AF_INET" "AF_INET6"];
          IPAddressDeny = "any";
          IPAddressAllow = ["localhost" "100.64.0.1"];
          StandardOutput = "journal";
          StandardError = "journal";
        };
      };
    };
  };
}
