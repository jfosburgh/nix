{self, ...}: {
  flake.nixosModules.james = {pkgs, ...}: {
    imports = with self.nixosModules; [
      zsh
    ];

    users.users.james = {
      isNormalUser = true;
      description = "James";
      # Let logind grant audio-device access to the active seat session only.
      # Static audio membership lets an inactive VT keep the sound card busy.
      extraGroups = ["networkmanager" "wheel" "video" "render" "i2c"];
      shell = pkgs.zsh;
    };
  };
}
