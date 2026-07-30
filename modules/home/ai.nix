{ config, pkgs, ... }:
{
	home.packages = with pkgs; [
		llama-cpp-vulkan
	];

	services.ollama = {
		enable = true;
		package = pkgs.ollama-vulkan;
	};

	programs.pi-coding-agent.enable = true;
}
