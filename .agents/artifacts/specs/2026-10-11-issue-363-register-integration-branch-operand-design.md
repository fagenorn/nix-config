# Reach the integration branch when the default branch's contract is stale, issue 363

https://github.com/fagenorn/nix-config/issues/363 (blocks
https://github.com/fagenorn/nix-config/issues/210, follows
https://github.com/fagenorn/nix-config/issues/341).

## Triage

Input: `{"signals":{"contract_change":{"value":"hit","evidence":"verify --register gains a branch-reach path; the report and the fleet registry entry must say which branch was pinned and why (public CLI report and registry shape)"},"concurrency_or_persistence":{"value":"doubt","evidence":"the user-scope fleet registry entry is persisted state and may gain a member; the spec decides"},"open_design_questions":{"value":"hit","evidence":"the issue leaves the design to the spec: remote-side source, explicit --integration-branch operand, or both"},"criteria_shape":{"value":"hit","evidence":"six acceptance criteria"}},"paths":["python/agent_tools/adopt_verify.py","python/agent_tools/adopt_project.py","python/agent_tools/adopt_inspection.py","python/agent_tools/agent_platform.py","home/common/agent-skills/tests/test_adopt_verify.py","python/README.md"]}`
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

`adopt-project verify --register` starts at `origin`'s default branch and learns
the integration branch only from the contract it finds there. An operator whose
repository integrates on one branch and promotes to the default branch only at
release cannot register: the default branch lags, its contract is on an older
schema (or absent) and does not resolve, so registration pins the default
branch and refuses `not_integrated`, saying that "the remote integration branch
carries no adoption evidence record". The integration branch on `origin`
carries a resolving contract that names itself and the adoption evidence
record, but nothing lets registration reach it. Adoption lands on the
integration branch by design, so the default branch is the last place to learn
about it, and the operator is blocked until an unrelated release.

## Solution

`verify --register` accepts one operand, `--integration-branch <name>`. It is a
pointer to where the contract is, never a second source of contract policy: the
named branch is used only when `origin` lists it and the contract on it
resolves and names that same branch (per D1). It takes effect only when the
default branch's contract does not resolve (per D2). Everything else about
registration is as issue 341 left it: `origin` is listed once, branches are
fetched into `refs/remotes/origin/<branch>` and pinned to commit ids, the
pinned commit is exported, and every check reads that one commit. Nothing is
read from the local checkout.

When the operand selected the branch, the report and the registry entry both
carry one **branch override** object that names the pinned branch, the default
branch that did not carry the hop, and the reason (per D3). A registration that
did not need the operand produces today's bytes.

## Requirements

- **R1 Operand.** `verify` accepts `--integration-branch <name>` at most once.
  Given without `--register` it refuses `adopt_failure` with repair id
  `adopt.verify.integration_branch_without_register` before the repository is
  touched (per D5).
- **R2 Unchanged start.** With or without the operand, registration lists
  `origin`, requires a default branch `D`, fetches and pins `D`, exports it and
  runs the resolver's `resolve` on the export, with today's refusals.
- **R3 Resolving default.** When the contract on `D` resolves, the branch is
  reached exactly as today (stay on `D`, or the one hop with its checks). An
  operand that names the branch the contract names changes nothing: no override
  is reported or stored. An operand that names any other branch refuses
  `not_integrated` / `adopt.registration.integration_branch_unresolved` before
  any further fetch (per D2).
- **R4 Unresolving default, no operand.** Today's behaviour: `D` is the source,
  `contract-resolves` fails in the report, and a `D` without an evidence record
  refuses `not_integrated` / `adopt.registration.not_integrated`. Only that
  refusal's message changes: it says the default branch's contract does not
  resolve and names `--integration-branch` (per D6).
- **R5 Unresolving default, operand `B`.** `B` must be in the step-one listing
  of `origin`, and no git command receives the operand before that membership
  check; it is then fetched, pinned and exported like any branch; the contract
  there must resolve and name `B`. Any failure (not listed, does not resolve,
  names another branch, or `B` is `D` itself) refuses `not_integrated` /
  `adopt.registration.integration_branch_unresolved`. There is no further hop.
  On success the source is `refs/remotes/origin/B` at its pinned commit and
  carries the branch override.
- **R6 Later steps unchanged.** The six checks, the integration gate (no
  evidence record on the pinned commit refuses `not_integrated`), the result
  policy and `register_project`'s inner checks (ancestry from the pinned id;
  the contract at the pinned commit names the fetched branch) apply to an
  operand-selected source without exception.
