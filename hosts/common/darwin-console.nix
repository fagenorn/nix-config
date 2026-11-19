# Issue 856: the console's darwin service (the page and service of home/common/console).
#
# Declared with `command`, not with program arguments, so launchd waits for the Nix
# volume before starting it (the rule in CLAUDE.md). `RunAtLoad` starts it and `KeepAlive`
# restarts it whenever it exits. On a login host it is a user agent in gui/<uid>, started
# at login. On a boot host (`ownerServices.atBoot`, issue 1290) it is a system daemon that
# runs as the owner, started at boot with nobody logged in; launchd restarts it on exit.
#
# launchd gives the job no login-shell environment, so `PATH` carries gh's bin (the
# tracker calls run `gh` by name) and `HOME` is set because the console's state root is
# read from `$HOME` with no fallback. Output goes to one log file in ~/Library/Logs.
{
  config,
  lib,
  username,
  ...
}:
let
  atBoot = config.ownerServices.atBoot;
  user = config.home-manager.users.${username};
  ac = user.agentConsole;
  home = user.home.homeDirectory;
  log = "${home}/Library/Logs/agent-console.log";
  job = {
    command = ac.command;
    serviceConfig = {
      Label = "org.nixos.agent-console";
      RunAtLoad = true;
      KeepAlive = true;
      # The manager the console starts runs in its own session (ADR-console-075), but launchd
      # kills the process group of a dying job; this key turns that off, so a restart of the
      # console or an activation never ends a manager (issue 894).
      AbandonProcessGroup = true;
      EnvironmentVariables = {
        PATH = ac.path;
        HOME = home;
      };
      StandardOutPath = log;
      StandardErrorPath = log;
    };
  };
in
{
  launchd.user.agents.agent-console = lib.mkIf (!atBoot) job;
  launchd.daemons.agent-console = lib.mkIf atBoot (
    lib.recursiveUpdate job { serviceConfig.UserName = username; }
  );
}
