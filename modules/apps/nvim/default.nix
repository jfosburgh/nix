{ ... }: {
	flake.homeModules.nvim = { pkgs, lib, config, dotfilesRoot, ... }: {
		programs.neovim.enable = true;

		# nvim-treesitter compiles its own parsers, so it needs a compiler.
		# Everything else (LSPs, formatters, toolchains) comes from devenv.
		home.packages = with pkgs; [
			tree-sitter
			gcc
		];

		xdg.configFile.nvim.source =
			config.lib.file.mkOutOfStoreSymlink "${dotfilesRoot}/modules/apps/nvim/config";

		xdg.configFile."nvim/init.lua".enable = lib.mkForce false;
	};
}
