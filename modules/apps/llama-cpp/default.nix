{...}: {
  flake.nixosModules.llama-cpp = {pkgs, ...}: let
    llama-cpp-vulkan = pkgs.llama-cpp.override {
      vulkanSupport = true;
    };

    maxModels = 1;
    reasoningBudget = 4096;
    modelsPreset = pkgs.writeText "llama-cpp-presets.ini" ''
      version = 1

      [*]
      load-mode = none
      ctx-size = 131072
      fit = on
      fitt = 4096
      fit-ctx = 131072
      fa = on
      reasoning-preserve = true
      temp = 0.6
      top-p = 0.95
      top-k = 20
      min-p = 0.0
      repeat-penalty = 1.0
      ngl = -1
      np = 1

      [qwen38-q4]
      hf-repo = unsloth/Qwen3.8-27B-GGUF:UD-IQ4_XS
      ctx-size = 112000
      presence-penalty = 0.0
      cache-type-k = q4_0
      cache-type-v = q4_0
      t = 8
    '';
  in {
    services.llama-cpp = {
      enable = true;
      package = llama-cpp-vulkan;
      settings.models-preset = "${modelsPreset}";
      settings.host = "0.0.0.0";
      openFirewall = true;
    };

    systemd.services.llama-cpp.serviceConfig.Environment = [
      "XDG_CACHE_HOME=/var/cache/llama-cpp"
    ];

    environment.systemPackages = [llama-cpp-vulkan];
  };
}
