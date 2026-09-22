{inputs, ...}: {
  flake.homeModules.zen = {
    config,
    pkgs,
    ...
  }: let
    profileRelPath = ".config/zen/1gbxz4hh.Default Profile/user.js";
    userJs = pkgs.writeText "zen-user.js" ''
      // VAAPI hardware video decode.
      user_pref("media.ffmpeg.vaapi.enabled", true);
      user_pref("media.hardware-video-decoding.force-enabled", true);

      // Fractional scaling and overscroll under Wayland.
      user_pref("widget.wayland.fractional-scale.enabled", true);
      user_pref("apz.overscroll.enabled", true);
      user_pref("widget.disable-swipe-tracker", false);
    '';
  in {
    home.packages = [
      inputs.zen-browser.packages.x86_64-linux.default
    ];

    # "1gbxz4hh.Default Profile" is this machine's zen profile id (from
    # ~/.config/zen/profiles.ini) -- not stable across a profile reset.
    # Copied via activation, not home.file: noctalia's zen-browser template
    # rewrites user.js in place, which fails against a Nix store symlink.
    home.activation.zenUserJs = config.lib.dag.entryAfter ["writeBoundary"] ''
      target="$HOME/${profileRelPath}"
      mkdir -p "$(dirname "$target")"
      install -m644 ${userJs} "$target"
    '';
  };
}
