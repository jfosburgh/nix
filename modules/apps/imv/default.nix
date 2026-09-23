{...}: {
  flake.homeModules.imv = {pkgs, ...}: {
    home.packages = [pkgs.imv];
  };
}
