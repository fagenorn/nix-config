{
  config,
  inputs,
  lib,
  pkgs,
  username,
  ...
}:
let
  home = "/Users/${username}";
  budget = import ./memory-budget.nix;
  launcher = "${
    inputs.self.packages.${pkgs.stdenv.hostPlatform.system}.agent-platform.launchers.omlx-memory-watch
  }";
  floorLauncher =
    inputs.self.packages.${pkgs.stdenv.hostPlatform.system}.agent-platform.launchers.memory-floor;
  record = "/var/db/memory-watch/fseventsd.json";
  censusRecord = "/var/db/memory-watch/census.json";
  # Matched against process cwds only; quoted because nix-darwin runs `command` through /bin/sh -c.
  agentRoots = [
    "${home}/Projects/*/.worktrees/*"
    "/private/tmp/verify-pending-*"
    "/private/var/folders/*/*/T/verify-pending-*"
  ];
  # A runner's user is null for the shared account.
  runnerUsers = lib.unique (
    map (r: if r.user == null then "_github-runner" else r.user) (
      builtins.attrValues config.services.github-runners
    )
  );
  watchLog = "${home}/.omlx/logs/memory-watch.log";
in
{
  # Samples memory every minute as the owner and records the day's peaks. Its alerts go through
  # the owner's host-alerts settings file, so no secret is declared here.
  launchd.daemons.omlx-memory-watch = {
    command = "${launcher} sample --state-dir ${home}/.omlx/memory --floor-gib ${toString budget.floorGiB} --others-budget-gib ${toString budget.othersBudgetGiB} --omlx-jetsam-priority ${toString budget.omlxJetsamPriority} --host ${config.networking.hostName} --fseventsd-record ${record}";
    serviceConfig = {
      UserName = username;
      EnvironmentVariables.HOME = home;
      RunAtLoad = true;
      StartInterval = 60;
      StandardOutPath = watchLog;
      StandardErrorPath = watchLog;
    };
  };

  # Restarts fseventsd when its footprint passes the budgeted limit and records its size for the
  # watcher. It runs as root because only root reads fseventsd's footprint.
  launchd.daemons.fseventsd-trim = {
    command = "${launcher} fseventsd --record ${record} --limit-gib ${toString budget.fseventsdLimitGiB} --min-restart-minutes ${toString budget.fseventsdRestartMinutes}";
    serviceConfig = {
      RunAtLoad = true;
      StartInterval = 60;
      StandardOutPath = "/var/log/fseventsd-trim.log";
      StandardErrorPath = "/var/log/fseventsd-trim.log";
    };
  };

  # Reads every process's footprint, which only root can, and records the system's unowned memory
  # for the owner's sampler.
  launchd.daemons.memory-census = {
    command = "${launcher} census --record ${censusRecord}";
    serviceConfig = {
      RunAtLoad = true;
      StartInterval = 60;
      StandardOutPath = "/var/log/memory-census.log";
      StandardErrorPath = "/var/log/memory-census.log";
    };
  };

  # Ends the largest agent workload while memory stays under the floor and sets oMLX's kernel
  # jetsam priority. It runs as root and writes only its record and /var/log/memory-floor.log,
  # never a path the agent user can write; the owner's sampler reads the record and alerts.
  launchd.daemons.memory-floor = {
    command = lib.concatStringsSep " " (
      [
        "${floorLauncher} enforce"
        "--floor-gib ${toString budget.floorGiB}"
        "--floor-samples ${toString budget.floorSamples}"
        "--grace-seconds ${toString budget.floorGraceSeconds}"
        "--margin-gib ${toString budget.floorMarginGiB}"
        "--fall-gib ${toString budget.floorFallGiB}"
        "--fast-seconds ${toString budget.fastSampleSeconds}"
        "--slow-seconds ${toString budget.slowSampleSeconds}"
        "--run-bound-gib ${toString budget.runBoundGiB}"
        "--min-tree-gib ${toString budget.floorMinTreeGiB}"
        "--omlx-jetsam-priority ${toString budget.omlxJetsamPriority}"
        "--agent-user ${username}"
      ]
      ++ map (root: "--agent-root ${lib.escapeShellArg root}") agentRoots
      ++ map (user: "--runner-user ${user}") runnerUsers
      ++ [ "--record /var/db/memory-watch/floor.json" ]
    );
    serviceConfig = {
      RunAtLoad = true;
      KeepAlive = true;
      StandardOutPath = "/var/log/memory-floor.log";
      StandardErrorPath = "/var/log/memory-floor.log";
    };
  };
}
