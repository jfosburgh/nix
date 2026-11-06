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
      # Repo-backed model registry; update the checkout on each Pi host together
      # with the service configuration. Opening /model reloads these entries.
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
      ".pi/agent/skills/karpathy-llm-wiki".source =
        config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/agents/skills/karpathy-llm-wiki";
    };

    home.sessionVariables = {
      LLAMA_BASE_URL = "http://127.0.0.1:11434";

      # Shared Blade-hosted search; clients need trusted LAN or tailnet access.
      SEARXNG_BASE_URL = "https://search.threegoldenhairs.me";
    };
  };

  # Retain the host module name for existing imports, but search is now
  # provided only by Blade's separate searxng module, not by each agent host.
  flake.nixosModules.agents = {...}: {};
}
