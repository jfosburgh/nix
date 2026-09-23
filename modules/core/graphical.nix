{
  self,
  inputs,
  ...
}: {
  # Autologin/session picking is per-host, in each host's -configuration.nix.
  flake.nixosModules.graphical = {
    pkgs,
    config,
    lib,
    ...
  }: {
    imports = with self.nixosModules;
      [
        core
        power
        audio
        bluetooth
        kanata
        fonts
      ]
      ++ [inputs.noctalia-greeter.nixosModules.default];

    services.displayManager.noctalia-greeter = {
      enable = true;
      cursorTheme.package = pkgs.bibata-cursors;
      # Without this, the autostart-triggered `noctalia msg greeter-sync`
      # prompts for a password (pkexec) on every login.
      passwordless-sync-users =
        ["james"] ++ lib.optional (config.users.users ? work) "work";
      settings = {
        appearance = {
          scheme = "Synced";
          hide_logo = true;
          # Matches the shell's own corner_radius_scale in
          # noctalia-settings.toml, not Hyprland's window rounding (a
          # different, pixel-based unit).
          corner_radius_scale = 0.3;
        };
        cursor.theme = "Bibata-Original-Classic";
      };
    };
  };
}
