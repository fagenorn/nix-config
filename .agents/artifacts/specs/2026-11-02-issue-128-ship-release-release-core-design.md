# Migrate ship-release onto the release core — issue 128

Design for [#128](https://github.com/fagenorn/nix-config/issues/128), 2026-11-02, against main
`0a25b80`. Written in autonomous mode (`from-issue --auto`). Every choice below is an agent
judgment inside the issue's delegated scope and is recorded in the decision ledger. None of them
is a human answer, grant or irreversible confirmation.

The authoritative decision store is the [#90 resolution](https://github.com/fagenorn/nix-config/issues/90).
This spec cites it and does not restate it. The other binding records are the #116 guard/core
decision (`2026-09-20-issue-116-permission-guard-core-design.md`), the #124 profile and forge
adapter design (`2026-10-09-issue-124-release-profiles-forge-adapter-design.md`) and #127's
evidence precedent.

## Triage

### Lane triage
Input signals: `contract_change` hit (adds a release driver command surface, enables forge pr_merge invoke, rewrites the ship-release skill contract and its contract tests); `concurrency_or_persistence` hit (release state moves into the fenced transaction core and the legacy state.json is deleted behind an in-flight gate); `open_design_questions` hit (driver CLI shape, administrative inspect operation, grant collection at preview and the pre-release receipt utility are not yet specified at code level); `criteria_shape` hit (ten acceptance criteria, including an approved #70 bundle and a 40% context reduction that no deterministic code check alone verifies). Paths: home/common/agent-skills/skills/ship-release/SKILL.md, home/common/agent-skills/tests/test_ship_release_contracts.py, python/agent_tools/release.py, python/agent_tools/forge_adapter.py, python/agent_tools/release_driver.py, python/agent_tools/transaction_core.py, .agents/project.json, lib/agent-tools.nix, justfile, tests/test_release_command.py, python/README.md.
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

The triage predicted a forge `pr_merge` invoke and edits to `transaction_core.py`,
`.agents/project.json` and `lib/agent-tools.nix`. The design makes none of them (per D2, D5, D3).

## Problem

A release today is 316 lines of ship-release prose: 21,321 bytes of `SKILL.md` plus the 8,177-byte
`CHANGELOG.md` rubric, re-read on every release. The prose also owns the release semantics. It keeps
its own state file, a hand-written resume table and a double-tag guard. It reads the forge first
after a crash. Only prose orders the version decision after a verified candidate. It proceeds when
the user does not answer the version question. The #123 transaction core and the #124 profile, compiler and forge adapter
are shipped, but nothing drives a release through them. `release` can inspect a profile, but no
command can invoke an adapter.

For the operator, this means three problems:

- A crash between publishing steps is recovered by skill-specific guesswork.
- No tool stops a release of a candidate whose required CI is red.
- Two irreversible publications go out without a confirmation that names them.

## Solution

Three new modules sit behind one new area of the existing `release` command,
`release transaction status|preview|run|abandon`. Together they own every release semantic the
skill hand-rolled:

- **The driver** finds the release on `{project, target}`, previews a compiled plan with one
  confirmation per irreversible action, and runs the plan through `TransactionStore` with
  `release_adapter.core_binding`.
- **The verification module** observes the candidate's required CI and seals that observation as
  core evidence.
- **The cutover module** classifies and retires the legacy state file.

The skill keeps only the work that is not release semantics:

- pre-flight hygiene;
- the changelog and the version proposal (from `CHANGELOG.md`'s rubric);
- one bounded wait for CI;
- presenting the preview and stopping;
- calling `run`;
- rendering the report from the core's output.

The path runs every profile shape the closed adapter registry can execute today. For nix-config
that is the forge-only, single-branch profile: tag then GitHub Release. Any other shape is refused
at entry with a typed refusal (per D1, D2). Merge and deploy handling is built into the driver and
proven against fixture adapters, so a certified merge arm or activation binding plugs in without
skill changes.

The work is delivered as the staged contract's three review packages on one branch:

1. driver, verification, preview and confirmations, with the nix-config dry-run demo;
2. the crash and retry matrix;
3. the skill rewrite, legacy cutover, context proof and #70 bundle.

## Decisions

### 1. Entry, selection and shape gates (per D1, D2, D13)

Every subcommand takes `--repo-root` and an optional `--profile`. It first resolves the project as
`resolve-project resolve --require release` does. A refusal reaches the caller byte for byte with
exit 2.

**Profile selection.** The sole profile that declares a publication is selected. With several, the
caller must name one with `--profile`; otherwise the command refuses `profile_ambiguous` and lists
the ids. An unknown id refuses `profile_unknown`.

**Gates.** Four gates run in order. Each refuses with exit 3 and a closed JSON error
`{code, repair_id, detail}`. `preview` and `run` apply all four. `status` and `abandon` apply only
gate 1, because neither publishes anything:

1. **Main checkout.** `--repo-root` must be the main checkout: its git common dir is its own
   `.git`. Otherwise the command refuses `not_main_checkout`. `run` and `abandon` also refuse
   `cwd_mismatch` unless the working directory's top level is `--repo-root`. The forge adapter
   takes its checkout, and the guard its cwd, from the working directory (#124 D23; per D15).
2. **Legacy release** (section 6).
3. **Merge shape.** When `integration_branch != default_branch`, the profile must declare a
   `materialize` publication action. Otherwise the command refuses `merge_not_declared`, with
   repair `release.profile.merge_unsupported`.
4. **Deploy binding.** `bindings.deploy.adapter` must be `none`. Otherwise the command refuses
   `deploy_watch_unowned`, with repair `release.profile.activation_unbound`. The core path cannot
   honour a watch the profile does not own, and dropping it silently would report an unwatched
   deploy as released.

A tracker-free project declares no forge profile, because no local-git adapter is registered, so
it already fails `--require release`. Every provider read and effect addresses the profile
target's `repository`.

### 2. Release identity, store and reservation (per D4)

**The store.** Release transactions live in one `TransactionStore` whose root is
`<git common dir>/agent-release/store`. The root is created with mode 0700 by `run` only. A missing
root reads as "no releases", so `status` and `preview` create nothing.

**The creation key.** It is `release/v1:<project id>:<profile id>:<n>`, with `n` counting from 1.
The driver finds a target's current release by probing `lookup` for `n = 1, 2, …` until the first
missing key. The last key found is the current release. A new release takes the next `n`, and the
driver never creates `n + 1` while `n` is nonterminal.

**Transaction inputs.**

- `create` receives `bind_candidate`'s inputs unchanged, with authority class `release`.
- The custody executor is `release-driver`, and its subject path is the main checkout.

**Reservation.** Creating key `n + 1` reserves the candidate's version. Before creating it, `run`
loads transactions `1..n` and refuses `version_reserved` when any of them holds the same version.
The one exception is an `abandoned` transaction: the core enters `abandoned` only when no action
had an effect, so its version was never published (per D14). `preview` runs the same check and
reports it as not runnable. A version that reached any other outcome is never reused (#81).

**Host locality.** The store is host-local. Two hosts releasing one target meet at the provider's
create-if-absent atomicity (#124 §7), never at the store. A same-candidate race converges to
`satisfied`; a different candidate at the same version parks `diverged` (per D16).

**Two concurrent `run` calls.** The loser gets the core's `CreationConflict` or `LeaseUnavailable`.
`run` reports that as `release_busy` (exit 3).

### 3. Pre-release verification receipt (per D5)

`release_verification` makes three reads with `gh api`, under one 30-second budget. `GITHUB_TOKEN`
and `GH_TOKEN` are removed from the child environment, as the forge adapter does (#124 D17):

1. **The integration tip.** `repos/<slug>/git/ref/heads/<integration>` must equal `--commit`.
   Otherwise the command refuses `candidate_stale` and seals no receipt.
2. **The required contexts.** They are the `checks` of
   `repos/<slug>/branches/<default>/protection`. A 403 or 404 response, or an empty list, refuses
   `verification_unavailable`: the required-check floor cannot be established (#116 D6). A failed
   or timed-out read refuses `verification_unavailable` too.
3. **The check runs.** `repos/<slug>/commits/<commit>/check-runs` is matched to the required
   contexts by name, and by `app_id` when one is given.

**Receipt.** The reads produce one closed receipt:

```text
{schema: "release-verification/v1", project, profile, profile_digest, candidate: {commit, version},
 required: [{context, app_id}], checks: [{context, status, conclusion}], result, observed_at}
```

**Result.** `result` is computed as follows:

- `passed` when every required context has a completed `success` run;
- `failed` when any required context has a completed run that did not succeed;
- `pending` otherwise. A context reported only as a legacy commit status reads as missing, so it
  fails closed.

**Effect on `run`.** `run` refuses before `create` unless `result` is `passed`. The refusal codes
are `verification_pending` and `verification_failed`. So a red or unfinished CI never reserves a
version.

**Sealing.** Once the transaction exists, `run` seals the receipt in the core. In
`awaiting_verification` it records one `event` evidence entry, `verification:<telemetry digest>`,
whose reference is the receipt's canonical text. Only then does the transaction advance to `ready`.
This follows the delivery transactions' canonical-text evidence (#339).

**Resume.** A transaction found before `ready` with no such entry re-observes its stored candidate.
If that observation has not passed, the transaction parks `attention_required`.

Local `just build` is not receipt content (per D5).

### 4. Preview and confirmations (per D6)

`release transaction preview` is read-only. It creates no directory, takes no lock and calls no
adapter. Its only provider calls are the verification reads, and only in `new` mode.

**Mode.** The preview has two modes:

- **`new`** applies when no release is nonterminal. It requires `--commit`, `--version`, `--title`
  and `--notes-file`, and `bind_candidate` validates the resulting candidate.
- **`resume`** applies when a release is nonterminal. Candidate arguments are refused with
  `release_in_flight`, which names the stored version.

**Output.** The preview prints one JSON object:

```text
{schema_version: 1, mode, profile, plan_digest,
 candidate: {version, commit, title}, verification: {result, checks},
 actions: [{name, operation, mode, effect, target, status}],
 confirmations: [{action, effect, operation, version, commit, token}],
 runnable, refusal}
```

Exit 0 means the plan can run. Exit 3 means it cannot, and `refusal` carries the reason.

**`plan_digest`.** It is `telemetry_digest` over a different input per mode:

- **new**: the profile digest, the next ordinal, the candidate (with notes reduced to their
  digest), the verification result with its per-context conclusions (no timestamps), and the
  ordered actions;
- **resume**: the transaction id and the proof plan digest.

**Which actions need confirmation.** One confirmation is listed for every publication action or
activation unit that meets both conditions:

- its profile `effect` is `irreversible`;
- it was not last inspected `satisfied`, judged from the stored fold without a new inspection.

**Token.** Each confirmation's token is `<action>:<12 hex>`. The hex is the first 12 hex digits of
`telemetry_digest([plan_digest, action, next attempt, next acquisition ordinal])`. So a retry, a
re-acquisition after a crash, or any change to the plan's inputs yields a new token.

**nix-config.** Its preview lists two confirmations, `tag` and `github-release`. Both actions are
`irreversible` under #124 D6.

**Collecting confirmations.** The skill presents the preview once and ends its turn. A reply that
confirms all of them lets it pass every token. Any other reply, or none, passes nothing. A reply
that changes the version is a changed target, so it needs a new preview.

**Stable tokens.** While a token's inputs are unchanged, a re-preview prints the same token. A
delegated owner therefore returns the preview JSON to its controller and ends there. The controller
relaunches one owner with the user's answer. That owner re-runs `preview` with the same arguments,
reading the notes file from a path outside both working trees, and calls `run` only when the
printed tokens equal the confirmed ones (per D17).

### 5. Run (per D6, D7)

`release transaction run` takes the preview's arguments plus one `--confirm <token>` per listed
confirmation.

**Before any write.** `run` re-derives the plan exactly as `preview` does. It then applies two
checks:

- A missing token refuses `confirmation_required`, listing the missing actions. The confirmations
  are all-or-nothing.
- A token that is not in the recomputed set refuses `confirmation_stale`.

Neither refusal creates or writes anything.

**Setup (new mode).** In order, `run`:

1. deletes a `completed` legacy file (section 6);
2. creates the transaction, which reserves the version;
3. acquires custody with a 15-minute TTL, renewed between actions;
4. issues the grants:
   - one per token: `grant_id` is the token, `actor_kind` is `human`, and the authority class is
     `release-irreversible`;
   - one `release-scope:<acquisition>` grant for the reversible predeclared set, since invoking
     the skill authorizes that set. It is issued only when the plan has a reversible action, so
     nix-config's plan has none;
5. seals the receipt (section 3);
6. advances through `awaiting_verification` to `ready`, then to `publishing`. It calls
   `verify_anchors` first only when the plan has a `restorable` unit, which nix-config's does not.

**Setup (resume mode).** `run` acquires custody and issues the grants. From `attention_required`,
it advances back to `parked_from`.

**The action loop.** For each publication action, then each activation unit, in compiled
topological order:

1. Call `inspect_action`. A `satisfied` result moves on to the next action.
2. Before invoking an `irreversible` action, call `check_grant` for the token of this attempt and
   acquisition. With no valid grant, stop with `next: confirm`.
3. Call `invoke_action`, then read the action's status from the snapshot:
   - `satisfied` continues the loop;
   - `in_progress` or `unknown` stops with `next: wait`;
   - `absent` after an attempt, or `diverged`, parks `attention_required`. The reason names the
     action and its outcome, and the result is `next: attention`.

An `InvocationRefused` from the core also parks, and its reason is kept.

**After the loops.**

- Advance `publishing → published`.
- With `activation: none`, record one `event` evidence entry, `activation-not-applicable`, then
  advance `published → proving`. This is divergence 1.
- Otherwise go through `activating`, using the same loop.
- In `proving`, run one cohort: `start_cohort`, `collect_obligation` for every plan obligation
  with `core_binding`'s observer, then `settle_proof`. The result is `next: done` with the
  terminal receipt digest, a parked `proof_*` state (`next: attention`), or `next: wait` while
  the cohort budget remains.

**Ending the run.** Custody is released before `run` returns, unless the transaction is terminal.

**Output.** One JSON object:

```text
{schema_version: 1, transaction_id, state, next, actions: [...], receipt_digest}
```

The exit code is 0 for any recorded progress and 3 for a refusal that wrote nothing.

**Abandon.** `release transaction abandon` acquires custody and advances the current nonterminal
transaction to `abandoned` with external state `known`. The core refuses that while any action had
an effect, and the refusal reaches the caller as exit 3. The skill runs it only on the user's
explicit word. This is the only exit for a no-effect park, such as a guard denial or a failed
precondition on the first action, which would otherwise block the target. It also frees the
version for reuse (section 2). A park after an effect stays blocking until a resume succeeds
(per D14).

### 6. Legacy cutover (per D8)

`release_cutover` reads `<repo-root>/.superpowers/workflows/ship-release/state.json` and classifies
it. It never reads a field into the core:

| Class | Condition | Effect |
|---|---|---|
| `absent` | no file | none |
| `completed` | a JSON object with the seven legacy keys, `releaseUrl` non-null (or `tag` non-null with `pr` null), and `deployState` `done` or `none` | `run` deletes the file before `create` and reports `legacy: deleted` |
| `in_flight` | any other object of that shape | `preview` and `run` refuse `legacy_release_in_flight` (exit 3, repair `release.legacy.finish`); `status` reports it |
| `unreadable` | not that shape | refused the same way. Nothing proves it is not in flight |

The repair says to finish the release with the retained previous generation's ship-release, or to
remove the file once the user confirms the release is abandoned. That removal is a human action,
never the driver's.

### 7. Status, the administrative operation (per D3)

`release transaction status` is read-only. It applies the resolve, selection and main-checkout
gates of section 1. It reports the legacy and shape gates in `legacy` and `shape` rather than
refusing on them, so an operator can always inspect. It exits 0 once those gates pass. The output
is:

```text
{schema_version: 1, profile, legacy, shape, release}
```

`release` is null when no transaction exists. Otherwise it describes the current one:

```text
{transaction_id, ordinal, state, parked_from, version, commit, actions,
 grants, evidence_ids, terminal, receipt, hazard_markers}
```

- `actions`: one entry per action, `{name, operation, effect, status, attempts, reference}`.
- `grants`: `{grant_id, authority_class, valid}`.
- `terminal` and `receipt`: the core's `terminal` view and `read_receipt` of its digest.
- `hazard_markers`: one entry per concurrency key.

This is the skill's re-entry question ("ask the core first") and the operator's inspection.

### 8. The skill (per D9, D10)

**What `SKILL.md` keeps:**

- the frontmatter, with the description updated;
- `## Ownership` and its dispatch marker, verbatim;
- one resolve paragraph;
- an authorization section: invoking authorizes the reversible set, the preview is the one stop,
  silence is never yes, and a delegated owner returns at the preview;
- doc-grounded escalations;
- pre-flight: the main checkout, a clean tree, a fetch, local sync with origin, and "nothing to
  release" against the previous tag;
- `release transaction status` first, with a nonterminal release going straight to the preview;
- the changelog phase (`CHANGELOG.md` rubric, the `--merged` previous-tag command, the bootstrap
  `v0.1.0` rule, no silent `v1.0.0`);
- the notes file written outside the working tree;
- one bounded CI wait when the preview reports `verification_pending`;
- the preview stop;
- `run`, re-run on `next: wait` or after a confirmation;
- a report rendered only from `status`. A parked release is reported with its reason, never as
  released. Its menu offers resume, plus `abandon` when no action took effect;
- in `## Ownership`, the delegated owner's return at the preview (section 4).

**What it deletes:**

- durable release state;
- gh hygiene;
- Phase 0 item 0 and its resume table;
- the open-PR and CI-on-PR items;
- Phase 2 (open PR) and Phase 4 (merge), per D1;
- 4.5a–4.5g;
- Phase 5;
- the tracker-free route;
- the `--auto` clause.

**`CHANGELOG.md`.** Its rubric and template are unchanged. Two of its references point into
deleted `SKILL.md` sections: the `§5d` deploy-verification line, and the
`#45d-decide-major--minor--patch` anchor. Both are repointed to the new version heading or dropped,
together with their contract pin, in the same commit (the-bar "Moves keep their history").

**Instruction load.** The `ship-release` and `release-owner` ceilings in `instruction-load.json` are
tightened in the same change.

**Evals.** `evals.json` keeps its four plan-only cases, rewritten for the new contract:

- a nix-config preview naming two confirmations, with the stop on silence;
- re-entry through `status`;
- the legacy in-flight refusal;
- a two-branch refusal.

The sandbox pipeline case now proves the tracker-free refusal and asserts that no tag is created.

### 9. Documentation

- `python/README.md` gains a `## Release driver` section: the four subcommands, the gates, the
  store and key, the receipt, the tokens and the legacy classes. The sentence that no adapter
  `invoke` is reachable from any command becomes "reachable only through `release transaction
  run`, which drives the core".
- `home/common/claude-code/README.md`, the guard and `CLAUDE.md` do not change. The forge adapter
  still runs the guard before each mutation (#124 D9), and a core grant never overrides it
  (#116 D1).

## The eight #90 divergences

| # | Divergence | Where it holds | Check |
|---|---|---|---|
| 1 | `activation_not_applicable` receipt | §5 evidence entry | run test: the entry exists before `proving` for nix-config's profile |
| 2 | can park `proof_did_not_converge` | core `settle_proof`; §5 one cohort | fixture world whose `publication_visible` never satisfies parks; `status` never reports it released |
| 3 | silence is not yes | §4–5 tokens | `run` with no or partial `--confirm` exits 3 and creates no transaction |
| 4 | unadopted repository cannot use the path | §1 `--require release` | resolver refusal byte for byte |
| 5 | CI failure burns no SemVer | §3 before `create` | failed or pending checks: exit 3, no creation key |
| 6 | core owns recovery after creation | §2, §5, §7 | crash matrix (Test seams) |
| 7 | `rolled_back` unreachable, surfaced by lint | #124 admissibility `rolled_back_reachable` | existing compiler and conformance tests stay green |
| 8 | provider deploys need a bounded-spend grant | #124 D4 grammar refuses `reversible_bounded_spend`; the driver adds no path around it | existing grammar test stays green |

## Acceptance mapping

| # | Criterion | Deterministic verification | Kind |
|---|---|---|---|
| 1 | No state spec or resume table in the skill; state core-owned and inspectable | Contract test: `SKILL.md` names no `.superpowers/workflows` path and no state field, and holds exactly the `release transaction` argv examples (`status`, `preview`, `run`, `abandon`). A command test runs `status` on a store with a nonterminal release and shows its state, actions and grants | code |
| 2 | One preview, both confirmations, unanswered does not proceed | nix-config-profile command test: `preview` lists exactly `tag` and `github-release`. `run` without tokens, with one token, or with a stale token exits 3 and leaves the store root absent | code |
| 3 | Merge done, tag interrupted, resume without re-merge or double tag | Library seam, fixture CAS forge: the merge is satisfied, then the tag effect raises after its provider mutation. Clock moves past the TTL, then a fresh preview and `run`. The world log shows one merge and one tag mutation, and the transaction ends `succeeded` | code (merge arm is fixture-only, per D2) |
| 4 | Failing release CI leaves no reserved SemVer | Verification world with a failed, then a pending, required context: `run` exits 3, no creation key exists, and the next `run` with passing checks takes ordinal 1. Also, a first action refused by the guard parks with no effect; `abandon` ends it `abandoned`, and the same version previews as runnable again. `abandon` after a satisfied tag exits 3 | code |
| 5a | Entry context −40% against a fresh base | `instruction_load report --base 0a25b80 --head <candidate> --format json`: hot bytes of `ship-release` and `release-owner` ≤ 17,698 (base 29,498 / 4,271 words, measured 2026-11-02). Instruction Budget green | evidence |
| 5b | #70 bundle `approved` | Committed trials manifest plus the bundle `just agent-gate-bundle` prints for it. It reads `unmeasured`, and approval needs paired live trials in both strata, so this row stays `human_pending` and the issue is held, not closed, at delivery (D11) | human |
| 6 | Cutover refuses while legacy state records an in-flight release | Command tests for the in-flight and unreadable files (exit 3, file untouched, no store root), the completed file (deleted by `run`, never in the store) and the absent file | code |
| 7 | Package 1 drives from the compiled profile with one preview collecting both confirmations | rows 2 and 1, plus a test that `run`'s action order and parameters are `bind_candidate`'s | code |
| 8 | Package 2 covers interruption and retry for merge, tag, Release and deploy, observing postconditions first | crash matrix (Test seams): merge (fixture), tag and Release (forge world), deploy (fixture activation unit) | code |
| 9 | Package 3 deletes legacy state only after proving none in flight, and reports context reduction | rows 6 and 5a | code + evidence |
| 10 | Each package passes the review-package feasibility check and keeps the eight divergences | `review-feasibility gate` per package boundary in the plan; the divergence table checks | evidence |
| Demo | A dry-run nix-config release reaches the preview naming both irreversible actions; the legacy spec and resume table are gone | Ship-time, read-only: `release transaction preview --repo-root <main checkout> --commit <main tip> --version <next> --title … --notes-file …` on nix-config prints both confirmations, plus row 1's contract test | evidence |

## Test seams

- **The `release` command from source** (`python -m agent_tools.release transaction …`). It runs
  against a temporary main checkout with `tests/forge_world.py`'s fake `gh`, `git` and
  `claude-bash-lifecycle-guard` on `PATH`. The fake `gh` is extended with the three verification
  reads, which stay outside the forge spelling fixture because they are not adapter spellings.
  Prior art: `tests/test_release_command.py` and `tests/test_forge_adapter.py`.
- **The driver library** with injectable dependencies, against the real `TransactionStore`.
  Prior art: `tests/test_release_adapter_core.py` and the #206/#207 core tests. Fixture adapters
  are descriptor data plus a world:
  - the injectable inputs are the adapter registry (the #124 `compile_profile(adapters=…)` seam),
    the clock and the git common dir;
  - a `materialize` merge whose world applies the merge only when the default tip equals its
    configured expected tip, which is atomic in the fake;
  - an activation unit for deploy.
- **The crash matrix.** A crash is an effect wrapper that delegates to the real or fixture adapter
  and raises after the provider mutation. The core leaves the intent open, the injected clock
  passes the custody TTL, and a new `run` resumes. Assertions use the world's mutation log and the
  core snapshot: one effect per action, each postcondition inspected before the next action, a
  retry only with a fresh token. Cases run per arm: merge, tag, Release, deploy.
- **The skill contract** (`test_ship_release_contracts.py`). It keeps the executable `--merged`
  previous-tag check and the evals-shape check. It replaces the deleted-phase pins with pins on the
  `release transaction` argv examples, the `resolve-project` argv and the dispatch marker
  (agent-helpers rule 6).
  It adds no English-phrase pin.
- **Measurement.** `instruction_load report`/`check` and `agent_gate_bundle` over the committed
  manifest.

No seam below these is introduced.

## Out of scope

- **Forge `pr_merge` invoke** and any real merge arm, including the PR-number and base-tip
  candidate members it would need. These wait on #116 D7's accepted, natively certified target-tip
  CAS.
- **Binding `github-actions-health` or any other adapter as a profile activation**, which #465
  handed to this migration. This includes spend grants and a `railway` adapter.
- **Host activation (`just switch`)**, host scheduling and capability adaptation (#150), and a real
  live release.
- **Disposition commands other than `abandon`**: `dispose_failed`, recovery and roll-forward. A
  release parked after an effect stays the target's blocking release until a resume succeeds.
- **`evals.json` conversion to `pipeline` mode** (#90 tier 1), paired dry-run plan equivalence,
  and any `agent-cost-record` campaign.
- **Unrelated cleanups.** The `release deploy inspect` command stays, though ship-release no longer
  calls it, and `bindings.deploy` with it until #130 retires them. Neither `CHANGELOG.md`'s rubric
  nor nix-config's profile changes: the Release stays `irreversible` (#124 D6).
- **Two-branch and deploy-watched projects.** Nodo- and JarBird-shaped releases are refused by the
  new path until those arms exist (D1). Their fleet cutover is #130's human gate.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The core path runs only shapes the closed registry executes today (forge-only, single-branch). Integration ≠ default without a `materialize` action, any `bindings.deploy` adapter, or no forge is refused at entry with a typed refusal and repair. The tracker-free route and the release-PR phase are deleted rather than kept with no runnable merge. Consequence: two-branch or deploy-watched projects (Nodo, JarBird) cannot release through ship-release after this skill is installed until a certified merge arm and an activation binding exist | #90 no dual mode and divergence 4; #71/#69 no fallback; #116 D9 (an unfinished arm stays unsupported); the-bar no half-wired path | Keeping legacy prose for unrepresentable shapes (dual mode). Merging skill-side before the transaction (moves the merged-untagged window back outside the core, against #90 and AC3). Keeping release-PR prose that can never merge |
| D2 | Forge `pr_merge` invoke stays `unsupported`/`target_cas_unproven`. The driver's `materialize` handling is generic and proven with a CAS-atomic fixture adapter. This reverses the Phase-0 suggested default | #116 D7 (head match, precheck or post-merge detection is not target CAS; a mechanism needs explicit acceptance and native certification) and D8 (fixtures cannot certify); #124 D8 | Enabling it on `--match-head-commit` plus strict protection: a self-granted acceptance of a human-required security decision with no native proof |
| D3 | One new area `release transaction status\|preview\|run` on the existing `release` command, over three new modules (driver, verification, cutover). No command-table row or core change. Adapter `invoke` stays reachable only through the core, now driven by `run` (refines #124 D15). `status` is the administrative operation | agent-helpers rules 1–2; #85 administrative inspection; the-bar token economy and single responsibility | A second top-level release command. Exposing core operations piecemeal to the skill, which would re-grow orchestration prose |
| D4 | Store root `<git common dir>/agent-release/store`. Creation key `release/v1:<project>:<profile>:<n>`, found by probing `lookup`. Only the latest may be nonterminal. Creating `n + 1` reserves the version and is refused when any earlier transaction holds it, so a reserved version is never reused | #82 one ledger; #81 reserve before the first effect; attempt-delivery `:<n>` key precedent; launch-scope's common-dir registry | The version in the key (re-entry cannot find a release whose version it does not know). A pointer file (a second ledger). Listing store directories (reads core layout). A `.superpowers/` root (needs gitignore handling and the main checkout) |
| D5 | The driver observes the candidate itself: live integration tip, protection's required contexts, and check runs. It refuses before `create` unless `passed`, then seals the canonical receipt as `event` evidence before `ready`. Local `just build` is not receipt content | #90 receipt (candidate, scope, versions, result, time); #88 CI is content, not activation proof; #116 D6 floor; #339 canonical-text evidence; the-bar defense in depth | A skill-supplied result sealed by a utility (agent self-report). A new `transaction_*` function (event evidence already exists; risk path). A separate receipt file store. Recording an exit code the tool cannot observe |
| D6 | One token per irreversible action not last seen `satisfied`, digesting plan, action, next attempt and next acquisition. `run` is all-or-nothing on the exact set, issues each token as a core grant (`human`, `release-irreversible`) plus one `release-scope` grant, and checks the matching grant under the held fence before each irreversible invoke. A retry or a crash re-entry needs a fresh preview | #84 one-action, single-use, named confirmations and its recovery/extra-attempt voids; #90 one preview, two grants, silence not yes; core grants are fence-bound | One combined confirmation (cannot name each target). A second stop after the first irreversible action (#90's corrected over-read). Carrying grants across a re-acquisition, which the core voids |
| D7 | One `run` invocation is one bounded pass: acquire, inspect, grant check, invoke in topological order, gates, `activation-not-applicable` evidence, at most one proof cohort, release custody. It returns `next: done\|confirm\|wait\|attention`. A divergence or refusal parks `attention_required`. No disposition commands | #206 inspect-before-retry; #207 only `settle_proof` seals; #90 divergences 1–2 and "parked is never released"; #150 owns cadence | A long-lived polling driver (host cadence). Disposition and recovery commands (no criterion asks; YAGNI) |
| D8 | The legacy file is classified `absent \| completed \| in_flight \| unreadable` per repository at every driver entry. `in_flight` and `unreadable` refuse everything. `run` deletes `completed` before `create`. Nothing is imported | #90 delete, never import; blocked while in flight; residue is a blocker; #82 quiescent upgrade | A translator into the core (#82). A check at home-manager activation (it cannot see each repository's checkout). Deleting an unreadable file |
| D9 | `SKILL.md` keeps preparation and narrative only (section 8). `CHANGELOG.md` is untouched. Evals stay plan-only and are rewritten to the new contract. The sandbox case proves the tracker-free refusal. Deleted-phase pins go with their phases, and no new phrase pin is added | #90 deletion list; agent-helpers rule 6; Phase-0 Q5 (no criterion needs `pipeline` conversion) | Converting evals to `pipeline` now (new work, no criterion). Leaving evals that grade deleted phases |
| D10 | Entry context is measured by `instruction_load report` on the `ship-release` and `release-owner` hot sets. The target is ≤ 60% of the 29,498 bytes measured at `0a25b80`, so `SKILL.md` must come in under about 9.5 KB. Ceilings are tightened in the same change | Issue AC5 "fresh measurement"; the instruction-load model is the repository's entry-load measure; the Instruction Budget gate needs ceilings within 5% | #90's line counts. A unit test pinning the base figure |
| D11 | The #70 evidence is a structurally valid trials manifest (four core classes, empty strata, commits bound) plus exactly the `unmeasured` bundle `just agent-gate-bundle` prints. AC5's approval stays `human_pending`, and delivery holds the issue open | #127 D17/D31; #70 forbids hand-authored records; #130 needs a fresh approved cutover bundle anyway | Hand-authored records or an approved bundle (fabrication). Running paired claude and codex live trials of real releases inside the attempt |
| D12 | Crashes are simulated in process: an effect wrapper raises after the provider mutation, and an injected clock passes the TTL. Verification reads extend `forge_world`'s fake `gh` but stay outside the adapter spelling fixture | Core contract: whatever an effect raises propagates and leaves the intent open; #124 D12 (the fixture pins adapter spellings only) | Killing a subprocess mid-call (timing-flaky). Adding non-adapter reads to the shared fixture |
| D13 | Selection is the sole publication profile, else `--profile`. Several with no argument refuses `profile_ambiguous`. nix-config's profile is unchanged, so its preview confirms tag and Release (#124 D6, though #90 classed the Release reversible) | #90 profile selection; #85 a child release selects one profile; #124 D6 | Picking the first profile. Reclassifying the Release now (a contract change no criterion needs) |
| D14 | Grill. Add `release transaction abandon`, which advances a nonterminal release to `abandoned` only where the core's no-effect gate allows, run on the user's explicit word. An `abandoned` transaction's version may be reserved again. Reverses D7 in part (one disposition command) and refines D4 | Without it, a guard denial or failed precondition on the first action parks a no-effect release that blocks the target and burns a version forever. The core's `abandoned` gate proves no effect; #81 burns only versions that were published | No exit, so the target is blocked until someone hand-edits the store. Auto-abandoning in `run` (a terminal decision no human made). Wrapping `dispose_failed` too (needs observability grounds; no criterion) |
| D15 | Grill. `run` and `abandon` refuse `cwd_mismatch` unless the working directory's top level is `--repo-root` | #124 D23: forge invoke takes its checkout from `git rev-parse --show-toplevel` in the working directory, and the guard judges that cwd | Changing directory inside the library (a hidden side effect). Trusting the caller's cwd (the tag would be prepared in the wrong checkout) |
| D16 | Grill. The store is host-local. A cross-host race on one target is arbitrated only by the provider's create-if-absent atomicity: the same candidate converges, and a different candidate parks `diverged` | #124 §7 provider-atomic `index` creation; the legacy path had the same scope | A shared or remote store (a new distributed-ledger problem, #82). Claiming cross-host exclusion the key lease cannot give |
| D17 | Grill. Tokens are stable while their inputs are unchanged. A delegated owner ends at the preview, and the controller relaunches one owner that re-previews and runs only on matching tokens. The notes file lives outside both working trees | Divergence 3 (a delegated release stops once at the preview); `## Ownership`'s single owner per launch; D6 tokens | Splitting ownership so the controller calls `run` itself. Carrying tokens in the controller without a re-preview, which would let inputs drift unseen |
| D18 | Plan. Every driver refusal prints `{"error":{"code","repair_id","detail"}}` with exit 3 (`repair_id` null where the spec names none). `preview` instead reports a refusal met after its plan is derived (verification, stale candidate, reservation) inside its own document, with confirmations still listed. The closed code set adds `profile_inadmissible`, `candidate_required`, `candidate_invalid`, `no_release` and `abandon_refused` | Spec §1 closed error; the-bar fail loud; the demo must name both confirmations whatever CI reads | Reusing the resolver's exit-2 `violations` envelope (conflates a tool fault with a refusal). Hiding confirmations while CI is pending |
| D19 | Plan. Gate 1 reads the filesystem, with no git child: a main checkout is a `--repo-root` whose `.git` is a real directory, which is also the common dir; the working directory's top level is its nearest ancestor holding a `.git` entry | Spec §1 gate semantics; command tests put a fake `git` first on `PATH` (forge_world); the forge adapter's own `--show-toplevel` stays the effect-side check (#124 D23) | `git rev-parse --git-common-dir` (one more child every command test must fake, and a child process for read-only `status`) |
| D20 | Plan. The driver drives every adapter alias through one router over per-alias `core_binding`s, choosing the binding by an action's `parameters.action` and an observation's `collector`. Fixture, flip and crash adapters enter only as registry entries. Refines D12 | `core_binding` binds one alias; #124 D5 descriptor pinning; spec test seams (registry injection) | A driver-side test hook (a seam below the agreed ones). One binding per profile (cannot drive a merge alias beside the forge) |
| D21 | Plan. `run` and `abandon` release custody on every normal return and never in a `finally`, so an exception leaves custody to lapse at its TTL, as a crashed process would | D12; the core leaves a raised effect's intent open; §5 "custody is released before `run` returns" | A try/finally release, which turns a simulated crash into a clean release and hides the TTL path from the matrix |
| D22 | Plan. A required context is judged by its matching check run with the largest `id`. One page of 100 check runs is read, and a `total_count` above 100 refuses `verification_unavailable`. A context with no run is `missing` (result `pending`) | D5; #116 D6 floor; the-bar fail closed | Any-success across re-runs (a later failure would be hidden). Paginating (unbounded reads under the 30-second budget) |
| D23 | Plan. AC10's per-package check is `review-package <plan> <package base> HEAD <out>` printing `"state":"complete"` at each package's last task, as #127 ran it. The plan carries no forecast blocks. Refines the acceptance mapping's row 10 | #127 plan precedent; the installed writing-plans and sdd contracts carry no projection step; an actual measurement is the stronger proof | `review-feasibility gate` over hand-authored byte forecasts (a projection of what `review-package` measures, adding no proof) |
| D24 | Plan. The #70 trials manifest binds base `0a25b8072c8252d069774f68e75981c39c137691` and, as candidate, the skill-rewrite commit that AC5's measurement reads, in #127 D31's shape | D11; #127 D31 | Binding the evidence commit itself (a commit cannot name its own hash) |
| D25 | Plan. `status`'s `release` also carries `reason`, the latest transition's reason, so §8's parked report has a core source. `run`'s `actions` entries are `{name, status, attempts}`. The resume `candidate.title` is read from the stored plan's first unit that carries a title | §8 "reported with its reason", rendered only from `status`; §5 output | A skill-side reason (narrative state outside the core). Re-reading the title from the notes file (it does not carry one) |
| D26 | Plan. A compiled profile with any `restorable` recovery unit is refused at entry as `anchors_unsupported` (repair `release.profile.anchor_unbound`), a fifth shape gate. This narrows §5's `verify_anchors` step. `core_binding` observes only derived predicate requests, so an anchor request cannot be answered, and no operation in the closed registry is recovery-capable, so no admissible profile is restorable today | `release_adapter.CoreBinding.observe`; the registry's descriptors; D1's typed refusal for unrunnable shapes; the-bar no half-wired path | Calling `verify_anchors` through a binding that refuses its requests (a certain mid-run failure). Extending `core_binding` (out of this change's scope) |
