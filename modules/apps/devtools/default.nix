{ ... }: {
	flake.homeModules.devtools = { pkgs, ... }: {
		home.packages = with pkgs; [
			ripgrep
			fd
			fzf
			eza
			bat
			rsync
			jq
			btop

			devenv

			man-pages
			man-db
		];
	};
}
