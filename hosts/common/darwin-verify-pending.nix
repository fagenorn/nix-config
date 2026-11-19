# Issue 632: the verify-pending job on every darwin host.
#
# On a login host the job is a launchd user agent in gui/<uid>; on a boot host
# (`ownerServices.atBoot`, issue 1290) it is a system daemon that runs as the owner, so it
# runs with nobody logged in at the console. The kick then starts it in the system domain
# (`sudo -n launchctl kickstart system/<label>`, the owner has passwordless sudo there).
#
# The job runs the home module's pass command (home/common/verify-pending) every
# 15 minutes and at load. It is declared with `command`, never
# `serviceConfig.ProgramArguments`, so launchd waits for the Nix volume before
# starting it (the rule in CLAUDE.md).
#
# The post-switch trigger is the `postActivation` kick below, not `WatchPaths`:
# a `WatchPaths` entry on /run/current-system never fires (spike S2 on issue 632).
# The kick passes `$systemConfig` because nix-darwin repoints /run/current-system
# only after `postActivation` has run and no hook runs after that, so the pass
# waits for that path to become current before it runs its round (D11).
{
  config,
  lib,
  username,
  ...
}:
let
  atBoot = config.ownerServices.atBoot;
  user = config.home-manager.users.${username};
  vp = user.verifyPending;
  asuser = lib.optionalString (!atBoot) ''launchctl asuser "$(id -u ${username})" '';
in
{
  launchd.user.agents.verify-pending = lib.mkIf (!atBoot) {
    command = vp.command;
    serviceConfig = {
      Label = vp.label;
      StartInterval = 900;
      RunAtLoad = true;
    };
  };

  launchd.daemons.verify-pending = lib.mkIf atBoot {
    command = vp.command;
    serviceConfig = {
      Label = vp.label;
      StartInterval = 900;
      RunAtLoad = true;
      UserName = username;
      EnvironmentVariables.HOME = user.home.homeDirectory;
    };
  };

  # The kick (home/common/verify-pending) starts and probes the job in the system domain.
  home-manager.users.${username}.verifyPending.launchdDomain = lib.mkIf atBoot "system";

  # Issue 705: skip nix-darwin's user-agent reload when the gui domain is absent (nobody
  # logged in at the console), with one log line, instead of aborting the switch. The
  # guard function is defined at the start of the `userLaunchd` script and removed at its
  # end; see the guard file.
  system.activationScripts.userLaunchd.text = lib.mkMerge [
    (lib.mkBefore (builtins.readFile ./darwin-user-agent-reload-guard.sh))
    (lib.mkAfter "unset -f launchctl\n")
  ];

  # Last postActivation entry (home-manager's activation runs earlier in the same
  # script). On a login host the `launchctl asuser ... sudo -u ... --set-home` form reaches
  # the user's GUI domain as home-manager does; a boot host has no GUI domain and its job is
  # in the system domain, so it runs the kick as the owner directly. `|| true` keeps the
  # `set -e` activation from failing on it, and the kick returns at once.
  system.activationScripts.postActivation.text = lib.mkAfter ''
    ${asuser}sudo -u ${username} --set-home ${vp.kick} "$(readlink -f "$systemConfig")" || true
  '';
}
