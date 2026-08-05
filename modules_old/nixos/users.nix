{ pkgs, ... }: {
  programs.zsh.enable = true;

  users.users.james = {
    isNormalUser = true;
    description = "James";
    extraGroups = [ "networkmanager" "wheel" "video" "audio" "render" ];
    shell = pkgs.zsh;
  };
}
