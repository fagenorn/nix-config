---
name: ship-issue
description: Deliver a finished feature-branch worktree — sync integration branch, PR, review, CI, merge, close or hold issue, clean up. Phase 7 of from-issue. Use for "ship #X", "land it".
---

# Ship Issue

Counterpart to `to-issues` and `from-issue`. Take a worktree branch with the implementation committed and deliver it: merged on the integration branch, issue closed or held as `needs-verification`, workspace gone.

## Project bindings (resolve first)

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. The only sanctioned exception is `workflow-state build-delivery`, which performs its own sealed, read-only resolution when it builds a delivery object; this skill still never resolves again itself. Use `bindings.tracker`, `bindings.vcs`, `bindings.commands`, `bindings.workflow.review.code`, and `bindings.workflow.verification`; dereference verification IDs through `bindings.commands`.

For code review, select `bindings.workflow.review.code` and route retained
`capabilities.review.code` first. `blocked` stops; authored `unsupported` takes
only its documented route. Only `available` dereferences
`bindings.commands[review_id].argv` before execution.

A blocked required capability stops. An authored unsupported tracker takes the existing tracker-free route; the sync/verify/consolidate/merge machinery still applies.

Retained `capabilities.review.code` governs the full review route.

**Invocation paths.** From `from-issue`, treat the handoff as received stdin
bytes: pass them through `artifact-budget validate-report --boundary
ship-handoff --input -` before decoding any field. With lifecycle identity it is a
`ship-handoff/v2` carrying `custody`, the installed delivery contract, its initial
intent and the ledger's pending stages; ledger-free it is the legacy handoff with
a null lifecycle group. Either carries the fixed lifecycle
scalars, `spec_artifact`, `plan_artifact`, `head_sha`, `review_state`, `acceptance_state`, `auto`, one
optional durable `report_path`, and notes. On entry, independently run
`artifact-budget check` for the design-spec and implementation-plan roots,
compare all four metrics, and recheck a non-null SDD detail root as a
review-package. Exit 2/3, stale metrics, a mismatch, or over-budget input stops
before Phase 0. After any later writer changes either artifact, repeat the same
checks before continuing. Standalone (`/ship-issue <num>`): `review_state` is
`unknown` unless the user supplies validated evidence of a completed sdd
two-axis review, and with `review_state: unknown` `acceptance_state` is
`not_applicable`; derive the issue number and artifacts, then establish the same
checker-valid root/metric objects. The worktree state — not the handoff — is
ground truth.

Only after the plan's successful artifact-budget check, discover the plan members
locally from its validated index for `review-range` exclusion. Supply one argument for the plan root and each discovered member.
Keep that private
list inside ship-issue: do not put the member list in the handoff, report, or
review prompt.

## Files beside this one

- `SYNC.md` — Phase 1: divergence, foreign commits, scope creep, the allowlist, the escalation format.
- `CONSOLIDATE.md` — Phase 3: the bar, the rubric, destinations and the procedure.
- `REVIEW.md` — Phase 5: Codex failure semantics, templates, the delta brief, the range record, severity mapping, the five-step fix flow, durable Minor/Discussion detail.
- `CI-MERGE.md` — Phases 6–7: the CI escalation, failing checks, advisory overflow, merge quirks, and the post-selection sync.
- `HUMAN-GATE.md` — the operator gates, entered only when `## Standing authorization` finds no grant.
- `DELIVERY-LOOP.md` — lifecycle identity: read it for every `ship-handoff/v2` and every remainder.
- `REMAINDER.md` — a `delivery_remainder` owner's entry, start points, close or hold, and `finish`.

## The flow

```
0. Pre-flight              → dispatch probe, worktree clean, branch pattern ok, no PR yet
1. Sync integration branch → fetch + merge origin/<integration>, hybrid conflict policy
2. Verify locally          → verified-tree check; run + record unless verified
3. Consolidate learnings   → see CONSOLIDATE.md; drop most candidates
4. Open PR                 → push -u; gh pr create with "Closes #<num>" unless held
5. Review the PR           → review-range picks delta, empty or full; two-axis review over it
6. Wait for CI             → gh pr checks --required --watch (one blocking call; all checks when none is required)
   Selection gate          → lifecycle identity only: select the CI-green head (## Delivery loop)
7. Merge                   → gh pr merge <pr-num> --repo <resolved-repository> --merge [--subject "<rendered subject>"] --delete-branch (true merge commit)
8. Cleanup                 → issue closed or held; worktree + branches removed
                             (lifecycle identity: each 7–8 effect is one ## Delivery loop cycle)
```

