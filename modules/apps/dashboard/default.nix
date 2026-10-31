{...}: {
  flake.nixosModules.dashboard = {...}: let
    domain = "threegoldenhairs.me";
    links = [
      { name = "Home Assistant"; subdomain = "homeassistant"; }
      { name = "Vaultwarden"; subdomain = "bitwarden"; }
      { name = "Nextcloud"; subdomain = "cloud"; }
      { name = "Immich"; subdomain = "photos"; }
      { name = "Jellyfin"; subdomain = "jellyfin"; }
      { name = "Audiobookshelf"; subdomain = "audiobooks"; }
      { name = "BookOrbit"; subdomain = "books"; }
      { name = "Norish"; subdomain = "recipes"; }
    ];
  in {
    services.glance = {
      enable = true;
      openFirewall = false;
      settings = {
        server = { host = "127.0.0.1"; port = 8081; };
        pages = [{
          name = "Home";
          columns = [
            {
              size = "small";
              widgets = [
                { type = "calendar"; first-day-of-week = "monday"; }
                { type = "clock"; hour-format = "24h"; timezones = [{ timezone = "America/New_York"; label = "Local"; }]; }
              ];
            }
            {
              size = "full";
              widgets = [
                {
                  type = "bookmarks";
                  groups = [{
                    title = "Services";
                    links = map (item: { title = item.name; url = "https://${item.subdomain}.${domain}"; }) links;
                  }];
                }
                { type = "hacker-news"; limit = 10; collapse-after = 5; }
              ];
            }
            {
              size = "small";
              widgets = [{
                type = "server-stats";
                servers = [{
                  type = "local";
                  name = "Blade";
                  hide-mountpoints-by-default = true;
                  mountpoints = {
                    "/" = { name = "System"; hide = false; };
                    "/data" = { name = "Data · RAID1"; hide = false; };
                  };
                }];
              }];
            }
          ];
        }];
      };
    };

    # Tailscale clients resolve the dashboard directly to Blade, not the WAN IP.
    services.headscale.settings.dns.extra_records = [{
      name = "dash.${domain}";
      type = "A";
      value = "100.64.0.1";
    }];

    services.nginx.virtualHosts."dash.${domain}" = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://127.0.0.1:8081";
        proxyWebsockets = true;
        # Restrict every dashboard route, including APIs and static assets.
        # ACME's separate challenge location remains public for renewal.
        extraConfig = ''
          allow 127.0.0.1;
          allow ::1;
          # OPNsense rewrites forwarded WAN traffic to its LAN address.
          # Require direct LAN DNS access rather than trusting hairpin/WAN NAT.
          deny 192.168.1.1;
          allow 192.168.1.0/24;
          allow 100.64.0.0/10;
          allow fd7a:115c:a1e0::/48;
          deny all;
          proxy_read_timeout 300s;
          proxy_send_timeout 300s;
        '';
      };
    };
  };
}
