{
  inputs,
  self,
  ...
}: {
  flake.nixosConfigurations.narsil = inputs.nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    modules = with self.nixosModules; [
      graphical
      hyprland
      narsil-configuration
      narsil-strata-mode
      narsil-hardware
      amd-gpu
      james
      tailscale
      nix-ld
      steam
      ollama
      agents
    ];
  };
}