## Standing authorization

Standing authorization exists where repository policy or an explicit user grant
covers the concrete action, target, and external effect. Carry that grant across
phase and session boundaries; do not demand that Codex receive the same literal
command text again. A harmless quoting or spelling change and a transient command
failure do not erase scoped authorization. The launch guard, required CI,
reviewed-tip check, protected-branch rules, and the host's actual automatic
approval decision still bind.

In a qualifying repository, the lifecycle guard covers pushing a non-default
branch, opening a PR to the default branch, the guarded merge, branch deletion,
and worktree removal. Execute that authorized chain without a phase-boundary
re-prompt while every check above passes.

On a host whose permission layer adjudicates intent by review, use an existing
user grant when it covers the same chain. When authority is absent, take the
consolidated operator gate of [`HUMAN-GATE.md`](./HUMAN-GATE.md). An actual
denial stops the denied action; never route around it.

## Launch guard

The lifecycle ledger reserves one worktree per issue and hands a retry the
predecessor's worktree and branch on purpose, so a superseded attempt can still
push, open a PR and merge. Before **every write to the forge or to `origin` this
skill makes up to and including the merge**, re-validate that the handoff's
launch identity is still the launch the ledger entitles. The rule binds
regardless of tracker capability, so an unsupported-tracker invocation — which skips
Phase 4's PR but still pushes the branch — guards that bare `origin` push too:

```
~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>
```

`<issue:attempt:launch>` is the `action_id` the handoff carried, passed through
verbatim — never recomputed, never derived from `attempt`; the launch ordinal is
exactly the part this owner cannot know. The verb is read-only: it takes no
clock, holds no lock and creates nothing.

Proceed only on `current: true`. Refuse the write on `current: false`, a
non-zero exit, a missing helper, or output that does not parse into the exact
four keys `action_id`, `current`, `current_action_id` and `reason`. **This one
call does not follow this skill's degrade-gracefully rule for absent optional
helpers** — that rule is written for optional bindings, not for a safety check,
and following it here would turn the guard into a no-op precisely when the
environment is broken.

