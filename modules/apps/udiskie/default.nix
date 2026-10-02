{...}: {
  flake.homeModules.udiskie = {...}: {
    # Hyprland has no session component that watches udisks2 for new
    # devices the way GNOME's settings daemon does, so removable drives
    # never auto-mount there without a client like this running.
    services.udiskie = {
      enable = true;
      tray = "never";

      # device_mounted/device_unmounted are the only lifecycle events worth
      # a popup -- device_added/device_removed just duplicate them one
      # step earlier/later (device appears -> gets automounted; device is
      # unmounted -> disappears), so they're silenced explicitly here
      # rather than relying on upstream's own defaults for them.
      settings.notifications = {
        device_mounted = 5;
        device_unmounted = 5;
        device_added = false;
        device_removed = false;
      };

      settings.program_options = {
        # udiskie Popen()s this verbatim (argv[0] resolved via PATH, then
        # the mount path appended as the final arg) -- it never goes
        # through a shell. launch-floating-yazi (modules/apps/hyprland)
        # opens that path in yazi inside a Ghostty window tagged to match
        # Hyprland's existing float-floatterm window rule, instead of
        # falling through to xdg-open's default (a browser) or tiling.
        file_manager = "launch-floating-yazi";
      };
    };
  };
}
