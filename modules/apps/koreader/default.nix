{...}: {
  flake.homeModules.koreader = {pkgs, ...}: {
    home.packages = [
      (pkgs.writeShellApplication {
        name = "kobo-install-koreader";
        runtimeInputs = [pkgs.python3 pkgs.curl];
        text = ''
          exec python3 ${./install.py} "$@"
        '';
      })
    ];
  };
}
