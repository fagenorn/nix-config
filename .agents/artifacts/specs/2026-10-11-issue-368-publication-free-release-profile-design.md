# Declare a forge target without a publication, issue 368

https://github.com/fagenorn/nix-config/issues/368 (blocks
https://github.com/fagenorn/nix-config/issues/367, which blocks
https://github.com/fagenorn/nix-config/issues/126; extends
https://github.com/fagenorn/nix-config/issues/124).

## Triage

Input signals: `contract_change` hit (contract grammar and resolver capability change); `concurrency_or_persistence` no (pure derivation); `open_design_questions` hit (spec chooses the form); `criteria_shape` hit (five criteria). Verdict: `{"hits":["contract_change","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}`. ran: full (shadow)

## Problem

A project that integrates on one branch and is released by people, not by this
platform, still has to tell the platform which forge repository it is. Issue 116
D3 derives the lifecycle guard's per-repository facts from the release-profile
forge target in the project's own contract, and nothing else may stand in for
it. Today the only way to author that target is a release profile, and the
smallest profile the grammar accepts must publish: `publication` must be
`{actions}` with at least one action, and the one registered adapter offers only
the irreversible `tag` and `release` operations. A maintainer who wants to say
"this is my repository, and the platform publishes nothing for it" must instead
declare a tag or a GitHub Release that nobody intends to run, and the resolver
then reports a release capability the project does not have. Nodo is the first
such project, and its registration into the derived guard path is blocked on it.

## Solution

A profile may say `"publication": "none"`, the same explicit word `activation`
already has. Such a profile declares its target, requirements and bindings as
any profile does, passes the unchanged same-repository rule, and has no node:
no action, no activation unit, no recovery unit and no proof obligation. It
compiles to an empty graph, is never bound to a release candidate, and gives
the project no release capability.

`resolve-project resolve` gains one derived member, `release`, that lists every
target a profile binds together with the operations the profile declares on it.
A publication-free profile's target is listed with no operations, so a reader
sees the repository and sees that nothing may be published to it.

## Requirements

- **R1 (AC1).** A contract whose one profile declares a `github_repository`
  target for its own repository and `"publication": "none"` resolves, and the
  snapshot's `release.targets` holds that target.
- **R2 (AC2).** For that contract `capabilities.release` is `unsupported`, the
  target's `operations` is empty, `bind_candidate` refuses the compiled profile,
  and an adapter bound to it through `core_binding` refuses every request before
  any child process runs.
- **R3 (AC3).** A publication-free profile whose target names another repository,
  another branch than the default branch, or a non-GitHub tracker is
  `invalid_contract` with `contract.release.same_repository`, exactly as a
  publishing profile is.
- **R4 (AC4).** For nix-config's own contract the four existing snapshot members
  are byte-identical before and after, and its contract file is not edited. Every
  existing test in the four `tests/test_release_*` modules stays unmodified and green.
- **R5 (AC5).** `just agent-workflow-tests` passes.
- **R6.** No path takes a target from anywhere but the authored contract: no
  flag, environment variable or default supplies one, and a refused contract
  prints no snapshot.

## Decisions

### 1. Grammar: `publication` is `"none"` or `{actions}` (per D1, D2)

`publication` stays a required member of the closed profile object. Its value is
one of two forms: the string `"none"`, or `{"actions": [action, at least one]}`
exactly as today. An empty `actions` list, an omitted member and any other value
stay `invalid_contract` with `contract.release.invalid`. Any other non-object
value reports `publication must be "none" or {actions}`, the wording `activation`
uses.

A profile with `"publication": "none"` is a *publication-free profile*. Three
rules hold for it, each a `contract.release.invalid` violation when broken:

- `activation` must be `"none"` (pointer `/activation`). Activation consumes a
  publication's receipt, and no activation-only profile exists today.
- `proof.obligations` must be `[]` (pointer `/proof/obligations`). No transaction
  is ever created for the profile, so an obligation would never be collected.
- `recovery.units` must be `{}`. This is the existing rule that every recovery
  key names a declared node; it needs no new code.

Every other member keeps its rule and stays required: `profile_version`,
`target`, `requirements`, `bindings`, `proof.convergence_window_ms`, `recovery`
and `limits`. Target kinds, credential classes, adapter ranges and the
same-repository rule are judged from `bindings` alone, so they apply unchanged.
`capabilities.deploy` must still be unsupported while any profile exists.

