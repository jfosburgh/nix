{inputs, ...}: {
  perSystem = {pkgs, ...}: let
    pi = inputs.pi.packages.${pkgs.stdenv.hostPlatform.system}.default;
  in {
    packages.pi-development-extensions = pkgs.buildNpmPackage {
      pname = "pi-development-extensions";
      version = "1.0.0";
      src = ./extensions;

      npmDepsHash = "sha256-kzfAKGYAHI2HW2HxsdDu47k+HajCaQoVW6Fxkv8FLLE=";
      npmFlags = ["--legacy-peer-deps"];
      npmRebuildFlags = ["--ignore-scripts"];
      dontNpmBuild = true;

      # Pi supplies its own host modules and typebox. Do not install peer copies.
      installPhase = ''
        runHook preInstall
        mkdir -p "$out"
        cp package.json package-lock.json "$out/"
        cp -r node_modules "$out/"
        runHook postInstall
      '';

      doInstallCheck = true;
      installCheckPhase = ''
        runHook preInstallCheck
        export HOME="$TMPDIR/check-home"
        export PI_CODING_AGENT_DIR="$HOME/agent"
        export PI_OFFLINE=1
        mkdir -p "$HOME"
        node check-load.mjs "$out" "${pi}/lib/pi/node_modules/@earendil-works/pi-coding-agent"
        runHook postInstallCheck
      '';

      meta = {
        description = "Pinned Pi questions, web access, and BTW extensions";
        platforms = ["x86_64-linux" "aarch64-linux"];
      };
    };
  };
}
