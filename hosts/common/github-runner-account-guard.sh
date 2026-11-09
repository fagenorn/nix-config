#!/bin/sh
# Refuse a runner account whose uid or gid does not belong to it alone (issue 680).
#
# nix-darwin creates the account with `dscl -create`, and that does not refuse a
# UniqueID or PrimaryGroupID another account holds. A shared uid would put that
# account's files within reach of a runner job, which runs untrusted workflow code.
# An account of the requested name that already exists with a different id is refused
# too: nix-darwin only warns and skips it, and launchd resolves the name, so the job
# would run under that other id.
# Run from `system.checks.text`, a non-zero exit aborts the activation before
# nix-darwin creates the account.
#
# Usage: github-runner-account-guard.sh NAME ID
# Exit 0: no account other than NAME holds ID, and NAME has no other id (free, or NAME's own).
# Exit 1: another user holds the uid or another group holds the gid, or NAME exists with
#         a different uid or gid.
# Exit 2: bad usage, or dscl failed (a failure must not read as "free").
set -eu

if [ $# -ne 2 ]; then
  echo "usage: github-runner-account-guard.sh NAME ID" >&2
  exit 2
fi
name=$1
id=$2
case "$id" in
  '' | *[!0-9]*)
    echo "usage: github-runner-account-guard.sh NAME ID (ID must be all digits, got '$id')" >&2
    exit 2
    ;;
esac

dscl=${DSCL:-/usr/bin/dscl}
users=$("$dscl" . -list /Users UniqueID) || exit 2
groups=$("$dscl" . -list /Groups PrimaryGroupID) || exit 2

other=$(printf '%s\n' "$users" | awk -v id="$id" -v name="$name" '$2 == id && $1 != name { print $1; exit }')
if [ -n "$other" ]; then
  echo "github-runner-account-guard: uid $id belongs to $other, not $name; pick a free id" >&2
  exit 1
fi

other=$(printf '%s\n' "$groups" | awk -v id="$id" -v name="$name" '$2 == id && $1 != name { print $1; exit }')
if [ -n "$other" ]; then
  echo "github-runner-account-guard: gid $id belongs to $other, not $name; pick a free id" >&2
  exit 1
fi

# The name -> id direction: an existing NAME must already carry ID.
mismatch=$(printf '%s\n' "$users" | awk -v id="$id" -v name="$name" '$1 == name && $2 != id { print $2; exit }')
if [ -n "$mismatch" ]; then
  echo "github-runner-account-guard: user $name has uid $mismatch, not $id; pick the existing id or a new name" >&2
  exit 1
fi

mismatch=$(printf '%s\n' "$groups" | awk -v id="$id" -v name="$name" '$1 == name && $2 != id { print $2; exit }')
if [ -n "$mismatch" ]; then
  echo "github-runner-account-guard: group $name has gid $mismatch, not $id; pick the existing id or a new name" >&2
  exit 1
fi