- **R7 Report.** When the source carries a branch override the report has one
  more member, `branch_override`; otherwise the member is absent and the report
  is byte-identical to today's. `schema_version` stays 2 (per D4).
- **R8 Registry.** A registry entry may carry the optional member
  `branch_override`. `register_project` writes it exactly when the source
  carries one and omits it otherwise, so a later registration that did not need
  the operand drops it. The registry's `schema_version` stays 1 (per D3, D4).
- **R9 No checkout reads.** The branch decision uses only the operand, the
  `origin` listing and the resolver's answers on exports of pinned commits.
- **R10 No new error code** and no repository-specific branch name, path or
  identity anywhere in the change.

## Decisions

**The branch override.** One closed object, the same in the report and the
registry entry:

```json
{"branch": "<B>", "default_branch": "<D>", "reason": "default_contract_unresolved"}
```

All three members are required non-empty strings and `reason` is a closed set
with that one member; a dispatch on it raises on an unknown value. It records
how the registration reached its branch. It is not a verdict and nothing reads
it to decide anything: fleet preflight still recomputes compatibility from the
live contract at `root`.

**Verification source.** The source `adopt_verify` hands to the checks gains
the optional override; `HEAD` sources and sources reached through the default
branch carry none. The source holds the override's default branch and reason
only, and the object's `branch` is always written from the source's own fetched
branch, so an override that names a branch other than the pinned one cannot be
built. The remote source takes the operand as a second input. It
also tells the integration gate whether the default branch's contract resolved,
which is all R4's message needs.

