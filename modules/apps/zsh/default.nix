{ ... }: {
	flake.nixosModules.zsh = { pkgs, ... }: {
		programs.zsh.enable = true;
	};

	flake.homeModules.zsh = { pkgs, ... }: {
		programs.zsh = {
			enable = true;

			oh-my-zsh = {
				enable = true;
				theme = "robbyrussell";
				plugins = [ "git" "sudo" "copyfile" "copybuffer" ];
			};

			plugins = [
				{
					name = "zsh-autosuggestions";
					src = pkgs.zsh-autosuggestions;
					file = "share/zsh-autosuggestions/zsh-autosuggestions.zsh";
				}
				{
					name = "fast-syntax-highlighting";
					src = pkgs.zsh-fast-syntax-highlighting;
					file = "share/zsh/site-functions/fast-syntax-highlighting.plugin.zsh";
				}
			];

			history = {
				size = 10000;
				save = 10000;
				share = true;
			};

			initContent = ''
				source ${./envs}
				source ${./aliases}
				source ${./functions}
			'';
		};

		programs.starship = {
			enable = true;
			enableZshIntegration = true;
		};

		programs.zoxide = {
			enable = true;
			enableZshIntegration = true;
		};

		programs.fzf = {
			enable = true;
			enableZshIntegration = true;
		};
	};
}
