{...}: {
  flake.nixosModules.fonts = {pkgs, ...}: {
    fonts.packages = with pkgs; [
      noto-fonts-color-emoji
      nerd-fonts.iosevka-term
      nerd-fonts.symbols-only
    ];

    fonts.fontconfig.enable = true;

    # Make the terminal's Nerd Font the actual "monospace"/"sans-serif" alias,
    # so any app that asks fontconfig for a generic family (not just terminals
    # with their font hardcoded) gets matching glyphs instead of falling back
    # to DejaVu. Serif is left alone so prose (reader views, PDFs) stays on a
    # normal reading font.
    fonts.fontconfig.defaultFonts = {
      monospace = ["IosevkaTerm Nerd Font" "Noto Color Emoji"];
      sansSerif = ["IosevkaTerm Nerd Font" "Noto Color Emoji"];
    };
  };
}