Guarded: the Phase-4 push, the Phase-4 PR create, every push in REVIEW.md's
five-step apply/push flow, and the Phase-7 merge. There is no post-merge
exemption: under lifecycle identity each post-merge effect is a `## Delivery loop`
cycle — the remote branch delete, and Phase 8's issue close or hold, `git worktree
remove` and `git branch -d` — fenced by `current-launch` before and after the
effect exactly like the merge. Local commits are fenced separately
(### Local commits).

**A refusal is a stop that writes nothing anywhere.** Do not execute the write.
Make no further forge write, **no ledger write**, and run no cleanup: leave the
worktree, the branch and any PR exactly as they are, because the successor is
working in that same worktree on that same branch. Print the canonical re-entry
line `/from-issue <num> --auto` on its own line, then return a truthful
`stopped` ship summary (under lifecycle identity, the `historical_owner_result`
of a `terminal_failed` `ship-summary/v2`) whose notes name the refusal, the reported `reason`, this
`action_id` and the reported `current_action_id`. Its fields are `merge_sha:
null`, `issue_closed: false`, `discussion_items: []`, `pr_url` the PR when one
was already opened and null otherwise, and `detail_state: "none"` with
`report_path: null` — or the failure-only `unpublished` shape when Phase 5
retained readable Minor/Discussion findings, naming that retained source and its
root in notes and keeping the worktree. An `unpublished` `report_path` is
worktree-relative, not main-root-relative (REVIEW.md §"Durable
Minor/Discussion detail"). Phase 8 does not run and no delivery detail is
published: the successor owns that worktree and will produce its own.

Without lifecycle identity — a standalone `/ship-issue <num>`, or a handoff
whose lifecycle group is all-null — skip the guard silently: a ledger-free
invocation has no attempts and no supersession mechanism, and the handoff
validator's all-or-nothing group means it is never partially present. That is
the only skip, and it is a statement about the invocation, not about the
environment.

### Local commits

When the prompt carries a `Lifecycle worker:` line, this run is a
registered worker, and it creates every local commit as
`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <git commit arguments>`.
That includes Phase 1's sync, run as
`git merge --no-commit --no-ff origin/<integration>` followed by
`launch-commit`, and Phase 3's commits. Exit 3 is a refusal like
`check-launch`'s: stop with the same no-write rule. An agent this run
dispatches that can write is registered with
`--parent <worker_id>` added to `workflow-state register-worker` (this
handoff's `action_id` as `--action-id`), gets its own `Lifecycle worker:`
line followed by the sentences "Run each long command, every verification command included, as
`launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`,
still in the foreground." and "Create every scratch directory or scratch worktree under the path that
`launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` prints.", and is released when it returns. Without the line, commit with plain
`git`.

## Doc-grounded escalations

Before forming *any* user-facing question this skill raises mid-flow, invoke the `doc-grounded-questions` skill and read only the retained declared paths. Lead with what the relevant document says; ask only the genuinely open part.

## gh hygiene

Prefix a forge invocation only with the names in `bindings.tracker.credential_env.unset_before_invocation`; for example, an exhaustive list containing `GITHUB_TOKEN` yields `unset GITHUB_TOKEN && gh ...` when a harness token lacks access to the target org. When `bindings.tracker.cli` is `glab`, substitute the equivalent `glab` verbs.

Throughout, follow `writing-plans`' Payload discipline: targeted `rg` over whole-file reads, bounded reads, summarized command output, logs on disk, artifacts handed over as paths.

## Phase 0 — Pre-flight

**Reviewer-dispatch probe — first, before any write.** This is Phase 0's first
step. It runs after entry validation and before the four checks below, and so
before `## Delivery loop`'s synchronizing null-scope checkpoint, the Phase-1
sync, and every forge, ledger or git write. Confirm that this context can launch
the subagents this skill's reviewer dispatch sites name: the subagent-launch
tool is in your tool surface, or, on a host that defers tool schemas, its tool
search returns that tool's schema (Claude Code: `ToolSearch` `select:Agent`).
Test the capability, never a host by name. The probe launches nothing, writes
nothing and makes no trial dispatch. It proves the tool is present, not that a
later launch will succeed: a Phase-5 launch that fails after a passing probe
keeps its existing failure handling. It runs in every review-bearing
invocation — a `ship-handoff/v2` or legacy handoff, or a standalone
`/ship-issue <num>` — even when the review range may turn out empty, because the
delta is unknown until the sync this probe precedes. Remainder mode skips
Phases 0–5 and probes only before a post-selection sync, per CI-MERGE.md.

When the probe fails, stop with nothing launched or written. From a handoff,
your whole return is exactly this closed line, with no ship summary and no
validation:

```text
capability_gap: agent_dispatch
```

Standalone, tell the user the probe found no subagent-launch tool, end with that
same line, and stop, keeping the worktree.

Then verify the workspace is shippable before doing anything destructive:

1. `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir` — a linked worktree, not the main checkout.
2. `git branch --show-current` matches the regex built from retained `bindings.vcs.branch_pattern` and `bindings.vcs.worktree.prefix`; both configured forms are valid. Extract `<num>`. An argument or handoff `issue_number` wins, but verify it matches the branch.
3. `git status --porcelain` returns nothing.
4. `gh pr list --head <branch> --json number,url` returns `[]` — no open PR for this branch.

Any failure: pause, ground, surface. Don't auto-fix the branch name or stash changes.

