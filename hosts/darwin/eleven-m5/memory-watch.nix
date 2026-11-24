{
  config,
  inputs,
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
  record = "/var/db/memory-watch/fseventsd.json";
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
}
