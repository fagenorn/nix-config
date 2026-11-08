{
  config,
  lib,
  pkgs,
  unstablePkgs,
  hostname,
  ...
}:
let
  # Registration tokens (not PATs) live here, outside the Nix store. They are
  # written by `just register-runners`, which mints a one-hour token per repo
  # through `gh`; a runner reads its token only on first registration (no
  # `.runner` in its state dir yet). A PAT would sit readable by every job, since
  # jobs run as the same user that must read the token file. A runner with its
  # own `account` keeps its token in `${tokenDir}-<account name>`, because the
  # shared directory is readable only by group `_github-runner`.
  tokenDir = "/var/lib/github-runner-tokens";

  tokenDirOf = e: if e.account == null then tokenDir else "${tokenDir}-${e.name}";
  tokenGroupOf = e: if e.account == null then "_github-runner" else e.account.name;

  accounts = lib.filter (e: e.account != null) config.githubRunners.repos;
in
{
  options.githubRunners.repos = lib.mkOption {
    description = "Repositories that get a self-hosted runner on this host, one launchd daemon each.";
    default = [ ];
    type = lib.types.listOf (
      lib.types.submodule {
        options = {
          owner = lib.mkOption {
            type = lib.types.str;
            description = "GitHub user or organization that owns the repository.";
          };
          name = lib.mkOption {
            type = lib.types.str;
            description = "Repository name.";
          };
          extraLabels = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ ];
            description = "Labels added after `nix` and the host name.";
          };
          account = lib.mkOption {
            default = null;
            description = ''
              A dedicated user and group for a runner that serves another tenant's
              repository. Null means the shared `_github-runner` account.
            '';
            type = lib.types.nullOr (
              lib.types.submodule {
                options = {
                  name = lib.mkOption {
                    type = lib.types.str;
                    description = "User and group name.";
                  };
                  id = lib.mkOption {
                    type = lib.types.int;
                    description = "uid and gid.";
                  };
                };
              }
            );
          };
        };
      }
    );
  };

  config = {
    # A personal GitHub account has no account-wide runner scope (only orgs do), so
    # each repository gets its own runner registration: one launchd daemon per repo.
    # Each entry names its owner, and an organization's repository is still
    # registered repo-scoped. Jobs reach tools only through the daemon's Nix-built
    # PATH, so nothing is installed globally.
    #
    # Runners of the owner's own repositories share the nix-darwin-managed
    # `_github-runner` user, which cannot read /Users/anis (mode 0750, group
    # staff). A runner serving another tenant's repository gets its own `account`:
    # nix-darwin creates each runner's state, log and work dirs `o=`, so a separate
    # account keeps one tenant's jobs away from the other's `.credentials` and work
    # dirs. Residual: `_github-runner` owns /private/var/lib/github-runners, so an
    # owner's job could rename another runner's dir but never read it.
    githubRunners.repos = [
      {
        owner = "fagenorn";
        name = "arcwave";
      }
      {
        owner = "fagenorn";
        name = "argus";
      }
      {
        owner = "fagenorn";
        # Public: a fork PR could run code here. The repo's fork-PR policy is set to
        # require approval for every outside contributor, and the hosted CI jobs stay
        # on ubuntu — only a job that asks for `self-hosted` lands on this Mac.
        name = "nix-config";
      }
    ];

    services.github-runners = lib.listToAttrs (
      map (entry: {
        name = "${hostname}-${entry.name}";
        value = {
          enable = true;
          # GitHub refuses jobs to a runner more than ~30 days behind the newest
          # release ("Runner version vX is deprecated and cannot receive messages"),
          # and Nix runs it with --disableupdate. The 25.11 channel lags too far, so
          # track unstable and keep `just update` at least monthly.
          package = unstablePkgs.github-runner;
          # Upstream dropped node20; the module's default still lists it.
          nodeRuntimes = [ "node24" ];
          url = "https://github.com/${entry.owner}/${entry.name}";
          tokenFile = "${tokenDirOf entry}/${entry.name}.token";
          replace = true;
          extraLabels = [
            "nix"
            hostname
          ]
          ++ entry.extraLabels;
          user = lib.mapNullable (a: a.name) entry.account;
          group = lib.mapNullable (a: a.name) entry.account;
          extraPackages = with pkgs; [
            curl
            findutils
            gnugrep
            gnused
            jq
            unzip
            xz
          ];
        };
      }) config.githubRunners.repos
    );

    users.users = lib.listToAttrs (
      map (e: {
        name = e.account.name;
        value = {
          uid = e.account.id;
          gid = e.account.id;
          # The canonical path: sysadminctl records /private/..., and nix-darwin compares
          # the recorded home to this literal on every later activation.
          home = "/private/var/empty";
          createHome = false;
          shell = "/bin/bash";
          description = "GitHub runner for ${e.owner}/${e.name}";
        };
      }) accounts
    );
    users.groups = lib.listToAttrs (
      map (e: {
        name = e.account.name;
        value = {
          gid = e.account.id;
          description = "GitHub runner for ${e.owner}/${e.name}";
        };
      }) accounts
    );
    users.knownUsers = map (e: e.account.name) accounts;
    users.knownGroups = map (e: e.account.name) accounts;

    # Refuses a uid or gid another account already holds, before activation.
    system.checks.text = lib.concatMapStringsSep "\n" (
      e: "/bin/sh ${./github-runner-account-guard.sh} ${e.account.name} ${toString e.account.id}"
    ) accounts;

    # Jobs run `nix run github:cachix/devenv/<rev>`; the runner users are untrusted, so
    # a workflow's `--option extra-substituters` is ignored and devenv would build
    # from source. Trust the cache system-wide instead of adding a runner to
    # `trusted-users`, which would hand PR code root-equivalent control of the store.
    nix.settings = {
      extra-substituters = [ "https://devenv.cachix.org" ];
      extra-trusted-public-keys = [
        "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
      ];
    };

    # Runs after nix-darwin has created the runner users (users activate first).
    system.activationScripts.launchd.text = lib.mkBefore (
      lib.concatMapStringsSep "\n" (
        d: "${lib.getExe' pkgs.coreutils "install"} -d -m 0750 -o root -g ${d.group} ${d.dir}"
      ) (
        lib.unique (
          map (e: {
            dir = tokenDirOf e;
            group = tokenGroupOf e;
          }) config.githubRunners.repos
        )
      )
      + "\n"
    );
  };
}
