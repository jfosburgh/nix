{...}: {
  flake.nixosModules.strata-proxy = {...}: let
    domain = "strata.threegoldenhairs.me";
  in {
    services.headscale.settings.dns.extra_records = [{
      name = domain;
      type = "A";
      value = "100.64.0.1";
    }];

    services.nginx.virtualHosts.${domain} = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://100.64.0.3:8081";
        proxyWebsockets = true;
        # Match the dashboard's trust boundary, on every route (API, UI and
        # controls). No client API key; network membership grants access.
        extraConfig = ''
          allow 127.0.0.1;
          allow ::1;
          # OPNsense SNATs forwarded WAN traffic to this address. Deny it
          # before the LAN range so the public HTTPS listener is not an API.
          deny 192.168.1.1;
          allow 192.168.1.0/24;
          allow 100.64.0.0/10;
          allow fd7a:115c:a1e0::/48;
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
}
