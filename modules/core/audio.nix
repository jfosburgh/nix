{ ... }: {
	flake.nixosModules.audio = { pkgs, ... }: {
		services = {
			pulseaudio.enable = false;

			pipewire = {
				enable = true;
				alsa.enable = true;
				alsa.support32Bit = true;
				jack.enable = true;
				pulse.enable = true;
				wireplumber.enable = true;
			};
		};

		environment.systemPackages = [ pkgs.wiremix ];
	};
}
