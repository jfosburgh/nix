{ self, ... }:
{
  services.kanata = {
    enable   = true;
    keyboards.default.configFile =
      "${self}/modules/nixos/kanata.kbd";
  };
}