One function in `release_profile` answers "the authored nodes of this phase" for
a grammar-valid profile, returning an empty list for `"none"`. Every reader of
`publication.actions` or `activation.units` after the grammar goes through it:
the admissibility rules, `lower`, `compile_profile` and the `release` command.
The `"none"` spelling is therefore known in the grammar and in that one function.

### 2. Admissibility and compilation (per D3)

The four admissibility rules run over a publication-free profile unchanged and
find nothing: the first three iterate nodes, and the fourth lowers the profile
to a proof declaration and a recovery declaration with no unit and no
obligation, which `compile_proof`, `compile_recovery` and `bind_recovery` accept
(probed at the worktree base). No rule is skipped and none is added.

`compile_profile` returns a `ResolvedReleaseProfile` for it: the usual `schema`,
`profile_id`, `profile_version`, `digest`, `target`, `adapters` and `limits`,
with `publication` and `activation` empty, `deadlines` and `candidate_members`
empty, and both declarations unit-free. The digest covers the authored profile,
`"publication": "none"` included, and the adapter identities, as today.

`bind_candidate` refuses a compiled profile whose `publication` is empty with a
`ValueError` naming the profile, before it reads the candidate. It is the only
producer of `TransactionStore.create` inputs from a profile (issue 124 D5, D20),
and the core accepts a unit-free plan, so this is the check that keeps a
publication-free profile out of the transaction core. `core_binding` needs no
change: its table of compiled nodes is empty, so it already refuses every
`inspect`, `invoke` and `observe` request as "not a node bound to this alias"
(issue 124 D24) before the adapter is called.

### 3. `capabilities.release` (per D4)

`release_capability` returns `unsupported` (null `reason_code` and `repair_id`)
when `release` is `"unsupported"` or when no profile declares a publication.
When at least one profile publishes, today's logic runs unchanged over all
profiles: first inadmissible profile, then first missing adapter executable,
else `available`. `CAPABILITY_STATES` and `REASON_CODES` gain nothing.

### 4. The resolved `release` member (per D5, D6)

The snapshot gains a fifth member, always present:

```json
"release": {"targets": [
  {"profile": "<profile-id>", "adapter": "<registered adapter name>",
   "target": {"handle": "<handle>", "kind": "<kind>", "<kind member>": "..."},
   "operations": ["<operation>"]}]}
```

- One entry per `bindings.targets` handle of every profile, ordered by profile
  id and then handle. `"unsupported"` gives `{"targets": []}`.
- `target` is the normalized target of issue 124 D23: `handle`, `kind` and the
  members the adapter's descriptor declares for that kind. For a
  `github_repository` those are `repository` and `branch`.
- `adapter` is the registered adapter name the target's alias binds, because a
  `kind` is only defined relative to its adapter.
- `operations` is the sorted, duplicate-free list of `operation` values of the
  publication actions and activation units whose `target` is that handle. It is
  `[]` for every target of a publication-free profile and for a target no node
  uses.

A pure function in `release_profile` builds the list from the grammar-valid
authored `release` and the descriptors; `build_snapshot` calls it. The entry
depends on the grammar only, so an inadmissible profile's targets are listed
too: the static same-repository proof has already passed for them.

`resolved_schema_version` stays 1. The member is additive, every reader takes
members by name, and no migration applies.

### 5. `release profile inspect` (per D7)

The command reports a publication-free profile like any other declared profile:
exit 0, exactly seven members, `profile.admissible` true, `graphs.publication`,
`graphs.activation`, `graphs.proof` and `graphs.recovery` empty, and
`graphs.handoffs` empty because nothing is handed from a publication that does
not exist. `bindings` and `conformance.adapters` list the bound adapter with no
node config and no operation mode. `"unsupported"` and an unknown profile id
keep their typed refusals.

### 6. What stays as it is

- The lifecycle guard file and its adversarial table. The guard reads only its
  policy file, so its verdict on `gh release create` is the same for a project
  with and without a publication-free profile (per D8).
- The adapter contract, the forge adapter and its descriptor: no observe-only or
  no-op operation is added.
- The conformance checks: the three release-profile checks judge the compiler
  rules over declared profiles and report `passed` when no rule has a finding.
- The legacy bridge: a forge-only publication-free profile already renders the
  legacy `deploy` member absent, as any forge-only profile with no activation does.
- nix-config's `.agents/project.json` and `tests/fixtures/release/github-release-profile.json`.

