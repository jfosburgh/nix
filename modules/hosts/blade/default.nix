{
  inputs,
  self,
  ...
}: {
  flake.nixosConfigurations.blade = inputs.nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    modules = with self.nixosModules; [
      inputs.disko.nixosModules.disko
      locale
      nix
      james
      tailscale
      audiobookshelf
      bookorbit
      norish
      norish-planner
      jellyfin
      nextcloud
      immich
      dashboard
      forgejo
      budget-tracker
      strata-proxy
      searxng
      blade-configuration
      blade-backups
      blade-hardware
    ];
  };
}
