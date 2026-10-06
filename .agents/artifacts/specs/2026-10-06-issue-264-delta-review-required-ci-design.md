# Ship reviews the delta since sdd's final review and waits only on required CI — issue 264

Design for [#264](https://github.com/fagenorn/nix-config/issues/264), 2026-10-06.
Its blocker, [#261](https://github.com/fagenorn/nix-config/issues/261)
(foreground verification and in-turn waits), is merged and its rules still bind.
The required-check floor and the lifecycle guard's merge validation
([#116 design](2026-09-20-issue-116-permission-guard-core-design.md)) are fixed
inputs, not decisions. Decisions D1–D9 bind the plan; the grill added D10.

## Problem

A branch reaches `ship-issue` after `sdd`'s final review graded it on two axes,
conformance and correctness, in parallel. The final review covered
`DELIVERY_BASE..DELIVERY_HEAD`. Ship's Phase 5 then reviews that same diff a
second time on both axes, in nearly every run. The reason is its degradation
gate, which measures the **whole branch** against ≤1,000 product lines and ≤20
product files. Most feature branches are bigger than that, so they never take
the cheap path. The only new code at ship time is the fix wave that followed
the final review, the Phase-1 sync merge and Phase 3's learning commits. Ship
pays for a full second review anyway, and the duplicate review is the most
expensive phase of a typical delivery.

Phase 6 has a related cost. It blocks on
`timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30`, which
waits for **every** check. In this repository that includes
`Agent Workflow Tests (advisory)`, a job of about nine minutes that no rule
requires. Branch protection requires only `Nix Eval`
(`.github/branch-protection.json`). So every delivery waits roughly two
watch windows on a check whose result cannot block the merge.

The owner sees both as wasted time and spend, with no gain in safety. The second
review covers no new code, and the extra wait guards nothing the forge
enforces.

## Solution

**Review only what the final review did not see.** The final review's
first-pass head (the *final-review head*, R, which is distinct from
ship's own "reviewed `HEAD_SHA`", D10) is already in sdd's report as `head_sha`, and from-issue passes it to ship as the handoff's `head_sha`. This
design makes that meaning explicit (D1). In Phase 5, ship runs one new
decision helper that never moves a ref or touches the working tree, `review-range` (D2). It takes R and the post-sync
ship head H and returns the range to review:

- **delta**: H's own changes since R. This is `<review_base>..H`, where
  `review_base` is R with the Phase-1 sync applied, so the integration branch's
  own commits are not counted as branch work (D3). It is measured with
  `diff-scope`'s accounting and is within the gate.
- **empty**: the delta has no changed path at all.
- **full**: there is no final-review head, R is not on H's first-parent history, a
  merge on that path is not a sync, the sync cannot be reproduced on R, or the
  delta is over the gate. Each case carries a closed reason code.

On **delta**, Phase 5 runs the same two isolated axes as the full review, over
`<review_base>..$HEAD_SHA` (D4). Correctness is at full rigor with its
unchanged rubric and correctness route. Conformance is scoped to the delta and
takes on the scope-creep checklist that used to belong to the merge-delta
check (D5). On **empty**, Phase 5 writes today's "nothing to review" record
and moves on. On **full**, Phase 5 runs today's full two-axis review over
`$BASE_SHA..$HEAD_SHA`. The gate's other conditions do not change: a clean
`review_state`, a sync with no manual conflict escalation, no `risky` label,
and a review capability that permits the route. If any of them fails, the
result is **full**, and in that case the helper does not run.

**Wait only on required checks; report the rest.** Phase 6 blocks on
`timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30`
(D6). When it succeeds, ship makes the phase's one non-watching call,
`gh pr checks <pr-num> --json name,bucket`, to read every check's state. It
writes each non-`pass` check that is not required into the ship summary's
`notes` as advisory, inside the existing bound (D7). If the PR has no required
checks, gh refuses the `--required` watch with its "no required checks
reported" error. That is either a base with no required set or a required
check not yet created. In both cases Phase 6 falls back to today's all-checks
watch for the rest of the phase, so a merge never has fewer gates than it does
today (D8).

## Decisions

### The final-review head is sdd's `head_sha` (D1)

sdd's report already carries `base_sha` and `head_sha` under a closed
validator, but sdd's prose never says which head `head_sha` is. The
cumulative delivery gate pins `DELIVERY_HEAD`, the final review's first pass
covers `DELIVERY_BASE..DELIVERY_HEAD`, and then one fix wave lands. Its
commits get only `reviewer-lite` re-reviews scoped to named findings. The fix
wave is exactly what the issue wants ship's delta to cover again at full
rigor. So `head_sha` means the final review's first-pass `DELIVERY_HEAD`, and
`base_sha` means `DELIVERY_BASE`. The report states the range both axes
reviewed whole, not the branch tip.

- `sdd/SKILL.md` `## Finish` and `final-review.md` define the two fields that
  way. When the fix wave adds commits, the branch tip is past `head_sha`, and
  that is expected.
- `from-issue/ship-handoff.md` states the mapping: handoff `head_sha` = the
  validated sdd report's `head_sha`, both in `ship-handoff/v2` and in the
  legacy handoff.
- `ship-issue/SKILL.md` names the handoff's `head_sha` as the final-review head
  when `review_state` is `clean`. Standalone, `review_state` is `unknown`
  unless the user supplies validated evidence. With `unknown` or `residuals`
  there is no final-review head, so the helper is not given one.

No schema changes. The sdd, legacy-handoff and `ship-handoff/v2` validators
keep their exact key sets. The handoff is still a hint, and the helper checks
the claim against the worktree's real history (D2).

### `review-range` — the decision helper (D2)

A new `agent_tools.review_range` module, plus one `review-range` row in the
command table in `lib/agent-tools.nix`, following `docs/standards/agent-helpers.md`.
The command module is a thin shell. Its policy lives in importable functions,
and it measures by calling `agent_tools.diff_scope`'s `measure` function
directly rather than running the command. It is read-only on refs and the
working tree. Its one write to the object store is D3's base commit.

```
review-range --root <worktree> --integration-ref origin/<integration>
             --head <HEAD_SHA> [--final-review-head <sha>]
             --max-lines 1000 --max-files 20
             [--artifact-path <path>]...
```

The gate thresholds come in as arguments. Their only home stays the Phase-5
bullet in `ship-issue/SKILL.md` (the diff-scope design's D9: a helper carries
no threshold). `--artifact-path` has the same meaning and the same caller
duty as in `diff-scope`: the spec root, the plan root, each plan member, and
any other process artifact this run wrote. Ship already discovers those
privately.

Stdout is one canonical JSON object with exactly these keys:

| key | value |
|---|---|
| `route` | `delta` \| `empty` \| `full` |
| `reason` | `within_gate` (delta) · `no_changes` (empty) · `no_final_review_head` · `final_review_head_not_on_branch` · `foreign_merge` · `sync_not_reproducible` · `over_gate` (full) |
| `final_review_head` | the resolved full SHA, or `null` |
| `head` | the resolved full SHA of `--head` |
| `review_base` | the full SHA to review from on `delta`/`empty`; `null` on `full` |
| `product_lines`, `product_files` | the delta's measurement on `delta`/`empty`/`over_gate`; `null` otherwise |

The decision, in order:

1. Without `--final-review-head`: `full`/`no_final_review_head`.
2. If R does not resolve to a commit, or R is not on H's **first-parent**
   history: `full`/`final_review_head_not_on_branch`. Being an ancestor is not
   enough. A branch whose sdd commits arrive only through a second parent is
   not the branch sdd reviewed.
3. Walk the first-parent path from R (exclusive) to H. Every merge on it must
   be a **sync merge**: exactly two parents, with the second parent an
   ancestor of `--integration-ref`. This is the same test as CI-MERGE.md's
   sync run. Every earlier sync's second parent must also be an ancestor of
   the newest sync's second parent P. If either check fails:
   `full`/`foreign_merge`.
4. `review_base`: R when the path has no merge, otherwise the D3 base built
   from R and P. If that build conflicts: `full`/`sync_not_reproducible`.
5. Measure `review_base..H` with `diff_scope.measure` and the artifact paths.
   If no path changed at all (not just no product path), the result is
   `empty`/`no_changes`. A change that touches only a lockfile or an artifact
   is still a change, and it still gets reviewed. Over either threshold is
   `full`/`over_gate`, with the measurement. Otherwise the result is
   `delta`/`within_gate`.

Exit codes: 0 for any decision, including `full`. 2 for a usage error
(argparse). 1 when the helper cannot produce a decision: a git failure, a
missing `--head`, or a measurement failure. In that case stderr gets one
`review-range: <detail>` line and stdout stays empty. Ship treats exit 1, or
stdout it cannot parse, as `full` and records "review-range unavailable", in
the same way the gate treats "no measurement" today: an unmeasured diff is
not a small diff.

### The reviewed-equivalent base (D3)

When H includes a sync merge, a plain `R..H` diff counts every integration
commit the sync brought in as if it were branch work. That breaks both the
size gate and the review packet. The right comparison point is *R as if it
had been synced the same way*. The helper builds it like this:

- `git merge-tree --write-tree R P` gives the clean merge tree T. Exit 1
  (conflicts) means `sync_not_reproducible`. Comparing against a tree full of
  conflict markers would be meaningless, and the real sync's resolution is
  then exactly what needs full review. This includes a lockfile conflict that
  SYNC.md's allowlist auto-resolved: a branch that changed `flake.lock` as
  the integration branch also moved it gets the full review. That case is
  rare and conservative, and resolving the lockfile again is out of the
  helper's scope.
- `git commit-tree T -p R -p P` builds a commit with `--no-gpg-sign` and a
  fixed identity and date (the `review-range` name, the Unix epoch) and a
  message naming R and P. The OID therefore depends only on R, P and T. A
  relaunched owner gets the same `review_base`, so the PR-body record is
  stable.

`review_base..H` is then the diff of the post-R commits (fix wave,
consolidation docs, ship-time fixes) **plus** each sync's conflict
resolutions and sweeps. `git log review_base..H` lists exactly those commits,
so every consumer of a `<base>..<head>` range works on it unchanged: diff-scope,
`codex-collaboration`'s `diff-review`, and the native reviewer templates. The
base commit is never referenced by a ref, never pushed and never selected. It
is a scratch object in the shared object store, and `git gc` prunes it like
any other unreachable object. The branch's real commits still go through
`launch-commit` and are signed. This object is not branch history, so neither
fence applies to it.

### One two-axis review over the selected range (D4)

The Phase-5 "Pick the path first" section keeps its prerequisites and replaces
its whole-branch size bullet with the `review-range` call. The thresholds are
spelled in the bullet as they are today (≤1,000 product lines AND ≤20 product
files) and passed to the helper. The old single-reviewer merge-delta check
leaves Phase 5. Its delta is now reviewed on two axes. The
`ship-issue-merge-delta-review` dispatch site stays in SKILL.md, because
CI-MERGE.md's post-selection sync still reviews each later sync merge
(`git show --cc`) with it, unchanged.

The two axes use the existing `ship-issue-full-conformance-review` and
correctness-route sites. Only the range they receive changes:
`<review_base>..$HEAD_SHA` on `delta`, `$BASE_SHA..$HEAD_SHA` on `full`.
The correctness ladder (blocked / `diff-review` / native fallback), the
severity mapping, the five-step apply/push flow, the scoped `reviewer-lite`
re-review and durable Minor/Discussion detail all apply to both ranges
without change. A fix that lands moves `HEAD_SHA`, as today. The range is not
re-selected. The re-review is the bounded fix diff.

The PR body records the route on the same surface that today records "nothing
to review" and the `diff-review` scope:
`review range: delta <review_base7>..<head7> since final-review <R7> (<L> lines, <F> files)`,
`review range: empty since final-review <R7>`, or `review range: full (<reason>)`.
On `empty`, Phase 5 skips to Phase 6, as an empty merge delta does today.
There is nothing to scope a review to, and sdd's final review already covered
every line.

### Conformance scoped to the delta (D5)

The conformance axis keeps sdd's `conformance-reviewer-prompt.md` and receives
the issue, spec and plan paths. On `delta`, its brief adds three things. First,
the final-review head R, with a statement that sdd's final review already graded
delivered-vs-promised for the branch at R. Second, its job: judge whether each
delta change keeps the branch consistent with the issue, spec, plan and
standards. That covers fix commits that resolve findings without breaking a
promise R already kept, sync resolutions, and learning docs. It also covers
SYNC.md's retirement and addition scope-creep categories plus every review
hint path in the retained snapshot, which together were the old merge-delta
checklist. Third, the stale-prose audit covers only files the delta touches.
It does not grade the whole branch's delivery again. That is the duplicate
work this issue removes. REVIEW.md's template section owns this brief once,
and SKILL.md links to it.

### Required-only CI wait (D6)

Phase 6's blocking command becomes:

```
timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30
```

gh's `--required` keeps only checks the forge reports as required for this
PR's base. The rule set is branch protection's own, so ship never keeps a
copy of a check list. Everything else about the wait is unchanged:
foreground only, one blocking call, exit 124 means a narration turn and then
the identical command (up to 8 times), the tip check comes first, there is no
improvised polling, and docs-only diffs skip the phase. With `--fail-fast`,
any other non-zero exit now means a *required* check failed, which takes
today's `gh run view <run-id> --log-failed` route. The guard's merge
validation and branch protection are not touched. The forge still refuses a
merge whose required checks have not passed.

### Advisory states reach the summary through `notes` (D7)

When the required watch exits 0, ship runs
`gh pr checks <pr-num> --json name,bucket` once. This is the one non-watching
`gh pr checks` call CI-MERGE.md already allows per phase, and it exits 0
whether or not checks are pending. Every row whose bucket is not `pass`
(`pending`, `fail`, `cancel`, `skipping`) is a check that was not required,
since every required check has already passed. Ship appends them to the ship
summary's `notes` as `advisory CI: <name>=<bucket>, …`. When the list does not
fit the shared notes bound, it ends with `+<n> more`, and a non-null
`report_path` stays named first. Under lifecycle identity the line goes in
the legacy row's `notes`, which `ship-summary/v2` carries as
`historical_owner_result`. An advisory `fail` does not block the merge, and
ship reports it truthfully.

No new field goes into `ship-summary` or `ship-summary/v2`. Notes are the
closed schemas' bounded free-text channel, and a structured advisory field
would need validator, wire-model and workflow-state changes for a value
nothing consumes mechanically (YAGNI).

### No required set falls back to waiting on all checks (D8)

gh ends a `--required` watch at once, with exit 1, when no required check has
been reported. It does not wait for one to appear. That happens in two cases:

- the PR's base marks no check required. One example is a declared
  integration branch such as `dev`, which the guard exempts from the
  protection demand. For that branch, "its CI gate stays in the shipping
  flow's wait-for-checks" (CLAUDE.md);
- the required check run has not been created yet on a head that was just
  pushed.

The two cases are indistinguishable from outside, and in both the safe answer
is today's behavior. When the required watch fails with gh's
`no required checks reported` error, Phase 6 switches to today's
`timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30` for the
rest of the phase, under the same retry budget. Ship then lists no advisory
states, because every check was gating, and notes say
`CI: no required checks reported; waited on all`. A required-only wait never
merges with fewer gates than the all-checks wait it replaces, which keeps the
rejected "ungated agent merges" idea rejected
(`.agents/knowledge/rejections/ungated-agent-merges.md`).

### Surfaces updated together (D9)

These ship as one change: `ship-issue/SKILL.md` (flow line 5/6, Phase 5 gate
and routes, Phase 6 command), `REVIEW.md` (the merge-delta section becomes
the delta-route conformance brief and the PR-body route record),
`CI-MERGE.md` ("Why the blocking watch", exit codes, fallback, advisory
listing), `ship-issue/evals/evals.json` eval 1's expected output (the
command, and the gate measured on the delta), `from-issue/ship-handoff.md`
(the `head_sha` mapping, the Phase-5 bullet's reviewer count, now zero or two first-pass reviewers, and the Phase-6 bullet's `--required`), from-issue
SKILL.md's sentence about the Phase-5 decision, and `sdd/SKILL.md` +
`final-review.md` (D1's field meaning). `ship-release` keeps its own all-checks
wait. It merges integration into default under the release arm's
fully-green-rollup rule, so the rule is different.

## Test seams

1. **`python -m agent_tools.review_range` over scratch git repositories.** This
   follows `home/common/agent-skills/tests/test_diff_scope.py`'s CLI layer: a
   `TemporaryDirectory` repo, no network, and assertions on the parsed stdout
   object and the exit code. Required cases, which are the acceptance
   criterion: R a first-parent ancestor and within the gate → `delta` with
   `review_base` = R; **non-ancestor** R → `final_review_head_not_on_branch`;
   **missing record** (no `--final-review-head`) → `no_final_review_head`;
   **over-gate delta** → `over_gate` with the measurement. Also: R = H →
   `empty`; a sync merge on the path → `delta` whose measurement leaves out the
   integration commits and whose `review_base` OID is the same on a second
   run; a non-sync merge → `foreign_merge`; a conflicting reproduction →
   `sync_not_reproducible`; R reachable only through a second parent →
   `final_review_head_not_on_branch`; an unresolvable `--head` → exit 1, empty
   stdout. Pure decision functions can also be imported and tested
   directly.
2. **`test_workflow_skill_contracts.py` skill-contract tests.** The existing
   degradation-gate tests move to the new bullet and keep
   `GATE_LINE_BOUNDARY`/`GATE_FILE_BOUNDARY` as the one spelling. They pin the
   whole `review-range` invocation, including `--max-lines 1000 --max-files 20`,
   the delta and full ranges, the exact Phase-6 command with `--required`, the
   fallback trigger and command, the advisory `--json name,bucket` call, and
   eval 1's restatement of the command. The sdd/handoff tests pin D1's
   `head_sha` meaning.
3. **The installed launcher.** The new command-table row is covered by the
   existing launcher and sibling tests (`tests/test_agent_tools_launchers.py`,
   `tests/test_agent_tools_siblings.py`) with no new seam. The new test file
   joins the `agent-workflow-tests` recipe.

## Acceptance criteria and verification

- AC1 → D1–D5 and seam 1's four named cases.
- AC2 → D6–D8 and seam 2's pinned command shape.
- AC3 → `just build` (the command-table row, import checks) and
  `just agent-workflow-tests`.

## Out of scope

- Any change to the lifecycle guard (`lifecycle_guard.py`), its merge
  validation, the required-check floor, or `.github/branch-protection.json`.
- sdd's own review mechanics: the final review, the fix wave and the re-review
  rules. Only the meaning of the `head_sha` field it already reports is
  pinned.
- CI workflow changes. The advisory job stays as it is.
- New fields in the sdd report, either handoff schema, `ship-summary` or
  `ship-summary/v2`.
- CI-MERGE.md's post-selection sync review route and `ship-release`'s CI wait.
- from-issue's inline fallback for when no ship-issue is installed. It keeps
  its own full first-pass review and all-checks wait.
- Re-selecting the range after a Phase-5 fix. The bounded fix re-review stays
  as it is.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The final-review head is sdd's existing `head_sha`, now defined as the final review's first-pass `DELIVERY_HEAD` (with `base_sha` = `DELIVERY_BASE`), carried unchanged as the handoff's `head_sha`; only a `clean` review_state supplies it | Issue Q1 (agent-choose) and its hint that the report already carries base/head; REVIEW.md already speaks of "the head sdd reviewed"; the fix wave is only scoped-re-reviewed, so it belongs in the delta | A new `final_review_head_sha` field in three closed schemas (sdd, legacy handoff, `ship-handoff/v2`): schema churn for a value the existing field already names; the post-fix tip as head: would drop the fix wave from ship's full-rigor review |
| D2 | Range selection is an executable read-only `agent_tools.review_range` command (`review-range`), JSON out with closed `route`/`reason` codes, thresholds passed in by the skill, exit 1 → the skill treats it as `full` | Issue Q2 and AC1's executable cases; agent-helpers.md rules 1–2; diff-scope D9 (the helper carries no threshold; SKILL.md is the policy's one home); the gate's "no measurement is not a small diff" | Prose-only selection: the four AC cases can't be tested; folding it into `diff-scope`: mixes ancestry policy into a pure accounting command; thresholds built into the helper: a second home for the gate |
| D3 | On a first-parent path with sync merges, the delta base is a deterministic unsigned, unreferenced `commit-tree` of `merge-tree --write-tree R P`; a conflicting reproduction, or any non-sync merge, routes to `full`; the whole check requires first-parent reachability, not just ancestry | `R..H` would count the integration branch's commits as branch work; CI-MERGE.md's sync-run definition; consumers (`diff-scope`, `diff-review`, templates) all take a commit range | Plain `R..H`: inflated gate and packet; listing each commit's patch plus `--cc` merges: no single range for `diff-review` or the gate; a tree-only base: breaks `git log`-based range consumers; a signed base commit: needs a key and is never history |
| D4 | The delta route runs the full two-axis machinery through the existing dispatch sites over `<review_base>..$HEAD_SHA`; Phase 5's single-reviewer merge-delta check is retired (its site stays for CI-MERGE's post-selection sync); an empty delta still skips with a PR-body record; the existing clean/no-escalation/not-risky/capability prerequisites stay | Issue: "correctness at full rigor on the delta … never skipped, only scoped"; precedent for the empty-delta record; reusing the sites keeps the model matrix and dispatch contracts unchanged | Keep the one-reviewer merge-delta check: violates correctness at full rigor; new `delta-*` dispatch ids: more surfaces for the same tiers; dropping the old prerequisites: widens scope beyond the issue |
| D5 | Delta-scoped conformance keeps sdd's template plus issue/spec/plan, is told R was already graded, judges only the delta's changes (incl. SYNC.md scope-creep categories and review hints), and limits the stale-prose audit to delta-touched files; REVIEW.md owns the brief | Issue Q4 (deferred to design); the merge-delta checklist being retired by D4 has to live somewhere; DRY: one brief home | Re-grading delivered-vs-promised on the whole branch: the exact duplicate this issue removes; no spec/plan context: can't judge whether a fix broke a promise |
| D6 | Phase 6 blocks on `timeout 300 gh pr checks <pr-num> --required --watch --fail-fast --interval 30`; the required set is the forge's, never a list kept in ship | Issue AC2; gh 2.93 `--required`; branch protection is the source of truth; #261's foreground/in-turn rules unchanged | Naming `Nix Eval` in the skill: a second copy of branch protection that breaks in other repos; filtering `--json` output by hand: improvised polling, banned by CI-MERGE.md |
| D7 | Advisory (non-required, non-`pass`) states come from one post-success `gh pr checks <pr-num> --json name,bucket` and go into the ship summary's bounded `notes` (`advisory CI: …`, `+<n> more`), the legacy row under v2 | Issue Q3 (agent-choose); notes are the closed schemas' bounded channel (500 chars, policy file); CI-MERGE.md allows one non-watch call per phase | A new summary field: validator, wire and ledger churn for data nothing consumes (YAGNI); a PR comment: a new forge write with no reader |
| D8 | gh's `no required checks reported` refusal (no required set on the base, or a required check not yet reported) switches the rest of Phase 6 to today's all-checks watch under the same retry budget | gh exits 1 immediately in that state (no waiting); CLAUDE.md: a declared integration base's CI gate stays in the shipping flow's wait-for-checks; rejections/ungated-agent-merges.md | Treating it as "nothing to wait for": ungated merges on unprotected bases; treating it as a CI failure: false stops on every fresh push; retrying the required watch: spins with no wait between attempts |
| D9 | `ship-release`'s CI wait and CI-MERGE.md's post-selection sync review are left unchanged | Issue scope boundary (ship-issue only); the release arm requires a fully green rollup | Making ship-release required-only too: contradicts the release arm's fully-green rule and is out of the issue's scope |
| D10 | Ship's terms are *final-review head* (R, sdd's first-pass `DELIVERY_HEAD`) and *review base* (`review_base`); the existing "reviewed `HEAD_SHA`" stays ship's own reviewed tip; the helper spells R as `--final-review-head` / `final_review_head` | Grill: ship-issue already uses "reviewed `HEAD_SHA`" for its Phase-6 tip check, so a second "reviewed head" would be ambiguous | Calling R the "reviewed head": collides with the Phase-6 tip check's term; naming it `DELIVERY_HEAD` at ship: leaks sdd's ledger variable into a surface that only sees the report |
| D11 | REVIEW.md keeps its merge-delta section, narrowed to CI-MERGE.md's post-selection sync (`git show --cc` scope and checklist unchanged), and gains a separate delta-route conformance brief; SKILL.md keeps the merge-delta marker and call line byte-identical under a paragraph naming post-selection sync as its only caller; that route's "Run Phase 6's CI wait" step inherits D6–D8 by reference | CI-MERGE.md step 3 runs "REVIEW.md's merge-delta check"; `model-matrix.json` pins the site's call line; D9 keeps that review route unchanged | Rewriting the merge-delta section into the delta brief (D5's wording): orphans CI-MERGE's step 3; restating a separate all-checks wait for post-selection sync: a second CI-wait home |
| D12 | `review-range --root` is optional and defaults to the current directory, as `diff-scope`'s does; Phase 5 runs it inside the worktree and omits `--root` | `diff-scope`'s parser precedent; the gate test's existing `--root`-absent pin | A required `--root <worktree>` (D2's sketch): a second path spelling in the gate for the directory ship already runs in |
