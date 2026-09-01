# TODO: figure out what of this is actually needed r.e. unfree
{
  inputs,
  self,
  ...
}: {
  perSystem = {
    config,
    lib,
    system,
    ...
  }: {
    _module.args.unfreePkgs = import inputs.nixpkgs {
      inherit system;
      config.allowUnfree = true;
    };

    _module.args.pkgs = import inputs.nixpkgs {
      inherit system;
    };

    legacyPackages = import inputs.nixpkgs {
      inherit system;
      config.allowUnfree = true;
      overlays = [self.overlays.hyprland-glaze-fix];
    };
  };

  flake.nixosModules.nix = {...}: {
    nix = {
      gc = {
        automatic = true;
        dates = "weekly";
        options = "--delete-older-than 5d";
      };

      optimise.automatic = true;

      registry.nixpkgs.flake = inputs.nixpkgs;

      settings = {
        experimental-features = [
          "nix-command"
          "flakes"
        ];
        auto-optimise-store = true;
      };
    };

    nixpkgs = {
      config = {
        allowUnfree = true;
        packageOverrides = pkgs: {
          unstable = import inputs.nixpkgs-unstable {
            config = {
              allowUnfree = true;
            };
          };
        };
      };
    };
  };
}
