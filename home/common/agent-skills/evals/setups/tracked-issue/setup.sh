#!/usr/bin/env bash
#
# The `tracked-issue` setup of run-eval.sh: setup.sh <WORK> <REPO>
#
# Gives the sandbox a read-only GitHub: $WORK/bin/gh runs gh.py (which logs every call to
# $WORK/gh-calls.jsonl), and the sandbox's project contract binds the tracker to github, so
# a lifecycle owner acquires issue 4 through the tracker adapter. run-eval.sh puts
# $WORK/bin first on the claude run's PATH. Any failure exits non-zero.
set -euo pipefail

WORK=$1
REPO=$2
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

mkdir -p "$WORK/bin"
cat >"$WORK/bin/gh" <<WRAPPER
#!/usr/bin/env bash
exec python3 -I $(printf '%q' "$HERE/gh.py") --repo $(printf '%q' "$REPO") --log $(printf '%q' "$WORK/gh-calls.jsonl") "\$@"
WRAPPER
chmod +x "$WORK/bin/gh"

project="$REPO/.agents/project.json"
jq '.bindings.tracker.kind = "github" | .capabilities.tracker.support = "supported"' "$project" >"$project.tmp"
mv "$project.tmp" "$project"
git -C "$REPO" commit -qam "chore: track issues on github"
git -C "$REPO" push -q origin main
