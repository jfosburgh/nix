{ pkgs, ... }:
{
	services.ollama = {
		enable = true;
		acceleration = "vulkan";
	};

	home.packages = with pkgs; [
		pi-coding-agent
	];
}
