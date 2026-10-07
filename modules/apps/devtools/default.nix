{...}: {
  flake.homeModules.devtools = {pkgs, ...}: {
    home.packages = with pkgs; [
      ripgrep
      fd
      fzf
      eza
      bat
      rsync
      jq
      btop
	  unzip
	  bluetui
      nvtopPackages.full

      devenv

      man-pages
      man-db
    ];
  };
}
