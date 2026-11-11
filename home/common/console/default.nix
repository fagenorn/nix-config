# The console as a user service on every host (issue 856): it serves the agent
# console on loopback port 27184 and starts with the user's session.
#
# On NixOS it is the systemd user unit `agent-console` (`Restart=always`,
# `WantedBy=default.target`); its log is in the journal
# (`journalctl --user -u agent-console`). The unit retries without limit: a console
# that cannot bind its port (a hand-started one still holds it at activation) fails
# at once, and with systemd's default start limit five such failures inside ten
# seconds leave the unit failed until the next activation, so `RestartSec` spaces the
# retries and `StartLimitIntervalSec = 0` removes the limit, and the unit serves
# within one interval of the port being freed. On darwin it is the nix-darwin agent in
# `hosts/common/darwin-console.nix`, which reads `agentConsole.command` and
# `agentConsole.path` from here so both hosts run one command.
#
# `PATH` carries gh because the tracker poll runs `gh` by name (not by store path), and
# a user service starts with a bare `PATH`. `/usr/bin:/bin` follows it for the system tools.
{
  config,
  lib,
  pkgs,
  agentTools,
  ...
}:
let
  consolePort = 27184;

  command = "${agentTools.launchers.console} --port ${toString consolePort}";

  path = "${lib.makeBinPath [ config.programs.gh.package ]}:/usr/bin:/bin";
in
{
  options.agentConsole = {
    command = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      description = "The console command: the launcher and its loopback port.";
    };
    path = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      description = "The PATH the console service runs with: gh's bin, then the system tools.";
    };
  };

  config = lib.mkMerge [
    {
      agentConsole = {
        inherit command path;
      };
    }
    (lib.mkIf pkgs.stdenv.isLinux {
      systemd.user.services.agent-console = {
        Unit = {
          Description = "agent console: the loopback status page (issue 856)";
          # Never give up on a busy port (issue 884); see the module comment.
          StartLimitIntervalSec = 0;
        };
        Service = {
          ExecStart = config.agentConsole.command;
          Environment = [ "PATH=${config.agentConsole.path}" ];
          Restart = "always";
          RestartSec = 3;
        };
        Install.WantedBy = [ "default.target" ];
      };
    })
  ];
}
