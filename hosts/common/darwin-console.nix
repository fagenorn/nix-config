# Issue 856: the console's darwin user agent (the page and service of home/common/console).
#
# Declared with `command`, never `serviceConfig.ProgramArguments`, so launchd waits for
# the Nix volume before starting it (the rule in CLAUDE.md). `RunAtLoad` starts it at
# login in gui/<uid> and `KeepAlive` restarts it whenever it exits.
#
# launchd gives a user agent no login-shell environment, so `PATH` carries gh's bin (the
# tracker calls run `gh` by name) and `HOME` is set because the console's state root is
# read from `$HOME` with no fallback. Output goes to one log file in ~/Library/Logs.
{
  config,
  username,
  ...
}:
let
  user = config.home-manager.users.${username};
  ac = user.agentConsole;
  home = user.home.homeDirectory;
  log = "${home}/Library/Logs/agent-console.log";
in
{
  launchd.user.agents.agent-console = {
    command = ac.command;
    serviceConfig = {
      Label = "org.nixos.agent-console";
      RunAtLoad = true;
      KeepAlive = true;
      EnvironmentVariables = {
        PATH = ac.path;
        HOME = home;
      };
      StandardOutPath = log;
      StandardErrorPath = log;
    };
  };
}
