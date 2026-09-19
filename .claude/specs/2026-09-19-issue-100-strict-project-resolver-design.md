# Issue 100: Strict Project Resolver Design

## Problem

The workflow system has two competing sources of project policy. The current
resolver reads the authored project contract, validates its complete shape,
normalizes repository paths, reports capability readiness, and refuses stale
generated instructions. Several living skills, support documents, evaluation
fixtures, and the Claude issue orchestrator still use the legacy binding helper
or describe its behavior: read a second configuration file, infer values from
Git, and fill missing values with defaults.

That split lets one workflow phase see different tracker, branch, artifact,
credential, review, or verification policy from another. A missing or malformed
contract can also look successful because the legacy path manufactures a usable
default. The legacy executable is still installed, so editing only the source
skills would leave an activated machine able to follow obsolete instructions.
There is currently no authored command through which this issue can activate
the managed files and inspect those installed surfaces.

## Solution

Adopt `ResolvedProject` as the only living project-policy interface. At the
entry boundary of each workflow phase, the owning skill runs
`resolve-project resolve --repo-root <checkout>` exactly once. It validates the
successful JSON in memory and retains that immutable snapshot for the whole
phase. Included documents, nested routines, and commands in that phase consume
values from the retained snapshot; they do not invoke either resolver again,
read the authored contract, persist the snapshot, infer policy from repository
state, or supply defaults.

A resolver refusal ends the phase before artifact mutation or external side
effects. The phase reports the resolver's `error.code`, `repair_id`, and ordered
violations without translating a refusal into a partial snapshot. Authored
unsupported capabilities remain distinct from errors: a skill may follow an
explicit no-capability route only where its workflow already defines one, while
a blocked capability stops the dependent operation with its reported reason and
repair identifiers.

Migrate every living consumer and supporting surface in one change. This
includes shared skills, the Claude-only issue orchestrator, from-issue support
documents, release and wayfinding policy prose, workflow documentation,
evaluation setup and fixtures, contract tests, and the lifecycle-guard comments
that still name the old configuration. Delete the legacy resolver, its dedicated
tests, its managed installation, and the obsolete configuration once no living
consumer remains. Point-in-time specifications and plans remain unchanged.

Add an authored command named `nix-activate` with argv `['just', 'switch']`,
repository-root cwd, and an empty environment-name list. The implementation
applies this as a narrow, reviewed bootstrap patch without reading or retaining
the raw contract. This is the sole pre-resolution repair: it supplies no policy
value to a consumer. The first and only resolver call for that implementation
phase must then validate the repaired contract before any other mutation or
effect. `nix-activate` is an installation command; it does not change the
authored deploy adapter or the deploy capability, which remain unsupported.
After the managed build succeeds, invoke the command exactly as returned in the
retained snapshot, then run the workflow suite against source and installed
surfaces.

## Decisions

### Resolution protocol

Every migrated skill states the same phase-entry contract: resolve once from the
checkout it was asked to operate in, retain the returned object in memory, and
treat every resolver error as fatal. There is no helper-missing branch,
`not_onboarded` exception, direct contract read, legacy configuration read,
manifest sniffing, Git-based policy inference, or literal fallback. A delegated
phase has its own entry boundary and therefore performs its one resolution in
its own worktree; subsequent work inside that phase reuses that result.

Consumers use the snapshot namespaces directly:

- artifact locations come from `bindings.paths.artifacts`;
- architecture, standards, context, hints, operations, and rejection material
  come from the corresponding `bindings.paths` lists and their knowledge
  capability states;
- tracker adapter, repository slug, and environment names to remove come from
  `bindings.tracker`, including
  `credential_env.unset_before_invocation` as an exhaustive list rather than a
  legacy Boolean;
- branches, worktree naming, commit policy, and merge policy come from
  `bindings.vcs`;
- orchestration limits, verification IDs, and review IDs come from
  `bindings.workflow`; and
- an executable named by policy is invoked from its `bindings.commands` entry,
  preserving argv words, absolute cwd, and the declared environment-name list.

Capabilities are checked at the operation they govern. Optional knowledge that
is authored unsupported is skipped; blocked knowledge is reported when that
knowledge is required for the current phase. Tracker-free and release-free
routes exist only when the corresponding skill already defines behavior for an
authored unsupported capability. No capability state licenses a guessed value.

### Living-surface migration

The canonical shared skill tree remains the source of truth. The Claude-only
orchestrator remains a separate source because its host features are not shared
with Codex. Their support documents and evaluation harnesses are living
consumers and migrate with them. The fixture repository is onboarded to the
project contract and current generated projections so evaluations exercise the
same resolver path as real projects.

The migration removes both mentions and behavior of the old policy surface.
Repository-wide living-surface checks reject the legacy executable name, the
legacy configuration name, default-value guidance, direct authored-contract
reads, and the legacy tracker-credential Boolean. Concrete shell-parser symbols
that recognize an allowed `unset GITHUB_TOKEN` command remain implementation
mechanics; their comments derive the behavior from the resolved tracker
credential list. Broader lifecycle-guard redesign belongs to issue 116.

### Source and installed parity

One assertion matrix accepts a surface descriptor and applies the same checks
to source and installed trees. It verifies the expected consumer set, exactly
one resolution instruction per phase entry, use of the required snapshot
fields, fatal handling of resolver errors, and absence of legacy references.
Source mode covers the shared source tree plus the Claude-only source.
Installed mode covers the managed Agents skill tree plus the installed
Claude-only orchestrator.

