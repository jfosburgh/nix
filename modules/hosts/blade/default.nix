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
      immich
      blade-configuration
      blade-hardware
    ];
  };
}
