{...}: {
  flake.homeModules.vintagestory = {pkgs, ...}: {
    home.packages = [
      pkgs.vintagestory
    ];
  };
}
