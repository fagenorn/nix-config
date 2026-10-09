# Release profiles, the adapter contract and the forge adapter — issue 124

Design for [#124](https://github.com/fagenorn/nix-config/issues/124), 2026-10-09, against main
`eca16cd`. Written in autonomous mode (`from-issue --auto`). Every choice below is an agent
judgment inside the issue's delegated scope and is recorded in the decision ledger. None of them
is a human answer, grant or irreversible confirmation.

## Triage

### Lane triage
Input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds release.profiles schema to .agents/project.json resolution, a compiled ReleaseProfile shape and the three-operation adapter contract"}, "concurrency_or_persistence": {"value": "hit", "evidence": "forge merge requires compare-and-swap on the prior tip; profiles compile immutably into transaction-core state"}, "open_design_questions": {"value": "hit", "evidence": "nix-config's legacy .claude/skills.config.json was deleted in 1722a65d, so AC5's byte-identity target and nix-config's own profile shape need a decision"}, "criteria_shape": {"value": "hit", "evidence": "nine acceptance criteria, one of which needs a live provider inspect against a real PR"}}, "paths": ["python/agent_tools/release_profile.py", "python/agent_tools/forge_adapter.py", "python/agent_tools/resolve_project.py", "python/agent_tools/conformance_checks.py", "home/common/claude-code/lifecycle_guard.py", "tests/test_claude_permission_guard.py", ".agents/project.json"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

The #123 transaction core is shipped, but nothing calls it. Release behavior today is ship-release
prose: it tags a commit, pushes the tag and creates a GitHub Release. Three things are missing:

- **An authored release contract.** A project cannot say what a release is. The contract carries a
  command-shaped `bindings.workflow.release` and a Railway-shaped `bindings.deploy`. Release
  support is a capability flag tied to that command, so the explicit support #85 requires does not
  exist.
- **A compiler.** No compiler turns a declaration into the immutable proof and recovery inputs the
  core takes. The three `repository.release_profile.*` conformance checks therefore report
  `not_run`/`profile_unsupported` on any project that declares a release (#122 D27).
- **An adapter seam.** Nothing exposes `describe`/`inspect`/`invoke` with the closed outcome sets
  #85 fixed. ship-release had to rewrite its double-tag guard because a Release's
  `targetCommitish` holds a branch name, not the tagged commit.

#116 adds obligations this issue owns:

- one enforcement implementation shared by the native hook and the adapter;
- the delete-branch arm's permanent-head repair;
- the required-check floor;
- refusing a CAS-required merge until an atomic target-tip mechanism is proven.

## Solution

Add one required top-level member, `release`, to `.agents/project.json`. Its value is either the
literal `"unsupported"` or a closed `profiles` map. Each profile carries exactly the nine #85
groups. The work is split between four places:

- **The resolver** validates the profile grammar, references and adapter support, and returns
  `invalid_contract` when they fail. It also compiles every profile so it can report release
  readiness.
- **The compiler** (`release_profile`) produces an immutable, candidate-independent
  `ResolvedReleaseProfile`. It applies the admissibility rules:
  - the #86 lints;
  - #91's derived-class ban, through the core's own `compile_proof`/`compile_recovery`;
  - #93's feasibility.

  A violation is reported as an ordered list of findings. Binding a candidate lowers the profile
  into exactly the `proof`, `recovery` and `concurrency_keys` inputs that `TransactionStore.create`
  takes. The core recompiles those inputs, so admissibility is checked again before any mutation.
- **The adapter contract** (`release_adapter`) is a deep module. It holds a closed registry of
  adapters, each exposing exactly `describe`, `inspect` and `invoke`, plus a thin core binding that
  projects them onto the core's existing effect/observer duck types.
- **The forge adapter** (`forge_adapter`) covers a GitHub-hosted release with three operations:
  - `pr_merge`: `materialize`. Inspect works; invoke is refused until target-tip CAS is proven.
  - `tag`: `index`.
  - `release`: `index`.

  Before every provider mutation the adapter calls the real lifecycle guard through its public
  CLI. Both the guard and the adapter read their spellings from one fixture file, so they cannot
  disagree.

nix-config declares one forge-only profile, `github-release`, matching ship-release's
single-branch path: tag plus Release, activation `none`. A read-only `release` command exposes
`profile inspect` (the seven-member `ReleaseProfileInspection`) and `adapter inspect` (the
demo's live PR read). The legacy `.claude/skills.config.json` keeps only its `deploy` member as a
generated projection during the bridge.

## Decisions

### 1. The authored `release` member (per D1)

`TOP_LEVEL_MEMBERS` gains `release`, and it is required. Omitting it is `invalid_contract` at
pointer `/release` with repair `contract.top_level.member_missing`. The value is one of two forms:

- `"unsupported"`: the project has no release contract.
- `{"profiles": {<profile-id>: <profile>, ...}}`, with exactly that one member and a non-empty map.
  Profile ids and every node id below match `^[a-z][a-z0-9-]{0,62}$`.

Any other value is `invalid_contract` with repair `contract.release.invalid`.

The authored `capabilities.release` entry is removed, and so is `bindings.workflow.release`
(`WORKFLOW_MEMBERS` loses `release`). Both become `member_unexpected` if they are still present.
`ResolvedProject` keeps its four members and its eleven capability entries.
`capabilities.release` is now derived:

- `"unsupported"` gives `unsupported`.
- Profiles give `available` when every profile compiles admissibly and every referenced adapter's
  declared executables resolve on `PATH`.
- Otherwise it is `blocked`, with the first failing reason code. `REASON_CODES` gains
  `release_profile_inadmissible` and `release_adapter_unavailable`. The repair id is
  `capability.release.<reason>`, as today.

The rule that a `supported` capability's binding must be complete (`CAPABILITY_BINDING_REQUIREMENTS`)
loses its `release` row. `bindings.deploy` and `capabilities.deploy` stay as the bridge-era legacy
deploy binding that ship-release's phase 5 still reads. One rule prevents dual authority: a
contract with profiles must declare `capabilities.deploy` unsupported. Breaking it is
`invalid_contract` with repair `contract.release.deploy_conflict`.

### 2. The profile grammar (resolver tier, `invalid_contract`; per D2, D4)

The grammar lives in one function, `release_profile.grammar_violations(release, contract)`. It
returns violations in the resolver's `{pointer, message, repair_id}` shape, and the resolver
merges them into its single ordered list. Every object is closed: an unknown member,
mode or reference is a violation. Each profile has exactly these members:

| Group | v1 shape |
|---|---|
| `profile_version` | positive integer |
| `target` | `{environment: <id>, concurrency_keys: [non-empty unique strings, ≥1]}` |
| `requirements` | `{adapters: {<alias>: {min_inclusive: SemVer, max_exclusive: SemVer}}}`. Both bounds are required, and min < max. Exact pins and minimum-only ranges are invalid (#85). |
| `bindings` | `{adapters: {<alias>: {adapter: <registered name>}}, targets: {<handle>: {adapter: <alias>, kind: <describe target kind>, ...kind members}}, principals: {<id>: {class: <string>}}, credentials: {<id>: {adapter: <alias>, class: <describe credential class>}}}` |
| `publication` | `{actions: [action, ≥1]}`; action = `{id, mode: materialize\|promote\|index, adapter, operation, target, principal, credential, effect, config_schema_version, config, deps, observation_deadline_ms?}` |
| `activation` | `"none"` or `{units: [unit, ≥1]}`; unit = action members with `mode: local_apply\|provider_deploy\|publication_triggered\|convergent_pull` |
| `proof` | `{convergence_window_ms: positive integer, obligations: [obligation]}` |
| `recovery` | `{units: {<action-or-unit id>: {posture, anchor, compatibility, edges}}}` |
| `limits` | `{}`, with no member admitted in v1 |

How references and values are checked:

- **References** are checked here:
  - `adapter`, `target`, `principal` and `credential` must name `bindings` entries;
  - `deps` must name ids in the same phase, with no cycle;
  - each recovery key must name exactly one declared action or unit, and every action and unit
    needs one recovery entry.
- **Effect classes** are #84's `reversible_no_incremental_spend | reversible_bounded_spend |
  irreversible`. `reversible_bounded_spend` is a violation in v1, because no spend-grant consumer
  exists.
- **Adapter support** is read from the registered adapter's static `describe`:
  - the alias must name a registered adapter;
  - the selected exact `adapter_contract_version` must fall inside the declared range;
  - every action's `(mode, operation)` must be one the descriptor marks `supported`, so a
    referenced `unsupported` operation is `invalid_contract` (#85);
  - `config_schema_version` must equal the descriptor's version for that operation, and `config`
    must validate against that operation's closed config schema;
  - each target `kind` and credential `class` must be one the adapter declares.
- **Same-repository proof (#116 D3), static half.** A `github_repository` target carries exactly
  `{adapter, kind, repository, branch}`. `repository` must equal `bindings.tracker.repo_slug`,
  `bindings.tracker.kind` must be `github`, and `branch` must equal `bindings.vcs.default_branch`.
  The live half is the adapter's (section 7).

The grammar deliberately does **not** close these vocabularies:

- the proof `semantic`/`form`/`predicate` values;
- the recovery `posture`/edge `action` values;
- the presence of `observation_deadline_ms`.

The core compilers and the admissibility rules own those (section 3). Otherwise a derived class,
a missing deadline or an unreachable `rolled_back` would show up as `invalid_contract`, and the
compile-time rejection that AC1 and the conformance checks need would never be observable.
Shapes are still checked. An obligation is `{id, semantic, form, predicate, collector, required,
deps, parameters, freshness_ms?}` with string-typed vocabulary members. `collector` names a
`bindings.adapters` alias. `anchor` is `null` or `{target, predicate, parameters}`, and
`compatibility` is `null` or `{predicate, parameters}`. An edge is
`{action, operation, parameters, residue}`.

### 3. The compiler and admissibility (per D2, D3, D5)

`compile_profile(profile_id, profile, contract, adapters=REGISTRY)` is pure. It reads no file,
clock or network. `adapters` is the injectable descriptor registry, and that injection is the test
seam for adapters other than the forge. The function returns a `ResolvedReleaseProfile` or raises
`ProfileInadmissible` with an ordered, non-empty `findings` list. Each finding is
`{rule, pointer, reason, detail}`.

The rules run in this order. Every rule runs over every node, so all findings are reported, unlike
the core's first-failure-wins compilers.

1. **`observation_deadline`**: every publication action and activation unit has
   `observation_deadline_ms` in `[1, 7_200_000]`. A missing value has reason
   `observation_deadline_optional`, and an out-of-range one `observation_deadline_out_of_bounds`.
   No default exists, following bootstrap's "no project policy is defaulted". The cap equals the
   core's maximum convergence window.
2. **`rolled_back_reachable`**: a profile *claims* a `rolled_back` path when any recovery unit is
   `restorable`. When it does, every action whose operation the descriptor marks
   `create_if_absent` (an immutable publication) must be `compensatable`, which by the core's
   posture table means only compensate edges, each with a declared residue. Anything else has
   reason `rolled_back_unreachable` (#86 friction 1).
3. **`restore_anchor`**: a `restorable` unit's `anchor.target` must not be the `target` of any
   action whose operation the descriptor marks `in_place`. Such an action overwrites the live
   bytes the anchor would return to, so the reason is `restore_anchor_destroyed` (#86 friction 2).
   The descriptor's closed mutability vocabulary is `create_if_absent | pointer_cas | in_place`.
4. **`core_plans`**: the profile is lowered into the candidate-independent core declarations, and
   `transaction_plan.compile_proof`, `transaction_recovery_plan.compile_recovery` and
   `bind_recovery` run over them. Their closed rejection reasons are reported verbatim, prefixed
   `proof.` or `recovery.`:
   - `proof.derived_class_named` and `proof.reserved_predicate` are #91's rule;
   - `proof.required_unsupported` is #85's required unsupported collector;
   - `proof.infeasible_cohort` and `proof.latency_out_of_bounds` are #93's;
   - `recovery.posture_violation` and `recovery.unsupported_operation` are #83/#208's.

   The core is the only home of the proof and recovery vocabulary. This compiler copies none of
   it.

How the profile is lowered into core declarations:

- Each publication action and activation unit becomes one core unit
  `{name: <id>, parameters: {"action": <id>, "operation": <op>, "target": <normalized target>}, phase, collector: <adapter alias>}`.
  The adapter dispatches on `parameters.operation`, because the core hands an effect the unit
  `name`, which is the action id.
- `collectors` come from each referenced adapter's `describe`:
  `{basis: deterministic, predicates, max_collection_latency_ms, max_concurrent_collections}`.
- Profile obligations pass through. Their `deps` may name `derived:<class>:<action id>`, the
  compile-time derived-id form #91 permits.
- `effects` maps each alias to every operation its descriptor offers: the supported forward
  operations plus the recovery-capable ones. `compile_recovery` checks a unit's own operation
  against this list as well as its edges' operations.
- `convergence_window_ms` is copied from `proof`, so the core default is never relied on.

`ResolvedReleaseProfile` is a deep-frozen mapping with these members:

- `schema` (`release-profile/v1`), `profile_id`, `profile_version` and `digest`;
- `target`;
- `adapters`: alias → `{adapter, adapter_contract_version, descriptor_digest}`;
- `publication` and `activation`, as validated DAGs in deterministic topological order;
- `deadlines`;
- `proof_declaration` and `recovery_declaration`, the candidate-independent core inputs;
- `limits`.

`digest` is `canonical.telemetry_digest` over the authored profile plus the selected adapter
identities. An adapter's implementation identity is its `descriptor_digest` together with the
platform manifest identity that `platform-status` already publishes. Nothing reads source through
`__file__` (agent-helpers rule 3).

`bind_candidate(compiled, candidate)` turns the compiled profile into the core's inputs.
`candidate` is `{version: "vMAJOR.MINOR.PATCH", commit: <40-hex>, title, notes}`. The function
returns `{proof, recovery, concurrency_keys, subject}`:

- each unit's `parameters` gains `"candidate": {version, commit}` and the action's normalized
  `config`;
- `subject` carries `{profile_id, profile_version, profile_digest, candidate}`.

The caller passes these to `TransactionStore.create`, which compiles them again before taking any
lock. A profile that compiled at resolution therefore still cannot reach a mutation if the core's
rules disagree. The transaction pins the profile id, version and digest through `subject`.
`title` and `notes` live only in the `release` action's parameters. They never enter the profile.

### 4. nix-config's own profile (per D6)

`.agents/project.json` declares `release.profiles.github-release`:

- `target`: `{environment: "github-main", concurrency_keys: ["release/fagenorn/nix-config"]}`.
- `requirements`: `{adapters: {forge: {min_inclusive: "1.0.0", max_exclusive: "2.0.0"}}}`.
- `bindings`:
  - adapter `forge` → `github-forge`;
  - target `repository` = `{kind: github_repository, repository: fagenorn/nix-config, branch: main}`;
  - principal `maintainer` = `{class: forge_write}`;
  - credential `forge-keyring` = `{adapter: forge, class: gh_keyring}`.
- `publication`: two `index` actions, both `irreversible` with `observation_deadline_ms: 600000`:
  - `tag` (operation `tag`);
  - `github-release` (operation `release`, `deps: ["tag"]`).
- `activation`: `"none"`.
- `proof`: `{convergence_window_ms: 1800000, obligations: []}`. The derived
  `published_artifact_identity` floor is added by the core.
- `recovery`: both units `supersedable_only`, with no anchor, compatibility or edges. Tags and
  Releases are never deleted, and recovery is roll-forward (#81).
- `limits`: `{}`.

`capabilities.deploy` stays `unsupported`, and `bindings.deploy` keeps `adapter: none`. The
profile has no `pr_merge`: nix-config is single-branch, so ship-release has no release PR, and #90
gives a single-branch profile no release-merge arm. With this profile all three release-profile
checks pass, and `capabilities.release` becomes `available` once the guard wrapper is on `PATH`
(section 8). Nothing consumes the profile for a live release yet; that is the ship-release
migration (#130).

### 5. `ReleaseProfileInspection` (per D15)

`release profile inspect <profile-id> [--repo-root]` resolves the project once and compiles. It
emits exactly the seven #85 members and performs no provider call and no mutation:

| Member | Content |
|---|---|
| `schema_version` | `1` |
| `subject` | project id and root; source revision (`git rev-parse HEAD` of the checkout); platform identity (manifest path and `platform_version`) |
| `profile` | id, version, digest, target, deadlines, effective `limits`; `admissible` boolean |
| `graphs` | publication and activation DAGs in topological order; core-fixed phase order and receipt handoffs (publication receipt → activation, `none` → `activation_not_applicable`); the proof DAG including derived nodes flagged `derived: true` with class, temporal form, reserved predicate and the unit they root (#91); recovery units with posture, anchor and edges |
| `bindings` | per alias the exact adapter name, contract version and descriptor digest, plus normalized non-secret config; targets, principal and credential handles |
| `conformance` | per alias the support facts for every referenced mode and predicate (reserved handles included), prerequisite executable readiness, the three release-profile check verdicts, and every compile finding |
| `repairs` | one structured route per finding or blocked prerequisite: `{repair_id, pointer, safety_class: user_action}` |

An inadmissible profile still produces a full report, because administrative diagnosis must not
mutate anything (#69). Two cases are typed errors with a JSON error envelope and exit 2:
`release_unsupported`, when the project declares `"unsupported"`, and `profile_unknown`. A
resolver refusal propagates exactly. Ordinary workflows never receive this report (#85).

### 6. The adapter contract module (per D7)

`release_adapter` owns everything shared by adapters:

- **The closed registry.** `REGISTRY = {"github-forge": forge_adapter}`. An unknown name is a
  grammar violation, never a lookup fallback.
- **The `Descriptor` schema**, validated when the registry is built:
  - `{name, adapter_contract_version, operations: {<op>: {mode, support: supported|unsupported, reason, mutability, config_schema_version, config_schema, effects: [effect classes], recovery_capable: bool}}}`;
  - `predicates: {<predicate>: supported|unsupported}`, where both reserved handles must appear and
    a mode able to carry publication must support `publication_visible` (#91);
  - `collector: {max_collection_latency_ms, max_concurrent_collections}` (#93);
  - `target_kinds`, `credential_classes` and `executables` (prerequisites resolved on `PATH`);
  - `host_capacity: "not_required" | "required"`.
- **Closed result shapes.**
  - Effect `Observation`: `{outcome: absent|in_progress|satisfied|diverged|unknown, reason, observed_subject, references, observed_at, facts}`.
  - Predicate `Observation`: `{outcome: satisfied|unsatisfied|unknown, reason, references, observed_at}`.
  - `InvokeResult`: `{result: accepted|rejected|unknown, error_class, reference}`. `error_class`
    is drawn from `transaction_invocation.ERROR_CLASSES`, null exactly when `accepted`. There is
    no `succeeded` value anywhere.
- **`core_binding(adapter, profile)`.** It returns the object the core already accepts:
  - `inspect`/`invoke` project an `Observation`/`InvokeResult` onto the core's closed
    `{outcome, reference}` and `{result, error_class, reference}` shapes. The reference is a
    canonical string built from the typed references.
  - An `observe` method routes a predicate request through the adapter's own `inspect` and projects
    the result onto `{outcome, reason, reference}`.

The binding adds no policy. Retry, ordering and outcome decisions stay in the core (#85), and the
core re-inspects after every `invoke` (#206). Each adapter module's public surface is exactly
`describe()`, `inspect(request)` and `invoke(request)`.

### 7. The GitHub forge adapter (per D8, D9, D11, D17)

`forge_adapter.describe()` is static. It declares:

- `adapter_contract_version` `1.0.0`;
- `target_kinds: [github_repository]`, `credential_classes: [gh_keyring]` and
  `executables: [git, gh, claude-bash-lifecycle-guard]`;
- `host_capacity: not_required`;
- `collector` `{max_collection_latency_ms: 30000, max_concurrent_collections: 1}`;
- the predicates `publication_visible: supported` and `running_subject_identity: unsupported`
  (reason `no_activation_mode`);
- no `recovery_capable` operation.

It has three operations:

| Operation | Mode | Mutability | Invoke | Inspect |
|---|---|---|---|---|
| `pr_merge` | `materialize` | `pointer_cas` | **unsupported**, reason `target_cas_unproven` | supported |
| `tag` | `index` | `create_if_absent` | supported | supported |
| `release` | `index` | `create_if_absent` | supported | supported |

**Inspect.** Every read goes through `gh`/`git` by name, with `GITHUB_TOKEN`/`GH_TOKEN`
scrubbed from the child environment so it authenticates with the keyring credential exactly as
the guard's lookups do.

- **`tag`** reads `gh api repos/<slug>/git/ref/tags/<tag>`:
  - HTTP 404 is `absent`;
  - an object of type `commit` (a lightweight tag) is `diverged`, reason `tag_not_annotated`;
  - an object of type `tag` leads to `gh api repos/<slug>/git/tags/<sha>`. When the peeled
    `object` equals the expected commit the result is `satisfied`; otherwise it is `diverged`,
    reason `tag_target_mismatch`.

  The target is always read from the tag object, never from a Release.
- **`release`** reads `gh api repos/<slug>/releases/tags/<tag>`:
  - 404 is `absent`;
  - a draft, or a `tag_name` mismatch, is `diverged`;
  - otherwise the outcome is the `tag` inspection's outcome for the same tag.

  `target_commitish` is never read.
- **`pr_merge`** reads `gh pr view <n> --repo <slug> --json state,baseRefName,headRefName,headRefOid,mergeCommit,url,statusCheckRollup`,
  `gh api repos/<slug>/git/ref/heads/<base>` and
  `gh api repos/<slug>/branches/<base>/protection`:
  - `OPEN` is `absent`;
  - `MERGED` is `satisfied` only when the merge commit's parents are exactly
    `[expected_base_tip, expected_head]`, and otherwise `diverged`;
  - `CLOSED` is `diverged`.

  `facts` carry the PR state, base, head OID, live base tip and protection
  (`{status: protected|unprotected|inaccessible, required_contexts, enforce_admins}`; 404 means
  unprotected and 403 means inaccessible). That is the demo's readback.
- **Errors.** Any lookup failure, timeout or unparseable payload is `unknown`, with the provider's
  bounded stderr kept as a reason detail.
- **Predicate requests.** `publication_visible` maps the effect inspection of the action named in
  the request:
  - `satisfied` → `satisfied`;
  - `absent` → `unsatisfied` with `ref_absent`;
  - `tag_not_annotated` → `unsatisfied` with `ref_not_immutable`;
  - `tag_target_mismatch` → `unsatisfied` with `subject_mismatch`;
  - `unknown` → `unknown` with `store_unreachable`.

  All of these are #91 reason codes.

**Invoke.** Each invoke issues one predeclared effect, in a fixed order, and stops at the first
refusal:

1. **Shape checks.** The operation must be supported. `pr_merge` returns `rejected`,
   `unsupported_operation`, before any call, implementing #116 D7. Parameters must match the
   closed schema.
2. **Live same-repository proof (#116 D3).** The origin URL, normalized as `adopt_planning`
   normalizes remotes, and `gh api repos/<slug> --jq .full_name` must both equal the target slug.
   A mismatch or redirect is `rejected`, `precondition_failed`.
3. **Candidate containment (`tag` only).** `gh api repos/<slug>/compare/<commit>...<branch>` must
   report `identical` or `ahead`. Otherwise the result is `rejected`, `precondition_failed`.
4. **Local preparation (`tag` only).** If `refs/tags/<tag>` is absent, create it with
   `git tag -a <tag> <commit> -m "release: <tag>"`. If it is present but is not an annotated tag
   peeling to `<commit>`, the result is `rejected`, `precondition_failed`. This local tag is not a
   provider effect. It survives a later refusal, and a retry reuses it.
5. **Render** the exact raw spelling and its argv, and assert `shlex.split(raw) == argv`.
6. **Enforcement (#116 D2).** Run `claude-bash-lifecycle-guard` by name with the payload
   `{"tool_name": "Bash", "tool_input": {"command": raw}, "cwd": <project root>}`. Exit 0 allows.
   Any other exit, a timeout or a missing executable is `rejected`, `authorization_denied`, with
   the guard's bounded stderr as the reference detail. The provider is not called.
7. **The provider mutation.** The argv runs once, with the token variables scrubbed:
   - exit 0 is `accepted`;
   - git's `already exists` or gh's HTTP 422 is `rejected`, `precondition_failed`;
   - a network failure or timeout is `unknown`, `transient_transport`.

The adapter never inspects inside `invoke` and never retries. A `release` invoke writes `notes`
to a mode-0600 file under the system temporary directory and removes it on every exit path.

**The two mutation spellings** are the only ones the adapter issues:

```text
git push origin refs/tags/<vMAJOR.MINOR.PATCH>
gh release create <vMAJOR.MINOR.PATCH> --repo <slug> --verify-tag --title "<title>" --notes-file <absolute-path>
```

`--verify-tag` makes the Release an `index` binding: gh refuses rather than creating a tag at a
branch tip. Git refuses to overwrite an existing remote tag without force, and gh refuses a second
Release for a tag. Both create-if-absent conditions are therefore provider-atomic, which a
`create_if_absent` index needs. `pr_merge` keeps the #116 D5 spellings for future use, but invoke
never renders them in v1.

### 8. Guard changes and the shared spelling fixture (per D10, D12)

`lifecycle_guard.py` stays standard-library-only. It gets four changes:

1. **Delete-branch permanent-head repair (#116 D5, owned here).** The feature arm
   (`--delete-branch`) now refuses when the PR's `headRefName` is the default branch or the
   repository's declared integration base. The existing PR lookup already returns that field.
2. **Tag-push arm.** `git push origin refs/tags/<tag>` is judged before the branch arm:
   - the argv has exactly four tokens;
   - the tag matches `^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`;
   - the owner is authorized;
   - `git cat-file -t refs/tags/<tag>` in the cwd prints `tag`, so the tag exists and is
     annotated.

   Every other `refs/...` push keeps today's refusal.
3. **A guarded `gh release create`.** It joins `GUARDED_LITERALS`, labelled "release creation".
   The exact segment is
   `gh release create <semver-tag> --repo <detected slug> --verify-tag --title "<title>" --notes-file <path>`:
   - flags must appear in exactly that order;
   - the raw text and the tokenized argv must agree;
   - the owner is authorized;
   - `title` passes `free_text_problem(title, False)`;
   - `path` is absolute and free of the unsafe characters and whitespace.

   It is segment-judged like `git push`, so the `unset GITHUB_TOKEN && ` segment form still
   composes.
4. **Branch arm unchanged.** `git push origin <name>` keeps its current behavior, including
   ship-release's existing `git push origin <tag>` form. Separating legacy tag-from-branch
   authority is not reopened here.

To match the third change, ship-release's step 4.5f spelling becomes the guarded `gh release
create` form. Today it uses `--target <default>` with no `--repo`, which the guard would now
refuse. Swapping the two flags is the skill's only edit.

**One spelling source.** `tests/fixtures/forge-adapter-spellings.json` holds one row per adapter
spelling: every inspect read and both mutations, rendered for a canonical parameter set. Each row
is `{id, operation, kind: read|mutation, raw, argv}`.

- The adapter tests assert that the adapter renders exactly these rows.
- `tests/test_claude_permission_guard.py` loads the same rows. Each one becomes an *allowed* row
  of its adversarial table, run against fixture repositories for every repository class below.

A spelling change on either side turns one of the two suites red.

New near-miss rows are refused:

- the tag arm with a lightweight tag, a non-SemVer name, `refs/heads/...`, a `+` force, extra
  tokens or another owner;
- `gh release create` without `--verify-tag`, with reordered flags, `--target`, a wrong `--repo`,
  an unsafe title, a relative notes path or a trailing segment;
- the feature-arm deletion of a `dev → main` PR with passing protection, and of a `main → dev` PR.

**Nix wiring.** `home/common/claude-code/default.nix` adds `lifecycleGuard` to `home.packages`,
so `claude-bash-lifecycle-guard` is on `PATH`. The forge adapter and the resolver's readiness
check find it by name (agent-helpers rule 3). `lib/agent-tools.nix` adds the `release` command row.

### 9. The legacy skills-config bridge (per D13)

The bridge lives in the module `release_bridge` and has two pure functions:

- **`plan_legacy_release(legacy_bytes, contract) -> {release, questions}`.** It reads only the
  legacy file's `deploy` member:
  - A missing member, or exactly `{"adapter": "none"}`, combined with a GitHub tracker, maps to
    the forge-only profile shape of section 4. This ratifies ship-release's formerly implicit tag
    plus Release, as the bridge plan must (#85 step 2). The target is filled from the contract's
    tracker and VCS facts.
  - Any other adapter, `services`, `project` or `env` member yields the stable adoption question
    `release.deploy_adapter_unrepresentable`, because no non-forge adapter exists yet.
  - A `watchDoc` yields `release.watch_doc_to_operations`, routed to `paths.operations`.

  It never invents a value. An unparseable or non-object file yields `release.legacy_unreadable`.
- **`project_legacy_deploy(legacy_bytes, release) -> bytes`.** This is a *member-scoped*
  projection, the JSON analogue of `managed_import`:
  - only the `deploy` member is generated;
  - a forge-only profile with activation `none` renders as *absent*, since ship-release's legacy
    default for a missing `deploy` was `adapter: none`;
  - when the existing member already equals the rendering, the input bytes are returned
    unchanged;
  - otherwise the file is re-serialized with adoption's existing `authored_bytes` formatting;
  - `"unsupported"` returns the input unchanged.

  The projection never creates a legacy file, because no native consumer requires a new one.

The adoption sweep (`adopt_planning.legacy_binding_operations`, #148 D30) is the one writer. After
merging its three path keys it applies `project_legacy_deploy`, so during the bridge the `deploy`
member is generated, not edited. Strict cutover (#130) deletes the file.

**AC5 for nix-config.** nix-config has no legacy file today, so its projection is absent. The test
fixture reproduces the last authored file byte-for-byte (`1722a65d^:.claude/skills.config.json`,
`orchestration` only). `project_legacy_deploy` over that file with nix-config's `github-release`
profile returns identical bytes. That resolves Phase-0 question 1. Using the planner when adopting
another repository belongs to #126.

### 10. Conformance activation (per D14)

`find_release_profile` reads the contract's `release` member, not `bindings.workflow.release`:

- `"unsupported"` gives `not_run` with `subject_absent` and `{"declared": false}`.
- With profiles, each check runs its compiler rule (section 3, rules 1–3) over every profile.
  - A violation gives `failed`, with the check's existing reason code (`observation_deadline_optional`,
    `rolled_back_unreachable` or `restore_anchor_destroyed`) and its existing repair.
  - Otherwise the result is `passed`.
  - Facts carry the profile id and the first finding's pointer.

The reason `profile_unsupported` leaves the registry's closed set, which reverses #122 D27. A
grammar-invalid profile already fails `repository.contract.valid`, and the engine's dependency
machinery suppresses the three checks. No path now reports `not_run` because a compiler is absent.

### 11. Delivery shape (per D16)

The work is built on one branch as two separately reviewable task groups. **A**, compiler and
inspection, lands before **B**, adapter and guard:

- **A**: `release` contract member and resolver, `release_profile`, `release_bridge` and the
  adoption sweep call, conformance activation, the `release` command's `profile inspect`, and
  nix-config's profile.
- **B**: `release_adapter`, `forge_adapter`, `adapter inspect`, the guard arms, the D5 repair, the
  spelling fixture, ship-release's 4.5f, and the Nix `PATH` and command rows.

If `diff-scope` reports the branch over the configured review limit, A and B ship as two PRs in
that order. Docs updates are:

- `python/README.md` gains the profile, compiler, adapter and command contracts;
- `home/common/claude-code/README.md` gains the new guard arms and the D5 repair.

CLAUDE.md is not touched.

## Acceptance mapping

| # | Criterion | Deterministic verification |
|---|---|---|
| 1 | Compiler accepts a valid nine-group profile, rejects derived class / missing deadline / unreachable `rolled_back` before mutation | `compile_profile` accepts nix-config's profile and a fixture-adapter restorable profile. It rejects `semantic: published_artifact_identity` (`proof.derived_class_named`), a missing deadline (`observation_deadline_optional`) and a restorable unit beside a `supersedable_only` immutable action (`rolled_back_unreachable`). The same three, bound and passed to `TransactionStore.create`, raise before any lock and leave the store root empty. |
| 2 | No profile → `release: unsupported`; omitted group → `invalid_contract` | Resolver CLI: `"release": "unsupported"` resolves with `capabilities.release.state == "unsupported"`. A contract without `release` refuses `invalid_contract` at `/release`, and leftover `capabilities.release` or `bindings.workflow.release` refuse `member_unexpected`. |
| 3 | Adapter has exactly the three operations; `invoke` never `succeeded`; tag target read from the tag | The module's public callables are exactly `describe`, `inspect` and `invoke`. Every invoke fixture returns one of the three results. The tag/release inspect fixture has `target_commitish: "main"` while the tag object peels to commit C ≠ the main tip, and inspect reports C. A lightweight tag is `diverged`. |
| 4 | Every adapter spelling is an allowed guard row; guard passes | The shared spelling fixture drives allowed rows in `tests/test_claude_permission_guard.py`. The adapter suite asserts its renderer equals the fixture. The full guard table, near-miss and D5 rows included, is green. |
| 5 | Legacy config is a generated projection, byte-identical for nix-config | `project_legacy_deploy` over the `1722a65d^` bytes with nix-config's profile returns identical bytes. With no file, nothing is generated. Planner fixtures cover forge-representable input and a Railway input (question). The adoption sweep fixture regenerates the `deploy` member. |
| 6 | Three conformance checks activated | Conformance runs give `passed` ×3 on nix-config's contract, `failed` with each reason on violating fixtures, and `not_run`/`subject_absent` on `"unsupported"`. The registry no longer contains `profile_unsupported`. |
| 7 | One exact inspect/invoke spelling per action, fixtures per repository class and failure mode | The fake `gh`/`git`/guard provider world covers default-only, distinct-integration, protection-inaccessible (403) and other-owner classes. Failure modes covered: absent, diverged (lightweight, mismatch, draft), unknown (timeout, non-zero, invalid JSON), guard denial, provider 422/`already exists`, origin or redirect mismatch, an uncontained commit, and `pr_merge` invoke refused with no provider call recorded. |
| 8 | Outcomes observed after invocation | Through the real `TransactionStore.invoke_action` and `core_binding`, an `accepted` invoke whose world never applies the effect records `action_inspected` `absent`, never `satisfied`. The fake provider's call log shows that the forge invoke never reads the target ref or Release: the precondition reads in steps 2–3 only. |
| 9 | Host capacity consumed as a capability, not in the adapter | The forge descriptor declares `host_capacity: not_required`. A static test asserts `forge_adapter` imports no `host_admission` or `launch_*` module. |
| Demo | Compile nix-config's profile; live `inspect` on a real open PR | Ship-time acceptance evidence, read-only: `release profile inspect github-release` on nix-config, and `release adapter inspect github-forge pr_merge --parameters '{...}'` against a live open PR. Its PR state and protection facts are recorded in the delivery evidence. |

## Test seams

- **Resolver CLI** (`python -m agent_tools.resolve_project resolve`): authored `release`
  shapes, grammar violations and the derived `capabilities.release`. Prior art is the existing
  `test_resolve_project` fixtures, which gain the required member.
- **`release_profile.compile_profile` / `bind_candidate`** with an injected descriptor registry,
  and **`python -m agent_tools.release`** for inspection. Fixture adapters are descriptor data
  only; no mock asserts calls.
- **The real `TransactionStore`** (`create`, `invoke_action`) with `core_binding(forge_adapter)`
  in a controlled provider world. Prior art is the #206/#207 core tests.
- **The forge adapter's three operations against fake `gh`, `git` and
  `claude-bash-lifecycle-guard` executables on `PATH`.** The fakes log argv and answer by
  scenario variables, as `FAKE_GH_SCRIPT` does in the guard suite. Assertions are on the returned
  observations and on whether a mutation argv was executed.
- **The guard's public CLI seam** (`tests/test_claude_permission_guard.py`, run against the built
  settings artifact), with the shared spelling fixture.
- **The conformance engine run** (existing `test_conformance*` suites) and **the adoption planner**
  (`test_adopt_project`) for the sweep.

No new seam below these is introduced.

## Out of scope

- A release driver or any live release. ship-release's migration onto the core and strict
  cutover, which deletes the legacy projection and `bindings.deploy`, belong to #130.
- Attempt-lifecycle migration (#125). Adopting Nodo, Argus or Arcwave, and running the bridge
  planner for them (#126/#129).
- Compiling the guard's owner and integration tables from fleet membership and adopted contracts
  (#116 D3/D4). That waits on adoption, and those tables stay Nix literals.
- Any non-forge adapter: Nix `local_apply`, Railway, OCI. Activation units, spend grants,
  evidence stores and limit members are therefore all unusable in v1.
- An atomic target-tip CAS merge, and hence any `pr_merge` invoke. The #116 D8 race and denial
  matrix for merge belongs to the work that lifts D7.
- Repairing the native guard's integration-arm protection exemption (#116 D6 native rows),
  ship-release's legacy `git push origin <tag>` branch-arm form, branch-protection or billing
  changes, credentials, host-capacity scheduling (#150, rejection KB), a fourth adapter operation,
  and any `ResolvedProject` member beyond the derived capability.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Required top-level `release` = `"unsupported"` or `{profiles}` replaces authored `capabilities.release` and `bindings.workflow.release`; schema 1 with no bump; `capabilities.release` becomes derived; profiles force `capabilities.deploy` unsupported | #85 explicit support and one authority; issue AC2; #147 D4/D8 precedent (`platform` added to schema 1, fail loud); nix-config is the only adopted contract | Keeping both flags plus an agreement rule (two authorities for one fact); schema 2 with a migration executor nobody runs |
| D2 | Two tiers. Grammar, references and adapter support give `invalid_contract` at resolve. Admissibility (core compilers, #86 lints, #91, #93) gives ordered findings, `capabilities.release` `blocked`/`release_profile_inadmissible`, and a refusal at `create`. Proof and recovery vocabularies live only in the core compilers | #85 (unsupported reference = `invalid_contract`; unsupported collector = inadmissible); #91 and #93 compile-time rejection; bar DRY | Everything `invalid_contract` (a profile flaw breaks every workflow and makes the three checks unobservable); everything `blocked` (contradicts #85) |
| D3 | Mechanical #86 rules. `rolled_back` is claimed by any `restorable` unit, and then every `create_if_absent` action must be `compensatable`. An anchor target written by an `in_place` action is destroyed. `observation_deadline_ms` is grammar-optional and compile-mandatory, with no default; `convergence_window_ms` must be authored. Reason codes are reused from the conformance registry | #86 frictions 1–3; #84 finite deadlines; bootstrap "no policy is defaulted"; #208 posture table | A grammar-required deadline (the lint could never fire); a new `retain` no-op operation to define residue-only edges (a new adapter semantic, #85) |
| D4 | v1 sub-schemas admit only what the forge adapter and the core consume. `limits` must be `{}`; `bindings` holds adapters, targets, principals and credentials (no `stores`); `reversible_bounded_spend` is refused | Bar YAGNI and "no half-wired path"; the core has no per-transaction limit seam or store consumer | Declaring limit and store members that nothing enforces (a false declaration) |
| D5 | Compile is candidate-independent and deep-frozen with a digest; `bind_candidate` lowers into the exact `create` inputs, the core recompiles, and `subject` pins profile id, version and digest | #85 immutable `ResolvedReleaseProfile` plus transaction pinning; #123 `create(proof, recovery)` | A parallel plan structure, or compiling only at `create` (no resolve-time readiness or inspection) |
| D6 | nix-config declares `github-release`: tag then Release `index`, `irreversible`, activation `none`, both units `supersedable_only`, no merge | ship-release single-branch path; #90 (no release-merge arm for single-branch); #81 never delete tags; Phase-0 Q2 | Including `pr_merge` (unsupported per D8, and no release PR exists); a `local_apply` activation (non-forge, out of scope) |
| D7 | `release_adapter` holds a closed registry, the descriptor schema, rich typed observations and a `core_binding` that projects onto the core's closed shapes and routes `observe` through `inspect`; adapters expose exactly three public operations | #85 deep module and envelopes; #123 effect and observer duck types; bar "fail loud" | Changing the core's result shapes (reopens #206); a fourth adapter method for predicates |
| D8 | `pr_merge` is `materialize`/`pointer_cas`. Inspect is supported, reading PR state, live base tip and protection facts. Invoke is `unsupported`/`target_cas_unproven`: a profile referencing it is `invalid_contract` and invoke refuses before any provider call | #116 D7 (no proven atomic target-tip mechanism) and D6 (floor needed before admission); #85 unsupported semantics; Phase-0 Q3 | `blocked`, implying an implementation only awaits certification; a head-OID precheck presented as CAS |
| D9 | Shared enforcement: before each mutation the adapter runs the real guard CLI (`claude-bash-lifecycle-guard`, now on `PATH`) with a synthesized PreToolUse payload, failing closed; the guard file is untouched as a module | #116 D1/D2 (one implementation, both entry paths, guard terminal); agent-helpers rule 3 and the guard's stdlib-only, no-`agent_tools` rule; Phase-0 Q4 | Extracting a shared module (the guard cannot import `agent_tools`; a copy is a second grammar); the adapter re-implementing grammar |
| D10 | Guard gains a `refs/tags/<semver>` annotated-tag push arm and a guarded `gh release create … --verify-tag` arm, plus the D5 delete-branch permanent-head refusal; ship-release 4.5f is aligned; the legacy branch-arm tag push is left alone | #116 D5 (tag and Release need their own enforcement route; #124 owns the delete-arm repair); #81 index binds existing bytes | Leaving `gh release create` unguarded (no grammar validates it); `gh api POST` tag creation (a new unguarded mutation surface); repairing the legacy branch arm too (widens into ship-release) |
| D11 | The tag target is read from the tag object; lightweight is `diverged`; a Release is `satisfied` only when its tag is; `target_commitish` is never read. The tag invoke first proves the live origin and canonical repository identity and that the commit is contained in the default branch | Issue AC3 and the ship-release double-tag lesson; #116 D3 same-repository proof; #81 no-clobber | Trusting a Release's commitish or a local tag listing; tagging a commit not on the protected branch |
| D12 | One fixture file of adapter spellings is consumed by both the adapter suite and the guard's adversarial table | Issue: the table gains a row per adapter spelling "so the two can never silently disagree" | Duplicated literals in two suites (drift stays green) |
| D13 | The bridge is a pure planner (forge-representable `deploy` becomes a profile; anything else becomes an adoption question) plus a member-scoped `deploy` projection written by the adoption sweep. nix-config's AC5 is proven against its last legacy file bytes and by absence today; running the planner for other repositories is #126 | #85 bridge steps 1–6; #148 D30 sweep is the one legacy writer; Phase-0 Q1; commit 1722a65d | A whole-file projection (clobbers D30-managed keys and unrelated legacy members); asserting identity against a file that no longer exists |
| D14 | The three conformance checks judge the compiler rules; `profile_unsupported` is retired (reverses #122 D27); `subject_absent` only for `"unsupported"` | Staged-delivery AC (no `not_run` for lack of a compiler); #122 registry reason codes | Checks that read only invalid-contract outcomes (always vacuous) |
| D15 | One read-only `release` command with `profile inspect` (seven members) and `adapter inspect` (demo); there is no invoke CLI, so invoke is reachable only through the core | #85 administrative inspection seam and "workflows never call adapters"; bar token economy | A public invoke surface (bypasses grants and fences); a separate demo script outside the command table |
| D16 | Two reviewable task groups (A compiler and inspection, B adapter and guard) on one branch, split into two PRs only when `diff-scope` exceeds the limit; the live demo is ship-time evidence; unit tests use fixtures | Staged-delivery contract; Phase-0 Q5/Q6 | Two branches up front (cross-dependency churn); live provider calls in unit tests |
| D17 | Adapter `gh` calls scrub `GITHUB_TOKEN`/`GH_TOKEN` (keyring credential, as the guard's lookups do); implementation identity = descriptor digest plus platform manifest identity | #84 just-in-time credentials never persisted; guard README credential rationale; agent-helpers rule 3 (no `__file__` reads) | The harness's narrower fine-grained token; hashing module source through `__file__` |
