{...}: {
  flake.nixosModules.norish = {pkgs, ...}: let
    compose = (pkgs.formats.yaml {}).generate "norish-compose.yaml" {
      name = "norish";
      services = {
        app = {
          image = "docker.io/norishapp/norish:v0.26.0-beta@sha256:0cc4fe677579fb0e9c6c5d460083373f1b52490a815075cdb700b938facbe49f";
          container_name = "norish-app";
          restart = "unless-stopped";
          ports = ["127.0.0.1:3002:3000"];
          volumes = ["/data/norish/uploads:/app/uploads"];
          environment = {
            AUTH_URL = "https://recipes.threegoldenhairs.me";
            DATABASE_URL = "postgres://norish:\${POSTGRES_PASSWORD:?missing database password}@db:5432/norish";
            MASTER_KEY = "\${MASTER_KEY:?missing master key}";
            OBSCURA_ENDPOINT = "ws://obscura:9222";
            OBSCURA_CDP_TOKEN = "\${OBSCURA_CDP_TOKEN:?missing browser token}";
            VALKEY_URL = "valkey://valkey:6379";
            UPLOADS_DIR = "/app/uploads";
            PASSWORD_AUTH_ENABLED = "true";
            TZ = "America/New_York";
          };
          depends_on = {
            db.condition = "service_healthy";
            valkey.condition = "service_healthy";
            obscura.condition = "service_started";
          };
          healthcheck = {
            test = ["CMD" "node" "-e" "require('http').get('http://localhost:3000/api/v1/health/live', r => process.exit(r.statusCode===200?0:1)).on('error', () => process.exit(1))"];
            interval = "30s";
            timeout = "15s";
            retries = 5;
            start_period = "120s";
          };
          stop_grace_period = "2m";
        };
        db = {
          image = "docker.io/postgres:17-alpine@sha256:266d3c257594e195b309ae9d1805e54c788f1d7b375f56bf6c367aac6c917e7b";
          container_name = "norish-db";
          restart = "unless-stopped";
          environment = {
            POSTGRES_USER = "norish";
            POSTGRES_DB = "norish";
            POSTGRES_PASSWORD = "\${POSTGRES_PASSWORD:?missing database password}";
          };
          volumes = ["/data/norish/postgres:/var/lib/postgresql/data"];
          healthcheck = {
            test = ["CMD-SHELL" ''pg_isready -h 127.0.0.1 -U "$${POSTGRES_USER}" -d "$${POSTGRES_DB}"''];
            interval = "10s";
            timeout = "5s";
            retries = 10;
            start_period = "20s";
          };
          stop_grace_period = "2m";
        };
        obscura = {
          image = "docker.io/norishapp/obscura:0.2.5-norish.1@sha256:7bd78a6dbb8329a172f8c4d38cd7a875139b5a7756118579c376c978f612a0a9";
          container_name = "norish-obscura";
          restart = "unless-stopped";
          environment.OBSCURA_CDP_TOKEN = "\${OBSCURA_CDP_TOKEN:?missing browser token}";
        };
        valkey = {
          image = "docker.io/valkey/valkey:9@sha256:c123e3715db63d06d4ad6964884037aa0d5d4d703939b9929954112889708e1d";
          container_name = "norish-valkey";
          restart = "unless-stopped";
          command = ["valkey-server" "--appendonly" "yes"];
          volumes = ["/data/norish/valkey:/data"];
          healthcheck = {
            test = ["CMD" "valkey-cli" "ping"];
            interval = "10s";
            timeout = "5s";
            retries = 10;
          };
          stop_grace_period = "1m";
        };
      };
    };
    composeCommand = "${pkgs.docker}/bin/docker compose --project-directory /etc/norish --env-file /data/norish/environment --file /etc/norish/compose.yaml";
  in {
    virtualisation.docker = {
      enable = true;
      daemon.settings.data-root = "/data/docker";
    };
    environment.systemPackages = [pkgs.docker-compose];
    environment.etc."norish/compose.yaml".source = compose;

    services.nginx.virtualHosts."recipes.threegoldenhairs.me" = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://127.0.0.1:3002";
        proxyWebsockets = true;
        extraConfig = ''
          client_max_body_size 100m;
          proxy_request_buffering off;
          proxy_buffering off;
          proxy_read_timeout 600s;
          proxy_send_timeout 600s;
        '';
      };
    };

    services.headscale.settings.dns.extra_records = [{
      name = "recipes.threegoldenhairs.me";
      type = "A";
      value = "100.64.0.1";
    }];

    systemd.services.norish = {
      wantedBy = ["multi-user.target"];
      requires = ["docker.service"];
      after = ["docker.service" "network-online.target"];
      wants = ["network-online.target"];
      unitConfig.RequiresMountsFor = ["/data"];
      preStart = ''
        ${pkgs.util-linux}/bin/mountpoint -q /data
        install -d -m 0700 /data/norish
        install -d -o 1000 -g 1000 -m 0755 /data/norish/uploads
        install -d -m 0700 /data/norish/{postgres,valkey}
        if [ ! -e /data/norish/environment ]; then
          # Never silently replace keys belonging to an existing deployment.
          if [ -n "$(ls -A /data/norish/postgres)" ] || [ -n "$(ls -A /data/norish/uploads)" ] || [ -n "$(ls -A /data/norish/valkey)" ]; then
            echo 'Existing Norish data without environment file; restore secrets before starting.' >&2
            exit 1
          fi
          umask 077
          tmp=$(mktemp /data/norish/environment.XXXXXX)
          printf 'POSTGRES_PASSWORD=%s\n' "$(${pkgs.openssl}/bin/openssl rand -hex 32)" >> "$tmp"
          printf 'MASTER_KEY=%s\n' "$(${pkgs.openssl}/bin/openssl rand -base64 32)" >> "$tmp"
          printf 'OBSCURA_CDP_TOKEN=%s\n' "$(${pkgs.openssl}/bin/openssl rand -hex 32)" >> "$tmp"
          mv "$tmp" /data/norish/environment
        fi
        chmod 0600 /data/norish/environment
      '';
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = "15min";
        ExecStart = "${composeCommand} up -d --wait --wait-timeout 300";
        TimeoutStopSec = "6min";
        ExecStop = "${composeCommand} stop";
      };
      restartTriggers = [compose];
    };
  };
}
