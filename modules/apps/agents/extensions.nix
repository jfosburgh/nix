{inputs, ...}: {
  perSystem = {pkgs, ...}: let
    pi = inputs.pi.packages.${pkgs.stdenv.hostPlatform.system}.default;
  in {
    packages.pi-development-extensions = pkgs.buildNpmPackage {
      pname = "pi-development-extensions";
      version = "1.0.0";
      src = ./extensions;

      npmDepsHash = "sha256-rmo9x5btet7z2iMWiAXmg//F5IdHOVhhfj1MTQYQEkI=";
      npmFlags = ["--legacy-peer-deps"];
      npmRebuildFlags = ["--ignore-scripts"];
      dontNpmBuild = true;

      nativeBuildInputs = [pkgs.autoPatchelfHook];
      buildInputs = [pkgs.stdenv.cc.cc.lib];

      # Pi supplies its own host modules and typebox. Do not install peer copies.
      # Published packages already include their runtime JS/TS and grammar assets.
      installPhase = ''
        runHook preInstall
        # This reviewed script only copies the already-fetched platform binaries.
        node node_modules/@ast-grep/cli/postinstall.js

        test "$(node -p 'require("./node_modules/pi-lens/package.json").version')" = "4.4.8"
        test "$(grep -rl --include='*.js' 'function resolvePiLensFlagWithSource' node_modules/pi-lens/dist | wc -l)" -eq 2
        patch --batch --fuzz=0 -p1 -d node_modules/pi-lens < lens-diagnostics-only.patch

        mkdir -p "$out/subagent"
        cp package.json package-lock.json "$out/"
        cp -r node_modules roles agents checks "$out/"
        cp ${inputs.pi}/packages/coding-agent/examples/extensions/subagent/{index.ts,agents.ts,README.md} "$out/subagent/"
        cp ${inputs.pi}/LICENSE "$out/subagent/LICENSE"
        chmod u+w "$out/subagent/index.ts"
        patch --batch --fuzz=0 -p1 -d "$out/subagent" < subagent-worker-isolation.patch
        runHook postInstall
      '';

      doInstallCheck = true;
      installCheckPhase = ''
        runHook preInstallCheck
        "$out/node_modules/.bin/ast-grep" --version
        node -e '
          const assert = require("node:assert/strict");
          const {Lang, parse} = require(process.argv[1] + "/node_modules/@ast-grep/napi");
          assert.equal(parse(Lang.JavaScript, "let value = 1;").root().kind(), "program");
        ' "$out"
        test ! -e "$out/node_modules/@earendil-works"
        test ! -e "$out/node_modules/typebox"

        export HOME="$TMPDIR/check-home"
        export PI_CODING_AGENT_DIR="$HOME/agent"
        export PI_LENS_HOME="$HOME/lens"
        export PI_LENS_DISABLE_LSP_INSTALL=1
        export PI_LENS_DISABLE_TOOL_INSTALL=1
        export PI_OFFLINE=1
        mkdir -p "$HOME"
        node check-load.mjs "$out" "${pi}/lib/pi/node_modules/@earendil-works/pi-coding-agent"
        node check-lens.mjs "$out" "${pi}/lib/pi/node_modules/@earendil-works/pi-coding-agent"
        node check-worker.mjs "$out" "${pi}/lib/pi/node_modules/@earendil-works/pi-coding-agent"
        runHook postInstallCheck
      '';

      meta = {
        description = "Pinned Pi development extensions and their runtime dependencies";
        platforms = ["x86_64-linux" "aarch64-linux"];
      };
    };
  };
}