**Registry shape.** `agent_platform` owns the entry shape: `project_id` and
`root` stay required, `branch_override` is the one optional member, and any
other member is still refused in both directions. The validator checks the
override's exact members, types and closed reason. The writer keeps an entry's
valid override and still strips everything else, so registering one project
does not erase another project's override. Sorting, the duplicate-id refusal
and the locked transaction are unchanged. Readers (`platform-status --fleet`,
the plan's collision check) ignore the member and their output does not change.

**Command shell.** `command_verify` stays a thin shell: it checks R1, passes
the operand to the remote source and otherwise runs the same sequence.

**Docs.** `python/README.md` § adopt-project gains the `verify --register`
contract: the branch-reach order, the operand and its conditions, the override
object in the report and the registry, and the refusals. The `adopt_verify` and
`adopt_project` docstrings, the `--register`/`--integration-branch` help text,
and the `agent_platform` registry comments and docstrings that state the
two-member shape are brought in line. Earlier specs are point-in-time records
and are not edited.

## Test seams

The two seams of issue 341's D9, with no new one:

1. **The CLI as a child process** against a local bare `origin` built by the
   existing `publish` helper, under the temporary `HOME`.
2. **Imported functions** for what no CLI path reaches: `register_project`, and
   `agent_platform`'s registry validator and writer.

**Fixture (per D7).** The stale default branch is a commit whose contract is
the fixture contract without its required top-level `release` member, the
`/release`-absent violation of a pre-release-profile schema. The fixture proves
its own premise: the resolver refuses that commit's tree `invalid_contract`. A
second variant has a default branch with no contract at all.

Acceptance criteria and their deterministic checks:

| AC | Check |
|----|-------|
| 1 | Stale `main`, `dev` self-naming with the adoption: `--register --integration-branch dev` reports `registered: true`, `revision.ref` `refs/remotes/origin/dev` at the pushed commit and `branch_override` `{dev, main, default_contract_unresolved}`; the registry entry is `{project_id, root, branch_override}` with the same object. The same holds for the no-contract variant. `platform-status --fleet` lists the project as before. |
| 2 | Same fixture, `dev` without the evidence record: refuses `not_integrated` / `adopt.registration.not_integrated`, no registry file. |
| 3 | Three cases refuse `not_integrated` / `adopt.registration.integration_branch_unresolved` with no registry file: operand not listed by `origin`; operand branch whose contract does not resolve (the operand naming stale `main`); operand branch whose contract names another branch. |
| 4 | The existing `RegistrationTest`, `RemoteRegistrationTest`, `RegisterProjectInnerCheckTest` and report-shape tests are not edited and pass. New: on a resolving default that hops to `dev`, the operand `dev` yields a report and registry bytes equal to the run without it; the operand `main` refuses per R3. Stale `main` without the operand refuses `adopt.registration.not_integrated` as today. |
| 5 | The AC1 run is made from a checkout whose local `dev` and `main` point at unrelated commits, with an untracked file and an unstaged edit, and whose working tree has no contract: it registers, and local branch ids, `git status --porcelain` and the untracked bytes are unchanged, with no `FETCH_HEAD`. |
| 6 | `just agent-workflow-tests` passes; `just build` passes. |

Further required cases: the operand without `--register` refuses per R1; a
normal re-registration of a project whose entry carries an override drops it;
registering a second project preserves the first one's override; a repeated
operand registration leaves the registry byte-identical; an operand-selected
branch that is `not_conformant` reports the override with `registered: false`
and writes nothing; the validator
refuses an override with a missing, extra or non-string member or an unknown
reason, and still refuses any other extra entry member.

## Out of scope

- A remote-side source of the branch name other than the contract (per D1).
- Overriding a default branch whose contract resolves but names a branch the
  operator considers wrong (per D2); the repair there is the contract.
- An `origin` that advertises no default branch: still
  `adopt.registration.remote_default_unknown`, with or without the operand.
- Showing the override in `platform-status --fleet`, or any other consumer.
- Plain `verify`, `plan`, `apply`, the resolver and the contract schema.
- Migrating existing registry files: every one of them is already valid.
- Rolling the platform back after an override was stored: an older reader
  refuses that entry as an unexpected member; re-registering after the default
  branch catches up removes it.
- Any Nodo-specific logic, running Nodo's registration, and the rest of
  https://github.com/fagenorn/nix-config/issues/210.

## Decision ledger

Rows cite issue 148's ledger as "148 Dn" and issue 341's as "341 Dn".

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The explicit `--integration-branch` operand only, accepted as a pointer that `origin` and the branch's own contract must confirm (listed, resolves, self-names). Narrows 341 D3's rejection of a CLI branch argument: the operand never supplies policy, the contract on the named branch does. | Issue 363 candidate (b) and its two conditions. 148 D26: the resolver is the only reader of contract policy. `bootstrap.md`: no policy is defaulted or guessed. The bar's YAGNI and token economy (one operand). | An automatic remote-side source: none exists that is independent of the default contract. Scanning every listed branch for a self-naming contract costs a fetch and export per branch and can match more than one; a custom ref or symref on `origin` is a new write surface nobody maintains; a forge API is not repository-agnostic and needs credentials; parsing the unresolvable contract by hand breaks 148 D26. Both operand and source: twice the surface for one need. |
| D2 | The operand takes effect only when the default branch's contract does not resolve (any non-zero `resolve`, including no contract). A resolving default contract stays the authority: an agreeing operand is a no-op, a disagreeing one refuses `integration_branch_unresolved` rather than being ignored or obeyed. | Issue 363, stated twice: "a default branch whose contract resolves keeps today's behaviour exactly" (and AC4). 341 D3: the contract at the remote names the branch. The bar's fail loud. Tight scope: loosening later is compatible, tightening is not. | Also honouring the operand when the default resolves but names another branch (the issue's "does not yet name it"): two resolving contracts on `origin` would disagree and an operand would pick the winner, which contradicts AC4's wording. Silently ignoring a disagreeing operand: an untruthful success. Skipping the default branch whenever the operand is given: loses the reason and changes behaviour for resolving defaults. |
| D3 | The registry entry gains one optional closed member, `branch_override` `{branch, default_branch, reason}`, written only for an operand-selected registration and dropped by any later registration without one. Amends 148 D18's "exactly an identity and a location" by that one provenance member; the ban on cached verdicts and version stamps stands, and no reader decides anything from it. | Issue 363 AC1: "the report and registry entry say which branch was pinned and why", and candidate (b): "the registry entry records that the default branch did not carry the hop" — a later, explicit statement by the author of 148 D18. 148 D18's stated reason (a stored verdict is stale by construction) does not reach a record of how registration was reached. | Report only, registry untouched: fails AC1 as written. A sidecar file beside the registry: a second persisted store with its own lock and lifecycle for three strings. Storing the member on every entry (source `default_branch`/`default_contract`): changes the bytes of every existing registration and the pinned issue-341 tests. |
| D4 | No version bump: the report keeps `schema_version` 2 with `branch_override` present only when set, and the registry keeps `schema_version` 1. | AC4: the existing tests pin the report's member set and version 2 and the registry document at version 1, and must pass unedited. Every report and registry a caller can produce today stays byte-identical; the new member appears only on a path that refuses today. No reader gates on the registry version value, so a bump would protect nothing. | Report schema 3 with an always-present nullable member: the cleaner shape, but it edits the pinned tests AC4 freezes. Registry schema 2: rewrites every registry on its next write for no reader's benefit. |
| D5 | No new `ADOPT_ERROR_CODES` member. Operand failures reuse `not_integrated` / `adopt.registration.integration_branch_unresolved`; the operand without `--register` refuses `adopt_failure` with a new repair id as a JSON error object. | AC3 names the repair id. 148 D20 and 341 D6: the ten codes are closed and causes are separated by repair id. `adopt_project` emits every refusal as a JSON error object and never uses argparse's own error exit for a semantic rule. | An argparse usage error: stderr text and no error object, unlike every other refusal of this command. Silently ignoring the operand on plain `verify`: the operator believes a branch was checked. |
| D6 | When the default contract does not resolve, no operand was given and the pinned default carries no evidence record, the `adopt.registration.not_integrated` message names the unresolved default contract and the operand. Code and repair id are unchanged. | The bar's truthful terminal states and "the log stream is the debugger": today's message calls the default branch "the remote integration branch", which is the misreport issue 363 quotes. It is how an operator discovers the operand. | Leaving the message: the refusal keeps pointing at a missing record on a branch that was never the integration branch. A new repair id: tests and callers key on the existing one, and AC2 keeps it. |
| D7 | The stale-default fixture is the current fixture contract minus its required top-level `release` member, and the fixture asserts the resolver refuses it `invalid_contract`; a no-contract default is a second variant. Seams stay those of 341 D9, plus imported `agent_platform` registry functions. | The bar's tests that can fail: fixtures shaped like production values (`/release` absent is one of the violations issue 363 reports), and a premise the test proves rather than assumes. agent-helpers rule 5. | A syntactically broken JSON file: resolves to a different refusal than an older schema and would stay green if schema drift stopped being refused. A mocked resolver: asserts calls, not behaviour. Reconstructing the full legacy `bindings.workflow.release` shape: couples the fixture to a schema no code here reads. |
| D8 | A repeated `--integration-branch` refuses `adopt_failure` with repair id `adopt.verify.integration_branch_repeated`; it and D5's without-`--register` refusal are both raised in `command_verify` after the manifest check and before the repository is opened. | R1 "at most once". D5: a semantic rule of this command is a JSON error object. The bar's fail loud: argparse's default action keeps the last value and discards the others without a word. 341 D6: one cause per repair id. | Argparse's default `store`: two different branch names would register against the second silently. Reusing D5's repair id: two causes under one id. |
| D9 | The override is carried on `VerificationSource` as two optional fields (the default branch, the reason) plus a flag for whether the default contract resolved, and one function builds the object, taking `branch` from the source's fetched branch. No dispatch on `reason` is written: the registry validator's membership test against the closed set is the only place the value is read, and the writer's reason is taken from that same set. Malformed overrides are refused with `platform.registry.projects.branch_override.*` codes. | The spec's "Verification source" and "The branch override" decisions; the existing `platform.registry.projects.*` code family. The bar's YAGNI: nothing consumes the reason, so a dispatch would have no caller. | A dispatch function over the one reason: dead code that only its own test would call. A whole override object stored on the source: it could name a branch other than the pinned one. |
| D10 | The new cases are new classes in `test_adopt_verify.py`, the imported `agent_platform` cases included, and every change to that file is an addition. The stale default is a local `stale` branch forked before the adoption and published as `stale:main`. AC3's "contract does not resolve" case is covered twice, by the operand naming the default branch and by a second stale branch that is not the default, because R5 refuses the first before its contract is read. The non-conformant case uses a second evidence record, because projection drift makes `resolve` itself refuse and would be reported as an unresolved operand branch. | AC4: the issue-341 tests are unchanged, which a zero-deletion diff of the file proves. D7 and 341 D9 (same fixtures, same seams). The bar's tests that can fail: each case was run red against the base and green against a throwaway prototype during planning. | A new test file: the fixtures and `VerifyTestCase` live here, and importing a `TestCase` across files collects its tests twice. Only the operand-names-default case for AC3: it would stay green if an unresolving operand contract were accepted. |
| D11 | The operand arm and the contract-named hop share one private pin-and-confirm helper in `adopt_verify` (fetch, pin, export, resolve, require the contract to name the branch); the plan's verbatim operand block and its "the hop block stays as it is" are read as fixing call order and refusal text, not the duplicated statements. | Task 2 review (Important): one policy written twice lets a later tightening of the hop miss the operator-supplied path into the fleet registry. The bar's DRY; R2–R4 hold because call order and every refusal are unchanged. | Keeping the plan's two verbatim blocks: plan-faithful, but duplicates the registry-admission check. |
