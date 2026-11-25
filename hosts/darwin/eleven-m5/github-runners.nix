{ ... }:
{
  # A runner for elevenyellow/jarbird Tests jobs (`runs-on: [self-hosted, jarbird]`,
  # tracked in elevenyellow/jarbird#516).
  #
  # One registration means one concurrent job.
  #
  # uid and gid 534 were free on eleven-m5 on 2026-11-08; the account guard
  # refuses them if that ever changes.
  #
  # A job needing more than 256 open files raises its own soft limit with
  # `ulimit -n`: launchd limits on a system daemon also set system-wide sysctls,
  # so none are set here.
  #
  # Port 5433 could also be held by a Colima container or by a teammate's own
  # `devenv up` on this host, so a Tests job that needs it can fail for that reason.
  #
  # Capacity: memory-budget.nix sets what the runners may take alongside oMLX, Colima,
  # verification runs and macOS.
  githubRunners.repos = [
    {
      owner = "elevenyellow";
      name = "jarbird";
      extraLabels = [ "jarbird" ];
      account = {
        name = "_github-runner-jarbird";
        id = 534;
      };
    }
  ];
}
