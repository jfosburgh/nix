{...}: {
  flake.nixosModules.ollama = {pkgs, ...}: {
    services.ollama = {
      enable = true;
      # narsil has an AMD GPU; rocm is the accelerated backend for that
      # (vulkan is llama.cpp's fallback, not needed here).
      acceleration = "rocm";
      # 9070 is RDNA4 (gfx1201); ROCm in nixpkgs may not yet list it as
      # officially supported, so report it as the nearest supported target.
      rocmOverrideGfx = "11.0.0";
      host = "0.0.0.0";
      port = 11434;
      openFirewall = true;
      loadModels = ["gemma4:12b"];
    };
  };
}
