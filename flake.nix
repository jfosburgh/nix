{
  description = "NixOS + Home Manager";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    helium.url = "github:AlvaroParker/helium-nix";
	niri.url = "github:sodiboo/niri-flake";
	noctalia.url = "github:noctalia-dev/noctalia/cachix";
  };

  outputs = { self, nixpkgs, home-manager, helium, niri, noctalia, ... }@inputs:
  let
    mkHost = { hostname, system ? "x86_64-linux" }: nixpkgs.lib.nixosSystem {
      inherit system;
      specialArgs = { inherit inputs self; };
      modules = [
        ./hosts/${hostname}/default.nix
      ];
    };

    mkHome = { username, system ? "x86_64-linux", modules }: home-manager.lib.homeManagerConfiguration {
      pkgs = nixpkgs.legacyPackages.${system};
      extraSpecialArgs = { inherit inputs self; };
      modules = [
        {
          home = {
            inherit username;
            homeDirectory = if nixpkgs.lib.hasSuffix "darwin" system then "/Users/${username}" else "/home/${username}";
          };
        }
      ] ++ modules;
    };
  in {
    nixosConfigurations = {
      glamdring  = mkHost { hostname = "glamdring"; };
    };

    homeConfigurations = {
      "desktop" = mkHome {
        username = "james";
        system = "x86_64-linux";
        modules = [
          ./home/desktop.nix
        ];
      };
    };
  };
}
