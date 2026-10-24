# Studio runner account home

## Problem

`just switch` on eleven-m5 aborts because nix-darwin compares the existing
`_github-runner` account home literally. Directory Service records
`/private/var/lib/github-runners`; the pinned runner module declares
`/var/lib/github-runners`. macOS resolves both paths to the same directory.

## Solution

Configure this Studio's managed runner account with its existing Directory
Service home. Keep the upstream runner module and service configuration.

## Decisions

The Studio host module overrides the upstream ordinary-priority home with
`lib.mkForce`. The account identity, files and runner service paths remain
under their existing management. Other hosts inherit the upstream home.

## Test seams

- Build the actual eleven-m5 system and execute only its generated runner
  account preflight against the real read-only Directory Service lookup.
- Evaluate the mbp account home to verify the host boundary.
- Run the declared build and agent workflow verification on the final tree.

## Out of scope

Account migration, Directory Service edits, runner registration, changes to
upstream nix-darwin, and unrelated service configuration.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Preserve the existing account home with a Studio-only forced override. | The pinned runner module assigns an ordinary-priority home; nix-darwin refuses existing-home changes. The real account records the canonical macOS path. | Changing the account risks a migration; a shared override assumes the other Mac has the same account state. |
