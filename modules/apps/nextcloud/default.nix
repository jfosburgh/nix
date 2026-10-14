{...}: {
  flake.nixosModules.nextcloud = {lib, pkgs, ...}: let
    mountCheck = "${pkgs.util-linux}/bin/mountpoint -q /data";
    storageDependency = {
      requires = ["nextcloud-storage.service"];
      after = ["nextcloud-storage.service"];
      unitConfig.RequiresMountsFor = ["/data"];
      serviceConfig.ExecStartPre = lib.mkBefore [mountCheck];
    };
  in {
    services.nextcloud = {
      enable = true;
      package = pkgs.nextcloud34;
      hostName = "cloud.threegoldenhairs.me";
      home = "/data/nextcloud";
      https = true;
      maxUploadSize = "16G";
      configureRedis = true;
      database.createLocally = true;
      config = {
        dbtype = "pgsql";
        adminuser = "james";
        adminpassFile = "/data/nextcloud/.secrets/admin-password";
      };
      phpOptions = {
        upload_tmp_dir = "/data/nextcloud/tmp";
        sys_temp_dir = "/data/nextcloud/tmp";
      };
      settings = {
        tempdirectory = "/data/nextcloud/tmp";
        overwriteprotocol = "https";
        default_phone_region = "US";
        maintenance_window_start = 7;
      };
    };

    services.postgresql = {
      package = pkgs.postgresql_18;
      dataDir = "/data/nextcloud-db/18";
    };

    services.nginx.virtualHosts."cloud.threegoldenhairs.me" = {
      enableACME = true;
      forceSSL = true;
    };

    systemd.services = {
      nextcloud-storage = {
        wantedBy = ["multi-user.target"];
        unitConfig.RequiresMountsFor = ["/data"];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStartPre = mountCheck;
        };
        script = ''
          install -d -o nextcloud -g nextcloud -m 0750 /data/nextcloud
          install -d -o nextcloud -g nextcloud -m 0700 /data/nextcloud/redis /data/nextcloud/tmp
          install -d -o postgres -g postgres -m 0700 /data/nextcloud-db /data/nextcloud-db/18
          install -d -o root -g root -m 0700 /data/nextcloud/.secrets
          if [ ! -e /data/nextcloud/.secrets/admin-password ]; then
            umask 077
            tmp=$(mktemp /data/nextcloud/.secrets/admin-password.XXXXXX)
            ${pkgs.openssl}/bin/openssl rand -hex 24 > "$tmp"
            mv "$tmp" /data/nextcloud/.secrets/admin-password
          fi
        '';
      };
      postgresql = storageDependency;
      nextcloud-setup = storageDependency // {
        requires = ["nextcloud-storage.service" "redis-nextcloud.service"];
        after = ["nextcloud-storage.service" "redis-nextcloud.service"];
      };
      nextcloud-cron = storageDependency;
      nextcloud-update-db = storageDependency;
      phpfpm-nextcloud = storageDependency // {
        requires = ["nextcloud-storage.service" "nextcloud-setup.service" "redis-nextcloud.service"];
        after = ["nextcloud-storage.service" "nextcloud-setup.service" "redis-nextcloud.service"];
      };
      redis-nextcloud = lib.recursiveUpdate storageDependency {
        serviceConfig = {
          StateDirectory = lib.mkForce [];
          BindPaths = ["/data/nextcloud/redis:/var/lib/redis-nextcloud"];
          ReadWritePaths = ["/var/lib/redis-nextcloud"];
        };
      };
    };
  };
}
