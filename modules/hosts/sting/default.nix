{
  inputs,
  self,
  ...
}: {
  flake.nixosConfigurations.sting = inputs.nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    modules = with self.nixosModules; [
      laptop
      hyprland
      sting-configuration
      sting-hardware
      amd-gpu
      james
      nix-ld
      agents
    ];
  };
}
