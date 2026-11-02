{...}: {
  flake.nixosModules.forgejo = {config, ...}: let
    domain = "git.threegoldenhairs.me";
  in {
    services.forgejo = {
      enable = true;
      stateDir = "/var/lib/forgejo";
      database.type = "sqlite3";
      lfs.enable = true;
      settings = {
        DEFAULT.APP_NAME = "Three Golden Hairs Git";
        server = {
          DOMAIN = domain;
          ROOT_URL = "https://${domain}/";
          HTTP_ADDR = "127.0.0.1";
          HTTP_PORT = 3001;
          # Keep Git SSH separate from Blade's administrative OpenSSH server.
          START_SSH_SERVER = true;
          SSH_DOMAIN = domain;
          SSH_PORT = 2222;
          SSH_LISTEN_PORT = 2222;
        };
        service.DISABLE_REGISTRATION = true;
        repository.DEFAULT_PRIVATE = "private";
        session.COOKIE_SECURE = true;
        # Runners execute repository code; provision them separately if needed.
        actions.ENABLED = false;
      };
    };

    environment.systemPackages = [config.services.forgejo.package];

    networking.firewall.allowedTCPPorts = [2222];

    services.nginx.virtualHosts.${domain} = {
      enableACME = true;
      forceSSL = true;
      locations."/" = {
        proxyPass = "http://127.0.0.1:3001";
        proxyWebsockets = true;
        extraConfig = ''
          client_max_body_size 512m;
          proxy_request_buffering off;
          proxy_read_timeout 600s;
          proxy_send_timeout 600s;
        '';
      };
    };

    services.headscale.settings.dns.extra_records = [{
      name = domain;
      type = "A";
      value = "100.64.0.1";
    }];
  };
}
