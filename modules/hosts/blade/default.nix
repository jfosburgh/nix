{
  inputs,
  self,
  ...
}: {
  flake.nixosConfigurations.blade = inputs.nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    modules = with self.nixosModules; [
      locale
      nix
      james
      tailscale
      blade-configuration
      blade-hardware
    ];
  };
}
