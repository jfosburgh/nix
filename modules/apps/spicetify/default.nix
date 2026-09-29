{...}: {
  flake.homeModules.spicetify = {
    pkgs,
    lib,
    config,
    ...
  }: let
    comfy = pkgs.fetchFromGitHub {
      owner = "Comfy-Themes";
      repo = "Spicetify";
      rev = "32ff101e27cfd33d85b7cc587f7f95db6b2df8b0";
      hash = "sha256-sqvmSXJMLE2in/cB8ZIJE/t4J5D0PKRddWECdYJjgX0=";
    };

    spotifyTree = "${config.xdg.dataHome}/spicetify/spotify";

    # nixpkgs' bin/spotify is a generated env wrapper whose last line execs
    # .spotify-wrapped by absolute store path. Repointing that one line is
    # enough to run the spiced copy while keeping the wrapper's LD_LIBRARY_PATH
    # and friends intact.
    spicedSpotify = pkgs.runCommand "spotify-spiced" {} ''
      mkdir -p $out/bin $out/share
      ln -s ${pkgs.spotify}/share/applications $out/share/applications
      ln -s ${pkgs.spotify}/share/icons $out/share/icons

      substitute ${pkgs.spotify}/share/spotify/spotify $out/bin/spotify \
        --replace-fail \
          ${pkgs.spotify}/share/spotify/.spotify-wrapped \
          ${spotifyTree}/.spotify-wrapped
      chmod +x $out/bin/spotify
    '';

    spicetify-sync = pkgs.writeShellApplication {
      name = "spicetify-sync";
      runtimeInputs = with pkgs; [spicetify-cli coreutils findutils];
      text =
        ''
          export SPOTIFY_SHARE=${pkgs.spotify}/share/spotify
          export SPOTIFY_TREE=${spotifyTree}
          export COMFY_SRC=${comfy}/Comfy
          export SPICE_CONFIG=${config.xdg.configHome}/spicetify
        ''
        + builtins.readFile ./scripts/spicetify-sync;
    };
  in {
    home.packages = [
      spicedSpotify
      spicetify-sync

      # On PATH for noctalia: its spicetify template's post_hook shells out to
      # `spicetify -q apply` whenever the palette changes.
      pkgs.spicetify-cli
    ];

    home.activation.spicetify = lib.hm.dag.entryAfter ["writeBoundary"] ''
      run ${lib.getExe spicetify-sync}
    '';
  };
}
