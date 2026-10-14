{...}: {
  flake.nixosModules.bookorbit = {pkgs, ...}: let
    uid = "1000";
    gid = "100";
    compose = (pkgs.formats.yaml {}).generate "bookorbit-compose.yaml" {
      name = "bookorbit";
      services = {
        app = {
          image = "ghcr.io/bookorbit/bookorbit:3.4.0@sha256:99539be044c94f10fa5fba616cb08e1b128deb4996c975d181a950818a8632e4";
          container_name = "bookorbit-app";
          restart = "unless-stopped";
          init = true;
          ports = ["127.0.0.1:3000:3000"];
          environment = {
            NODE_ENV = "production";
            PORT = "3000";
            POSTGRES_HOST = "postgres";
            POSTGRES_PORT = "5432";
            POSTGRES_USER = "bookorbit";
            POSTGRES_DB = "bookorbit";
            POSTGRES_PASSWORD = "\${POSTGRES_PASSWORD}";
            JWT_SECRET = "\${JWT_SECRET}";
            PODCAST_ENCRYPTION_KEY = "\${PODCAST_ENCRYPTION_KEY}";
            SETUP_BOOTSTRAP_TOKEN = "\${SETUP_BOOTSTRAP_TOKEN}";
            APP_URL = "https://books.threegoldenhairs.me";
            CLIENT_URL = "https://books.threegoldenhairs.me";
            TZ = "America/New_York";
            PUID = uid;
            PGID = gid;
            NODE_MAX_OLD_SPACE_SIZE = "2048";
            BOOK_DOCK_PATH = "/book-dock";
            LIBRARY_BROWSE_ROOT = "/books";
          };
          depends_on.postgres.condition = "service_healthy";
          volumes = [
            "/data/bookorbit/books:/books"
            "/data/bookorbit/dock:/book-dock"
            "/data/bookorbit/app:/data"
          ];
          read_only = true;
          tmpfs = ["/tmp"];
          cap_drop = ["ALL"];
          cap_add = ["CHOWN" "DAC_OVERRIDE" "FOWNER" "SETGID" "SETUID"];
          security_opt = ["no-new-privileges:true"];
          stop_grace_period = "30s";
        };
        postgres = {
          image = "pgvector/pgvector:pg18@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11";
          container_name = "bookorbit-db";
          restart = "unless-stopped";
          environment = {
            POSTGRES_USER = "bookorbit";
            POSTGRES_DB = "bookorbit";
            POSTGRES_PASSWORD = "\${POSTGRES_PASSWORD}";
            PGDATA = "/var/lib/postgresql/18/docker";
          };
          volumes = ["/data/bookorbit/postgres:/var/lib/postgresql"];
          healthcheck = {
            test = ["CMD-SHELL" ''pg_isready -h 127.0.0.1 -U "$${POSTGRES_USER}" -d "$${POSTGRES_DB}"''];
            interval = "10s";
            timeout = "5s";
            retries = 10;
            start_period = "20s";
          };
        };
      };
    };
    composeCommand = "${pkgs.docker}/bin/docker compose --project-directory /etc/bookorbit --env-file /data/bookorbit/environment --file /etc/bookorbit/compose.yaml";
  in {
    virtualisation.docker = {
      enable = true;
      daemon.settings.data-root = "/data/docker";
    };

    environment.etc."bookorbit/compose.yaml".source = compose;

    services.nginx.virtualHosts."books.threegoldenhairs.me" = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://127.0.0.1:3000";
        proxyWebsockets = true;
        extraConfig = ''
          client_max_body_size 0;
          proxy_request_buffering off;
          proxy_buffering off;
          proxy_read_timeout 600s;
          proxy_send_timeout 600s;
          client_body_timeout 600s;
        '';
      };
    };

    systemd.services.bookorbit = {
      wantedBy = ["multi-user.target"];
      requires = ["docker.service"];
      after = ["docker.service" "network-online.target"];
      wants = ["network-online.target"];
      unitConfig.RequiresMountsFor = ["/data"];
      preStart = ''
        ${pkgs.util-linux}/bin/mountpoint -q /data
        install -d -m 0755 /data/bookorbit
        install -d -o ${uid} -g ${gid} -m 0755 /data/bookorbit/{books,dock,app}
        install -d -o 999 -g 999 -m 0700 /data/bookorbit/postgres
        if [ ! -e /data/bookorbit/environment ]; then
          umask 077
          tmp=$(mktemp /data/bookorbit/environment.XXXXXX)
          for key in POSTGRES_PASSWORD JWT_SECRET PODCAST_ENCRYPTION_KEY SETUP_BOOTSTRAP_TOKEN; do
            printf '%s=%s\n' "$key" "$(${pkgs.openssl}/bin/openssl rand -hex 32)" >> "$tmp"
          done
          mv "$tmp" /data/bookorbit/environment
        fi
      '';
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = "15min";
        ExecStart = "${composeCommand} up -d --wait --wait-timeout 300";
        TimeoutStopSec = "2min";
        ExecStop = "${composeCommand} stop";
      };
      restartTriggers = [compose];
    };
  };
}
