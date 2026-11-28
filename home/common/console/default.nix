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
# `agentConsole.path` from here so both hosts run one command. The command also names the
# screenshot folders a manual check's pictures may come from (issue 1112).
#
# `PATH` carries gh because the tracker poll runs `gh` by name (not by store path), and
# a user service starts with a bare `PATH`. `/usr/bin:/bin` follows it for the system tools.
# The manager launch (issue 888) runs `systemd-run` and `claude-account` by name,
# `claude-account` runs coreutils by name, the page's activation runs `just` by name (#1290),
# and the manager is an agent that needs the owner's tools, so both platforms carry the owner's
# profile (`claude-account`, `just` and the tools a terminal session has) and the system profile
# (coreutils, bash, and `systemd-run` on Linux) between gh and `/usr/bin:/bin`. On darwin the
# owner's profile is `/etc/profiles/per-user/<user>` (`useUserPackages`) and the system profile
# is nix-darwin's `/run/current-system/sw`.
#
# Only Linux carries the setuid wrappers: `/run/wrappers/bin` comes first after gh, before the
# owner's profile, so the `sudo` the page's activation runs (`just switch` runs
# `sudo nixos-rebuild switch` by name) is the setuid wrapper. The `sudo` in `/run/current-system/sw/bin` is the plain binary and
# fails with "must be owned by uid 0 and have the setuid bit set". The activation the console
# starts runs in its own transient user scope (`systemd-run --user --scope`), so the unit's
# restart during the switch (`KillMode=control-group`) does not end it, and the restarted
# console resumes waiting for its recorded exit. `systemd-run` and `systemctl` are reached
# through `/run/current-system/sw/bin`, already on the path.
#
# The command also names the guest socket Tailscale Serve proxies to (`--guest-socket`, #1299,
# ADR-console-077), in a mode-0700 folder the console makes, and, when `agentConsole.tailscale`
# is set, this host's Tailscale client. When `agentConsole.lockBump` is set it also names the
# project whose lock the console bumps to each proven revision, its branch and the platform
# repository (`--lock-bump-project`, `--lock-bump-branch`, `--platform-repo`).
{
  config,
  lib,
  pkgs,
  agentTools,
  ...
}:
let
  consolePort = 27184;
  guestSocket = "${config.home.homeDirectory}/.agents/state/console/guest/guest.sock";

  command =
    "${agentTools.launchers.console} --port ${toString consolePort} --guest-socket ${lib.escapeShellArg guestSocket}"
    + lib.optionalString (
      config.agentConsole.tailscale != null
    ) " --tailscale ${lib.escapeShellArg config.agentConsole.tailscale}"
    + lib.concatMapStrings (
      d: " --screenshots ${lib.escapeShellArg d}"
    ) config.agentConsole.screenshotDirs
    + lib.optionalString (config.agentConsole.lockBump != null) (
      " --lock-bump-project ${lib.escapeShellArg config.agentConsole.lockBump.project}"
      + " --lock-bump-branch ${lib.escapeShellArg config.agentConsole.lockBump.branch}"
      + " --platform-repo ${lib.escapeShellArg config.agentConsole.lockBump.platformRepo}"
    );

  path = lib.concatStringsSep ":" (
    [ (lib.makeBinPath [ config.programs.gh.package ]) ]
    ++ lib.optionals pkgs.stdenv.isLinux [ "/run/wrappers/bin" ]
    ++ [
      "${config.home.profileDirectory}/bin"
      "/run/current-system/sw/bin"
      "/usr/bin"
      "/bin"
    ]
  );
in
{
  options.agentConsole = {
    screenshotDirs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "${config.home.homeDirectory}/tmp/clarity-screenshots" ];
      description = "Folders whose PNGs a manual check may show on the console (issue 1112), beside the project's own checkout.";
    };
    tailscale = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Path of this host's Tailscale client the console reads `serve status --json` and `status --json` from, the second for this host's own tailnet name (#1237, #1299, #1305, ADR-console-078); null reads nothing, so the guest door lets no guest in.";
    };
    lockBump = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.submodule {
          options = {
            project = lib.mkOption {
              type = lib.types.str;
              description = "The registered project, as owner/name, whose platform lock the console bumps.";
            };
            branch = lib.mkOption {
              type = lib.types.str;
              description = "The integration branch of that project.";
            };
            platformRepo = lib.mkOption {
              type = lib.types.str;
              description = "The platform repository, as owner/name, whose proven revisions are offered.";
            };
          };
        }
      );
      default = null;
      description = "The one registered project whose lock the console bumps to each proven revision, its integration branch and the platform repository; null bumps no project.";
    };
    command = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      description = "The console command: the launcher and its loopback port.";
    };
    path = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      description = "The PATH the console service runs with: gh's bin, on Linux the setuid wrappers (sudo), the owner's and system profiles, then the system tools.";
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
