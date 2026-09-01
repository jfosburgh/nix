{ ... }: {
	flake.homeModules.beancount = { pkgs, config, ... }: {
		home.packages = [
			pkgs.beancount
		];

		systemd.user.services.fava = {
			Unit = {
				Description = "Fava web interface for beancount";
			};

			Service = {
				ExecStart = "${pkgs.fava}/bin/fava ${config.home.homeDirectory}/dev/misc/ledger/ledger.beancount";
				Restart = "on-failure";
			};

			Install = {
				WantedBy = [ "default.target" ];
			};
		};
	};
}
