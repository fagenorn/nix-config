# Forge `pr_merge` invoke under the owner-accepted strict-protection merge — issue 554

Design for [#554](https://github.com/fagenorn/nix-config/issues/554), 2026-11-02, against main
`e692c96`. Written in autonomous mode (`from-issue --auto`). The one human decision it rests on is
the owner's, recorded in the issue body on 2026-11-02: merging the release PR with
`gh pr merge --merge --match-head-commit <bound head>` under strict required-check protection is the
accepted target-tip mechanism that #116 D7 and #128 D2 reserved. Every other choice below is an
agent judgment inside the issue's scope, recorded in the decision ledger. None of them is a human
answer, grant or irreversible confirmation, and none waives #116 D8's native certification.

The binding records are the #116 guard/core decision
(`2026-09-20-issue-116-permission-guard-core-design.md`), the #124 profile and forge adapter design
(`2026-10-09-issue-124-release-profiles-forge-adapter-design.md`) and the #128 release core design
(`2026-11-02-issue-128-ship-release-release-core-design.md`). This spec cites their ledgers and does
not restate them.

## Triage

### Lane triage
Input: {"signals":{"contract_change":{"value":"hit","evidence":"forge adapter descriptor flips pr_merge invoke to supported, adds candidate members (PR number, expected base tip) and a new guard-admitted gh pr merge spelling"},"concurrency_or_persistence":{"value":"hit","evidence":"target-tip CAS race semantics and crash-resume between merge and tag over the persisted release transaction"},"open_design_questions":{"value":"hit","evidence":"issue leaves open who opens the release PR (core action, index action or skill) and how the tag retargets to the merge commit"},"criteria_shape":{"value":"hit","evidence":"five criteria, including native certification against a real sandbox GitHub repository that no deterministic code check verifies"}},"paths":["python/agent_tools/forge_adapter.py","python/agent_tools/release_driver.py","python/agent_tools/release_adapter.py","python/agent_tools/release_profile.py","python/agent_tools/release.py","home/common/claude-code/lifecycle_guard.py","python/agent_tools/guard_policy.py","tests/forge_world.py","tests/test_forge_adapter.py","tests/test_release_command.py","tests/fixtures/forge-adapter-spellings.json","home/common/agent-skills/skills/ship-release/SKILL.md",".agents/artifacts/evidence/release-554-native-certification.json","python/README.md"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

The triage predicted edits to `lifecycle_guard.py`, `guard_policy.py` and `release.py`. The design
changes none of them: the guard's release arm already admits the rendered spelling (per D5), and the
command surface is unchanged. It adds `release_verification.py` and a certification harness under
`tests/` (per D3, D10).

## Problem

Since #128, a project whose integration branch differs from its default branch cannot release.
`release transaction preview` refuses `merge_not_declared`, because the only merge operation, the
forge adapter's `pr_merge`, is `unsupported`/`target_cas_unproven` and a profile cannot name it.
JarBird (`dev` into `main`) is the waiting consumer. Its operator today has no tool path from a
verified `dev` tip to a tagged release on `main`.

The owner has now accepted the merge mechanism. Three things are still missing:

- the adapter cannot merge, and nothing binds which PR, which head and which base a merge means;
- the tag of a merged release would point at the integration tip, not at what landed on `main`;
- no evidence shows that GitHub really refuses the races the mechanism relies on.

## Solution

`pr_merge` becomes a supported `materialize` operation. A two-branch release is one transaction
whose plan is `pr_merge`, then `tag`, then `github-release`, all three irreversible and confirmed at
the one preview (#128 D6).

- **The candidate carries a merge binding.** A profile with a merge action binds
  `merge: {pr, base_tip}` into the candidate at creation, beside `version` and `commit`. The driver
  observes both values itself at preview. The skill opens the release PR when the preview reports
  none (per D1, D2, D3).
- **The merge** is `gh pr merge <pr> --repo <slug> --merge --match-head-commit <commit>`. It runs
  only after a read of the target's protection proves strict required checks with admin
  enforcement, and after prechecks of the head auto-delete setting, the PR and the base tip (per
  D4, D5, D6, D13).
- **The tag targets the merge commit.** With a merge binding, the forge adapter resolves the
  released commit as the release PR's merge commit, whose parents must be exactly
  `[base_tip, commit]`. A crash after the merge resumes by inspecting the PR as `MERGED`; it never
  merges again (per D7, D8).
- **Native certification** runs a scripted harness against one public sandbox repository and
  commits its evidence (per D10, D11).

The transaction core, the lifecycle guard, the `release` command's argv and nix-config's own profile
are unchanged.

## Decisions

### 1. The candidate's merge binding (per D2)

**Descriptor.** `pr_merge` becomes `support: supported`, `reason: null`, still `materialize`,
`pointer_cas`, `irreversible` and not recovery-capable. Its `candidate_members` is `["merge"]`. The
adapter contract's closed candidate-member set becomes `merge`, `notes`, `title`.

**Two kinds of candidate member.** `notes` and `title` keep binding into the parameters of the unit
that consumes them (#124 D19). `merge` is an identity member. When any node of a compiled profile
consumes it, the candidate must carry it, and it binds into the subject's `candidate` and into every
unit's `candidate`. It must be there because it fixes the released commit for every action after the
merge. When no node consumes it, a candidate that carries `merge` is refused. So a single-branch
profile, or the fixture merge of #128's matrix, binds exactly what it binds today.

**Shape.** `merge` is exactly `{pr, base_tip}`: `pr` is a positive integer (not a boolean) and
`base_tip` is 40 lowercase hex digits. `bind_candidate` validates it, and so does the forge adapter's
parameter check.

**`pr_merge` parameters.** They become `{action, operation, target, candidate, config}`, the shape
every other forge operation has. The merge's expected head is `candidate.commit`, the verified
integration tip. The old top-level `pr`, `expected_base_tip` and `expected_head` members are removed,
including from `release adapter inspect github-forge pr_merge --parameters`. For `tag` and
`release`, a `candidate` with or without `merge` is valid. For `pr_merge`, a candidate without
`merge` is `invalid_input` on invoke and `parameters_invalid` on inspect.

**Surfaces.** The preview document's `candidate` gains `merge`, which is `null` when the profile has
no merge. In `new` mode, the `plan_digest` candidate input covers it. A resumed preview reads it
from the stored subject. The schema version stays 1, because the member is additive.

### 2. The release PR and the preview's merge observation (per D1, D3)

**Who opens the PR.** The skill opens the release PR before the preview that needs it (per D1). The
driver never opens one: preview is read-only, and `run` makes no mutation outside the core.

**What the driver observes.** In `new` mode, when the profile consumes `merge`,
`release_verification.observe_merge` runs before the receipt reads. It makes three `gh api` reads
under its own `READ_BUDGET_SECONDS` deadline, with the token variables removed:

1. `repos/<slug>/pulls?state=open&base=<default>&head=<owner>:<integration>&per_page=2`.
   - An empty list refuses `release_pr_missing`.
   - Two entries refuse `verification_unavailable`. GitHub allows only one open PR per head and base
     pair.
   - Otherwise `pr` is the entry's `number`. Its `head.sha` must equal `--commit`, else the read
     refuses `release_pr_stale`.
2. `repos/<slug>/git/ref/heads/<default>`. Its `object.sha` is `base_tip`.
3. `repos/<slug>/compare/<base_tip>...<commit>`. Its `status` must be `ahead`. Anything else refuses
   `release_pr_behind`, whose detail names the status and says to merge `<default>` into
   `<integration>`, push, wait for CI and preview again. Strict protection would refuse such a
   merge at the provider anyway, so the driver refuses it before a doomed transaction reserves a
   version.

Any failed, timed-out or malformed read refuses `verification_unavailable`.

**How a refusal surfaces.** Each refusal is the preview's `refusal`, in its document, with the
confirmations still listed (#128 D18). Its `repair_id` is null. When `observe_merge` refuses, the
receipt is not read and `verification` is null.

**Order and drift.** The merge observation comes first because a PR-triggered CI never starts
before the PR exists. With the receipt first, its pending check would never clear. `run` re-derives
the plan, so a base that moved between preview and run changes `plan_digest` and refuses
`confirmation_stale`. Every confirmation therefore names the base the user saw.

### 3. `pr_merge` invoke (per D4, D5, D6)

`invoke` keeps the adapter's invariants: at most one provider mutation, no retry, the token variables
removed from every child, the guard verdict before the mutation, and only
`accepted | rejected | unknown` returned (#124 §7, D9, D23). The `pr_merge` steps run in this order
and stop at the first refusal:

1. **Request shape.** `merge` is present and the parameters are well formed.
2. **Working checkout and same repository.** Unchanged (#124 D23).
3. **Protection floor.** One read with the `pr_merge.protection` spelling, parsed by the same
   function that produces inspect's protection facts. That parse gains `strict`. The floor holds
   only when all of these are true:
   - the answer is 200;
   - `required_status_checks.strict` is `true`;
   - `required_status_checks.contexts` is non-empty;
   - `enforce_admins.enabled` is `true`.

   Otherwise the result is `rejected`/`precondition_failed`, with reference
   `protection_floor_unmet: <member>`. The member is the first one unmet, in the order
   `unprotected` (404), `inaccessible` (403), `strict`, `required_contexts`, `enforce_admins`. A
   failed read is `rejected` with `transient_transport` or `provider_unavailable` (#124 D23). This is
   the issue's precondition: neither the guard nor the provider is reached.
4. **The head survives.** One read, `gh api repos/<slug> --jq .delete_branch_on_merge`, must print
   `false`. Otherwise the result is `rejected`/`precondition_failed`, with reference
   `head_auto_delete_on`, because GitHub would delete the permanent integration branch after the
   merge (#116 D5, per D13).
5. **The PR.** One read with the `pr_merge.view` spelling. The state must be `OPEN`,
   `baseRefName` must equal `target.branch`, and `headRefOid` must equal `candidate.commit`.
   Otherwise the result is `rejected`/`precondition_failed`, with a reference naming which check
   failed. A `MERGED` PR is refused here too, so a stray invoke can never merge twice.
6. **The base tip.** One read with the `pr_merge.base_ref` spelling. The tip must equal
   `merge.base_tip`, else `rejected`/`precondition_failed`, with reference `base_moved: <tip>`. This
   narrows the race window. The compare-and-swap itself is GitHub's strict rule (D4, D7).
7. **Render.** The argv is `["gh", "pr", "merge", "<pr>", "--repo", "<slug>", "--merge",
   "--match-head-commit", "<candidate.commit>"]`. The raw text is the same words joined by single
   spaces, and `shlex.split(raw) == argv` is asserted. The adapter renders no `--subject`,
   `--admin`, `--auto`, `--delete-branch`, `--squash` or `--rebase`.
8. **Enforcement.** The real `claude-bash-lifecycle-guard` judges the raw text, as for every forge
   mutation (#124 D9).
9. **The mutation**, once:
   - exit 0 is `accepted`, with reference `https://github.com/<slug>/pull/<pr>`;
   - a spawn failure is `rejected`/`provider_unavailable`;
   - a timeout or any non-zero exit is `unknown`/`transient_transport`. The adapter parses no
     refusal text (D6). The core inspects within the same `invoke_action` call, so the PR's state
     decides the action's status.

### 4. `pr_merge` inspect and inspect-before-retry (per D7)

The #124 D8 reads and rules stand, with the expected head now read from `candidate.commit`:

| PR state | Outcome |
|---|---|
| base differs from `target.branch` | `diverged`/`base_mismatch` |
| `OPEN` | `absent` |
| `CLOSED` | `diverged`/`pr_closed` |
| `MERGED`, parents exactly `[merge.base_tip, candidate.commit]` | `satisfied` |
| `MERGED`, any other parents | `diverged`/`merge_parents_mismatch` |

The facts gain `protection.strict`. Recovery after a crash is the core's ordinary path:

- an open intent forces inspection before any retry (#206);
- `satisfied` moves the driver to the tag;
- `absent` after an attempt parks `attention_required` with no effect, so `abandon` stays available
  (#128 D14);
- a retry needs a fresh preview and token, and step 6's base check refuses a retry whose bound base
  has moved, before any provider call.

A second host racing the same release meets GitHub's single merge. Its precheck refuses `MERGED`,
or its merge fails, and its inspect reads `satisfied` (#128 D16).

**The park names the refusal (per D12).** When an action is not `satisfied` after an invoke whose
result was not `accepted`, the driver's park reason is
`<action>: <status> after <result> <error_class>: <reference>`. It reads that from the action's
latest `invocation_returned` event. `status` reports the reason (#128 D25), so the skill's report
shows, for example, `protection_floor_unmet: enforce_admins` instead of a bare `absent`. This holds
for every operation the driver invokes.

### 5. The tag targets the merge commit (per D8)

**The released commit.** Without `merge` it is `candidate.commit`, which is today's behaviour. With
`merge` it is the release PR's merge commit, and only when the PR is `MERGED` into `target.branch`
with parents exactly `[merge.base_tip, candidate.commit]`. One helper resolves it from the
`pr_merge.view` and `pr_merge.merge_commit` reads. The same helper decides `pr_merge`'s
`satisfied`, so the two can never disagree.

**Inspect.** `tag` and `release` read the tag first, exactly as today. They resolve the released
commit only when a tag exists, then compare the peeled tag with it. A tag that exists while the
released commit cannot be resolved is `diverged`/`tag_target_mismatch`.

**Invoke (`tag`).** After the same-repository proof, the adapter resolves the released commit. If it
cannot, the result is `rejected`/`precondition_failed` (`release PR not merged as bound`). It then:

1. checks containment with `repos/<slug>/compare/<released>...<branch>` (`identical` or `ahead`);
2. runs `git fetch --no-tags origin refs/heads/<branch>` in the checkout. This is local
   preparation, and a failure is a refusal (#124 D23);
3. creates or reuses `git tag -a <tag> <released>`;
4. renders `git push origin refs/tags/<tag>` and pushes it unchanged.

The guard's tag-push arm is unchanged.

**Invoke (`release`).** Unchanged. `--verify-tag` binds it to the pushed tag.

`publication_visible` already maps through the effect inspection, so the proof judges the same
commit.

### 6. The guard (per D5)

`lifecycle_guard.py` does not change. Its merge release arm already admits
`gh pr merge <n> --repo <slug> --merge [--subject "<subject>"] [--match-head-commit <sha>]` for the
declared integration branch into the default branch. It still enforces its own checks: a fully green
rollup, a merge state other than `BEHIND`, and `--match-head-commit` equal to the PR head.

The shared spelling fixture gains:

- the mutation row `pr_merge.merge` at canonical values;
- the read rows for the head auto-delete setting and for the merged tag's compare.

The guard suite admits `pr_merge.merge` only in the distinct-integration class. It refuses the row
in the default-only and protection-inaccessible classes, where there is no declared integration
branch ("missing --delete-branch"), and in the other-owner class. The near misses refused are
`--admin`, `--auto`, `--squash`, `--rebase`, `--delete-branch` on the integration head, reordered
flags, a short or uppercase SHA, a missing `--repo` and a trailing segment. The floor lives in the
adapter's precondition (#116 D1 condition 3). The guard's release arm keeps its rollup gate for
native merges.

### 7. The skill (per D9)

`ship-release` Phase 3 gains one sentence. A two-branch preview that refuses `release_pr_missing`
opens the release PR once, with the guard's pr-create form:

```text
gh pr create --repo <slug> --base <default> --head <integration> --title "<title>" --body "<version>"
```

Here `<slug>` is `bindings.tracker.repo_slug`. The skill then re-runs the same preview. Every other
merge refusal is reported as printed, under the skill's existing rule.

The hot bytes of the `ship-release` and `release-owner` profiles stay at or below their ceilings,
16,997 bytes, which equals the measurement at `e692c96`. The sentence is therefore offset by
tightening existing `SKILL.md` prose, and `instruction_load check --base origin/main` passes with the
ceilings unchanged. Raising a ceiling needs the `instruction-budget-raise` label, which only the
user applies. If no offset keeps the skill's meaning, implementation stops at that human gate. The
evals, `CHANGELOG.md` and the description are unchanged.

### 8. Native certification (per D10, D11)

**The harness** is `tests/release_merge_certification.py`. It has no `test_` prefix, so no suite
collects it, and a `just` recipe runs it from source with `--scratch <dir> --output <file>`. It makes
live GitHub calls and nothing else in the repository runs it.

**The sandbox** is `fagenorn/release-merge-sandbox`, a constant with no override:

- **Visibility.** Public, because branch protection on a private personal repository needs a paid
  plan.
- **Creation.** When the repository is absent, the harness creates it with `gh repo create --public
  --add-readme` and a fixed description marker. When it exists without that marker, the harness
  refuses before any mutation, so it never mutates a repository it did not create.
- **Protection.** Every run first PUTs protection on `main`:
  - `strict: true`;
  - one required check, `release-merge-certification` (`app_id: -1`);
  - `enforce_admins: true`;
  - no review or push restrictions.

  It then reads protection back through the adapter's own parse and stops unless the floor holds.
- **The required check.** Commit statuses that the harness posts for the context on each head it
  pushes. No Actions workflow runs.
- **Lifecycle.** The repository is reused and never deleted; the keyring token lacks `delete_repo`.
  Each run uses fresh `cert-<run>-*` branches, works in a scratch clone under the launch-scope
  scratch directory, and closes the PRs it left open.

**The rows.** Each row opens a fresh head branch from `main`'s tip with one commit and a passing
status, and a PR into `main`. Before any merge attempt, it waits a bounded time for
`mergeStateStatus` to leave `UNKNOWN`, which is GitHub's asynchronous computation.

| Row | Setup | Attempt | Pass condition |
|---|---|---|---|
| a, base unchanged | bind head H and base B0 | the real adapter `invoke` from the clone, then `inspect`, then `invoke` and `inspect` again | first invoke `accepted`; inspect `satisfied` with parents `[B0, H]`; second invoke `rejected` (PR not open) with no new merge; second inspect `satisfied` |
| b, base moved to a commit the head lacks | bind H and B0, then merge a side PR so `main` moves to B1 ⊄ H | (b1) the rendered argv; (b2) the GraphQL `mergePullRequest` gh sends (`expectedHeadOid: H`, `mergeMethod: MERGE`), issued directly so gh's client-side precheck cannot be the refuser | both refused; PR `OPEN`; `main` still B1 |
| c, head mismatch | bind H, then push H′ to the head with a passing status | the rendered argv with `--match-head-commit H` | refused; PR `OPEN`; `main` unchanged |

**The guard in row a.** The adapter's `claude-bash-lifecycle-guard` is a recording shim, prepended
on `PATH`, that allows. The harness asserts that the recorded command equals the rendered spelling.
The real guard is not used, for two reasons:

- it would refuse every sandbox merge, because the sandbox declares no integration branch;
- in rows b and c, its own prechecks would refuse before the provider could.

The guard's admission of the spelling is certified hermetically (§6).

**Out-of-band mutations.** The harness mutates the sandbox, and only the sandbox, from a subprocess
the native hook never sees. It is launched openly through the Bash tool and launch-scope. If any
permission layer refuses that launch or a sandbox mutation, the attempt stops at a human gate.

**Evidence.** `.agents/artifacts/evidence/release-554-native-certification.json`:

```text
{schema: "release-merge-certification/v1", issue: 554, repository, actor,
 implementation: {commit, pr_merge_descriptor_digest}, protection: {strict, required_contexts,
 enforce_admins}, spelling, guard: "recording-shim",
 rows: [{id, pr, bound: {head, base_tip}, attempts: [{via: adapter|argv|graphql, outcome:
 accepted|refused, detail}], after: {state, base_tip, merge_commit, parents}, passed}],
 result: passed|failed, started_at, finished_at}
```

- `detail` is the first line of bounded stderr, or the GraphQL error `type` and message.
- No token, header or raw transcript is kept (#116 D8).
- `result` is `passed` only when all three rows pass.

### 9. Documentation

- **`python/README.md` § Release adapters.** It describes `pr_merge` as supported: the floor, the
  steps, the spelling and the merge-commit tag target. The sentence on `target_cas_unproven` goes.
- **`python/README.md` § Release driver.** It gains `merge` in the candidate, `observe_merge`, the
  three new refusal codes and the park reason of D12. The preview's provider reads now include the
  merge reads.
- **`home/common/claude-code/README.md`.** The guard/core paragraph's "future core admission waits"
  sentence now names this delivery: the adapter floor plus native evidence.
- **Point-in-time records.** The #116, #124 and #128 records keep their text. This spec's ledger
  carries the reversals.

## Race and denial matrix

Each "fixture" row is an adapter or driver test against `forge_world`. Each "native" row is a
certification row.

| # | Case | Expected | Proven by |
|---|---|---|---|
| 1 | `strict: false`, empty `contexts`, `enforce_admins` off, 404, 403 | `rejected`/`precondition_failed`, `protection_floor_unmet: <member>`; no guard call, no `pr merge` call | fixture (adapter) |
| 2 | protection read fails or times out | `rejected`, `provider_unavailable` or `transient_transport`; no mutation | fixture (adapter) |
| 3 | PR `MERGED`, `CLOSED`, other base, or head ≠ `candidate.commit` at invoke | `rejected`/`precondition_failed`; no mutation | fixture (adapter) |
| 4 | base tip ≠ `merge.base_tip` at invoke | `rejected`/`precondition_failed`, `base_moved`; no mutation | fixture (adapter); the provider-side race is row 6 |
| 5 | guard denies | `rejected`/`authorization_denied`; no mutation | fixture (adapter) |
| 6 | base moves to B1 ⊄ H between precheck and merge | provider refuses; the core inspects `OPEN` → `absent` → parks with no effect; `abandon` allowed | native b; fixture (driver: non-zero merge, PR stays open) |
| 7 | head moves between precheck and merge | provider refuses (`--match-head-commit`); same park | native c; fixture (driver) |
| 8 | merge exits non-zero or times out but landed | `unknown`; the same-call inspect reads `MERGED` → `satisfied`; tag follows | fixture (driver) |
| 9 | base moves to B1 ⊆ H inside the window | GitHub merges; inspect `diverged`/`merge_parents_mismatch`; parks after an effect, never tagged (D7) | fixture (adapter inspect) |
| 10 | crash after the merge mutation, before the tag | resume inspects `satisfied`, one `pr merge` in the log, tag created at the merge commit, `succeeded` | fixture (crash matrix) |
| 11 | no open release PR / PR head ≠ commit / head lacks base | preview refuses `release_pr_missing` / `release_pr_stale` / `release_pr_behind`; no store root | fixture (driver, command) |
| 12 | base moves between preview and run | `run` refuses `confirmation_stale`; nothing written | fixture (driver) |
| 13 | tag invoke before the PR merged | `rejected`/`precondition_failed`; no push | fixture (adapter) |
| 14 | tag present at the integration tip instead of the merge commit | `diverged`/`tag_target_mismatch` | fixture (adapter) |
| 15 | `delete_branch_on_merge` is on | `rejected`/`precondition_failed`, `head_auto_delete_on`; no guard call, no mutation | fixture (adapter) |
| 16 | the merge invoke is refused by the floor inside a `run` | the park reason ends `rejected precondition_failed: protection_floor_unmet: <member>`; `status` reports it; `abandon` succeeds | fixture (driver) |

## Acceptance mapping

| # | Criterion | Verification | Kind |
|---|---|---|---|
| 1 | A profile naming `pr_merge` compiles, and the shape check no longer refuses `merge_not_declared` | Grammar test: the forge descriptor pins `pr_merge` supported, and a JarBird-shaped profile (`pr_merge` → `tag` → `github-release` on one GitHub target, branch `main`) compiles. Driver test: with integration `dev`, `shape_refusal()` is `None` and the preview lists three confirmations | code |
| 2 | Invoke refuses before any mutation when protection lacks strict required checks | Matrix rows 1–2: each floor gap is `rejected`/`precondition_failed`, and the world log holds no guard call and no `pr merge`. Row 16: the parked release names the unmet member | code |
| 3 | A crash between merge and tag resumes with no second merge and tags the merge commit | Matrix row 10: the crash matrix over a real-forge two-branch profile. The world log shows exactly one `pr merge` and `git tag -a <tag> <merge_commit>`, and the transaction ends `succeeded` | code |
| 4 | The native certification evidence exists and passes | The harness run (§8) writes the evidence. An evidence test pins `result: passed`, all three rows passed, the sandbox repository, the spelling equal to the fixture's `pr_merge.merge` row with the sandbox slug, and the recorded `pr_merge` descriptor digest equal to the current one | native + code |
| 5 | Adapter and driver tests cover the race and denial rows with `forge_world` fakes | Matrix rows 1–16, each a named test | code |

## Test seams

- **The forge adapter in process** against `forge_world`'s fake `gh`, `git` and guard, as
  `test_forge_adapter.py` does. The world's canonical responses gain the protection `strict` member
  and the merge-landing answers.
- **The driver library** with registry injection over the real `TransactionStore` (#128 D20).
  `release_driver_support.StatefulForge` learns to land a merge, flipping the PR view to `MERGED`
  with its merge commit and parents. The crash matrix gains a real-forge two-branch profile beside
  the existing fixture-merge one, which stays as it is.
- **The `release` command from source** for the preview refusals (#128 test seams). The fake `gh`
  answers `observe_merge`'s three reads, which stay outside the spelling fixture (#128 D12).
- **The guard's public CLI seam** over the shared spelling fixture (#124 D12, D22).
- **The certification harness** against the live sandbox, plus one evidence test.

No seam below these is introduced.

## Out of scope

- **Any change to a real repository's branch protection.** That includes enabling
  `enforce_admins` on JarBird's `main`, which the floor requires (D4) and only its owner may do.
- **JarBird adoption.** That covers its release profile, its fleet registration, and the derived
  guard row the release arm needs to know its integration branch.
- **Deploy watching and activation binding.** `deploy_watch_unowned` stays.
- **Other merge methods and bypasses.** `--auto`, `--admin`, squash and rebase merges, a merge
  subject, and syncing the integration branch with the default after a release.
- **A core-owned or driver-owned release PR,** and any disposition command for a release parked
  after an effect (row 9).
- **Changes to the transaction core, the lifecycle guard's code, the `release` command's argv or
  nix-config's profile.**

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The skill opens the release PR, once, when a two-branch preview refuses `release_pr_missing`. The driver discovers the PR itself and never opens one. This narrowly reverses #128 D1's deletion of the release-PR phase, now that a runnable merge exists | The issue offers the core, an `index` action or the skill; #128 D5 (the driver observes the candidate itself); preview is read-only and `run` mutates only through the core; an open PR is reversible and is the merge's subject | A core `index` action (a new operation, guard spelling and certification, and a PR number unknown at creation). The driver opening the PR in `run` (a mutation outside the core that preview cannot bind). A `--pr` flag (an agent-supplied identity the driver must re-verify anyway) |
| D2 | The candidate gains an identity member `merge: {pr, base_tip}`. A profile binds it when a node's descriptor consumes it (`pr_merge`), into the subject and every unit. `pr_merge`'s expected head is `candidate.commit`, and its top-level `pr`, `expected_base_tip` and `expected_head` parameters go. Refines #124 D19 | The issue asks that the merge's members be bound at creation; the tag needs the same binding to find the merge commit; descriptor-driven, so fixture merges and single-branch profiles are unchanged | Members bound only into `pr_merge`'s unit (the tag cannot see them). Late-binding the tag's commit in the core (a risk-path core change against an immutable plan). Splitting merge and publication into two transactions (breaks one reservation and AC3's single resume) |
| D3 | In `new` mode, the driver observes the merge binding before the receipt: the one open PR from `<owner>:<integration>` into the default branch, its head equal to the candidate, the default tip, and `compare` reading `ahead`. Its refusals (`release_pr_missing`, `release_pr_stale`, `release_pr_behind`) are preview refusals with a null repair. The plan digest covers `merge`, so a moved base rotates the tokens | #128 D5 and D18; GitHub's REST pulls `head` filter and compare `status`; strict protection refuses a head that lacks the base | The receipt first (a PR-triggered CI never starts, so pending never clears). No compare (a doomed transaction reserves a version and parks). A separate receipt member (the bound plan already seals it) |
| D4 | `pr_merge` invoke is supported under the owner-accepted mechanism. Its precondition floor is protection answered 200, `strict` true, non-empty `contexts` and `enforce_admins` enabled; anything else is `rejected`/`precondition_failed`, `protection_floor_unmet: <member>`, before the guard and the mutation. Reverses #128 D2 and the invoke half of #124 D8. Consequence: JarBird's `main`, read on 2026-11-02 as strict with `enforce_admins` off, is refused until its owner enables admin enforcement | The owner's 2026-11-02 acceptance (strict and a required check); #116 D6 (preserve admin enforcement, no privileged bypass); the protection read needs admin rights, and GitHub applies protection to admins only under `enforce_admins` (nix-config `CLAUDE.md`: under its protection even `--admin` is refused); the guard's feature-arm floor demands the same | Only the owner's two named conditions: for the admin actor the floor admits, GitHub would not refuse a behind merge, so the mechanism's premise fails. Reading the actor's admin bit (bypass also comes from roles, at the cost of more reads) |
| D5 | The rendered spelling is exactly `gh pr merge <pr> --repo <slug> --merge --match-head-commit <commit>`, with no subject. The guard is unchanged: its release arm already admits that spelling and keeps its rollup gate. The shared spelling fixture pins the row, admitted only in the distinct-integration class, with the near misses refused | #116 D5 spellings; issue 402 and 476 (`--match-head-commit`, mergeability check); #124 D9 and D12; #116 D1 condition 3 puts the floor in inspection | A protection floor in the guard's release arm (changes native Nodo merges and touches a risk path for a floor the adapter already enforces). A `--subject` (another free-text slot and no need) |
| D6 | Invoke checks, in order: same repository, floor, PR (`OPEN`, base, head), base tip. Then it renders, asks the guard and mutates once. Exit 0 is `accepted`; any non-zero exit or timeout is `unknown`/`transient_transport`, with no stderr parsing | #124 D23 (a failed precondition is `rejected`; any other non-zero exit is `unknown`); the core inspects in the same `invoke_action` call (#206); the base precheck refuses a doomed retry before any provider call | Parsing gh and GitHub refusal texts into `rejected` (brittle wording that no driver behaviour depends on). Skipping the base precheck (widens row 9's window from moments to the whole run) |
| D7 | Inspect keeps #124 D8's exact rule: `satisfied` only for parents `[base_tip, commit]`. A base that moves in the window to a commit the head contains is merged by GitHub, then parks `diverged` after an effect. This is a documented limitation with no disposition command | #116 D7 (the target-tip identity stays the CAS subject; strict only narrows which divergences GitHub refuses); the confirmation named B0; #90 "parked is never released" | Accepting any first parent the head contains (the tree is equal, but the base is not the one the user confirmed, and it silently weakens #124 D8) |
| D8 | With a `merge` binding, `tag` and `release` resolve the released commit as the release PR's merge commit with parents exactly `[base_tip, commit]`, using the `pr_merge` reads and the helper that decides `pr_merge`'s `satisfied`. Tag invoke fetches `refs/heads/<branch>` before `git tag -a` | The issue: "the tag action then targets that merge commit"; one helper keeps the merge and tag judgments identical; the merge commit exists only on the remote after the merge | Tagging the integration tip (against the issue). Tagging the default tip after the merge (it may have moved). Finding the PR by commit search (ambiguous across feature and release PRs) |
| D9 | `ship-release` gains one Phase 3 sentence (`release_pr_missing` → `gh pr create` → preview again), offset so that both hot profiles stay at or below 16,997 bytes with the ceilings unchanged. If no offset fits, implementation stops at the user's label gate | `instruction_load` raise control; the global rule that only the user applies `instruction-budget-raise`; agent-helpers rule 6 (no phrase pin) | Raising the ceilings (needs the user's label). A new eval (no criterion asks) |
| D10 | Certification is a `tests/` harness run by a `just` recipe against the constant public sandbox `fagenorn/release-merge-sandbox`. The harness creates it behind a description marker and refuses it without one. Every run PUTs strict protection with one status-satisfied context and `enforce_admins`. The sandbox is reused, never deleted. Rows a, b (argv and direct GraphQL) and c. Row a uses the real adapter with a recording guard shim. The harness mutates only the sandbox, launched openly, and stops at a human gate on any permission refusal | #116 D8 (native proof where fixtures cannot certify; distinguish simulated from real); the issue's three cases; the gh client prechecks `BEHIND`, so only a direct mutation proves the server refuses; the keyring scopes lack `delete_repo`; the-bar (no test doubles in shipped code) | An Actions workflow as the check source (CI minutes and timing). A private sandbox (protection needs a paid plan). The real guard under a scratch policy (it refuses rows b and c first, so the provider is never reached). Certifying on JarBird or nix-config (forbidden). A harness inside `agent_tools` (ships a guard shim) |
| D11 | The evidence file records identities, protection, spelling, per-attempt bounded outcomes and `result`. An evidence test pins `passed`, the sandbox, the fixture spelling and the current `pr_merge` descriptor digest, so a spelling or descriptor change demands re-certification | #116 D8 (exact identities, no secrets or raw transcripts); #128 D24 (an evidence commit cannot name itself, so it binds the commit that ran); agent-helpers rule 3 (no source hashing through `__file__`) | A hand-written record (fabrication risk). Binding the whole descriptor (churn from unrelated operations). Keeping no test (the evidence could silently go stale) |
| D12 | Grill. When an invoke is not `accepted` and the action is left unsatisfied, the park reason appends the invocation's result, error class and reference from its `invocation_returned` event. This applies to every operation | the-bar ("the log stream is the debugger", truthful terminal states); #128 D25 (`status` carries the reason the report renders); the core records the reference but `status` shows only the inspection's | A bare `<action>: absent` (the floor refusal, AC2's whole point, would be invisible to the operator). A new `status` member (a contract change for one string) |
| D13 | Grill. `pr_merge` invoke refuses `head_auto_delete_on` unless `gh api repos/<slug> --jq .delete_branch_on_merge` prints `false`. JarBird reads `false` on 2026-11-02 | #116 D5 (the release arm preserves the permanent integration head) and D1 condition 3 (inspection establishes the allowed branch shape); the adapter renders no `--delete-branch`, so only the repository setting can still delete `dev` | Trusting the setting (one flip deletes the integration branch on the next release). Folding it into the shared `invoke.repository` read (changes every operation's spelling) |
| D14 | Grill. The preview does not duplicate the protection floor. A floor gap surfaces at the merge invoke as a no-effect park whose reason names the gap (D12), and `abandon` frees the version (#128 D14) | #128 §4 (preview calls no adapter); the-bar DRY (the floor has one home, the adapter's precondition); defense in depth keeps the authoritative inner check | A second floor predicate in `release_verification` (two homes for one policy that must change together). Calling the adapter from the preview |
