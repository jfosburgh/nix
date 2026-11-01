{...}: {
  flake.nixosModules.budget-tracker = {pkgs, lib, ...}: {
    environment.systemPackages = [
      pkgs.budget-tracker-tui
      (pkgs.writeShellApplication {
        name = "budget-tracker";
        runtimeInputs = [pkgs.tmux];
        text = ''
          # Keep financial data private and share one app instance across hosts.
          umask 077
          exec tmux -L budget-tracker new-session -A -s budget ${lib.getExe pkgs.budget-tracker-tui}
        '';
      })
    ];
  };

  flake.homeModules.budget-tracker = {pkgs, ...}: {
    home.packages = [
      (pkgs.writeShellApplication {
        name = "budget";
        runtimeInputs = [pkgs.openssh];
        text = ''
          # Use a widely available terminfo entry, including from Ghostty.
          export TERM=xterm-256color
          exec ssh -t james@blade /run/current-system/sw/bin/budget-tracker
        '';
      })
    ];
  };
}
