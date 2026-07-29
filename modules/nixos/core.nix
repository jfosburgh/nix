{ pkgs, inputs, ... }: {
  nix = {
    settings = {
      experimental-features = [ "nix-command" "flakes" ];
      auto-optimise-store = true;
    };
	gc = {
	  automatic = true;
	  dates = "weekly";
	  options = "--delete-older-than 14d";
	};
    registry.nixpkgs.flake = inputs.nixpkgs;
  };

  time.timeZone = "America/New_York";
  i18n.defaultLocale = "en_US.UTF-8";

  networking.networkmanager.enable = true;

  environment.systemPackages = with pkgs; [
    bash
    curl
    wget
    git
    vim
    rsync
    home-manager
  ];

  nixpkgs.config.allowUnfree = true;
}
