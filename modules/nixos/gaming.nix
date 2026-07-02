{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
	vintagestory
  ];

  programs.steam = {
    enable = true;
	remotePlay.openFirewall = true;
	dedicatedServer.openFirewall = true;
	localNetworkGameTransfers.openFirewall = true;
	gamescopeSession.enable = true;
  };
}
