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
	flake-parts.url = "github:hercules-ci/flake-parts";
	import-tree.url = "github:vic/import-tree";
	wrappers.url = "github:BirdeeHub/nix-wrapper-modules";
	zen-browser = {
	  url = "github:youwen5/zen-browser-flake";
	  inputs.nixpkgs.follows = "nixpkgs";
	};
  };

  outputs = inputs: inputs.flake-parts.lib.mkFlake { inherit inputs; } {
    imports = [
	  inputs.home-manager.flakeModules.home-manager
	  (inputs.import-tree ./modules)
	];
  };
}
