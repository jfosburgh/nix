{ pkgs, inputs, ... }: {
  imports = [
    ./audio.nix
	./bluetooth.nix
	./power.nix
  ];
}
