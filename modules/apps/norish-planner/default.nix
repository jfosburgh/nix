{self, ...}: {
  perSystem = {pkgs, ...}: {
    packages.norish-planner = pkgs.writeShellApplication {
      name = "norish-planner";
      runtimeInputs = [pkgs.python3];
      text = ''
        exec python3 ${../../../scripts/norish-planner.py} "$@"
      '';
    };
  };

  flake.nixosModules.norish-planner = {pkgs, ...}: {
    environment.systemPackages = [self.packages.${pkgs.stdenv.hostPlatform.system}.norish-planner];
  };
}
