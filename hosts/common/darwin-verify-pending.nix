# Issue 632: the verify-pending job on every darwin host.
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
  vp = config.home-manager.users.${username}.verifyPending;
in
{
  launchd.user.agents.verify-pending = {
    command = vp.command;
    serviceConfig = {
      Label = vp.label;
      StartInterval = 900;
      RunAtLoad = true;
    };
  };

  # Issue 705: skip nix-darwin's user-agent reload when the gui domain is absent (nobody
  # logged in at the console), with one log line, instead of aborting the switch. The
  # guard function is defined at the start of the `userLaunchd` script and removed at its
  # end; see the guard file.
  system.activationScripts.userLaunchd.text = lib.mkMerge [
    (lib.mkBefore (builtins.readFile ./darwin-user-agent-reload-guard.sh))
    (lib.mkAfter "unset -f launchctl\n")
  ];

  # Last postActivation entry (home-manager's activation runs earlier in the same
  # script). The `launchctl asuser ... sudo -u ... --set-home` form reaches the
  # user's GUI domain as home-manager does; `|| true` keeps the `set -e` activation
  # from failing on it, and the kick returns at once.
  system.activationScripts.postActivation.text = lib.mkAfter ''
    launchctl asuser "$(id -u ${username})" sudo -u ${username} --set-home ${vp.kick} "$(readlink -f "$systemConfig")" || true
  '';
}