### 7. Documentation

`python/README.md` § Release profiles states the two `publication` forms, the
three publication-free rules, the `unsupported` capability, the `release.targets`
member and the `bind_candidate` refusal. The module docstrings of
`release_profile` and `release` follow. No standards shard changes.

## Test seams

Five existing seams, one fixture. Each new test extends the suite that already
owns its seam; no existing test in the four `tests/test_release_*` modules is edited.

- **Fixture.** `tests/fixtures/release/publication-free-profile.json`: one
  profile shaped like the forge fixture beside it, with `"publication": "none"`,
  activation `"none"`, no obligations and no recovery units. Like its siblings it
  is a profile, placed into a contract by each suite's existing builder.
- **Grammar** (`grammar_violations`; prior art `tests/test_release_grammar.py`).
  The fixture has no violation. One row each for: an activation with units;
  a non-empty `obligations`; a recovery unit; `{"actions": []}`; a `publication`
  that is another string; and the three same-repository mutations (R3).
- **Compiler** (`admissibility_findings`, `compile_profile`, `bind_candidate`;
  prior art `tests/test_release_profile.py`). No finding; the compiled profile's
  empty members; `bind_candidate` raises with a store tree untouched.
- **Resolver command** (`python -m agent_tools.resolve_project resolve`; prior
  art `ReleaseMemberTest` in the resolver suite). The fixture contract exits 0
  with the R1 target, empty `operations` and `unsupported`; a different
  repository refuses `invalid_contract`; the forge profile lists its target with
  `["release", "tag"]` and stays `available`; `"unsupported"` gives an empty
  list; a contract with one publishing and one publication-free profile is
  `available`.
- **Release command** (`python -m agent_tools.release profile inspect`; prior
  art `tests/test_release_command.py`). The section 5 report for the fixture.
- **Adapter binding** (`release_adapter.core_binding` over the fake forge world;
  prior art `tests/test_release_adapter_core.py`). A `release` invoke request
  against the compiled fixture profile is refused and the world records no `gh`,
  `git` or guard invocation (R2).

R4's byte-identity is acceptance evidence, not a suite: `resolve-project resolve`
on nix-config at the base and at the head, compared after dropping `release`.

## Out of scope

- Authoring Nodo's profile (issue 367) and anything in `elevenyellow/nodocom`.
- Any lifecycle-guard change, including reading `release.targets` or refusing
  `gh release create` from the contract (issue 126).
