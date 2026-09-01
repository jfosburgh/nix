{...}: {
  flake.homeModules.vlc = {pkgs, ...}: {
    home.packages = [pkgs.vlc];
  };
}
