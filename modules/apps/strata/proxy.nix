{...}: {
  flake.nixosModules.strata-proxy = {...}: let
    domain = "strata.threegoldenhairs.me";
  in {
    services.headscale.settings.dns.extra_records = [
      {
        name = domain;
        type = "A";
        value = "100.64.0.1";
      }
    ];

    services.nginx.virtualHosts.${domain} = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://100.64.0.3:8081";
        # Port 8081 is the coordinator's restricted gateway, not a raw backend.
        # /v1 is Strata; /ollama/v1 is the native-backed OpenAI chat bridge.
        # The gateway never exposes admin or model load/unload controls.
        # No secret on Blade/Pi: LAN/tailnet membership grants inference access.
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
          # Match the coordinator's bounded 4 MiB cap for 256K code histories.
          client_max_body_size 4m;
          proxy_next_upstream off;
          proxy_buffering off;
          proxy_request_buffering off;
          proxy_read_timeout 3600s;
          proxy_send_timeout 3600s;
        '';
      };
    };
  };
}