**Effective acceptance state.** Start from the handoff's `acceptance_state`;
standalone with `review_state: unknown` it is `not_applicable`. The acceptance
record is `<plan stem>.acceptance.md` beside the plan root, named by its
repository-relative path, never an absolute one, or `none` when no such file
exists. With `human_pending` and `auto: false`, ask the user, as one
grounded question, to attest each `human_pending` row of the record. When every
row is attested, rewrite those Verdict cells to `met (attested)`, commit the
record (### Local commits) and continue with `met`; the new commit means Phase 2
cannot skip its rerun. Otherwise keep `human_pending`. `--auto` never asks and
never self-attests. The value is then fixed for the run, and ship grades
nothing: `met` or `not_applicable` **closes** the issue, while `unmet` or
`human_pending` **holds** it open as `needs-verification` (Phase 8). A hold
whose record is `none` stops with `terminal_failed` before any hold effect: no
hold exists without a record.

## Phase 1 — Sync from the integration branch

**Read [`SYNC.md`](./SYNC.md) first** — it owns divergence handling, foreign-commit checks, scope-creep sweeps (retirement/addition), the auto-resolve allowlist, and the conflict escalation format.

```
git fetch origin
git log origin/<integration>..<integration> --oneline
```

The load-bearing rules, in brief:

- Merging `origin/<integration>` into the feature branch is safe even when the local integration branch has diverged (expected under parallel `--auto` runs). **Anything that rewrites the local integration branch — reset, rebase, push — stops and surfaces; `--auto` never auto-resolves history rewrites.**
- Foreign commits on the branch (another issue's work) → surface, never clean up silently.
- Conflicts: the allowlist auto-resolves lockfiles, migrations and generated files, and always keeps `.claude/settings.json` out of the merge. **Everything else escalates one conflict at a time**; skipped conflicts pause the phase.

Otherwise run `git merge --no-commit --no-ff origin/<integration>`; when it reports `Already up to date` there is nothing to commit, otherwise commit the merge with the configured merge-commit message through `launch-commit` when this run holds a `Lifecycle worker:` line (### Local commits), or plain `git commit` without one. Don't squash.

## Phase 2 — Verify locally

This is the one verification step. Phase 3 after a promotion commit,
REVIEW.md's apply/push step 2 and CI-MERGE.md's post-selection sync run it too.

A blocked verification capability stops and reports its `reason_code` and
`repair_id`; authored unsupported follows only its documented no-verification
route.

1. **Check.** Run `verified-tree check --verification <id>` in the worktree,
   repeating `--verification` for every id in retained
   `bindings.workflow.verification`, in order, and keep the `tree` it prints.
2. **Skip only on `verified`.** Exit 0 with `verified` means this exact tree
   already passed these commands, at sdd's final gate or an earlier run of
   this step: skip the run. On Phase 2's own run, note
   `verification reused: tree <id>` in the PR body's Summary.
3. **Otherwise run and record.** On any other answer, run every command id in
   retained `bindings.workflow.verification` through its `bindings.commands`
   argv and cwd. When every command passes, run
   `verified-tree record --tree <the checked tree>` with the same
   `--verification` ids. A `record` that exits 3 with `tree_changed` is a
   failing verification under the rules below: the passing run no longer
   describes the worktree. A `check` that exits 2 leaves no tree to record:
   run the commands anyway, and leave the pass unrecorded. A `record` that
   exits 2 leaves the pass unrecorded too; the run itself still counts by its
   commands' results.

These failure rules apply only to an actual run. On a failing verification
command, pause, ground, and surface; do not invent a fix command outside
retained `bindings.commands`.

Test failures: separate *environmental* (container connectivity, missing network, sandbox limits) from *real* by baselining the same project in a scratch worktree on `origin/<integration>`. Same failures → pre-existing; continue and note the baseline diff in the PR body. Different failures → real; pause, ground, surface.

## Phase 3 — Consolidate learnings

**Read [`CONSOLIDATE.md`](./CONSOLIDATE.md) first** — it owns the mining commands, rubric, destination table, and reporting format. Run its step-1 mining commands as actual tool calls *before* concluding anything: empty is a finding, not a default — earn it by mining. Promoted candidates commit as `docs(<scope>): <summary>`, following retained `bindings.vcs.commit.co_authored_by`. When Phase 3 commits anything, run Phase 2's verification step again before Phase 4.

## Phase 4 — Open PR

Skip entirely when the tracker capability is unsupported (push the branch and stop, or merge locally per the user's request).

When `## Standing authorization` finds no existing grant for these concrete
actions, enter Gate 1 of [`HUMAN-GATE.md`](./HUMAN-GATE.md) before running
anything below. Never use the gate to retry an actual denial.

Run `check-launch` (see `## Launch guard`); on anything but `current: true`,
stop without pushing. Then:

```
git push -u origin <branch>
```

Run `check-launch` again, then:

```
gh pr create --repo <resolved-repository> --base <integration> --head <branch> --title "<title>" --body "## Summary
<2-4 bullets of what shipped>

## Spec
<spec-path>

## Plan
<plan-path>

## Acceptance
Acceptance state: <effective acceptance state>

Acceptance record: <record-path or none>

<acceptance table>

Closes #<num>"
```

This is the one form the lifecycle guard accepts: one command, those five flags in that order, `<resolved-repository>` the retained `bindings.tracker.repo_slug`, and the body a single double-quoted argument that may span lines but contains no `"`, `$`, backtick or backslash. A body written to a file, a heredoc or a command substitution is refused, so render the body in place.

The `## Acceptance` section always appears. `Acceptance state:` carries Phase 0's
effective value, and `Acceptance record:` carries the record's repository-relative
path or `none`. With a record, `<acceptance table>` is a Markdown table with the
three columns `AC`, `Kind` and `Verdict`, one row per record row, copying its
closed tokens; without one, drop that line. On a **hold** drop the
`Closes #<num>` line too: a hold body carries no closing keyword (close, closes,
closed, fix, fixes, fixed, resolve, resolves or resolved before an issue
reference), so the merge cannot close the issue.

Title: the issue title verbatim unless the implementation deviated meaningfully. Under 70 chars; details go in the body.

GitHub auto-close on merge fires only when the PR base equals the **default branch**; when retained integration and default branches differ, the real close mechanism is Phase 8's explicit `gh issue close <num>` — on the close branch keep the `Closes #<num>` trailer for traceability, don't rely on it.

**Use full URLs, not bare `#N`**, in PR bodies, comments, and commit-message references (`https://github.com/<resolved-repository>/issues/<n>`) — GitHub resolves bare `#N` against the source repo context, which under cross-references lands on unrelated refs. The `Closes #<num>` trailer is the one exception.

## Phase 5 — Review the PR

```
BASE_SHA=$(git merge-base HEAD origin/<integration>)
HEAD_SHA=$(git rev-parse HEAD)
```

The branch normally arrives already reviewed on two axes by sdd's final review (conformance ∥ correctness); this phase reviews only what that review could not have seen — unless a risk signal calls for the full ladder. **Read [`REVIEW.md`](./REVIEW.md) before dispatching or applying anything.**

**Pick the range first.** The *final-review head* is the handoff's `head_sha` when `review_state` is `clean`; it is distinct from the reviewed `HEAD_SHA` this phase fixes. Check the first, second and fourth conditions first; when any fails, the range is full and `review-range` does not run. Select the range with `review-range` when ALL of these hold:

- `review_state` is `clean` (handoff / sdd report: both axis verdicts clean, or every residual parked-with-ruling). `unknown` never degrades.
- The Phase-1 sync needed no manual conflict escalation (allowlist auto-resolves count as clean).
- The delta since the final-review head is small: **≤1,000 product lines AND ≤20 product files**. Measure, never hand-count: start with `~/.agents/bin/review-range --integration-ref origin/<integration> --head $HEAD_SHA --final-review-head <final-review head> --max-lines 1000 --max-files 20 --artifact-path <spec_path> --artifact-path <plan_path>`, then append one argument for each plan member and any other process artifact this run wrote. Each exclusion is an individual `--artifact-path <path>` argument. It prints one JSON object whose `route` is `delta`, `empty` or `full`, with a closed `reason`; its `product_lines` and `product_files` measure `<review_base>..$HEAD_SHA` after dropping lockfiles, generated-header files, and those exact artifacts. The gate measures PRODUCT changes, not process artifacts; never exclude the resolved artifact directories themselves, which hold every artifact this repo has ever accepted, and a historical artifact that is itself the requested product still counts. No measurement — exit 1, unparseable stdout, or invalid plan discovery — is not a small diff: the range is full, recorded as `review-range unavailable`.
- The issue does NOT carry the `risky` label (`<tracker-cli> issue view <num> --json labels`; with an unsupported tracker capability the condition passes), and the retained `capabilities.review.code` state permits the documented review route.

**Route the review.** `delta` → the full two-axis review below over `<review_base>..$HEAD_SHA`, with REVIEW.md's delta-route conformance brief. `empty` → nothing to review: record it and skip to Phase 6. `full`, a failed prerequisite, or an unavailable helper → the full two-axis review below over `$BASE_SHA..$HEAD_SHA`. Record the route in the PR body per REVIEW.md.

**Merge-delta reviewer (post-selection sync only).** Phase 5 never dispatches it: CI-MERGE.md's `## Post-selection sync` reviews each later sync merge with it, over REVIEW.md's merge-delta scope and checklist:

<!-- agent-dispatch: id=ship-issue-merge-delta-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") reviews exactly the non-empty merge delta.

**Full two-axis review.** Both the `delta` and `full` routes run it. Templates and fallback rubrics per REVIEW.md, over the selected range: `<review_base>..$HEAD_SHA` on `delta`, `$BASE_SHA..$HEAD_SHA` otherwise. Launch the native conformance axis with:

<!-- agent-dispatch: id=ship-issue-full-conformance-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the full conformance review.

Run it in parallel with the correctness axis. Choose the correctness route from the retained `capabilities.review.code` state before either axis is dispatched, never from how a Codex call failed:

1. `blocked` stops with its capability reason and repair ID; neither axis is dispatched.
2. `available`, with `codex-collaboration` installed → its `diff-review` operation. This is the only rung that reaches Codex and the only one where a capacity rejection binds, on the terms in REVIEW.md. A completed non-capacity failure takes that skill's one native fallback.
3. `unsupported`, or `available` without `codex-collaboration` installed → this native first-pass dispatch, directly; `codex-collaboration` is never invoked on this rung:

<!-- agent-dispatch: id=ship-issue-full-correctness-fallback role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the full correctness fallback review.

A Codex call made under `unsupported` anyway is a routing error: discard its outcome — verdict, refusal or failure — record the routing error in the PR body beside the correctness verdict, and run the rung-3 native dispatch, with no retry, stop or suspension.

Axis reports are never merged, and when the correctness axis came through `diff-review`, its scope is recorded in the PR body per REVIEW.md. Apply findings through REVIEW.md's severity mapping and five-step apply/push flow. After the fix lands, re-review only a named finding and the bounded fix diff — never as a first-pass, merge-delta, or whole-branch review:

<!-- agent-dispatch: id=ship-issue-scoped-fix-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") re-reviews named prior findings against the bounded fix diff.

If the fix changes unrelated behavior or the finding cannot be checked in that bounded diff, stop the cheap re-review and return to the appropriate full Opus/high axis above.

**Interim child results.** A child's return that the host marks interim — it stopped with background work of its own still running, or its result may be interim — is not a completion: the child is still running. Re-engage that same child by its recorded agent identity: message it to wait for its own job inside its turn and then return its final report, and wait for that report. You may end your own turn while the re-engaged child is live, because the host wakes you with its next notification; that is a child's work, not a command you started. Never answer an interim result with a text-only reply, never suspend for it (it is not an `external` wait), and never dispatch a replacement or stop the child. A registered lifecycle worker stays registered under its existing worker id: an interim result is not its `returned` event, and re-engagement is not a resume, so it registers nothing new. If the message cannot be delivered, the child is one you cannot wait for: follow from-issue's **Writing workers** route (task-stop, then release `--event stopped`), then this skill's ordinary handling of a lost child; that is the one case that may lead to a fresh dispatch. Only the child's final hand-back counts as its result.

## Phase 6 — Wait for CI

**Docs-only changes never wait for CI.** `git diff --name-only <base>..HEAD` — every path ends in `.md` → skip straight to Phase 7 (a markdown-only diff cannot break a build); anything else → the phase runs normally.

Before blocking, verify the tip: `gh pr view <pr-num> --json headRefOid` must
equal the reviewed `HEAD_SHA` — the value fixed in Phase 5 and re-fixed by
REVIEW.md's step 5 after each applied fix lands — never `git rev-parse HEAD`
read afresh. Two attempts of one issue share this checkout, so live local HEAD
is not evidence about what was reviewed.

Diverged → the PR head carries **unreviewed commits** on the branch. Never
resolve it by re-pushing, resetting, re-reviewing or merging, except for a head
that CI-MERGE.md's `## Post-selection sync` admits. In `--auto` this
is the genuinely-blocked stop: stop before the CI wait and before the merge,
make no further forge write, run no cleanup, keep the worktree and the branch,
and return a truthful `stopped` ship summary naming both SHAs — the reviewed
`HEAD_SHA` and the observed `headRefOid`. In interactive mode, surface and wait
at the same point. Divergence here is also evidence of a superseded launch,
which is why `## Launch guard` runs before the merge regardless of how this
check came out.

Then block on the required checks with `gh`'s built-in watch — one Bash call, **300s timeout**:

```
timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30
```

**Foreground only — never backgrounded, and the blocking watch is the only sanctioned wait shape: no bare re-polls, no no-op keep-alive commands.** Exit `0` → list advisory states, then Phase 7. Exit `124` → one short narration turn, re-run the identical command, up to 8 times (~40 min), then escalate. Exit `1` with gh's `no required checks reported` error → the base marks no check required, or the required check is not reported yet: run `timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30` for the rest of the phase under the same exit codes and retry budget, list no advisory states, and note `CI: no required checks reported; waited on all`. Other non-zero → a gating check failed; pull `gh run view <run-id> --log-failed`, ground, surface. After the required watch exits `0`, run `gh pr checks <pr-num> --json name,bucket` once and append each non-`pass` row to the ship summary's notes as `advisory CI: <name>=<bucket>, …`. An advisory failure does not block the merge. Rationale, escalation script, advisory format and JSON-field notes: [`CI-MERGE.md`](./CI-MERGE.md).

## Phase 7 — Merge

(When the tracker capability is unsupported, merge the branch into the integration branch locally per the user's instruction instead.)

When `## Standing authorization` finds no existing grant for the merge and
cleanup chain, enter Gate 2 of [`HUMAN-GATE.md`](./HUMAN-GATE.md) before
anything below. The gate comes first because it waits for the operator's own
message; `check-launch` is then re-validated after the grant arrives,
immediately before the merge. Never use the gate to retry an actual denial.

Run `check-launch` (see `## Launch guard`) immediately before the merge, and
run it regardless of how Phase 6's tip check came out. On anything but
`current: true`, refuse the merge and take the no-write stop. Under lifecycle identity this effect is a `## Delivery loop` cycle.

Use retained `bindings.tracker.repo_slug` and `bindings.vcs` values to build the subject. Emit the subject form only when the rendered result is nonempty and representable by D18's quoted-subject grammar: it contains none of double quote, dollar, backtick, backslash, NUL, LF, or CR; otherwise omit `--subject` and its value and let the forge choose its normal subject. Never pass `--no-ff` (rejected by recent `gh`; `--merge` already produces a true merge commit).

```
gh pr merge <pr-num> --repo <resolved-repository> --merge --subject "<rendered subject>" --delete-branch
```

**Judge success by the verify below, never by the exit code** — in a worktree checkout the merge can land on the remote while local post-merge steps fail (details: CI-MERGE.md).

Verify: `gh pr view <pr-num> --json state,mergeCommit` → `MERGED` plus a non-null `mergeCommit.oid` means it landed.

After verifying the merge, ask the REMOTE whether the branch still exists — `git ls-remote --heads origin <branch>` (the actual configured branch name); PR metadata like `headRefName` is retained after deletion and proves nothing. Non-empty output → `git push origin --delete <branch>`.

## Phase 8 — Cleanup

Before cleanup, take every non-empty Minor/Discussion finding retained per
REVIEW.md and invoke review-package (`~/.agents/bin/review-package`) in
`delivery-detail` mode. Independently run
`artifact-budget check --kind review-package` on the returned durable root and
compare metrics. Record the checked `detail_state` and single `report_path`, but
do not construct or validate a successful `merged` ship summary yet. With non-empty findings,
publication failure may return `unpublished` only after the no-follow retained
source passes `validate-detail-input`; keep the worktree and do not remove it.
Otherwise fail closed. Only `none` or a checker-valid `present` detail can proceed
to remove the worktree.

Under lifecycle identity this effect is a `## Delivery loop` cycle.

1. Close or hold, per Phase 0's effective acceptance state.
   - **Close** (`met` or `not_applicable`): `gh issue view <num> --json state`; if `OPEN`, `gh issue close <num>` (the real close mechanism when retained integration and default branches differ — see Phase 4).
   - **Hold** (`unmet` or `human_pending`), in this order: `gh issue view <num> --json state,comments`; if `CLOSED` (a commit's closing keyword can close it), `gh issue reopen <num>`. When `gh label list --repo <resolved-repository> --search needs-verification --json name` shows no name exactly `needs-verification`, run `gh label create needs-verification --repo <resolved-repository> --description "Merged, acceptance criteria await verification"` — never `--force`, which would overwrite a user's label. Then `gh issue edit <num> --add-label needs-verification`. The hold comment's first line is `Held for verification: <PR URL>`; the rest gives the effective acceptance state, the PR body's three-column table and the record's link at the merge SHA (`https://github.com/<resolved-repository>/blob/<merge-sha>/<record-path>`). When the earlier view already shows one or more comments with that first line, reuse the earliest one's URL; otherwise post it with `gh issue comment <num> --body "<hold comment>"`, whose stdout is the comment URL. Finally `gh issue view <num> --json state,labels` must show `OPEN` with `needs-verification`; anything else keeps ownership and retries, as for any failed post-merge action.

2. Remove the worktree from the main repo root, never from inside the worktree:
   ```
   MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
   BUCKET="$MAIN_ROOT/.superpowers/sdd/wt-$(basename "$(git -C <worktree-path> rev-parse --path-format=absolute --git-dir)")"
   cd "$MAIN_ROOT"
   git worktree remove <worktree-path>
   git worktree prune
   git branch -d <branch>
   ```

   After the worktree is gone, remove the `$BUCKET` directory recorded above —
   the shape `<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/`,
   captured from the worktree's own git directory before removal rather than
   guessed from its path, because a stale registration under the same
   basename makes `git worktree add` register `<name>1` instead of `<name>`,
   and guessing would delete another worktree's bucket. Nothing else prunes
   it: the bucket lives in the primary checkout and outlives the worktree
   that named it, so a later worktree recreated under the same name would
   resolve to this attempt's ledger and read its `Task <N>: complete` lines
   as its own. Remove only that one worktree's bucket — never `primary/`,
   and never another worktree's.

3. If `git worktree remove` refuses on the rebased-branch case: confirm the PR landed via `gh pr view`, then retry with `ExitWorktree action: "remove", discard_changes: true` — the "discarded N commits" wording is misleading; the content is on the integration branch.

4. Only after issue closure and worktree cleanup both succeed — on a hold the confirmed hold stands in for closure — construct the
   successful `merged` ship summary with the observed full `merge_sha`,
   `issue_closed: true` on close or `issue_closed: false` on hold (its notes name the hold and the comment URL), `discussion_items: []`, and the checked detail fields.
   Validate it through `artifact-budget validate-report --boundary ship-summary`
   and report only canonical stdout. Never predeclare closure or cleanup in a
   candidate. If an earlier phase fails before merge, validate and return the
   truthful `stopped` or `failed` row. If a post-merge cleanup action fails, keep
   ownership and recover or retry that action; do not forge either a pre-merge
   failure row or a successful summary for actions that have not happened.

The final validated ship-summary contains only `issue`, `state`, `pr_url`, full
`merge_sha`, `issue_closed`, `discussion_items: []`, `detail_state`,
`report_path`, and notes. `report_path` is relative, and which root it is
relative to follows `detail_state`: a `present` path resolves against the
primary checkout, an `unpublished` one against the feature worktree. Notes say
which, because the path alone does not. That 9-key row has two roles: it is the
ledger-free return, and under lifecycle identity it is the
`historical_owner_result` of the `ship-summary/v2` that `## Delivery loop`
returns. Under implementation custody a ship owner writes only
`checkpoint-delivery`, never `finish`; a remainder owner writes its own
`finish --summary-file -`.

## Notes

- Merge commits, learning-doc updates, and blocker fixes fall under standing local-commit authorization. Don't re-confirm each. The `Co-Authored-By` trailer follows retained `bindings.vcs.commit.co_authored_by`.
- If a phase reveals an earlier one was wrong (review surfaces a misaligned spec, say), back up to the appropriate `from-issue` phase. Don't paper over.
- Absent sibling skills (`from-issue`, `sdd`, `worktrees`) degrade to no-ops; this skill still runs.

## Delivery loop

Under lifecycle identity — a validated `ship-handoff/v2`, or the `delivery_remainder` of `## Remainder mode` — every delivery effect from the pre-merge selection gate on runs through this loop. Ledger-free, Phases 7–8 run as written and no ledger call is made. The builder is `workflow-state build-delivery --repo-root <ledger_repo_root> --kind <kind> --input -`. The lifecycle-call rule, the checkpoint call, the `ship-checkpoint/v2` keys and loop steps 1–7 are in `DELIVERY-LOOP.md`.

## Remainder mode

Entered with a validated `delivery_remainder` object instead of a handoff. It skips Phases 0–5 and runs `## Delivery loop` from the ledger's ready stage, as `REMAINDER.md` says.
