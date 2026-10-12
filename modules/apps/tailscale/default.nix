{...}: {
  flake.nixosModules.tailscale = {...}: {
    services.tailscale = {
      enable = true;
      # Allow direct WireGuard connections instead of relying on DERP relays.
      openFirewall = true;
    };

    # Enrollment is a one-time operation, not a reusable key in the Nix store.
    # See docs/headscale.md for the login-server and approval commands.
  };
}
