{...}: {
  flake.nixosModules.fonts = {pkgs, ...}: {
    fonts.packages = with pkgs; [
      noto-fonts-color-emoji
      nerd-fonts.iosevka-term
      nerd-fonts.symbols-only
    ];

    fonts.fontconfig.enable = true;
  };
}
