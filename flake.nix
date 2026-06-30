{
  description = "NixOS + Home Manager";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    helium.url = "github:amaanq/helium-flake";
    niri.url = "github:YaLUG/niri";
  };

  outputs = { self, nixpkgs, home-manager, helium, niri, ... }@inputs:
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
      sting      = mkHost { hostname = "sting"; };
      glamdring  = mkHost { hostname = "glamdring"; };
      pinas      = mkHost { hostname = "pinas"; system = "aarch64-linux"; };
    };

    homeConfigurations = {
      "desktop" = mkHome {
        username = "james";
        system = "x86_64-linux";
        modules = [
          ./home/james.nix
          ./modules/home/wm/niri.nix
        ];
      };

      "laptop" = mkHome {
        username = "james";
        system = "x86_64-linux";
        modules = [
          ./home/james.nix
          ./modules/home/wm/niri.nix
        ];
      };

      "server" = mkHome {
        username = "james";
        system = "x86_64-linux";
        modules = [
          ./home/james.nix
        ];
      };

      "arm-server" = mkHome {
        username = "james";
        system = "aarch64-linux";
        modules = [
          ./home/james.nix
        ];
      };
    };
  };
}
