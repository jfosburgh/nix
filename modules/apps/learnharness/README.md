# LearnHarness

Packages the upstream x86_64 Linux AppImage with `appimageTools`; no FUSE or
system-wide AppImage support is required. The release URL and SHA-256 are pinned
in `default.nix`. Upstream does not currently publish an aarch64 Linux build.

## Try it

From the repository root:

```sh
nix run .#learnharness
```

The `learnharness` Home Manager module is included in the laptop and desktop
profiles, but not steammachine (glamdring). After applying one of those profiles, launch
`learnharness` from a terminal or **LearnHarness** from the application launcher.
No NixOS rebuild is needed just to try the package with `nix run`.

Configure a model provider in the app before starting a lesson. Provider usage
may incur charges. API keys are configured at runtime, not stored in the Nix
store. By default, settings, keys, and learning data live under
`${XDG_CONFIG_HOME:-$HOME/.config}/LearnHarness/`.

The extracted AppImage does not self-update. To update, change `version` and
`src.hash` in `default.nix`, obtaining the new hash with:

```sh
nix store prefetch-file --json \
  https://github.com/amosblomqvist/learnharness/releases/download/v<VERSION>/LearnHarness-<VERSION>-x86_64.AppImage
nix build .#learnharness
```

Packaging validation: build the package, evaluate the Home Manager profiles,
and launch with isolated XDG directories under Xvfb to verify that the bundled
server starts and the Electron window opens. This does not test paid model
requests or interactive lessons.
