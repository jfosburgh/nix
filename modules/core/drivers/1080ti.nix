{...}: {
  flake.nixosModules.nvidia-1080ti = {
    config,
    pkgs,
    ...
  }: {
    environment.sessionVariables = {
      ELECTRON_OZONE_PLATFORM_HINT = "wayland";
    };

    environment.systemPackages = [pkgs.nvtopPackages.full];

    services.xserver.videoDrivers = ["nvidia"];

    hardware = {
      graphics = {
        enable = true;
        enable32Bit = true;
      };

      nvidia = {
        modesetting.enable = true;
        open = false;
        nvidiaSettings = true;
        package = config.boot.kernelPackages.nvidiaPackages.legacy_580;
      };
    };
  };
}
