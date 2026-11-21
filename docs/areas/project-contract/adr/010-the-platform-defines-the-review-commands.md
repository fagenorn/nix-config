# ADR-project-contract-010 — The platform defines the review commands

- **Status:** accepted
- **Decided in:** #1450 (per #1430)

## Context

Every contract that wires second-model review copied the same two argv lists, `codex-companion task --fresh` followed by the companion's `--reviewer` flag and the operation, and every copy has to keep one shape that the collaboration skill checks. A project that wants review authors both commands again, and a project that forgets gets a snapshot the review skill refuses.

## Decision

**D1. Ids and home.** The platform defines two commands, `codex-plan-review` and `codex-diff-review`, in `agent_platform.PLATFORM_COMMANDS`. They live in `agent_platform` because adoption must not import the resolver, so the module both read is the one definition. The argv is `codex-companion task --fresh` plus the companion's `--reviewer` flag and the operation `plan-review` or `diff-review`, with `cwd` `.` and no environment.

**D2. Precedence.** The resolver adds each platform command the contract does not author under its id. An entry the contract authors under a platform id is read as authored and replaces the platform's whole; the two are never merged member by member.

**D3. Reference scope.** A command id in `workflow.verification`, `workflow.review`, `vcs.commit.environment` or the production command lists is valid when it is authored or platform defined. Only the authored `commands` are shape-validated, so no violation pointer names a platform entry. An id that is neither stays refused.

**D4. Schema 2 is unchanged.** A supported `review.plan` or `review.code` capability still needs its authored `bindings.workflow.review` id. Removing that requirement is #1453.

**D5. Two-step rollout.** A contract may drop its entries under a platform id only once every host it is read on runs this platform. nix-config's contract keeps its identical entries until then, and follow-up #1503 deletes them.

## Consequences

- A host's installed resolver older than this change refuses any contract that relies on a platform entry until that host switches.
- The shell-indirection conformance check reads authored entries only, so the platform entries, which hold no shell, are not scanned.
- Rejected: a manifest member for the commands, because the argv is code the resolver and its tests must agree on and a manifest is data a host can leave stale.
- Rejected: refusing an authored platform id, because the other registered projects' contracts author these ids today and would stop resolving.
- Rejected: deleting nix-config's entries in this change, because an installed older resolver refuses the contract and the frozen consumers run it on this checkout.
