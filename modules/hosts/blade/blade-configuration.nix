{...}: {
  flake.nixosModules.blade-configuration = {pkgs, ...}: {
    boot.loader.systemd-boot.enable = true;
    boot.loader.efi.canTouchEfiVariables = true;

    networking.hostName = "blade";

    networking.useNetworkd = true;
    systemd.network.enable = true;
    systemd.network.networks."10-wired" = {
      matchConfig.Name = "eth*";
      networkConfig.DHCP = "yes";
    };

    services.openssh = {
      enable = true;
      settings = {
        PasswordAuthentication = true;
        PermitRootLogin = "no";
      };
    };

    zramSwap.enable = true;
    systemd.oomd.enable = true;

    # Coordination server for the headscale/tailscale network the rest of
    # the fleet will join. DERP left on headscale's default (Tailscale's
    # public DERP map) rather than self-hosting relay, since that needs
    # direct UDP reachability this box doesn't have yet.
    #
    # headscale.threegoldenhairs.me resolves through the existing
    # Namecheap -> Cloudflare -> nginx-on-homeassistant chain; that nginx
    # needs a reverse-proxy entry pointing at blade's LAN IP on port 8080
    # once blade has one. TLS is terminated there, not on blade.
    services.headscale = {
      enable = true;
      address = "0.0.0.0";
      port = 8080;
      settings = {
        server_url = "https://headscale.threegoldenhairs.me";
        dns = {
          base_domain = "ts.threegoldenhairs.me";
          nameservers.global = ["1.1.1.1" "1.0.0.1"];
        };
      };
    };

    networking.firewall.allowedTCPPorts = [8080];

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
