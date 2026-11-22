# ADR-project-contract-013 — Project schema 3 leaves the platform constants out of the contract

- **Status:** accepted
- **Decided in:** #1453 (per #1430)

## Context

Every registered project's schema-2 contract spells out the same values: the branch pattern, the worktree directory, the signed commit, the merge strategy, the tracker CLI, the knowledge directories, the verification list, the review command ids and each command's `cwd` and `env`. Their resolved snapshots agree on them, so each copy is a place for one project to drift from the platform. #1430 decided that these values belong to the platform and that four members leave the contract.

## Decision

**D1. The constant values.** The platform fixes each value from #1430, #1413 and the registered projects' snapshots. `vcs`: kind `git`, default branch `main`, branch pattern `issue-<num>-<slug>`, worktree root `.worktrees` and prefix `worktree-`, signed commits, the commit environment `commit-environment`, merge strategy `merge` with the branch deleted. `tracker`: kind `github`, CLI `gh`, and `GITHUB_TOKEN` and `GH_TOKEN` unset before an invocation. `paths`: `docs/CONTEXT-MAP.md`, `docs/standards`, `docs/guides/architecture.md`, `docs/operations`, `.agents/knowledge/hints` and `.agents/knowledge/rejections`. `workflow`: verification `lint` then `test`, review ids `codex-plan-review` and `codex-diff-review`, `max_parallel` 2 and an attempt budget of 240 minutes. Every command has `cwd` `.` and no environment.

**D2. Commits run inside devenv.** Schema 3 adds the platform command `commit-environment`, `devenv shell --`, on top of the schema-2 platform commands. It exists only for schema 3, so a schema-2 snapshot is unchanged.

**D3. Fill, then the schema-2 rules.** Every member a schema-3 contract authors sits at its schema-2 pointer. The resolver writes each constant at its pointer, removes the four retired members (`project.name`, `paths.artifacts`, `vcs.commit.co_authored_by`, `workflow.light_lane`), validates the result with the schema-2 rules over member lists without them, and builds the snapshot from it. The snapshot is schema 2 without the retired members, and the projection header records the authored schema.

**D4. Refused by name.** A schema-3 contract that authors a constant is refused `contract.<section>.platform_constant` at that pointer, whatever the value, even the platform's own, and one that authors a retired member is refused `contract.<section>.retired_member`. A command authored under a platform command id, or with its own `cwd` or `env`, is a constant too. This amends ADR-010 D2 for schema 3 only and settles ADR-010 D4.

**D5. Verification commands are required.** The verification list is a constant, so a contract must author `lint` and `test`. One that does not, including one with no `bindings.commands`, is refused `contract.commands.member_missing` at `/bindings/commands/<id>`, never at the constant `/bindings/workflow/verification/<n>`. A `bindings.commands` that is not an object keeps its schema-2 shape error.

**D6. Adoption target.** Adoption targets the highest supported schema that some migration reaches, so it keeps writing schema 2 until a migration to 3 exists. A schema-3 contract or draft is refused until then.

**D7. Optional homes are always filled.** `paths.architecture` and `paths.operations` are filled even when the file or directory is absent. The authored `knowledge.architecture` capability still gates readiness.

## Consequences

- No repository is on schema 3 until the migration slice.
- Adoption refuses a schema-3 contract until a migration reaches 3.
- The four values of #1458 are derived from the repository (ADR-project-contract-014); the attempt budget of #1466 stays as decided here until that issue.
- Rejected: a manifest member for the constants, for the reason ADR-010 rejected one for the commands: the values are code the resolver and its tests must agree on, and a manifest is data a host can leave stale.
- Rejected: refusing an authored platform id in schema 2, because the registered projects' schema-2 contracts author these ids today and would stop resolving.
