# ADR-project-contract-014 — Schema 3 derives four values from files the repository holds

- **Status:** accepted
- **Decided in:** #1458 (per #1430 and #1413)

## Context

Until now the contract was the resolver's only input. Schema 3 still made a project author its tracker repo, its project id, its required checks and its platform range, although the repository states each one elsewhere. #1430 decided that these four are derived.

## Decision

**D1. Inputs.** For a schema-3 contract the resolver reads, besides `.agents/project.json`: the repository's git config, found through `.git` (a directory, or a `gitdir:` file and its `commondir`), for the first `url` of `[remote "origin"]`; `.github/branch-protection.json`; and the platform manifest of one tree, of which it reads only `platform_version`. A schema-2 contract still reads only the contract. The resolver starts no child process and opens no network connection for either schema.

**D2. The values.** The tracker repo is the `owner/repo` of the origin URL, in the two spellings adoption already accepts, and the project id is the same slug. The required checks are the `context` of each `required_status_checks.checks` entry in file order; `required_status_checks: null` or an empty list gives none, and the snapshot then has no `required_checks`. The platform range runs from the tree's `platform_version` up to the next major.

**D3. Which tree.** A repository holding `home/common/agent-skills/platform-manifest.json` is the platform's own and is judged by that file; its `devenv.lock` is not read (#1413). Any other repository is judged by the `agent-platform` input of its `devenv.lock`: the tree at the Nix store path that Nix computes from the input's `narHash`.

**D4. Refusals.** An authored derived value is refused `contract.<section>.derived_value` at its pointer, as is a `project` that is empty or not an object. A value that cannot be derived (no origin URL, an unrecognised spelling, an unreadable or malformed protection file, no lock entry, a locked tree missing from the store) is refused `contract.<section>.not_derivable` at the value's pointer, with a message naming its source. Nothing is guessed.

## Consequences

- A project moving to schema 3 needs an origin remote, a `.github/branch-protection.json` and, unless it is the platform's own repository, a realised `agent-platform` lock entry; adoption (#1454) writes the lock entry under that name and keeps the protection file in step with the forge.
- `platform-status` and the fleet preflight report and judge the derived id and range.
- Rejected: asking `git`, `gh` or `nix` as child processes. Every skill entry resolves, so each resolve would need the network and a credential; GitHub's branch-protection endpoint needs admin rights a CI token lacks; and the answer would follow the forge rather than the reviewed tree.
