{
  self,
  moduleWithSystem,
  ...
}: {
  # A module can define any/all of these. flake.nixosModules.<name> and
  # flake.homeModules.<name> are just attributes under `flake` -- nothing
  # auto-wires them into a host or user. Something else (a host in
  # modules/hosts/, or a user in modules/users/) has to reference
  # `self.nixosModules.<name>` / `self.homeModules.<name>` in its own
  # `imports` list for this to actually do anything.

  # --- system-level (NixOS) ---
  # Packages, services, hardware, anything installed for every user of the
  # machine. Use this for local-only/GUI/WM/hardware things (per our
  # hybrid convention) -- stuff that only makes sense on this NixOS box.
  #
  # Plain `{ pkgs, ... }: { ... }` is enough most of the time. Only reach
  # for `moduleWithSystem` (as below) when the module body needs `self'`/
  # `inputs'` -- e.g. referencing a package built in this file's own
  # `perSystem` block, or another flake input's per-system output.
  flake.nixosModules.name = moduleWithSystem ({
    pkgs,
    self',
    inputs',
    ...
  }: let
    modules = with self.nixosModules; [];
  in {
    imports = modules;
    programs.name = {
      enable = true;
      package = self'.packages.hello;
    };
  });

  # --- home-manager (per-user) ---
  # Reserve this for things that should stay usable outside of NixOS too
  # (zsh, tmux, nvim, git, lazygit, ...): plain config files sourced via
  # `${./file}`, not baked into a wrapped package. A user glue module
  # (modules/users/james.nix) pulls these in via
  # `home-manager.users.james.imports = with self.homeModules; [ ... ];`
  #
  # Leave this out entirely for modules that are pure NixOS (like the
  # kanata module -- no home-manager needed there).
  flake.homeModules.name = {pkgs, ...}: {
    programs.name.enable = true;
  };

  # --- perSystem (per-architecture) ---
  # Anything that needs building per-system: packages, wrapped binaries
  # (inputs.wrappers), devShells, checks. `self'`/`inputs'` here are the
  # per-system views of `self`/`inputs` (e.g. `self'.packages.foo`).
  perSystem = {
    pkgs,
    lib,
    self',
    ...
  }: {
    packages.hello = pkgs.hello;
  };
}
