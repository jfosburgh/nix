{...}: {
  flake.nixosModules.audiobookshelf = {lib, pkgs, ...}: {
    services.audiobookshelf = {
      enable = true;
      host = "127.0.0.1";
      port = 8000;
      openFirewall = false;
    };

    users.users.james.extraGroups = ["audiobookshelf"];

    systemd.tmpfiles.rules = [
      "d /data/audiobookshelf 2775 audiobookshelf audiobookshelf - -"
      "d /data/audiobookshelf/config 2770 audiobookshelf audiobookshelf - -"
      "d /data/audiobookshelf/metadata 2770 audiobookshelf audiobookshelf - -"
      "d /data/audiobookshelf/audiobooks 2775 audiobookshelf audiobookshelf - -"
    ];

    systemd.services.audiobookshelf = {
      wants = ["network-online.target"];
      after = ["network-online.target"];
      unitConfig = {
        RequiresMountsFor = ["/data"];
        ConditionPathIsMountPoint = "/data";
      };
      serviceConfig = {
        ExecStart = lib.mkForce "${pkgs.audiobookshelf}/bin/audiobookshelf --host 127.0.0.1 --port 8000 --config /data/audiobookshelf/config --metadata /data/audiobookshelf/metadata";
        ExecStartPre = "${pkgs.util-linux}/bin/mountpoint -q /data";
        ReadWritePaths = ["/data/audiobookshelf"];
      };
    };

    services.nginx.virtualHosts."audiobooks.threegoldenhairs.me" = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://127.0.0.1:8000";
        proxyWebsockets = true;
        extraConfig = ''
          client_max_body_size 0;
          proxy_request_buffering off;
          proxy_buffering off;
          proxy_read_timeout 3600s;
          proxy_send_timeout 3600s;
        '';
      };
    };
  };
}