The ordinary suite always verifies source behavior and adds installed mode when
both managed roots exist. Installed mode uses the same assertion function and
fails on a missing expected consumer; it does not silently downgrade to source
mode after either root is detected. On the managed host for this issue,
activation is required and both installed roots exist, so the matrix must run
rather than skip. The installation declaration must also no longer publish the
legacy executable. The final sequence is managed build, resolved activation,
then the complete workflow suite, making parity observable at user-facing paths
instead of assuming that a successful Nix evaluation updated them.

### Refusal fixtures

Keep resolver subprocess output as the behavioral boundary. Four explicit
fixtures exercise the migration contract:

| Fixture | Required refusal |
|---|---|
| Repository root with no authored contract | `not_onboarded` with `onboarding.contract.missing` |
| Repository root with malformed contract JSON | `invalid_contract` with `contract.parse` |
| Non-repository directory with no contract above it | `not_onboarded` with `onboarding.contract.missing` |
| Repository with a stale generated instruction projection | `invalid_projection` with the affected `projection.<id>.stale` repair ID |

Each fixture asserts exit status 2, the closed error shape, no snapshot members,
no fallback behavior, and no filesystem mutation. Existing detailed resolver
tests remain the authority for schema validation and projection rendering; the
new workflow-facing cases prove that migrated consumers document and preserve
those refusals.

## Test seams

1. **Resolver subprocess seam.** Extend the existing resolver contract suite
   with the four named fixtures and exact documented error identities. This is
   the highest existing seam for root discovery, parsing, projection freshness,
   output shape, and read-only refusal.
2. **Workflow instruction seam.** Refactor the existing workflow contract suite
   into the shared surface assertion matrix. Run it against canonical source
   consumers and, when present, their installed counterparts. It must fail for
   a second resolver call, a default/fallback instruction, a direct policy read,
   an incorrect snapshot field, or any legacy reference.
3. **Managed installation seam.** Nix evaluation/build proves the managed file
   declarations contain the resolver and current skills but no legacy resolver.
   The resolved `nix-activate` command then materializes that generation, after
   which the installed mode of the workflow suite proves the user-facing tree.
4. **Whole-workflow seam.** The authored verification command IDs continue to
   run the Nix build and complete agent workflow suite, in that order around
   activation. Existing evaluations use an onboarded fixture and therefore
   exercise strict resolution without a compatibility path.

## Out of scope

- Redesigning lifecycle-guard parsing, command adjudication, or credential
  security; issue 116 owns that architecture.
- Adding a deployment adapter or changing deploy from unsupported.
- Rewriting historical specifications, plans, reports, or other point-in-time
  artifacts that record the former interface.
- Adding resolver defaults, compatibility aliases, schema-version expansion,
  or a second policy abstraction around `ResolvedProject`.
- Changing unrelated host configuration or retained worktrees.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Resolve exactly once at each phase entry, retain one in-memory `ResolvedProject`, and stop on every resolver refusal before mutation or external effects. | Project invariants require one resolution, no raw read or persisted snapshot, and no defaulted policy; the issue requires fail-closed consumers. | Preserve `not_onboarded` or helper-missing fallbacks; they recreate policy the resolver declined to provide. |
| D2 | Migrate every living source, support document, fixture, evaluation, installed surface, and policy comment in one cutover; delete the legacy resolver, tests, installation, and obsolete configuration while preserving historical artifacts. | The issue requires zero living source or installed references; the bar preserves point-in-time records and gives policy one authoritative home. | Leave a compatibility shim or partial consumer allowlist; either keeps two policy interfaces alive. |
| D3 | Map consumers directly to snapshot namespaces and capability states, including the tracker credential environment-name list and command IDs with exact argv/cwd/env. | The resolver already exposes these closed namespaces, and project invariants require commands to be addressed by authored ID. | Translate back into legacy flat bindings or Boolean/default forms; that loses authored distinctions and invites drift. |
| D4 | Use one behavioral assertion matrix for canonical and installed skill surfaces, and require installed execution after managed activation on this host. | The issue requires identical source/installed zero-reference and behavior checks; architecture documents the managed source-to-install topology. | Check source only or compare build success alone; neither observes what agents actually load. |
| D5 | Pin missing, malformed, non-repository, and projection-drift cases to the resolver's closed errors and assert no snapshot, fallback, or mutation. | Existing resolver contracts define `not_onboarded`, `invalid_contract`, and `invalid_projection`; the bar requires truthful terminal states and observable tests. | Assert only nonzero exit status; that would allow error translation, partial output, or fail-soft regression. |
| D6 | Add `nix-activate` as `just switch` at repository root with empty env, apply it through a narrow bootstrap patch, and keep deploy unsupported. | Program-owner direction and `CLAUDE.md` identify `just switch` as the supported activation path; the resolved contract currently has no activation command. | Invoke an unauthored activation command or reclassify activation as deployment; both contradict the project contract. |
| D7 | Treat each resolved review command as base argv and append a direct, fresh Codex `exec` invocation with read-only sandbox, explicit `gpt-6-astra` model, explicit `model_reasoning_effort="xhigh"`, JSONL events, a last-message output file, and ephemeral state; establish the route with a real bounded review and record Codex identity only after validating selected runtime metadata and the operation's output contract. | The resolved review IDs and command entries are the only executable policy. `codex exec` shares the local app-server daemon, so argv shape and binary availability do not establish reviewer identity or spare host capacity. | Preserve the plugin-agent bridge, infer success from availability/exit zero, or route around a capacity rejection; these can misattribute a run or overcommit the host. |
