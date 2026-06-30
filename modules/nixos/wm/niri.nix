{ pkgs, inputs, ... }: {
  hardware.graphics = {
    enable = true;
    enable32Bit = true;
  };

  programs.niri = {
    enable = true;
    package = inputs.niri.packages.${pkgs.system}.niri;
  };

  xdg.portal = {
    enable = true;
    config.common.default = [ "gnome" "wlr" ];
    extraPortals = with pkgs; [
      xdg-desktop-portal-gnome
      xdg-desktop-portal-wlr
    ];
  };

  services.greetd = {
    enable = true;
    settings = {
      default_session = {
        command = "${pkgs.greetd.tuigreet}/bin/tuigreet --time --cmd niri";
        user = "greeter";
      };
    };
  };
  environment.systemPackages = [ pkgs.greetd.tuigreet ];
}
