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

    # Zen (MOZ_LEGACY_PROFILES=1) keeps its profile under ~/.config/zen rather
    # than ~/.zen. "1gbxz4hh.Default Profile" is this machine's existing
    # profile id from ~/.config/zen/profiles.ini, not something Nix generates
    # deterministically, so this breaks if the profile is ever reset/recreated
    # or copied to a host with no (or a different) profile yet.
    #
    # Deployed via an activation script (copy) rather than home.file (symlink):
    # the noctalia zen-browser theme template rewrites user.js in place to wire
    # up userChrome/userContent.css, which fails outright against a read-only
    # symlink into the Nix store (touch/cat get EACCES on the target).
    home.activation.zenUserJs = config.lib.dag.entryAfter ["writeBoundary"] ''
      target="$HOME/${profileRelPath}"
      mkdir -p "$(dirname "$target")"
      install -m644 ${userJs} "$target"
    '';
  };
}
