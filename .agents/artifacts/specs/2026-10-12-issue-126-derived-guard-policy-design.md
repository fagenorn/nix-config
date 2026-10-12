# Derived lifecycle-guard policy for registered projects — issue 126

Design for https://github.com/fagenorn/nix-config/issues/126, as narrowed on
2026-09-27 to the nix-config-side guard cutover and settled by the owner's
2026-10-11 decisions. "Issue 116 Dn" cites the ledger of
`.agents/artifacts/specs/2026-09-20-issue-116-permission-guard-core-design.md`;
a bare "Dn" cites this spec's ledger.

## Triage

Input: `contract_change` hit (the guard policy's source changes from Nix literals to a compiled projection); `concurrency_or_persistence` hit (an activation step persists the projection the guard reads); `open_design_questions` doubt (the five questions are answered, but the projection location and contract-read mechanics are left to the spec); `criteria_shape` hit (the proof is a real Nodo PR and merge that no deterministic check verifies); paths `home/common/claude-code/lifecycle_guard.py`, `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `tests/test_claude_permission_guard.py`, `python/agent_tools/guard_policy.py`, `tests/test_guard_policy.py`, `CLAUDE.md`. Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}`. `ran: full (shadow)`.

## Problem

The lifecycle guard decides which repositories carry standing authorization
for push, PR creation, merge and release from two hand-written Nix tables: an
owner roster (`fagenorn`, `elevenyellow`) and an integration-branch table
(`elevenyellow/nodocom` and `fagenorn/arcwave`, both `dev`). Nodo is now a
registered project whose contract on `origin/dev` declares the same facts and
a release profile with an explicit forge target, so its two rows are a second,
independently editable copy of facts the project already owns. The owner row
is also wider than the fact: `elevenyellow` authorizes every repository under
that owner, while only `elevenyellow/nodocom` is adopted. Issue 116 D3 requires
the guard's facts for an adopted project to be compiled from registry
membership, the release-profile forge target and the tracker/VCS facts, with a
same-repository proof, and issue 116 D4 requires the cutover to leave no
parallel table.

## Solution

A new `agent_tools` command, `guard-policy`, compiles one **guard policy** file
from two inputs: the **base policy** Nix builds (the literal rows for
repositories that are not registered, plus the tool paths) and the fleet
registry. For every registered project it pins the contract on the registered
branch of `origin`, proves that the registry entry, the checkout's `origin`,
the tracker slug, the release-profile forge target and the provider all name
one repository, and writes one derived row keyed by that exact repository. A
home-manager activation step runs the compiler on each switch. The guard reads
that one file, authorizes a repository when its owner is in the literal roster
or the repository itself has a derived row, and takes a derived repository's
integration branch from its row. Nodo's two literal rows are deleted in the
same change. A project the compiler cannot prove has no row, and a compile that
cannot run leaves no file, which blocks the guard.

## Requirements

- **R1.** After a switch on a host whose registry lists Nodo, the guard allows
  the guarded verbs in `elevenyellow/nodocom` exactly as today (feature PRs
  into `dev`, the `dev` → `main` release arm, default-branch rules unchanged),
  from a policy file holding no hand-authored Nodo fact.
- **R2.** Another repository under `elevenyellow` is outside standing
  authorization. `fagenorn` repositories and `fagenorn/arcwave`'s `dev` row
  behave as today.
- **R3.** The Nix source declares neither `elevenyellow` nor
  `elevenyellow/nodocom`, and a test pins the built base policy's literal rows.
- **R4.** A registered project whose proof fails at any step has no derived
  row in the written file, whatever the previous file held.
- **R5.** When the compile refuses as a whole, no policy file exists afterwards
  and the guard blocks every Bash call with its existing `invalid policy`
  refusal.
- **R6.** The guard refuses a policy in which a derived repository also has a
  literal integration row, and refuses guarded verbs in a derived repository
  whose live default branch differs from the row's.
- **R7.** `just build` still fails when the guard source or the base policy
  cannot load, and the adversarial table stays green.

## Decisions

### 1. One policy schema, two producers

The guard policy is one JSON object with a closed key set: the five existing
members (`authorized_owners`, `integration_bases`, `git_bin`, `gh_bin`,
`jq_bin`) plus `derived_repositories` and `derivation`.

- `derived_repositories` maps an exact `owner/name` slug to a closed row
  `{default_branch, integration_branch, evidence}`. The two branches are
  non-empty ref names; they are equal for a project with no distinct
  integration branch. `evidence` is an object the guard does not interpret.
- `derivation` is `null` in a base policy and an object in a compiled one.

Nix writes the base policy to the store with `derived_repositories` `{}` and
`derivation` `null`. It is a valid guard policy by itself, which is what the
wrapper's build-time check and the guard tests load. The compiler copies the
base's five members unchanged and fills the other two. There is no second file
for the guard to read and no merge at guard run time (D1).

`evidence` binds what the row was derived from: the registry `project_id`, the
digest of its registry entry, the source `{ref, commit}`, the git blob id of
the contract at that commit, the provider's canonical repository name, and one
`{id, version, digest}` per release profile whose target selected the
repository. The row holds only the facts issue 116 D3 names for the projection;
no resolver snapshot and no contract body is persisted (D11). `derivation` binds `schema_version` 1, the `agent_tools` version and
the digest of the registry document (`null` for an absent registry). Digests
come from `agent_tools.canonical.telemetry_digest`. The file holds no grant,
credential or contract body (issue 116 D3).

### 2. The compiler's proof, per registered project

`guard-policy compile --base <path> --output <path>` reads the registry through
`agent_platform.read_registry` and treats each entry independently. A row is
written only when every step holds; the first failing step refuses the project
with one reason code from a closed set.

| Step | Proof | Reason code on failure |
|---|---|---|
| 1 | The entry's `root` is a git checkout. | `root_unavailable` |
| 2 | `origin`'s effective fetch URL and its single push URL are GitHub URLs that normalise to one slug `S` (the forge adapter's slug rule, shared, not restated). | `origin_unproven` |
| 3 | The contract branch `B` is selected by the rule registration uses: the entry's `branch_override.branch` when present, otherwise the remote's `HEAD` branch followed at most once to the contract's `integration_branch`. `B` is fetched with the pinned-fetch spelling `fetch_pinned` owns and pinned to commit `C`. | `branch_unresolved`, `fetch_failed` |
| 4 | An export of `C` resolves through `resolve_project.resolve` (contract valid, the release grammar's same-repository rule included, platform range, projections in sync). | `contract_unresolved` |
| 5 | The contract's `project.id` equals the entry's `project_id`. | `identity_mismatch` |
| 6 | `bindings.tracker.kind` is `github` and `bindings.tracker.repo_slug` equals `S` exactly, with no case folding. | `tracker_mismatch` |
| 7 | `release.targets` holds at least one `github_repository` target. `release: "unsupported"` or a profile set with none refuses; the tracker slug never stands in. | `no_forge_target` |
| 8 | Every such target names repository `S` and the contract's `default_branch`, and each of their profiles compiles through `release_profile.compile_profile` to a digest. | `target_mismatch`, `profile_inadmissible` |
| 9 | The contract's `integration_branch` equals `B`, and its `default_branch` equals the remote's `HEAD` branch read in step 3. | `branch_mismatch` |
| 10 | `gh api repos/S` reports the canonical full name `S`, with the gh token variables scrubbed as the guard scrubs them. | `provider_unproven` |
| 11 | No other registered project derived `S`. Both refuse. | `duplicate_repository` |
| 12 | `S` is not a key of the base `integration_bases`. | `literal_conflict` |

The row's `default_branch` and `integration_branch` are the contract's. The
local working tree, index and local branches of `root` are never read; the only
write to `root` is the remote-tracking ref and the fetched objects (issue 341
D4, D11, D12). Every network child runs with prompts off and a 30-second bound.

Every contract fact is read through the resolver module's own functions; the
compiler has no contract parser of its own. A derived row authorizes the
repository, not the registered root: any checkout whose `origin` is `S` is
judged by it, as the literal rows are today.

The compiler derives every registered project, not Nodo by name. nix-config's
own row is derived too and is redundant with the `fagenorn` owner literal,
which the owner kept for unregistered repositories (D3).

### 3. Compile outcomes

| Outcome | Exit | Output file | When |
|---|---|---|---|
| complete | 0 | written atomically | every registered project has a row (an absent registry is the empty fleet) |
| written with refusals | 1 | written atomically, refused projects absent | at least one project refused in section 2 |
| refused | 2 | does not exist afterwards | the base policy is unreadable or not a valid base policy; the registry exists but does not validate; the output cannot be written; any unexpected failure |

Stdout is one JSON report: `schema_version`, `outcome`, the derived slugs, and
for each refused project its `project_id`, `root`, `reason_code` and a bounded
`detail`. A whole refusal reports its cause the same way. Stderr carries one
line per refusal. The file is replaced with `agent_platform.write_atomically`,
so a reader sees the old policy or the new one, never a partial one, and a
previous file never survives a refused compile (D4).

A `literal_conflict` (step 12) is the dual table issue 116 D4 forbids. Neither
table wins: the project gets no derived row and the conflicting literal
integration row is left out of the written file, so the repository falls back
to the default-branch-only rule until the source is fixed (D5).

### 4. Activation and the installed commands

The claude-code module gains:

- the base policy in the store, replacing today's store policy;
- `claude-guard-policy`, an argument-free installed command that runs the
  `guard-policy` launcher with `compile`, the store base policy and the output
  path `<home>/.agents/state/guard/policy.json`, with `git`, `gh` and `ssh` from
  the store first on `PATH`;
- an activation step, ordered after `writeBoundary` and before the settings
  copy, that runs that command, prints its stderr, removes the output file on
  exit 2 or any other non-zero status but 1, and never aborts the activation;
- the registered hook wrapper naming that output path as its `--policy`. The
  path is built from the configured home directory at evaluation time, so the
  hook reads no environment variable to find it.

The wrapper's build-time check keeps running the guard against a harmless
payload, now with a trailing `--policy <base policy>`, so R7 holds in the
sandbox where no compiled file exists.

The compiler fetches at activation (D2). A switch without network or without
usable credentials therefore writes a file with no row for the affected
project, and its verbs are refused until `claude-guard-policy` is run from an
authenticated shell or the next switch succeeds. That command is the repair
route the activation warning names; rerunning it can only re-derive from the
registry and `origin`, so it grants nothing an agent could not already obtain.

Registry and contract changes take effect at the next compile. The guard does
not re-read the registry or the contract per invocation (D6).

### 5. The guard

- `load_policy` accepts exactly the seven-member schema of section 1, validates
  each derived slug against the guard's slug pattern and each branch against
  its ref-name pattern, requires `evidence` to be an object and `derivation` to
  be `null` or an object, and refuses a policy in which a derived slug is also
  an `integration_bases` key (R6).
- **Ownership.** A repository is inside standing authorization when its owner
  is in `authorized_owners` or the repository is a key of
  `derived_repositories`. A derived row never authorizes its owner's other
  repositories.
- **Default branch.** For a derived repository, the branch `origin/HEAD` names
  must equal the row's `default_branch`; otherwise every repository-bound verb
  is refused with a reason naming both.
- **Integration branch.** For a derived repository whose two branches differ,
  the row's `integration_branch` is the integration base everywhere the guard
  reads one today (PR target, feature-merge base, release arm, permanent-head
  check). A literal `integration_bases` row serves the others.

Nothing else changes: grammar, the protection demand and its integration-branch
waiver, the release arm's rollup check, branch deletion, detaching words and
the raise label are untouched, and the gaps issue 116 D6 records stay recorded.
The guard remains one standard-library file that imports nothing from
`agent_tools` and reads one policy file.

### 6. The literals

`authorizedOwners` becomes `[ "fagenorn" ]` and `integrationBases` keeps only
`"fagenorn/arcwave" = "dev"`. Their comments say that registered projects are
derived and that a row here is only for a repository that is not registered.
This lands in the same commit as sections 4 and 5, so no revision has both a
Nodo literal and a guard that reads derived rows, and none has neither.

### 7. Prose

The guard section of `home/common/claude-code/README.md` describes the two
producers, the compile outcomes and the repair command, and names the compiled
policy as the authoritative roster instead of restating Nodo's rows. Its
terms are fixed here: the **base policy** (Nix-built), the **compiled policy**
(the file the hook reads) and a **derived row**.
`python/README.md` gains the `guard-policy` command contract. `CLAUDE.md`
changes only where a sentence becomes false, within the instruction budget and
without the raise label.

## Test seams

- **Compiler command** (`python -m agent_tools.guard_policy compile`, a new
  suite added to `just agent-workflow-tests`). Fixture: a temporary `HOME`
  holding a registry, checkouts whose `origin` is a local bare repository
  published by a helper like the registration suite's `publish`, and `PATH`
  shims in the style of `tests/forge_world.py` that answer the two
  `git remote get-url` reads and the `gh api` read and pass every other `git`
  call to the real one. Cases: a Nodo-shaped project (override to `dev`,
  publication-free profile) and a single-branch project both derive; one case
  per reason code of section 2; each whole refusal of section 3 leaves no
  output file, including over a pre-existing one; a refused project's stale row
  is gone from the rewritten file; an absent registry yields the base rows and
  an empty derived map. Assertions are on the written file, the report and the
  exit status.
- **Guard command** (the existing built-wrapper seam of
  `tests/test_claude_permission_guard.py`, with a fixture policy passed as a
  trailing `--policy`). The Nodo cases move from the built literals to a
  derived-row fixture and keep their expectations. New adversarial rows: a
  sibling repository of a derived repository's owner is refused; a derived
  repository whose `origin/HEAD` branch differs from its row is refused; a
  policy with a missing or extra member, a malformed row or a derived/literal
  overlap blocks every call; a missing policy file blocks every call. One test
  pins the built base policy (R3).
- **Round trip.** One test feeds a file written by the compiler seam to the
  guard seam and asserts one allowed and one refused verb, so the two sides
  cannot drift on the schema.
- **Build.** `just build` runs the wrapper check against the base policy.

No test contacts GitHub or a network remote, and none reads the host registry.
The forge adapter runs the installed guard by name, so it reads the compiled
policy with no change of its own; suites that only carry Nodo's slug as fixture
data are untouched unless they execute the built guard, in which case they pass
a fixture policy the same way.

## Acceptance and hold

The pull request refers to the issue without closing it. Per the owner's
decision 5 the issue is held as `needs-verification` after merge: the
orchestrating session runs one `just switch` and one Nodo PR into `dev` with
its merge through the derived guard. If activation cannot fetch or reach the
provider under the switch's environment, the proof reports that outcome and
whether `claude-guard-policy` repaired it.

## Out of scope

- `fagenorn/arcwave`'s row, the `fagenorn` owner literal and Arcwave's
  adoption; https://github.com/fagenorn/nix-config/issues/129.
- Any write to `elevenyellow/nodocom` or its checkout beyond the fetched
  remote-tracking ref; the host `just switch`; the Nodo PR proof.
- Per-invocation rechecking of the registry, contract or provider by the guard,
  and any release-core grant, fence or shared-enforcement extraction (issue 116
  D1, D2, D8).
- Closing the protection gaps issue 116 D6 records for integration branches.
- Re-running adoption conformance (`adopt-project verify`) inside the compiler;
  the resolver run of section 2 step 4 is the conformance it revalidates.
- A registry schema change, an unregister command, a non-GitHub forge.
- Adding the guard suite to a `just` recipe or to CI.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | One guard-policy schema with two producers: Nix writes a base policy that is itself valid (empty derived map), the compiler copies it and adds derived rows, and the hook's `--policy` names the compiled file under `~/.agents/state/guard/`. | Owner decision 3 (the guard reads one file). `agent_platform.state_root` is the one user-scope state directory. The build check and tests need a loadable policy without a registry. | A second projection file the guard merges at run time: two files, and a file-presence fallback issue 116 D4 forbids. A compiled file in the store: the registry is machine-local state Nix cannot read. |
| D2 | The compiler fetches the contract branch at each compile with the pinned-fetch spelling and never falls back to the ref already present; a failed fetch refuses that project. `claude-guard-policy` is the same compile outside activation. | Owner decision 4 and issue 341 D4, D11 (pin after an explicit fetch). The bar's fail-closed and "say something useful". | Reading the existing remote-tracking ref: no network at switch, but an unbounded-stale source that any local ref write moves. Fetch with a fallback to the stale ref: the stale row the brief rules out. |
| D3 | Derived rows are keyed by exact repository and authorize only that repository; removing the `elevenyellow` owner narrows authorization to `elevenyellow/nodocom`. Every registered project is derived, so nix-config gets a row beside the `fagenorn` literal. | Issue 116 D3 ("admitting one repository never admits its owner's other repositories"). Owner decision 2 keeps `fagenorn` and Arcwave's row. The bar: no special case. | Deriving an owner entry from the slug: re-widens to the owner. Deriving Nodo only: a named special case. |
| D4 | Per-project failures omit the project and still write the file (exit 1); installation and authoring defects refuse the whole compile and leave no file, which blocks every Bash call (exit 2). The activation step never aborts the switch. | The guard README: an unreadable policy blocks every call. `read_registry` treats a corrupt registry as an installation defect. The bar's truthful terminal states. | Blocking everything when one project is unreachable: an offline switch would disable Bash. Keeping the previous file on failure: a stale row. Writing literals only when the registry is corrupt: hides the defect and drops every derived project silently. |
| D5 | A repository cannot be both derived and a literal integration row: the compiler refuses that project and withholds both rows, and the guard refuses a file that carries both. Owner-literal overlap is allowed. A test pins the built literals. | Issue 116 D4 (no independently editable old and new tables). Owner decision 2 (the `fagenorn` owner stays). Defense in depth. | Derived-wins or literal-wins precedence: a silent rule that hides the duplicate. A whole-compile refusal: registering Arcwave before its literal is removed would block every Bash call on the host. |
| D6 | The guard does not recheck the registry, contract or provider per invocation. The projection's bound inputs are recorded as evidence and re-proven at every compile. Narrows issue 116 D3's "fresh invocation rechecks" for the native guard. | Owner decision 3: one file, compiled at activation, registry changes effective at the next switch. Issue 116 D9 leaves per-invocation authority to the core work. | A registry or contract recheck in the guard: a second and third input at run time, which the owner decided against, and a git child on every guarded verb. |
| D7 | The provider's canonical repository name is checked at compile time with `gh api`, beside the exact slug and `origin` checks. | Issue 116 D3 (canonical provider identity; redirects do not rebind). The forge adapter's same-repository precondition is the precedent. | Slug and `origin` only: a renamed or redirected repository would keep its row. |
| D8 | The guard checks a derived repository's live `origin/HEAD` branch against the row's `default_branch`. | Issue 116 D8 (default/integration disagreement refuses). It costs no new read: the guard already resolves that branch. | Trusting the row alone: the guard would judge bases against one default while the row declares another. |
| D9 | Branch selection, the pinned fetch, the GitHub slug rule and canonical digests are reused from their existing homes, made importable where they are private; the compiler imports the resolver directly. | The bar's DRY (one home per policy). Issue 148 D26 restricts only the adopt modules from importing the resolver. agent-helpers rules 3 and 4. | A second copy of the branch rule or the fetch flags in the compiler: two spellings that must change together. |
| D10 | Test seams are the compiler command, the built guard wrapper and one round trip; `origin` is a local bare repository behind `PATH` shims for the identity reads. | agent-helpers rule 5. Issue 341 D9 and `tests/forge_world.py`. The bar's tests that can fail. | Mocked git or resolver functions: asserts calls. A network remote: non-hermetic. |
| D11 | The compiled policy persists only the three derived facts and identity evidence (git blob id, profile digests), and reads the contract only through the resolver module. | `bootstrap.md` (never read the contract directly, never persist a snapshot). Issue 116 D3 sanctions a derived policy cache of exactly these facts. Issue 148 D26 (the resolver is the only reader of contract policy). | Embedding the resolved snapshot or contract in the file: a persisted snapshot. A digest of the file bytes read by the compiler: a second contract reader. |
| D12 | No glossary or ADR is written by the grill: the three terms are fixed in the guard README instead, and this ledger is the decision record. | `bindings.paths.context` is `[]` (capability unsupported), so the grill has no write route. The issue 116 spec is the precedent for a spec as decision record. | Creating a context map or `adr/` directory: an unauthorized new knowledge surface. |
| D13 | Refines D9 (plan). The slug rule moves to a new module, `agent_tools.github_remote`, which the forge adapter imports. Branch selection is `adopt_verify.remote_source` itself, called with the registry entry's override branch as its operand and an in-process resolver callback; its source gains `remote_default`. The network git children take a caller bound whose default stays 300 s, and the compiler passes 30 s. So the default branch is fetched too, a branch that registration would refuse is `branch_unresolved`, and any other adoption refusal inside the read is `fetch_failed`. | D9. `PublicSurfaceTest` in `tests/test_forge_adapter.py` pins the adapter to three public functions. Section 2 step 3 ("the rule registration uses") and its 30-second bound. | Making `_github_slug` public in the adapter: breaks that pin. Recomposing the hop from `remote_heads` and `fetch_pinned` in the compiler: the second copy D9 rejects. A 30 s bound for every caller: changes registration. |
| D14 | Compiler details section 3 left open (plan). A whole refusal carries a `cause` member with one code of `base_invalid`, `registry_invalid`, `platform_unavailable`, `output_unwritable`, `internal`; `cause` is `null` otherwise. `derivation` records the installed platform manifest's `platform_version` as the agent-tools version, so a manifest that cannot load refuses the whole compile. A literal integration row is withheld whenever a project that passed steps 1 to 10 derived its slug, a duplicated slug included. | Sections 1 and 3. The package has no runtime version and tests run it from source (agent-helpers rule 5); the resolver already requires the manifest. D5 and the bar's fail-closed. | `importlib.metadata`: absent from source. Withholding the literal only under `literal_conflict`: a slug two projects derive would keep its literal row. |
| D15 | Extends D10 (plan). `target_mismatch` is pinned at the imported function `guard_policy.target_profiles` on a hand-built snapshot. One fixture module, `tests/guard_policy_world.py`, serves the compiler suite and the guard suite's round trip. The guard suite passes a fixture policy on every invocation and finds the built base policy through `CLAUDE_GUARD_BASE_POLICY_PATH`, beside `CLAUDE_SETTINGS_PATH`. | The release grammar's same-repository rule refuses a foreign target before the compiler runs, so no command input reaches that step; issue 368 D14 is the precedent. The registered wrapper names the host's compiled policy, which no test may read. | Leaving the step untested or deleting it: an unpinned or missing defense (D5). Reading the base path out of the wrapper: the wrapper no longer names it. |
| D16 | Guard and activation details (plan). For a derived repository an unresolvable `origin/HEAD` is refused by the same row check as a differing one. The effective integration base is computed once per invocation, so no validator's logic changes. The activation step also runs after `linkGeneration`. | D8 and fail-closed. Section 5 ("nothing else changes"). The platform manifest the compiler needs is a `home.file` link, created by `linkGeneration`. | Ordering after `writeBoundary` alone: a first switch would compile before the manifest exists and block every Bash call. |
