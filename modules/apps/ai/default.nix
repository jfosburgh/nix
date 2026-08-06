{ ... }: {
	flake.nixosModules.ai = { pkgs, ... }: {
		services.ollama = {
			enable = true;
			package = pkgs.ollama-vulkan;
		};
	};

	flake.homeModules.ai = { pkgs, ... }: {
		home.packages = [ pkgs.pi-coding-agent ];
	};
}
