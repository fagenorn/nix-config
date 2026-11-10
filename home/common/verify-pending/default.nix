# verify-pending schedule (issue 632): runs this host's due read-only verification
# checks every 15 minutes and once after each switch, on every host.
#
# Two scripts carry the logic: pass.sh (one pass for a host) and kick.sh (ask for a
# pass after a switch). The switch trigger is a kick, not a systemd path unit that
# watches a profile link (D1): a path unit misses a switch that leaves the watched
# link unchanged. On NixOS the kick runs from home-manager activation (below); on
# darwin it runs from nix-darwin's postActivation with the target system, because
# home-manager's darwin activation runs before /run/current-system is repointed
# (D11). The darwin launchd agent also lives there, in
# hosts/common/darwin-verify-pending.nix (D2).
#
# The host is the flake `hostname` special argument baked into the command, never the OS
# hostname. On darwin a nix-darwin `launchd.user.agents.verify-pending` (label
# `org.nixos.verify-pending`, `command`, `StartInterval` 900, `RunAtLoad`) runs the pass; on NixOS a
# systemd user `verify-pending.service` (oneshot) and `verify-pending.timer` (`OnBootSec=2min`,
# `OnUnitActiveSec=15min`) do.
#
# After each switch the kick (`verify-pending-kick`) writes
# `~/.agents/state/verify-pending/switch-request` and starts the job without blocking
# (`launchctl kickstart` / `systemctl --user start --no-block`): from home-manager activation on
# NixOS, and on darwin from the last `postActivation` entry with the new system's path, which the
# pass waits (up to 300 s) to see at `/run/current-system` because nix-darwin repoints it only after
# `postActivation`. A request that lands mid-round earns one more round. A launchd `WatchPaths` on
# `/run/current-system` never fires (spike S2), hence the kick (D1, D11).
#
# Each round appends `pass start host=H` and `pass end host=H verify=N owner_actions=N|skipped`
# lines (preceded by `switch host=H target=T current=yes|timeout` for a switch) with UTC times to
# `~/.agents/state/verify-pending/runner.log`, rotated to `runner.log.1` above 1 MiB, then runs
# `owner-actions refresh`, and the pass always exits 0; what runs unattended is decided by
# `verify-pending run` itself (see `agent_tools.verify_exec`).
#
# Every Mac is logged-in only (issue 668): the darwin job is a launchd user agent in `gui/<uid>`,
# and gh reads its token from the login keychain, so neither exists while nobody is logged in at
# the console. On such a host the agent never loads and no pass runs; the kick still writes the
# switch request, then prints one `verify-pending-kick:` notice instead of starting the job, and
# the switch exits 0. The host's held checks surface through the stale-check owner prompt
# (`verify-stale-check`, cause `silent`), which another host's pass posts once the host has not
# reported for 7 days. nix-darwin's user-agent reload step is guarded the same way, with or without
# a tty (issue 705): `hosts/common/darwin-user-agent-reload-guard.sh` skips its `launchctl asuser`
# calls with one log line when `gui/<uid>` is absent, and the plist is still installed for the next
# login. There is no LaunchDaemon form and no credential outside the keychain; NixOS is unaffected.
{
  config,
  lib,
  pkgs,
  agentTools,
  hostname,
  ...
}:
let
  label = "org.nixos.verify-pending";

  start =
    if pkgs.stdenv.isDarwin then
      # No -k: never kills a running round; no -p. Returns once launchd has the request.
      "/bin/launchctl kickstart gui/$(id -u)/${label}"
    else
      "env XDG_RUNTIME_DIR=\"\${XDG_RUNTIME_DIR:-/run/user/$(id -u)}\" ${pkgs.systemd}/bin/systemctl --user start --no-block verify-pending.service";

  # The job is loaded in gui/<uid> only while the user is logged in at the console (issue 668).
  probe = if pkgs.stdenv.isDarwin then "/bin/launchctl print gui/$(id -u)/${label}" else "true";

  path = lib.concatStringsSep ":" [
    (lib.makeBinPath [
      pkgs.gh
      pkgs.git
      pkgs.coreutils
    ])
    "${config.home.profileDirectory}/bin"
    "/run/current-system/sw/bin"
    "/nix/var/nix/profiles/default/bin"
    "/usr/bin"
    "/bin"
    "/usr/sbin"
    "/sbin"
  ];

  pass = pkgs.writeShellScript "verify-pending-pass" (
    builtins.replaceStrings
      [ "@path@" "@caFile@" "@verifyPending@" "@ownerActions@" "@currentSystem@" "@switchWait@" ]
      [
        path
        "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "${agentTools.launchers.verify-pending}"
        (if agentTools.launchers ? owner-actions then "${agentTools.launchers.owner-actions}" else "")
        "/run/current-system"
        "300"
      ]
      (builtins.readFile ./pass.sh)
  );

  kickText = builtins.replaceStrings [ "@path@" "@start@" "@probe@" ] [ path start probe ] (
    builtins.readFile ./kick.sh
  );

  kick =
    assert lib.assertMsg (lib.all (line: builtins.match ".*@[a-zA-Z]+@.*" line == null) (
      lib.splitString "\n" kickText
    )) "verify-pending: kick.sh keeps a placeholder that default.nix does not substitute";
    pkgs.writeShellScript "verify-pending-kick" kickText;

  command =
    assert lib.assertMsg (
      builtins.match "[a-z0-9][a-z0-9-]*" hostname != null
    ) "verify-pending: hostname ${hostname} is not a plain host name";
    "${pass} ${hostname}";

  readOnlyStr = description: lib.mkOption {
    type = lib.types.str;
    readOnly = true;
    inherit description;
  };
in
{
  options.verifyPending = {
    command = readOnlyStr "The verify-pending pass command for this host: the pass script and the flake hostname.";
    label = readOnlyStr "The launchd label / unit name of the verify-pending job.";
    kick = readOnlyStr "Store path of the script that asks for one pass after a switch.";
    start = readOnlyStr "The line the kick script runs to start the job without waiting.";
    probe = readOnlyStr "The line the kick script runs to check the job is loaded before starting it.";
    kickText = readOnlyStr "The kick script's text after its placeholders are substituted.";
  };

  config = lib.mkMerge [
    {
      verifyPending = {
        inherit command label start probe kickText;
        kick = "${kick}";
      };
    }
    (lib.mkIf pkgs.stdenv.isLinux {
      systemd.user.services.verify-pending = {
        Unit = {
          Description = "verify-pending: this host's due read-only verification checks (issue 632)";
          # A pass can outlast sd-switch's two-minute wait (each check may run ten minutes).
          # Without keep-old, reloadSystemd restarts this oneshot on a changed store path and
          # waits for it, failing activation before the kick; keep-old leaves a running pass
          # alone, and the next timer or kick run uses the new script.
          X-SwitchMethod = "keep-old";
        };
        Service = {
          Type = "oneshot";
          ExecStart = config.verifyPending.command;
        };
      };

      systemd.user.timers.verify-pending = {
        Unit.Description = "verify-pending every 15 minutes";
        Timer = {
          OnBootSec = "2min";
          OnUnitActiveSec = "15min";
          Persistent = true;
        };
        Install.WantedBy = [ "timers.target" ];
      };

      # On NixOS home-manager activates from the home-manager-<user> unit that
      # switch-to-configuration starts after /run/current-system is repointed, so
      # the kick needs no target. `run` honours dry-run; `|| true` keeps activation green.
      home.activation.verifyPendingKick = lib.hm.dag.entryAfter [ "writeBoundary" "reloadSystemd" ] ''
        run ${kick} || true
      '';
    })
  ];
}
