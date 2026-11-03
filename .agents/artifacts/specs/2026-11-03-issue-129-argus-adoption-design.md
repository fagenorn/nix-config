# Adopt Argus onto the project system — issue 129

Design for https://github.com/fagenorn/nix-config/issues/129, written autonomously (`from-issue --auto`)
after the 2026-11-02 Phase-0 note of launch 4. Every call made without the owner is a row of the
Decision ledger; "Dn" cites that ledger, "552 D8" cites the ledger of
`.agents/artifacts/specs/2026-11-02-issue-552-guard-merge-floor-design.md`, "547 D9" that of
`.agents/artifacts/specs/2026-11-02-issue-547-host-local-release-units-design.md` and "126 §4" a
section of `.agents/artifacts/specs/2026-10-12-issue-126-derived-guard-policy-design.md`.

## Triage

Input: `contract_change` hit (Argus gains a contract whose merge checks and release profiles feed the derived guard policy); `concurrency_or_persistence` hit (registration writes the fleet registry and recompiles the guard policy); `open_design_questions` hit (bootstrap merge order and floor check names); `criteria_shape` hit (nine criteria, several verifiable only from live host and forge state); paths `.agents/artifacts/specs/2026-11-03-issue-129-argus-adoption-design.md`, `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.md`. Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`. `ran: full (shadow)`.

## Problem

Argus (`fagenorn/argus`, private, integration and default branch `main`) is the last stage of the
project-system rollout and the fleet's most different release shape: a per-user launchd daemon
rooted in its checkout and locally signed helpers. It has no project contract, so:

- No agent can resolve its policy; `adopt-project plan` stops at `contract-valid-after-amendment`
  (`adopt.contract.absent`) and `conformance run --purpose doctor` stops at
  `repository.contract.present`, suppressing every host check.
- The lifecycle guard authorizes Argus pushes and PR creation only through the `fagenorn` owner
  literal, and refuses every Argus merge: the forge answers the default branch's protection read
  with the plan-gated 403 and no derived row declares the checks the 552 floor would use. The owner
  merges Argus PRs by hand.
- Nothing records Argus's release units in a compiled profile, and the fleet registry has no Argus
  entry.

Every blocker the earlier launches found is closed (#126, #124, #547, #552). What remains is to adopt
Argus through the standard path with every fact declared in Argus's own contract, and to prove the
result on this host (`mbp`) and the forge, adding no Argus literal to nix-config's central policy.

## Solution

1. **Argus's contract** (section 1) declares Argus's identity, tracker, branches, the merge floor
   check, paths, commands, workflow, capabilities, one instruction projection and two release
   profiles: the host-local units under the 547 adapters and a publication-free forge target.
2. **The adoption** (section 4) runs the standard path: the contract is committed on a branch, the
   tool's ready plan is applied as one atomic adoption commit on top of it, and both reach Argus
   `main` through one PR. Doctor runs before the apply and after the merge, and its findings are
   repaired only through the report's repair channel.
3. **The bootstrap merge** (section 5): the guard cannot judge the PR that first publishes Argus's
   contract (552 D8), so the run proves the guard's refusal with a non-executing probe and suspends
   on a human gate for the owner's merge. No route around the guard or the floor is used.
4. **Registration and the derived row** (section 4): after the merge, `verify --register` writes the
   registry, the guard policy is recompiled, and non-executing probes of the installed guard show
   Argus pushes, PR creation and merges judged from the derived row, the floor included.
5. **Evidence** (section 6): a fresh baseline before planning, every verdict and report in the
   acceptance record, and a diff of the central policy tables showing no Argus literal. nix-config's
   product change is nil: this delivery commits only its spec, plan and evidence.

## Decisions

### 1. Argus's contract (per D1, D2, D3, D4)

The contract is authored at `.agents/project.json` in Argus, on project schema 1, and validated only
by the installed resolver. Every value below is Argus's own, read from its tree at `dc7564b3`, its
remote and its CI; none is copied from nix-config's contract where Argus's evidence differs.

| Member | Value |
|---|---|
| `project` | `id` `fagenorn/argus` (the Phase-0 plan's recommended identity, from Argus's one remote), `name` `argus` |
| `bindings.tracker` | `kind` `github`, `cli` `gh`, `repo_slug` `fagenorn/argus`, `credential_env.unset_before_invocation` `["GITHUB_TOKEN", "GH_TOKEN"]` |
| `bindings.vcs` | `kind` `git`; `default_branch` and `integration_branch` `main`; `branch_pattern` `issue-<num>-<slug>`; worktree prefix `worktree-`, root `.worktrees`; commits `signed` and `co_authored_by`; merge `strategy` `merge`, `delete_branch` `true`, `required_checks` `["memory foundation (unit + forced checks)"]` |
| `bindings.paths` | artifacts `.agents/artifacts/specs` and `.agents/artifacts/plans`; `context` `["docs/CONTEXT-MAP.md"]`; `standards` `["docs/standards/README.md"]`; `architecture` `["docs/guides/architecture.md"]`; `operations`, `hints` and `rejections` empty |
| `bindings.commands` | one entry per verification step (below) and `build-notifier` (section 2); every argv names its program, with no shell asked to read a command and no shell metacharacter |
| `bindings.workflow` | `verification` lists the verification ids in CI order; `orchestration` `max_parallel` 2, `attempt_budget_minutes` 240; `review.plan` and `review.code` `null`; `light_lane` and `verification_conditions` absent |
| `bindings.deploy` | `adapter` `none`, `command` `null`, `config` `{}` |
| `capabilities` | `tracker`, `worktrees`, `knowledge.context`, `knowledge.standards`, `knowledge.architecture` and `verification` supported; `knowledge.hints`, `review.plan`, `review.code` and `deploy` unsupported |
| `projections` | one entry: agent `claude`, kind `managed_import`, target `CLAUDE.md`, source `AGENTS.md` |
| `platform` | the interval `adopt-project` derives for the installed platform version, authored in the contract commit |
| `release` | two profiles, `local-host` and `forge-main` (section 2) |

**The floor check (per D2).** `memory foundation (unit + forced checks)` is the `name` of Argus's
only CI job in its only workflow, which runs on every `pull_request`. GitHub reports a job as a
`CheckRun` with that name, so the 552 floor finds it in the PR rollup. The workflow name `CI` is
never a rollup entry and is not declared.

**The projection (per D3).** Argus's `AGENTS.md` is the 7.9 KB development guide that Claude Code,
Codex and the pi kernel's development sessions read; it stays authored. The one projection writes
the managed line `@AGENTS.md` into `CLAUDE.md`, whose pointer prose stays as authored, as Arcwave's
and JarBird's contracts do.

**Verification (per D4).** The commands mirror the steps of the required CI job, in job order, run
with the host's `node` and `npm` from the checkout root: `npm ci`, the coverage guard
(`tests/docs/ci-covers-every-test.test.ts`), the unit-test glob `tests/**/*.test.ts` (Node expands
it; no shell), the forced checks and the recall-cap checks, each with the job's
`--experimental-strip-types --experimental-sqlite --disable-warning=ExperimentalWarning` flags.
`apply`'s `workflow-verification-commands` gate runs all of them in full in a fresh worktree, so the
run pre-flights them in a fresh checkout before `adopt-project plan` (section 4, step 4). A
pre-flight failure stops the stage; the contract is corrected only toward a truthful command, never
by dropping or narrowing a step.

**`platform` is authored (per D9).** With `platform` present the contract is valid at the contract
commit, so the pre-apply doctor reaches its host checks instead of suppressing them, and the plan's
amendment adds nothing. The value is exactly the interval the adoption tool would write, so no
second policy is introduced.

### 2. Argus's release profiles (per D5, D6)

- **`local-host`** carries exactly the values that 547 verified against Argus's tree and committed
  as `tests/fixtures/release/argus-shaped-profile.json`: the `notifier` publication
  (`codesigned-artifact` `install` of `daemon/notifyd/Argus.app` to
  `~/Library/Application Support/Argus/Argus.app`, prefix `Apple Development`, override
  `ARGUS_CODESIGN_IDENTITY`, no ad-hoc fallback), the `daemon` activation (`launchd-agent`
  `activate` of `dev.argus.daemon` running `devenv shell -- daemon run`, keep-alive, background, logs
  under `home/daemon/logs/`), the required `daemon-live` liveness obligation, `supersedable_only`
  recovery for both units and concurrency key `release/fagenorn/argus`. The fixture stays a
  nix-config test fixture; the contract is the only place Argus's values become policy. At design
  time the two profiles, keyed as here and sharing that concurrency key, passed
  `release_profile.grammar_violations` and `compile_profile` from `origin/main` source with no
  finding, and none of the three conformance release-profile rules fired.
- **`forge-main`** is publication-free: one `github_repository` target `fagenorn/argus` on `main`
  through `github-forge`, `publication` and `activation` `none`. `guard-policy` derives a row only
  from a `github_repository` target (126 §2 step 7), and the tracker slug never stands in.
- **`build-notifier`** is a `commands` entry, `bash daemon/notifyd/build.sh` from the root (a script
  path, not `-c`). It is the declared build-before-release step 547 D9 left outside the adapter,
  because the bundle is a gitignored build output that `install` copies only once built.
- **The bare helpers.** `authd`, `ocr-helper`, `wa-bridge` and `wkfetch` are signed in place inside
  the checkout, gitignored, rebuilt by Argus's `devenv` shell entry only when absent, and become
  live when the daemon restarts. They have no target outside the checkout and no activation of
  their own, so they are inputs of the `daemon` unit, not release units. The `daemon` unit's
  identity proves the checkout at the candidate commit with no tracked change, which an untracked
  stale helper binary passes. The acceptance record states this limitation, the counterpart of the
  bundle-build limitation 547 D9 documents; it is not recorded as a contract gap.
- **No release runs.** The profiles are proven by compiling, never by a release, so no bundle is
  installed and the running daemon is never booted out. The legacy `~/Applications/ArgusPing.app`
  that 547 assigned here is absent on `mbp`, which the baseline records.

### 3. Duplicated and vendor-sensitive knowledge (per D7)

Every item the #62 inventory names for Argus receives one reconciliation action from the closed set
(`move-canonical`, `generate-projection`, `retain-product`, `archive-history`,
`delete-exact-duplicate`). None is an exact duplicate, none is a development record and none is
generated from another source, so each is `retain-product`. The listed candidates are carried forward as
candidates, not decided.

| Item (#62 class) | Action | Where it is recorded |
|---|---|---|
| `AGENTS.md` § How we collaborate, the root-causes and verify leads (duplicate-of-global) | `retain-product`; demotion candidates | plan table |
| `AGENTS.md` § Key facts about the pi kernel (vendor-derived) | `retain-product`; dated re-verification stays Argus's | plan table |
| `.claude/skills/writing-pi-extensions/`, `.claude/skills/writing-pi-skills/` (vendor-derived) | `retain-product` (class `legacy-native-store`) | plan table and the adoption plan's evidence row `.claude/skills` |
| `docs/standards/README.md` (duplicate-of-global) | `retain-product`; bound as `paths.standards`; demotion candidate | plan table |
| `docs/standards/pi-extensions.md` (vendor-derived) | `retain-product` | plan table |

The adoption plan classifies paths, not sections, and never inspects `docs/`, so the item-level
table lives in the committed nix-config plan and its acceptance record, and cites the adoption
evidence record for the path-level rows. `AGENTS.md` and `CLAUDE.md` keep their tool classification
(`native-projection`), which the plan records.

### 4. The effects, in order (per D8, D10, D11, D12, D13, D14)

The owner authorized four out-of-contract effects on 2026-11-02: an Argus PR adding the contract and
its adoption evidence record, opened and merged; the registry write; `doctor`; `just switch` on
`mbp`. Every other step below is read-only, local to a scratch worktree, or the tool's own state.
Each step's evidence enters the acceptance record (section 6).

| # | Step | Effect and authorization | Evidence |
|---|---|---|---|
| 1 | Fresh baseline (section 6) | read-only | the baseline record |
| 2 | `just switch` on `mbp` from a scratch checkout of the current `origin/main` (which contains `ed332155`). `sudo` there authenticates by Touch ID; if it cannot complete, the run suspends `blocked_on=human_gate`, naming the commit and the command for the owner to run from a clean checkout of it | authorized switch; installs the 561 resolver and guard and recompiles the guard policy (no Argus row yet) | installed/source conformance (D11) |
| 3 | A scratch worktree of Argus at `origin/main`, then the contract commit on a local branch in it | Argus-local commit, not pushed yet | the contract commit id |
| 4 | Pre-flight in the scratch worktree: each verification command in full, then `conformance run --purpose doctor` | read-only, plus `npm ci`'s ignored `node_modules` | doctor report 1: no `host` finding; its repository findings listed with the plan operation that repairs each (D10) |
| 5 | `adopt-project plan --repo-root <scratch worktree>`: `ready`, outcome `reconcile` | the tool's own plan store | plan id, gates, evidence rows |
| 6 | `adopt-project apply --plan-id <id>`; the scratch worktree then checks out `adopt-<digest12>` and runs `resolve-project resolve` and `release profile inspect` for both profiles | the tool's isolated worktree and branch `adopt-<digest12>` holding the contract commit and the signed adoption commit | the apply report and its seven commit gates; the resolve and inspection outputs (AC5, early) |
| 7 | Push `adopt-<digest12>`; open the PR into `main` in the guard's accepted form; wait for the declared check | authorized Argus PR; the guard allows both through the owner literal | PR URL, head SHA, the check green on that head |
| 8 | Non-executing probe of the exact merge command (section 5) | read-only | the guard's verdict, expected `protection lookup failed: …` |
| 9 | Human gate: the owner merges (section 5); the scratch worktree is removed before suspending | authorized merge, performed by the owner | merge commit on Argus `main` |
| 10 | A fresh scratch worktree of Argus at the merged `origin/main`: doctor and plain `adopt-project verify`; installed/source conformance re-checked | read-only | doctor report 2 `passed` with no `host` finding; verify `adopted` with all six checks passed |
| 11 | `adopt-project verify --register --repo-root /Users/anis/Projects/argus` | authorized registry write | `registered: true`, `result` `adopted`; the registry entry |
| 12 | `claude-guard-policy`, then `guard-policy derive --repository fagenorn/argus` and `resolve-project platform-status --fleet` | the guard-policy rebuild the authorized switch exists to produce (D12); `derive` writes only remote-tracking refs | compile report naming `fagenorn/argus` derived; the row with `required_checks`; Argus `compatible` |
| 13 | Non-executing guard probes for push, PR creation and merge (D13) | read-only | the probes' verdicts |
| 14 | Central-literal diff and acceptance record; the nix-config PR ships last | nix-config delivery | section 6 |

The registry root is the primary checkout, `/Users/anis/Projects/argus`. Registration and the guard
compile read only `origin` and write only remote-tracking refs and fetched objects there (126 §2), so
its working tree, its branch, the running daemon and its untracked `home/skills/humanizer/` stay
untouched. The owner fast-forwards it when they choose.

**A plan that opens a question** answers it with the plan's own recommendation only when one value
is recommended, logging each answer as a plan ledger row; any other open question is a human gate.
**A refusal the contract cannot express** at any step (a binding, capability or artifact class)
records the failed observation on the issue, files a nix-config issue that blocks this one, and
suspends, per #71 and the owner's instruction. No Argus-local workaround ships.

### 5. The bootstrap merge (per D8)

A derived row exists only for a registered project whose contract is on the registered branch of
`origin`, and registration needs the adoption evidence record and commit on Argus `main` (the
default branch; `--integration-branch` can never name it). So the PR that publishes the contract is
judged with no row: owner literal for authorization, the plan-gated 403 with no declared checks, and
`protection lookup failed`. 552 D8 left that merge refused on purpose.

- **One PR** carries both commits, so the bootstrap costs one human merge.
- **Probe first.** Before asking the owner, the run feeds the installed guard wrapper (the
  `PreToolUse` command in `~/.claude/settings.json`) the hook payload of the exact merge command,
  `gh pr merge <n> --repo fagenorn/argus --merge --subject "<subject>" --match-head-commit <head>
  --delete-branch`, with `cwd` in the Argus scratch worktree, from a payload file. The guard reads
  the PR and the protection and returns its verdict; nothing merges. If it unexpectedly allows, the
  agent runs that same merge as authorized. The wrapper path is read from the current settings, so
  every probe (here and at step 13) judges with the guard the switch installed, even when the
  running session's own hook predates the switch; such a hook reads the schema-3 policy as
  contributing no row (552's transition), which leaves Argus's owner-literal push and PR creation
  unaffected.
- **The owner's merge applies the floor by hand**: merge only when
  `memory foundation (unit + forced checks)` is green on the head the run reviewed, and use a merge
  commit (GitHub's merge, not squash or rebase, which would leave the adoption commit unreachable and
  make `verify --register` refuse `not_integrated`), deleting the branch.
- **Rejected routes:** a separate integration branch or the registration operand (drops the floor),
  reading the checks from the PR head's contract (552 D8), a direct push to `main` (the guard refuses
  it), and an admin or forge-side bypass.

### 6. Evidence and acceptance (per D11, D13, D14)

**The fresh baseline**, measured at step 1 before any planning and committed with the plan:

- Workflow outcomes: Argus's orchestrated runs from `.superpowers/workflows/*/state.json` in the
  primary checkout (read-only; per issue, `merged` or `stopped`), and every Argus PR merged or closed
  since 2026-08-01 with who merged it.
- CI duration and bounds: the job's declared `timeout-minutes` (15) and the conclusion and duration
  of the last 20 `CI` runs. Adoption proceeds only when every completed run of the last ten that was
  not cancelled finished within that bound; Argus issue 5 ("workflow has never completed") is
  recorded with the runs that contradict it.
- Daemon-to-child handoff: Argus issue 80's state and the live daemon's
  `launchctl print gui/<uid>/dev.argus.daemon` `state`, `pid` and `runs`, read only.
- Host: the installed generation, the registry and the compiled policy's `derivation`, and the
  presence of the legacy `~/Applications/ArgusPing.app`.

**Installed/source conformance (per D11)** holds when the checkout `just switch` ran from is at the
then-current `origin/main` with a clean tree, `/run/current-system` resolves to the same store path
as that checkout's `just build` result, the hook command in `~/.claude/settings.json` names that
build's guard wrapper, and `test_installed_policy_surface_matches_source_contract` passes against
the installed skills.

**Acceptance mapping.** Each of the issue's nine criteria, its check and its threshold:

| AC | Criterion (abridged) | Check | Threshold |
|---|---|---|---|
| 1 | Registered and compatible | step 11 report; registry entry; `resolve-project platform-status --fleet` | `adopted`, `registered: true`; entry `{project_id: fagenorn/argus, root: /Users/anis/Projects/argus}` with no `branch_override`; the merged contract compatible via `platform-status --repo-root` on a clone at merged `main`; the `--fleet` row compatible once the owner fast-forwards the primary checkout (`human_pending` until then, D21) |
| 2 | Guard allows push, PR creation and merge with the floor, from derived facts; no Argus literal in guard tables | step 12 row; step 13 probes; the central diff | row `{main, main, ["memory foundation (unit + forced checks)"]}`; push and PR-creation probes allowed; merge probe allowed and the same merge without `--match-head-commit` refused by the floor (D13); diff empty |
| 3 | Doctor reports no `host` finding; store-symlink and PATH classes repaired through the repair channel | doctor reports 1 and 2 | no `host` check `failed` in either; `host.policy_path.no_follow_readable` and `host.executor.helper_on_path` `passed` in both; every `host` check `passed` in report 2; every report-1 finding closed by its named repair (D10) |
| 4 | Every duplicated or vendor-sensitive item classified | section 3 table in the committed plan; the evidence record's `.claude/skills` row | one action per item, none unclassified |
| 5 | Daemon and signed-helper units expressible in a compiled profile, or the gap recorded and the stage rewound | `release profile inspect local-host` and `forge-main`; `resolve-project resolve` | both admissible; `capabilities.release` `available`; `release.targets` lists `daemon`, `notifier` and `repository`; the three `repository.release_profile.*` checks `passed` |
| 6 | Fresh baseline before planning | the baseline record | committed on this delivery's branch, measured before step 5 creates the adoption plan |
| 7 | Units compile through #124, or the exact gap recorded | as AC5, plus the bare-helper limitation statement (section 2) | as AC5 |
| 8 | No Argus literal centrally; owner, branches, release units and host requirements derive from Argus's contract | `git diff --stat ed332155 <delivered head>` over `home/common/claude-code/`, `python/agent_tools/`, `home/common/agent-skills/scripts/`, `lib/` and `hosts/`; the built base policy's `authorized_owners` and `integration_bases` | the diff is empty; neither base table names Argus; the row, the floor check, the release targets and the adapters' executables are read from Argus's contract |
| 9 | Doctor, adoption verification and installed/source conformance pass before registration | steps 2 and 10 | all three recorded passing with times before step 11 |

AC2's merge probe needs an open Argus PR whose head carries the declared check green; PR #115 is one
today. If none qualifies at step 13, AC2's merge half is `human_pending` until the next Argus merge
through the floor, and the issue is held `needs-verification`, as #126 held its live proof. Push and
PR creation also stand on the pre-existing `fagenorn` owner literal, which names no Argus fact
(126 D3); once the row exists the guard confirms it on every Argus verb and takes the base from it,
so the probes exercise the derived row, and only the row can supply the floor.

Report 1 judges the contract commit, whose projection drift suppresses `host.capability.required`
(a stage after `repository.projection.fresh`); suppression is not a finding, and report 2 must show
that check `passed`. If the store-symlink and PATH checks pass in report 1, those classes did not
recur on this host; the record says so instead of claiming a repair.

## Test seams

This delivery adds no code, so it adds no test. The mechanisms it relies on are already pinned at
their existing seams, and its own proof is live evidence at three boundaries:

- **The installed commands, as an operator runs them:** `adopt-project plan`/`apply`/`verify`,
  `conformance run --purpose doctor`, `resolve-project resolve`/`platform-status`,
  `release profile inspect`, `guard-policy derive` and `claude-guard-policy`, with their reports
  recorded.
- **The registered guard hook, fed a payload** (D13): the same boundary
  `tests/test_claude_permission_guard.py` drives, here against the host's compiled policy and the
  live forge, never executing the judged command.
- **The forge:** the PR, its check rollup and the merge commit's ancestry.

Prior art: `test_an_argus_shaped_project_merges_under_the_plan_gated_floor` (552),
`HostLocalReleaseTest` and `HostLocalCoreTest` (547), and the registration suite. nix-config's
declared verification is `nix-build`; `agent-workflow-tests` is skipped, because no path it watches
changes (`.agents/artifacts/specs` and `plans` are outside its `when_changed` set).

## Out of scope

- Any change to nix-config's central policy tables, guard, resolver, adoption engine, adapters or
  conformance registry, and any new release adapter. A gap rewinds into a new blocking issue.
- Running a release of Argus: installing the bundle, activating or restarting the daemon, removing
  any host artifact (D6).
- Changing the bare helpers' build or signing, Argus issue 5, Argus issue 80, or any Argus product
  file beyond the contract and the tool's adoption commit.
- Editing or reconciling Argus's guidance text (the section 3 candidates), promoting any lesson, or
  creating hints or rejections trees in Argus.
- Branch protection, repository visibility or billing for Argus; removing the `fagenorn` owner
  literal; a second Argus PR made for evidence.
- Fast-forwarding, cleaning or otherwise touching Argus's primary checkout and its running daemon.
- Codex review for Argus (D1) and a light lane.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Argus's contract carries Argus's own facts: id `fagenorn/argus`, tracker `gh` with the `GITHUB_TOKEN`/`GH_TOKEN` scrub, `main` as both branches, merge strategy `merge`, paths from Argus's docs layout (CONTEXT-MAP, standards README, `docs/guides/architecture.md`), no hints or rejections, review `null` and unsupported, no light lane, orchestration 2 and 240 minutes | The issue: owner, branches and host requirements derive from Argus's contract. #67: policy is never silently inferred. Phase-0 plan's recommended id. Arcwave and JarBird contracts (scrub, paths, review unsupported). Argus's run ledgers and merge history show no configured reviewer and merge commits. Argus's map passes `context-map-lint` (150 lines) | Copying nix-config's contract: adds Codex review, risk paths and literal paths Argus never had. Declaring Codex review: new review policy without evidence; one contract line enables it later |
| D2 | `required_checks` is exactly `["memory foundation (unit + forced checks)"]` | Argus's only workflow has one job of that name on `pull_request`; 552 D1 and D3 (exact check-run names, every declared check green) | The workflow name `CI`: never a rollup entry, so every floor merge would refuse. No declaration: the guard keeps refusing every Argus merge. Splitting into step names: steps are not check runs |
| D3 | One projection, Claude `managed_import` of `AGENTS.md` into `CLAUDE.md`; `AGENTS.md` stays authored | Argus's `AGENTS.md` is the shared development guide (#62 inventory); Arcwave and JarBird precedent; the resolver forbids a target that is a source | A `generated_file` `AGENTS.md` from a bootstrap source: overwrites the 7.9 KB guide. No projection (Nodo): `CLAUDE.md` would reach the guide only through prose |
| D4 | Verification mirrors the required CI job's steps in order, with host `node`/`npm`, dependency install first, and is pre-flighted in a fresh checkout before planning | `apply` runs every verification command in full in a fresh worktree; the CI job is the merge floor; bootstrap invariant (every executable is a `commands` entry) | A `devenv shell --` wrapper: its shell entry builds and signs helpers and can prompt the keychain. A subset: local verification would diverge from the floor |
| D5 | Two profiles: `local-host` with the values 547 verified (bundle install, daemon activation, liveness) and publication-free `forge-main`; `build-notifier` declares the bundle build; the four in-place-signed binaries are inputs of the `daemon` unit, with their stale-binary limitation recorded, not a contract gap; `deploy` unsupported | 547's settled roster of two units and its fixture; the seam inventory (bare helpers: target inside the checkout, activation belongs to the daemon); 126 §2 step 7 (a row needs a `github_repository` target); 547 D9; 547 (activation units force `deploy` unsupported) | Rewinding on the bare binaries: they have no release target or activation of their own, and 547's owner-closed scope excluded in-place signing. A forge-only profile: misdescribes Argus (#71). Commands for every helper build: nothing reads them, and the daemon's own shell entry builds them |
| D6 | No live release, install, activation or host clean-up in this delivery; the profiles are proven by compilation and inspection | The owner's authorization names four effects only; criteria 5 and 7 ask for expressibility; a release boots out the running assistant daemon | Running the 547-suggested live release here: an unauthorized effect on a live service, left for the owner to request separately |
| D7 | Every #62 Argus item is `retain-product`, with demotion and promotion candidates carried, not decided; the item table lives in the committed nix-config plan and cites the adoption evidence record for path-level rows | #67's closed action set; no item is an exact duplicate, record or projection; #62 lists candidates "not deciding"; the adoption plan classifies paths only and never inspects `docs/` | Stable question ids per item: no decision is pending in this delivery. Editing Argus's guidance to dedupe: a content change outside adoption |
| D8 | One Argus PR (contract commit, then the tool's adoption commit); a non-executing probe proves the guard's refusal; the owner merges as a human gate, with a merge commit and the declared check green on the reviewed head | 552 D8 (that merge stays refused); `verify --register` reads only the default branch for Argus and checks adoption-commit ancestry; the rejection record `ungated-agent-merges`; the owner's authorization | Integration-branch or registration-operand routes: drop the floor. Two PRs (Arcwave's order): two human merges. Agent merge by any bypass: defeats the guard |
| D9 | The contract commit authors `platform` as the interval the tool derives | The pre-apply doctor suppresses every host check under an invalid contract; the issue asks for doctor before apply | Leaving `platform` to the amendment: the pre-apply doctor could not judge the host |
| D10 | Doctor runs twice, before apply on the contract commit and after the merge; a `host` finding is repaired only by its report-named repair and doctor re-run; repository findings before apply are each matched to the plan operation that repairs them; a repair that needs a central change rewinds | #69 (doctor-driven repair before adoption); the issue's "repaired through the plan's repair channel"; the registry's repair table | Running doctor only after the merge: misses "before the plan is applied". Fixing a finding by hand mid-run: the per-run workaround the issue forbids |
| D11 | `just switch` runs first, from a scratch checkout of the current `origin/main`; Touch ID that cannot complete turns it into a human gate; installed/source conformance is the generation, hook and policy-surface comparison of section 6 | The installed resolver predates 561 and refuses `required_checks`; `sudo -n` fails on `mbp`; criterion 9 | Running source tools before the switch: mixes the installed manifest with source code. Switching only after registration: plan and apply would run a resolver that refuses the contract |
| D12 | After registration the guard policy is rebuilt with `claude-guard-policy`, the activation's own compile run alone; a second `just switch` is the equivalent fallback if the owner prefers it | 126 §4 (registry changes take effect at the next compile; the command grants nothing a switch would not); the owner authorized the switch "so … the guard policy is rebuilt" | Waiting for an unrelated switch: no row until then. Hand-editing the compiled policy: the row check refuses it |
| D13 | Guard evidence comes from non-executing probes of the installed hook: push and PR creation in the Argus worktree; merge on an open Argus PR whose head carries the declared check green, allowed with `--match-head-commit` and refused by the floor without it; no qualifying PR makes the merge half `human_pending` | The registered hook is the guard suite's seam; the owner's authorization covers one Argus PR; #126 held its live proof `needs-verification` | A throwaway Argus PR or merging the owner's open PR: unauthorized effects. Unit tests alone: they cannot show the host's compiled row |
| D14 | Doctor and verify run in a fresh scratch worktree at the merged `origin/main`; registration names the primary checkout, which is never modified | The primary checkout runs the live daemon and holds untracked owner work; registration and the guard compile read only `origin` (126 §2) | Fast-forwarding the primary checkout: changes the daemon's code under it without authorization. Registering the scratch path: it vanishes |
| D15 | No glossary or ADR is written; this ledger and the acceptance record are the decision record | `bindings.paths.context` is `[]` (capability unsupported); 126 D12 precedent | Creating a context or ADR surface: an unauthorized new knowledge home |
| D16 | Amends steps 7–9 and section 5's probe (planning): the owner opens the Argus PR as well as merging it, inside the one bootstrap gate. The run pushes `adopt-<digest12>` with `git -C`, then probes the exact PR creation and the merge of an open Argus PR into `main` without executing either, and suspends. An unexpected allow is recorded, never executed | The guard reads a `gh` verb's repository from the hook payload's `cwd` (`detect_repository` in `lifecycle_guard.py`), and only `git push` and `git branch -d` take `git -C`. Every agent in this run starts each Bash call in the nix-config launch directory, so its `gh pr create --repo fagenorn/argus` is judged as a nix-config command and refused | `cd <clone> && gh pr create`: the payload `cwd` stays the same, and the guard refuses the slug mismatch. `gh api` POST: routes around the guard. A nested session started in the clone: a launch surface outside `launch-scope`. Two gates (open, then merge): two owner interactions for one PR |
| D17 | Each Argus copy the run works in is a fresh `git clone` of `git@github.com:fagenorn/argus.git` under the launch's scratch root, made again after any suspension (one clone for Tasks 3–5, another for Task 6). It is never a `git worktree add` on the primary checkout. Argus commits run as `env -C <clone> launch-commit …` | D14 (the primary is never modified); `adopt-project apply` creates `adopt-<digest12>` and its worktree in the repository it planned; the launch's scratch root and every worktree registered in it are reaped with the launch | A worktree of the primary: writes branches and worktree metadata into it, and leaves stale entries once the reaper deletes the root. A clone of the local checkout: its `origin` would be a local path |
| D18 | Live evidence lives in one committed file beside the plan, `<plan stem>.evidence.md`, with one section per task. Each section holds the exact commands, the condensed reports (every check that did not pass, with its reason and repair; outcomes, verdict lines, ids and UTC times), the adoption plan's answered questions and the owner gate block. Raw outputs stay in the launch scratch. Each task's verification caps `E`'s cumulative size, so the file stays under 56 KB, inside one review shard. Task 8's acceptance record cites the sections. Nothing is written under `.agents/artifacts/evidence/` | sdd's acceptance record is one table; section 6 asks for every verdict and report; `.agents/artifacts/evidence/*` is in `agent-workflow-tests`' `when_changed`, which the spec's test seams keep skipped | Reports pasted into the acceptance record: breaks its one-table schema. Raw JSON committed: unbounded bytes in a review package. `.agents/artifacts/evidence/`: triggers the suite with no code change |
| D19 | Argus's command ids are `install`, `coverage-guard`, `unit-tests`, `forced-checks` and `recall-cap-checks` (the verification list, in CI order) plus `build-notifier`. `forge-main` declares empty `principals` and `credentials`, as JarBird's does. The plan dictates the whole contract except `platform`, which Task 3 derives (D9). At planning, the contract was checked in a scratch clone of `dc7564b3` with its projection regenerated. From `ed332155` source it resolved with `release` `available` and the three expected targets. Both profiles inspected with the three release-profile checks `passed`. A source doctor passed every `host` check, and its one repository finding, `repository.ignore.runtime_sentinel`, is repaired by the adoption plan's `.gitignore` amendment | Argus's CI step names; JarBird's `forge-main`; the planning run, which is no evidence for any criterion | The publication-free fixture's `maintainer` and `forge-keyring`: a profile without publication never reads them. Leaving the contract text to the implementer: the contract is a public interface the plan review must see |
| D20 | Installed/source conformance compares the installed generation with the build of the commit the switch ran from. That commit is recorded, or named in the switch gate, and must contain `ed332155`. A later `origin/main` never reopens the gate | D11; an owner-run switch happens between launches, while `origin/main` keeps moving | Rebuilding the current `origin/main` on resume: a merge landing in the meantime would demand a fresh switch each time |
| D21 | AC1's fleet compatibility half is `human_pending` until the owner fast-forwards `/Users/anis/Projects/argus` past the merge; the run proves the merged contract compatible on a fresh clone instead (Phase-5 review AR129-01) | `fleet_verdict` (`python/agent_tools/resolve_project.py`) reads the registered root's working tree, while D14 forbids modifying the primary checkout, which runs the live daemon | Fast-forwarding the primary checkout: unauthorized and moves the daemon's code. Registering a scratch root: rejected by D14 |
| D22 | Refines D20: the switch commit `C` is the commit the owner's switch actually ran from, as the owner's gate-resolution comment records it, even when the switch gate named another commit. For this run `C` is `5dfe65efbae09024aaf259d5a013d5658eeec0a0` (contains `ed332155`), whose build must equal the installed generation; the switch is not rerun | D20's own rule (compare the installed generation with the build of the commit the switch ran from); the owner's resolution comment on the issue (generation 308, built from `main` at `5dfe65ef`, "do not run the switch again") | Keeping the gate's `ed332155`: its build differs from the installed generation, so Step 4 would demand a second owner switch to a commit older than the one installed |
| D23 | On `mbp` the pre-flight (Task 3 Step 6) and `adopt-project apply` (Task 4) run with `TMPDIR=/tmp` set on that one command only (`launch-scope exec … -- env TMPDIR=/tmp <argv>`); the contract's verification commands stay unchanged, and the evidence records the failing run under the default `TMPDIR` beside the passing one | Argus `tests/extensions/email/review-render.test.ts:100` caps a receipt that embeds an `os.tmpdir()` path at 500 characters: 504 under macOS's per-user `TMPDIR`, a pass under `/tmp` (Linux CI's tmpdir). It is a host-path dependence in an Argus test, not a wrong argv; D4's command list and the CI merge floor are untouched; `adopt_apply` runs the commands with the inherited environment | Treating it as a contract gap and rewinding: the contract is truthful and the resolver lacks nothing. Fixing the Argus test in the adoption PR: an Argus product change beyond adoption scope, left as a follow-up for Argus |