- A new adapter, operation, target kind or observe-only mode.
- Any edit to nix-config's own contract or its release fixture.
- An activation-only profile, and proof obligations without a publication.
- A `resolved_schema_version` bump or a platform manifest change.
- Reporting anything about `release.targets` in conformance or adoption output.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The form is a profile with `"publication": "none"`; `{"actions": []}` stays invalid | The user's 2026-10-11 decision on issues 367 and 126 (a minimal profile, no publication actions); issue 116 D3 names `release.profiles.<id>.bindings` as the one owner of the forge target; `activation` precedent; bootstrap "no project policy is defaulted" (an explicit word, not an empty list that reads as unfinished) | A dedicated target-only declaration: a second authority for the target that issue 126 would have to read beside profiles. Empty `actions`: weakens the existing non-empty rule for every profile |
| D2 | A publication-free profile must have activation `"none"`, no obligations and no recovery units; every other member stays required | Issue 124 D4 (no declared member that nothing enforces); activation needs a publication receipt; the profile object stays closed | Letting the core judge obligations nobody collects; making `proof`, `recovery` or `target` optional for this form (a second profile shape) |
| D3 | The profile compiles through the unchanged rules to an empty graph; `bind_candidate` refuses it; no rule is skipped | Probe: the core compilers and `TransactionStore.create` accept zero units, so only `bind_candidate` can stop it; issue 124 D5, D20, D24; bar "defense in depth" | `compile_profile` refusing (loses the digest and version issue 116 D3 binds to the target, and breaks inspection); relying on `core_binding` alone |
| D4 | `capabilities.release` is `unsupported` when no profile publishes; otherwise today's logic over all profiles | Issue AC2; issue 124 D1 (`unsupported` = no release contract to run); `blocked` promises a repair that does not exist | A new state or reason code such as `release_publication_free`; excluding publication-free profiles from the mixed-set checks (no such contract exists) |
| D5 | Targets are exposed as a new always-present top-level snapshot member `release.targets`, for every profile of every project, with no schema bump | Issue AC1 and "repository-agnostic, no Nodo special case"; mirrors the authored top-level `release`; `bindings.workflow.light_lane` precedent for an additive member at schema 1; capability entries are closed to `{state, reason_code, repair_id}`; grill probe: no package module, skill script or test pins the snapshot's top-level key set or digests the snapshot | Under `bindings` (normalized authored input, not derived facts); inside `capabilities.release`; only for publication-free profiles (a special case, and issue 126 needs nix-config's target the same way) |
| D6 | Each target entry carries the `operations` its profile declares on it | Issue: the resolver reports "a forge target but no publication capability"; a bare target invites a reader to treat presence as release authority; `capabilities.release` is project-wide while targets are per profile | Target only, leaving the reader to join against the capability |
| D7 | `release profile inspect` reports a publication-free profile and exits 0, with `handoffs` empty | Issue 124 D15 and issue 69 (diagnosis never refuses a declared profile); `release_unsupported` means no profile is declared | Refusing with `release_unsupported`, which the Phase-0 note's "inspect refusal" suggested: it would call a declared profile undeclared |
| D8 | AC2's "`gh release create` and the release command path are still refused" is met at the profile-driven path (capability, `bind_candidate`, `core_binding`); the guard is untouched | Probe: the guard reads only its policy file and already allows the guarded spelling for an authorized owner whatever the contract says; guard consumption of the contract is issue 126; `operations: []` (D6) is what that derivation must honor | Teaching the guard to read the contract here (issue 126's scope, and the guard imports nothing from `agent_tools`) |
| D9 | AC4's "resolves exactly as before" means the four existing members are byte-identical; nix-config's snapshot gains `release.targets` with its own target | D5 is repository-agnostic; the contract file and the release fixture are not edited | Hiding the member for publishing profiles to keep the output byte-identical (a special case) |
| D10 | The three resolver-suite pins of the snapshot's member set move from four members to five (`SnapshotShapeTest`, `WorkflowRefusalFixtureTest.SNAPSHOT_MEMBERS`, and the non-current-schema case of the platform suite); corrects D5's probe claim that no test pins the key set | Plan probe at the base: those tests assert exactly four names; they are outside the `tests/test_release_*` modules R4 freezes; a prototype with only these pins moved passed `just agent-workflow-tests` | Keeping four members by nesting targets under `capabilities` or `bindings` (D5 already rejects both) |
| D11 | A recovery unit in a publication-free profile is reported by the unedited existing rule as `contract.release.reference_unknown` (section 1 says both "`invalid`" and "needs no new code"; the code wins), and an activation other than `"none"` there gets one `invalid` violation at `/activation` and is judged no further | Plan probe: the existing rule already reports each stray key with `reference_unknown`; the module rule that a malformed input is reported once | A second, `invalid` rule for the same key (two violations for one mistake); also judging the refused activation's units (cascading reports about nodes that cannot exist) |
| D12 | R4's byte-identity is measured by running the base and the head `agent_tools` against the same checkout root and comparing after dropping `release`; the base package comes from `git archive` into scratch | The installed `resolve-project` is neither version, and `project.root` is absolute, so two checkouts or the installed command would differ for unrelated reasons | Comparing a base worktree's output with the head worktree's (roots differ); a golden snapshot file in the repository (a persisted snapshot, which the bootstrap invariants forbid) |
| D13 | Amends D12: the AC4 comparison runs both resolvers from one process and holds both snapshots in memory; only the base package source is extracted to scratch, and only the verdict is recorded | Bootstrap invariant "never persist a snapshot", which has no scratch exception (standards review B1) | Redirecting the two outputs to scratch files and deleting them afterwards (still a persisted snapshot while they exist) |
| D14 | The post-grammar readers, `release_targets`, the capability rule and the snapshot member land first while the grammar still refuses `"publication": "none"`; grammar acceptance, the `bind_candidate` refusal and the inspection report are one later commit. The publication-free branches of the first commit are proven by calling `lower`, `release_targets` and `release_capability` as imported functions on the fixture | The bar: no half-wired path in a commit (standards review B2); those functions take a grammar-valid profile as an argument, so they are testable below the grammar without a new production seam | Grammar first (interim commits resolve a publication-free contract with a wrong capability, no bind refusal and a failing inspection); one single task for everything (a review unit of about twelve files with no independently approvable part) |
