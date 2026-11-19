# ADR-project-contract-009 — A plan can add the commit environment to an existing contract

- **Status:** accepted
- **Decided in:** #1333

## Context

ADR-project-contract-008 let a contract name the command its adoption commit runs through, and left adding it to the project. A checkout whose commit hooks need its development environment but whose contract names none still planned `no_change`, so no adoption could carry the member, and the commit at Apply failed on the hook.

## Decision

**D1. The flag and what it adds.** `adopt-project plan --commit-environment COMMAND` reads COMMAND as shell words and adds them to a contract that names no environment. Whether the contract names one is decided by the binding `bindings.vcs.commit.environment` alone, the only member Apply reads, never by a command id. The planned `.agents/project.json` gains that binding and the command `{argv, cwd: ".", env: []}`. The command id is the first of `commit-environment`, `commit-environment-2`, `commit-environment-3`, ... that is absent from `bindings.commands` or whose entry equals the proposed entry. An authored entry equal to the proposal is reused and left as it is. A different authored entry is kept unchanged and the proposal takes the next free id. Nothing else in the contract changes.

**D2. When it is ignored.** The flag changes nothing when the checkout has no contract, when the contract is not of the current schema (a schema 1 checkout is `migration_required` and writes nothing), when `bindings`, `bindings.commands`, `bindings.vcs` or `bindings.vcs.commit` is not an object, or when the contract already names an environment. The plan is then exactly the plan made without the flag: the same `plan_id`, the same changes and no `commit_environment` member.

**D3. Identity and Apply.** The argv is the plan's `commit_environment` member and the twelfth input of `plan_id`, after the drafted contract when there is one. Apply re-derives the plan with the stored argv, refuses a stored member that is not a non-empty list of non-empty strings as `adopt.plan.malformed` at `/plan/commit_environment`, and refuses a changed one as `plan_stale` (`adopt.plan.inputs_changed`). The amendment is substantive work, so a checkout that plans `no_change` without the flag plans `reconcile` with it.

**D4. Refusals.** The flag with `--contract-draft` is refused `adopt.environment.drafted`, because a drafted contract names its own commit environment. A COMMAND `shlex` cannot read, or that has no word or an empty word, is refused `adopt.environment.unreadable`. Each is exit 2 with one error object and nothing stored.

## Consequences

- This amends ADR-project-contract-008 D4: a plan now writes the member it names, and only Apply still reads it.
- A plan without the flag is unchanged, in its document and its `plan_id`.
- The caller that proposes the command owns choosing it. The plan only adds what it is given.
