{...}: {
  flake.nixosModules.searxng = {pkgs, ...}: let
    domain = "search.threegoldenhairs.me";
    secretFile = "/var/lib/searxng/environment";
  in {
    # Generate once on Blade, outside the store and independent of user homes.
    systemd.services.searxng-secret = {
      description = "Provision persistent SearXNG secret";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        StateDirectory = "searxng";
        StateDirectoryMode = "0700";
        UMask = "0077";
      };
      script = ''
        if [ ! -s ${secretFile} ]; then
          secret=$(${pkgs.openssl}/bin/openssl rand -hex 32)
          printf 'SEARXNG_SECRET=%s\n' "$secret" > ${secretFile}.tmp
          mv ${secretFile}.tmp ${secretFile}
        fi
      '';
    };
    systemd.services.searx-init = {
      requires = ["searxng-secret.service"];
      after = ["searxng-secret.service"];
    };

    services.searx = {
      enable = true;
      openFirewall = false;
      environmentFile = secretFile;
      # Run behind nginx; do not use the development HTTP server or log queries.
      configureUwsgi = true;
      uwsgiConfig = {
        http = "127.0.0.1:8888";
        disable-logging = true;
      };
      settings = {
        server = {
          bind_address = "127.0.0.1";
          port = 8888;
          base_url = "https://${domain}/";
          # Agent search uses GET /search?format=json.
          method = "GET";
          secret_key = "\${SEARXNG_SECRET}";
        };
        search.formats = ["html" "json"];
      };
    };

    services.headscale.settings.dns.extra_records = [
      {
        name = domain;
        type = "A";
        value = "100.64.0.1";
      }
    ];

    services.nginx = {
      enable = true;
      virtualHosts.${domain} = {
        enableACME = true;
        forceSSL = true;
        locations."/" = {
          proxyPass = "http://127.0.0.1:8888";
          recommendedProxySettings = true;
          # All application paths, including static assets and JSON search.
          # ACME's separate challenge location remains public for renewal.
          extraConfig = ''
            allow 127.0.0.1;
            allow ::1;
            # OPNsense SNATs forwarded WAN traffic to its LAN address.
            # Direct LAN DNS access is required, as with the dashboard.
            deny 192.168.1.1;
            allow 192.168.1.0/24;
            allow 100.64.0.0/10;
            allow fd7a:115c:a1e0::/48;
            deny all;
            access_log off;
            proxy_read_timeout 120s;
            proxy_send_timeout 120s;
          '';
        };
      };
    };
  };
}
