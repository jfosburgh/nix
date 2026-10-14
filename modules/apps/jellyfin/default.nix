{...}: {
  flake.nixosModules.jellyfin = {lib, pkgs, ...}: {
    services.jellyfin = {
      enable = true;
      openFirewall = false;
      dataDir = "/data/jellyfin";
      cacheDir = "/data/jellyfin/cache";
      hardwareAcceleration = {
        enable = true;
        type = "vaapi";
        device = "/dev/dri/renderD128";
      };
      forceEncodingConfig = true;
      transcoding = {
        enableHardwareEncoding = true;
        enableToneMapping = false;
        hardwareDecodingCodecs = {
          h264 = true;
          hevc = true;
          hevc10bit = true;
          mpeg2 = true;
          vc1 = true;
          vp8 = true;
          vp9 = true;
        };
      };
    };

    hardware.graphics = {
      enable = true;
      extraPackages = [pkgs.intel-vaapi-driver];
    };

    users.users.jellyfin.extraGroups = ["video" "render"];

    systemd.services.jellyfin = {
      environment = {
        HOME = "/data/jellyfin";
        LIBVA_DRIVER_NAME = "i965";
      };
      unitConfig.RequiresMountsFor = ["/data"];
      serviceConfig.ExecStartPre = lib.mkBefore ["${pkgs.util-linux}/bin/mountpoint -q /data"];
    };

    services.nginx.virtualHosts."jellyfin.threegoldenhairs.me" = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://127.0.0.1:8096";
        proxyWebsockets = true;
        extraConfig = ''
          client_max_body_size 0;
          proxy_buffering off;
          proxy_read_timeout 3600s;
          proxy_send_timeout 3600s;
        '';
      };
    };
  };
}
