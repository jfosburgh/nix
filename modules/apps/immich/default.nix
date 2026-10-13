{...}: {
  flake.nixosModules.immich = {pkgs, ...}: let
    compose = (pkgs.formats.yaml {}).generate "immich-compose.yaml" {
      name = "immich";
      services = {
        server = {
          image = "ghcr.io/immich-app/immich-server:v3.3.1@sha256:db996e352359771c6a3db121a0ed8761516b22f727fc092a0f46dcfef82c1bc1";
          container_name = "immich_server";
          volumes = [
            "/data/immich/media:/data"
            "/data/immich/media:/photos"
            "/data/immich/media:/usr/src/app/upload"
            "/etc/localtime:/etc/localtime:ro"
          ];
          environment = {
            DB_HOSTNAME = "database";
            DB_USERNAME = "postgres";
            DB_DATABASE_NAME = "immich";
            DB_PASSWORD = "\${DB_PASSWORD}";
            REDIS_HOSTNAME = "redis";
            IMMICH_MACHINE_LEARNING_URL = "http://machine-learning:3003";
            IMMICH_MEDIA_LOCATION = "/photos";
            TZ = "America/New_York";
          };
          ports = ["127.0.0.1:2283:2283"];
          depends_on = {
            database.condition = "service_healthy";
            redis.condition = "service_healthy";
          };
          healthcheck.start_period = "120s";
          restart = "unless-stopped";
        };
        machine-learning = {
          image = "ghcr.io/immich-app/immich-machine-learning:v3.3.1@sha256:513c831cfb010ad319341a0c86b42c575a0d5b688d3e8cae346ee624074a58ed";
          container_name = "immich_machine_learning";
          volumes = ["/data/immich/model-cache:/cache"];
          restart = "unless-stopped";
        };
        redis = {
          image = "docker.io/valkey/valkey:9@sha256:c123e3715db63d06d4ad6964884037aa0d5d4d703939b9929954112889708e1d";
          container_name = "immich_redis";
          healthcheck = {
            test = ["CMD" "redis-cli" "ping"];
            interval = "10s";
            timeout = "5s";
            retries = 5;
          };
          restart = "unless-stopped";
        };
        database = {
          image = "ghcr.io/immich-app/postgres:16-vectorchord0.4.3-pgvectors0.2.0@sha256:1a078b237c1d9b420b0ee59147386b4aa60d3a07a8e6a402fc84a57e41b043a4";
          container_name = "immich_postgres";
          environment = {
            POSTGRES_PASSWORD = "\${DB_PASSWORD}";
            POSTGRES_USER = "postgres";
            POSTGRES_DB = "immich";
            POSTGRES_INITDB_ARGS = "--data-checksums";
            DB_STORAGE_TYPE = "HDD";
          };
          volumes = ["/data/immich/postgres:/var/lib/postgresql/data"];
          shm_size = "128mb";
          stop_grace_period = "5m";
          healthcheck.start_period = "120s";
          restart = "unless-stopped";
        };
      };
    };
    composeCommand = "${pkgs.docker}/bin/docker compose --project-directory /etc/immich --env-file /var/lib/immich/environment --file /etc/immich/compose.yaml";
  in {
    virtualisation.docker = {
      enable = true;
      daemon.settings.data-root = "/data/docker";
    };

    services.nginx.virtualHosts."photos.threegoldenhairs.me" = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://127.0.0.1:2283";
        proxyWebsockets = true;
        extraConfig = ''
          client_max_body_size 0;
          proxy_request_buffering off;
          proxy_read_timeout 600s;
          proxy_send_timeout 600s;
          client_body_timeout 600s;
        '';
      };
    };

    environment.systemPackages = [pkgs.docker-compose];
    environment.etc."immich/compose.yaml".source = compose;

    systemd.services.docker.unitConfig.RequiresMountsFor = ["/data"];
    systemd.services.docker.serviceConfig.ExecStartPre = ["${pkgs.util-linux}/bin/mountpoint -q /data"];

    systemd.services.immich = {
      wantedBy = ["multi-user.target"];
      requires = ["docker.service"];
      after = ["docker.service" "network-online.target"];
      wants = ["network-online.target"];
      unitConfig = {
        RequiresMountsFor = ["/data"];
        ConditionPathExists = "/data/immich/.restored";
      };
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = "15min";
        ExecStartPre = "${pkgs.util-linux}/bin/mountpoint -q /data";
        ExecStart = "${composeCommand} up -d --wait --wait-timeout 300";
        TimeoutStopSec = "6min";
        ExecStop = "${composeCommand} stop";
      };
      restartTriggers = [compose];
    };
  };
}
