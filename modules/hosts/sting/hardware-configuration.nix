# Placeholder — sting hasn't been installed yet. Replace this file's contents with
# the output of `nixos-generate-config --root /mnt` after the fresh install. The
# fileSystems entry below is a stub (not a real device) so `nix flake check` can
# still evaluate system.build.toplevel for every other host in the meantime.
{ lib, ... }: {
	flake.nixosModules.sting-hardware = { ... }: {
		fileSystems."/" = {
			device = "/dev/disk/by-uuid/00000000-0000-0000-0000-000000000000";
			fsType = "ext4";
		};

		swapDevices = [ ];

		nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
	};
}
