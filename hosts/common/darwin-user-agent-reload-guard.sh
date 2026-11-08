# Issue 705: nix-darwin's user-agent reload step must not abort a host with nobody
# logged in at the console. Such a host has no gui/<uid> domain (issue 668), and
# `launchctl asuser <uid> ...` into it fails: headless it prints "Bootstrap failed: 125",
# under a tty it aborts the whole switch (SIGABRT, exit 134). While this function is
# defined, that call is skipped with one log line; the plist is still copied into
# ~/Library/LaunchAgents by the step, so launchd loads the agent at the next login.
# Spliced around the `userLaunchd` activation script by hosts/common/darwin-verify-pending.nix,
# which ends it with `unset -f launchctl` so later scripts (the post-switch kick) are unaffected.
# The definition goes through eval so shellcheck, which builds the activate script, does not see a
# function named launchctl: nix-darwin's removal loop runs `sudo -- launchctl unload`, which
# sudo resolves to the real binary, and shellcheck flags that as SC2033 (a function passed to sudo).
eval 'launchctl() {
  if [ "${1:-}" = asuser ] && [ -n "${2:-}" ] && ! command launchctl print "gui/$2" >/dev/null 2>&1; then
    if [ -z "${userAgentReloadSkipLogged:-}" ]; then
      echo "skipping user launchd reloads: there is no gui/$2 domain (nobody is logged in at the console); the user agents load at the next login" >&2
      userAgentReloadSkipLogged=1
    fi
    return 0
  fi
  command launchctl "$@"
}'
