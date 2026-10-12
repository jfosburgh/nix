{...}: {
  flake.nixosModules.blade-configuration = {pkgs, ...}: {
    boot.loader.systemd-boot.enable = true;
    boot.loader.efi.canTouchEfiVariables = true;

    networking.hostName = "blade";

    networking.useNetworkd = true;
    systemd.network.enable = true;
    systemd.network.networks."10-wired" = {
      matchConfig.Name = "enp2s0";
      networkConfig.DHCP = "yes";
    };

    services.openssh = {
      enable = true;
      settings = {
        PasswordAuthentication = true;
        KbdInteractiveAuthentication = false;
        PermitRootLogin = "no";
      };
    };

    users.users.james.openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOCJlsTWKZJG5/95FeLb0+3/DEkjFCnGtyXA/Hs2BUd+"
    ];
    # Key-only remote administration; no initial account password is needed.
    security.sudo.extraRules = [{
      users = ["james"];
      commands = [{ command = "ALL"; options = ["NOPASSWD"]; }];
    }];

    zramSwap.enable = true;
    systemd.oomd.enable = true;

    services.tailscale = {
      useRoutingFeatures = "server";
      extraSetFlags = ["--advertise-exit-node"];
    };

    services.headscale = {
      enable = true;
      address = "127.0.0.1";
      port = 8080;
      settings = {
        server_url = "https://headscale.threegoldenhairs.me";
        dns = {
          base_domain = "ts.threegoldenhairs.me";
          nameservers.global = ["1.1.1.1" "1.0.0.1"];
        };
      };
    };

    services.vaultwarden = {
      enable = true;
      dbBackend = "sqlite";
      backupDir = "/var/backup/vaultwarden";
      config = {
        DOMAIN = "https://bitwarden.threegoldenhairs.me";
        ROCKET_ADDRESS = "127.0.0.1";
        ROCKET_PORT = 8222;
        SIGNUPS_ALLOWED = false;
      };
    };

    security.acme = {
      acceptTerms = true;
      defaults.email = "jwfosburgh@gmail.com";
    };

    services.nginx = {
      enable = true;
      recommendedTlsSettings = true;
      recommendedProxySettings = true;
      recommendedGzipSettings = true;
      recommendedOptimisation = true;

      virtualHosts = {
        "homeassistant.threegoldenhairs.me" = {
          enableACME = true;
          forceSSL = true;
          locations."/" = {
            proxyPass = "http://100.64.0.4:8123";
            proxyWebsockets = true;
          };
        };

        "bitwarden.threegoldenhairs.me" = {
          enableACME = true;
          forceSSL = true;
          locations."/" = {
            proxyPass = "http://127.0.0.1:8222";
            proxyWebsockets = true;
            extraConfig = ''
              client_max_body_size 128m;
            '';
          };
        };

        "headscale.threegoldenhairs.me" = {
          enableACME = true;
          forceSSL = true;
          locations."/" = {
            proxyPass = "http://127.0.0.1:8080";
            proxyWebsockets = true;
            extraConfig = ''
              proxy_buffering off;
              proxy_read_timeout 600s;
              proxy_send_timeout 600s;
            '';
          };
        };
      };
    };

    networking.firewall.allowedTCPPorts = [80 443];

    environment.systemPackages = with pkgs; [
      git
      vim
      rsync
      restic
    ];

    nix.settings.trusted-users = ["root" "james"];

    services.journald.settings.Journal.SystemMaxUse = "50M";

    system.stateVersion = "25.11";
  };
}
