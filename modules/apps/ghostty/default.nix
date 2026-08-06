{ ... }: {
	flake.nixosModules.ghostty = { pkgs, ... }: {
		environment.systemPackages = [ pkgs.ghostty ];

		# Verify ghostty actually reads /etc/xdg -- if not, wrap it with
		# --config-file baked in instead (same trick as niri's --config).
		environment.etc."xdg/ghostty/config".source = ./config;
		environment.etc."xdg/ghostty/themes".source = ./themes;
	};
}
