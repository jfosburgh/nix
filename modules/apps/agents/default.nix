{ ... }: {
	flake.homeModules.agents = { pkgs, config, dotfilesRoot, ... }: {
		home.packages = [
			pkgs.pi-coding-agent
			pkgs.claude-code
			pkgs.nodejs
		];

		home.file.".pi/agent/models.json".source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/agents/models.json";

		home.sessionVariables.LLAMA_BASE_URL = "http://127.0.0.1:8080";
	};
}
