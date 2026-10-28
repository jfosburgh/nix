{self, ...}: {
  perSystem = {
    pkgs,
    lib,
    ...
  }: {
    packages = lib.optionalAttrs (pkgs.stdenv.hostPlatform.system == "x86_64-linux") {
      learnharness = let
        pname = "learnharness";
        version = "0.3.7";
        src = pkgs.fetchurl {
          url = "https://github.com/amosblomqvist/learnharness/releases/download/v${version}/LearnHarness-${version}-x86_64.AppImage";
          hash = "sha256-7zRlGDOxGOpcdEnM2UUFgBB66xg+bHGrFQdrQ7xFGOw=";
        };
        appimageContents = pkgs.appimageTools.extract {
          inherit pname version src;
        };
      in
        pkgs.appimageTools.wrapType2 {
          inherit pname version src;

          extraInstallCommands = ''
            install -Dm644 ${appimageContents}/learnharness.desktop $out/share/applications/learnharness.desktop
            substituteInPlace $out/share/applications/learnharness.desktop \
              --replace-fail 'Exec=AppRun' "Exec=$out/bin/learnharness"
            cp -r ${appimageContents}/usr/share/icons $out/share/
          '';

          meta = {
            description = "AI-powered adaptive teaching, practice, and a persistent knowledge graph";
            homepage = "https://github.com/amosblomqvist/learnharness";
            license = lib.licenses.agpl3Only;
            platforms = ["x86_64-linux"];
            mainProgram = "learnharness";
          };
        };
    };
  };

  flake.homeModules.learnharness = {pkgs, ...}: {
    home.packages = [self.packages.${pkgs.stdenv.hostPlatform.system}.learnharness];
  };
}
