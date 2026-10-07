{...}: {
  flake.nixosModules.ollama = {pkgs, ...}: {
    services.ollama = {
      enable = true;
      package = pkgs.ollama-rocm;
      host = "0.0.0.0";
      port = 11434;
      openFirewall = true;
      loadModels = ["gemma4:12b"];
    };
  };
}
