# Ask for one verify-pending pass after a switch (issue 632), without waiting.
# TARGET, when given, is the resolved store path of the system being activated;
# the pass waits until it is current before running. Run from home-manager
# activation on NixOS and from nix-darwin's postActivation on darwin. Never fails.
# The kick starts the job only when the probe says it is loaded; on darwin with
# nobody logged in at the console there is no gui/<uid> domain, so it prints one
# notice instead (issue 668).
# Placeholders (@...@) are substituted by home/common/verify-pending/default.nix.
set -u
if [ "$#" -gt 1 ]; then
  echo "verify-pending-kick: usage: verify-pending-kick [TARGET]" >&2
  exit 2
fi
export PATH=@path@
[ -n "${HOME:-}" ] || exit 0
umask 077
state="$HOME/.agents/state/verify-pending"
mkdir -p "$state" || exit 0
printf '%s\n' "${1:-}" > "$state/switch-request.$$" && mv -f "$state/switch-request.$$" "$state/switch-request" || exit 0
if { @probe@; } >/dev/null 2>&1; then
  { @start@; } >/dev/null || true
else
  echo "verify-pending-kick: the verify-pending job is not loaded in this session (on darwin: nobody is logged in at the console); no pass started now, the switch request waits for the job's next run" >&2
fi
exit 0
