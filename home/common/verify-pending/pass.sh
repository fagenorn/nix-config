# One verify-pending pass for this host (issue 632), run by the launchd agent on
# darwin and the systemd user timer on NixOS, and kicked after each switch by
# kick.sh. The host is the flake hostname, passed as the only argument; checks
# that are not this host's, not read-only, or not a workflow.verification command
# are skipped inside `verify-pending run` itself. A kick leaves a switch request
# naming the system being activated: the pass waits (bounded) until that system
# is current before its round, and runs one more round when a request lands
# while a round is running, because the service manager ignores a start of a
# running job. A pass never fails: it exits 0 whatever its children do.
# Placeholders (@...@) are substituted by home/common/verify-pending/default.nix.
set -u
if [ "$#" -ne 1 ]; then
  echo "verify-pending-pass: usage: verify-pending-pass HOST" >&2
  exit 2
fi
host=$1
export PATH=@path@
export SSL_CERT_FILE=@caFile@
if [ -z "${HOME:-}" ]; then
  echo "verify-pending-pass: HOME is unset" >&2
  exit 0
fi
umask 077
state="$HOME/.agents/state/verify-pending"
mkdir -p "$state" || exit 0
log="$state/runner.log"
request="$state/switch-request"
# One rotated generation; checked at pass start, so a round never splits across files.
if [ -f "$log" ] && [ "$(wc -c < "$log")" -gt 1048576 ]; then
  mv -f "$log" "$log.1"
fi
exec >>"$log" 2>&1
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
while :; do
  target=
  if mv -f "$request" "$request.taken" 2>/dev/null; then
    target=$(cat "$request.taken" 2>/dev/null || true)
    rm -f "$request.taken"
  fi
  if [ -n "$target" ]; then
    waited=0
    current=yes
    while [ "$(readlink -f @currentSystem@ 2>/dev/null || true)" != "$target" ]; do
      if [ "$waited" -ge @switchWait@ ]; then
        current=timeout
        break
      fi
      sleep 1
      waited=$((waited + 1))
    done
    echo "$(stamp) switch host=$host target=$target current=$current"
  fi
  echo "$(stamp) pass start host=$host"
  @verifyPending@ run --host "$host"
  verify=$?
  owner=skipped
  if [ -x "@ownerActions@" ]; then
    "@ownerActions@" refresh
    owner=$?
  fi
  echo "$(stamp) pass end host=$host verify=$verify owner_actions=$owner"
  [ -e "$request" ] || break
done
exit 0
