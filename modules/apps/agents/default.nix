{ ... }: {
	flake.homeModules.agents = { pkgs, config, dotfilesRoot, ... }: {
		home.packages = [
			pkgs.pi-coding-agent
			pkgs.claude-code
			pkgs.nodejs
		];

		home.file.".pi/agent/models.json".source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/agents/models.json";

		home.sessionVariables = {
			LLAMA_BASE_URL = "http://127.0.0.1:8080";

			# Local SearXNG backend for pi-web-access' web_search (auto mode prefers it).
			SEARXNG_BASE_URL = "http://127.0.0.1:8888";
		};
	};

	flake.nixosModules.agents = { ... }: {
		services.searx = {
			enable = true;

			# Read by systemd as root at unit start, so ProtectHome is no obstacle;
			# keeps the secret out of the Nix store.
			environmentFile = "/home/james/.config/searxng/env";

			settings = {
				server = {
					bind_address = "127.0.0.1";
					port = 8888;

					# pi-web-access queries SearXNG over GET (?format=json); the upstream
					# default is POST which would 405 those requests.
					method = "GET";
				};

				# This SearXNG release gates non-HTML output behind an explicit opt-in;
				# without this pi-web-access' format=json queries get 403.
				search.formats = [ "html" "json" ];
			};
		};
	};
}
