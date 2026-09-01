{inputs, ...}: {
  flake.homeModules.zen = {...}: {
    home.packages = [
      inputs.zen-browser.packages.x86_64-linux.default
    ];

    # Zen (MOZ_LEGACY_PROFILES=1) keeps its profile under ~/.config/zen rather
    # than ~/.zen. "1gbxz4hh.Default Profile" is this machine's existing
    # profile id from ~/.config/zen/profiles.ini, not something Nix generates
    # deterministically, so this breaks if the profile is ever reset/recreated
    # or copied to a host with no (or a different) profile yet.
    home.file.".config/zen/1gbxz4hh.Default Profile/user.js".text = ''
      // VAAPI hardware video decode.
      user_pref("media.ffmpeg.vaapi.enabled", true);
      user_pref("media.hardware-video-decoding.force-enabled", true);

      // Fractional scaling and overscroll under Wayland.
      user_pref("widget.wayland.fractional-scale.enabled", true);
      user_pref("apz.overscroll.enabled", true);
      user_pref("widget.disable-swipe-tracker", false);
    '';
  };
}
