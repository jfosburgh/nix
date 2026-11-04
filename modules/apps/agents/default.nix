{
  self,
  inputs,
  ...
}: {
  flake.homeModules.agents = {
    pkgs,
    config,
    dotfilesRoot,
    ...
  }: let
    extensions = self.packages.${pkgs.stdenv.hostPlatform.system}.pi-development-extensions;
  in {
    home.packages = [
      inputs.pi.packages.${pkgs.stdenv.hostPlatform.system}.default
      pkgs.claude-code
      pkgs.nodejs
    ];

    home.file = {
      ".pi/agent/models.json".source =
        config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/agents/models.json";

      # Writable repo-backed settings: Pi's own writes to this file show up as
      # working-tree changes here, so they are reviewed like any other config edit.
      ".pi/agent/settings.json".source =
        config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/agents/settings.json";

      # Discover only these three extensions; dependencies stay outside discovery paths.
      ".pi/agent/nix-packages".source = extensions;
      ".pi/agent/extensions/development.ts".text = ''
        export { default } from "${extensions}/node_modules/@juicesharp/rpiv-ask-user-question/index.ts";
      '';
      ".pi/agent/extensions/web-access.ts".text = ''
        export { default } from "${extensions}/node_modules/pi-web-access/dist/index.js";
      '';
      ".pi/agent/extensions/btw.ts".text = ''
        export { default } from "${extensions}/node_modules/pi-btw/extensions/btw.ts";
      '';
      ".pi/agent/skills/btw".source = "${extensions}/node_modules/pi-btw/skills/btw";
    };

    home.sessionVariables = {
      LLAMA_BASE_URL = "http://127.0.0.1:11434";

      # Local SearXNG backend for pi-web-access' web_search (auto mode prefers it).
      SEARXNG_BASE_URL = "http://127.0.0.1:8888";
    };
  };

  flake.nixosModules.agents = {...}: {
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

          # Substituted from environmentFile at unit start; keeps the secret
          # out of the Nix store.
          secret_key = "\${SEARXNG_SECRET}";
        };

        # This SearXNG release gates non-HTML output behind an explicit opt-in;
        # without this pi-web-access' format=json queries get 403.
        search.formats = ["html" "json"];
      };
    };
  };
}
