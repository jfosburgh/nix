{...}: {
  flake.homeModules.rbw = {pkgs, ...}: {
    programs.rbw = {
      enable = true;
      settings = {
        email = "jwfosburgh@gmail.com";
        base_url = "https://bitwarden.threegoldenhairs.me";
        pinentry = pkgs.pinentry-curses;
      };
    };
  };
}
