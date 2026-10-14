{...}: {
  flake.nixosModules.localsend = {...}: {
    networking.firewall.allowedTCPPorts = [53317];
    networking.firewall.allowedUDPPorts = [53317];
  };

  flake.homeModules.localsend = {pkgs, ...}: {
    home.packages = [pkgs.localsend];
  };
}
