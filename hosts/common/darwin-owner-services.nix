# Issue 1290: the owner's services on a host nobody logs in to at the screen.
#
# A launchd user agent loads in the owner's gui/<uid> domain, which exists only while the
# owner is logged in at the console. eleven-m5 is reached over SSH with automatic login
# off, so nobody is ever logged in there as the owner and its login-session agents never
# load. A "boot host" sets `ownerServices.atBoot = true`: the console, verify-pending, the
# secrets decryption (sops-nix) and the cache proxy are then launchd daemons that run as the
# owner from boot, and launchd restarts them on exit. A login host (the laptop) keeps its
# user agents.
#
# This module turns the two home-manager agents (sops-nix, claude-cache-proxy) into
# daemons: each daemon is built from its agent's own definition, so the program, the
# environment and the logs stay declared where they were. The agents are then disabled,
# and home-manager's sops-nix activation step is emptied. Both would otherwise address
# gui/<uid>, which a boot host does not have: the activation step boots the agent out and
# bootstraps it on every switch, and home-manager's agent removal boots out an old plist.
# Either prints launchctl's "Domain does not support specified action" line, and the
# bootstrap would load a second copy of the secrets decryption in a session. To run the
# decryption again by hand: sudo launchctl kickstart system/org.nixos.sops-nix.
#
# The agents of an earlier generation are still loaded in gui/<uid> (when the owner has a
# session) and their plists are still in ~/Library/LaunchAgents. nix-darwin removes old
# user-agent plists only on a host that still has user agents, so this module's cleanup
# does it: it boots each legacy agent out and deletes its plist, and refuses to go on
# when one stays loaded, so that no daemon starts beside a loaded copy of it. It sits at
# the start of nix-darwin's `launchd` step and not in `preActivation`, because the
# preflight checks run between the two: a check-only run, or a switch a check rejects,
# must not touch the owner's services. It prints which of the two cases it found (the
# owner has or has no login session) to stderr, for the verification that reads the
# activation log. It also creates the one-shot decryption's log directory as the owner,
# because launchd creates the log files and not their directory, and stops when it cannot.
# A gui probe that fails for any reason but a missing domain stops it too (it proves nothing
# about a logout), and a bootout that has not finished is waited for, up to 20 seconds,
# before the agent counts as stuck.
{
  config,
  lib,
  username,
  ...
}:
let
  atBoot = config.ownerServices.atBoot;
  user = config.home-manager.users.${username};
  home = user.home.homeDirectory;

  # The daemon form of a home-manager agent: the same program, environment, restart and
  # log settings (only these keys, by name), run as the owner with HOME set. `command`,
  # not program arguments, so launchd waits for the Nix volume (the rule in CLAUDE.md).
  daemonOf =
    label: agent:
    let
      cfg = agent.config;
      keep = lib.filterAttrs (_: v: v != null);
    in
    {
      command = if cfg.Program != null then cfg.Program else lib.escapeShellArgs cfg.ProgramArguments;
      serviceConfig =
        keep {
          inherit (cfg)
            RunAtLoad
            KeepAlive
            StandardOutPath
            StandardErrorPath
            ;
        }
        // {
          Label = label;
          UserName = username;
          EnvironmentVariables =
            (if cfg.EnvironmentVariables == null then { } else cfg.EnvironmentVariables)
            // {
              HOME = home;
            };
        };
    };

  legacyLabels = [
    "org.nixos.agent-console"
    "org.nixos.verify-pending"
    "org.nix-community.home.sops-nix"
    "org.nix-community.home.claude-cache-proxy"
  ];
in
{
  options.ownerServices.atBoot = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = "Run the owner's services (console, secrets decryption, cache proxy, verify-pending) as boot-time launchd daemons of the owner instead of login-session agents, for a Mac the owner reaches only over SSH (issue 1290).";
  };

  config = lib.mkIf atBoot {
    launchd.daemons.claude-cache-proxy = daemonOf "org.nixos.claude-cache-proxy" user.launchd.agents.claude-cache-proxy;
    launchd.daemons.sops-nix = daemonOf "org.nixos.sops-nix" user.launchd.agents.sops-nix;

    home-manager.users.${username} = {
      launchd.agents.claude-cache-proxy.enable = lib.mkForce false;
      launchd.agents.sops-nix.enable = lib.mkForce false;
      home.activation.sops-nix = lib.mkForce "";
    };

    system.activationScripts.launchd.text = lib.mkBefore ''
      # ownerServices legacy login agents: begin
      uid=$(id -u -- ${username})
      if ! sudo -u ${username} -- /bin/mkdir -p ~${username}/Library/Logs/SopsNix; then
        echo "ownerServices: cannot create ~${username}/Library/Logs/SopsNix, which the secrets decryption logs to" >&2
        exit 1
      fi
      # Exit 112, 113 and 125 are launchd saying the domain is not there (no session); any other
      # exit means the probe itself failed, which proves nothing about a logout.
      probe=0
      launchctl print "gui/$uid" >/dev/null 2>&1 || probe=$?
      case "$probe" in
        0)
          session=1
          echo "ownerServices: the owner has a login session" >&2
          ;;
        112 | 113 | 125)
          session=0
          echo "ownerServices: the owner has no login session" >&2
          ;;
        *)
          echo "ownerServices: launchctl could not read gui/$uid (exit $probe); activate again" >&2
          exit 1
          ;;
      esac
      for label in ${lib.concatStringsSep " " legacyLabels}; do
        if [ "$session" = 1 ] && launchctl print "gui/$uid/$label" >/dev/null 2>&1; then
          launchctl bootout "gui/$uid/$label" >/dev/null 2>&1 || true
          # A bootout can return before the agent has finished exiting, so wait for it to go.
          waited=0
          while launchctl print "gui/$uid/$label" >/dev/null 2>&1; do
            if [ "$waited" -ge 20 ]; then
              echo "ownerServices: $label is still loaded in gui/$uid 20 seconds after its bootout; boot it out by hand and activate again" >&2
              exit 1
            fi
            waited=$((waited + 1))
            sleep 1
          done
        fi
        rm -f ~${username}/Library/LaunchAgents/"$label".plist
      done
      # ownerServices legacy login agents: end
    '';
  };
}
