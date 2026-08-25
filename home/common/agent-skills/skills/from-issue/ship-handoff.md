# Phase 7 detail — ship handoff and inline fallback

Loaded from `SKILL.md` at Phase 7.

## Ship-owner subagent prompt

The handoff goes in the prompt, not a file — the subagent's starting context *is*
the prompt. Recheck the current spec and plan roots immediately before building
it and include their canonical checker objects. The public handoff must never carry task member paths
and must never carry artifact contents; ship-issue
discovers validated members locally. A durable SDD `report_path` is relative to
the primary worktree and is the only detail pointer.

```
You are running ship-issue for issue #<num> in <autonomous|interactive> mode. Use
"autonomous" only when the from-issue invocation included `--auto`; otherwise use
"interactive".

Handoff from from-issue is the canonical stdout from
`artifact-budget validate-report --boundary ship-handoff` over a candidate with
exactly these fields:
{"state":"complete","ledger_repo_root":"<immutable ledger root or null>","run_id":"<run or null>","attempt":<integer or null>,"owner":"<owner or null>","owner_worktree":"<owner worktree or null>","action_id":"<action id or null>","issue_number":<num>,"branch":"<branch-name>","worktree_path":"<absolute-worktree-path>","spec_artifact":{"kind":"design-spec","path":"<root>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"plan_artifact":{"kind":"implementation-plan","path":"<root>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"head_sha":"<full sha>","review_state":"clean|residuals","auto":true,"report_path":null,"notes":"<bounded notes>"}

Use `state: failed` only according to the ship-handoff validator's before/after
matrix. `notes` is bounded by `phase_reports.notes_max_characters`; it names a
non-null `report_path`. Build a candidate file, validate it, and dispatch only
the validated stdout bytes. A residual SDD report requires the durable path.

`action_id` is the `issue:attempt:launch` string the acquisition envelope
issued; it joins the all-or-nothing lifecycle group and is passed through
verbatim — never recomputed, never derived from `attempt` — so ship-issue's
launch guard can re-validate it before each forge write.

Your task:
  1. Invoke the `ship-issue` skill via the Skill tool. Read its SKILL.md and follow
     every phase 0 → 8 in order. The pre-flight checks still run — the handoff is a
     hint, the worktree state is ground truth.
  2. In Phase 5 (PR review), follow ship-issue's path selection — it may dispatch
     zero (empty merge-delta), one, or two reviewer subagents.
     Nested Agent calls are supported.
  3. In Phase 6, block on `<tracker-cli> pr checks --watch` per ship-issue's
     instructions.
  4. If auto is true, apply ship-issue's auto-mode rules throughout: apply Blocking
     and Should-fix items inline rather than surfacing; only Discussion items and
     genuinely blocked situations should return to me. If auto is false, honor every
     ship-issue checkpoint and confirmation; return anything requiring a user decision
     instead of treating it as autonomous.

Return exactly canonical JSON from `artifact-budget validate-report --boundary ship-summary`
over a candidate with these exact keys: `issue`, `state`, `pr_url`,
`merge_sha`, `issue_closed`, `discussion_items`, `detail_state`, `report_path`,
and `notes`. `discussion_items: []` because non-empty details are moved to the
single report. `detail_state` is `none`, `present`, or failure-only `unpublished`
per the validator matrix. With `unpublished`, name the readable retained source
in notes, keep the worktree, and do not claim merge success. Never inline detail.
```

## Inline fallback (no ship-issue skill)

Deliver inline: push the branch, open a PR against `<integration-branch>`, then use the same full-review tier over the diff:

<!-- agent-dispatch: id=from-issue-inline-ship-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") launches a fresh first-pass reviewer over the shipping diff.

Then wait for CI (`<tracker-cli> pr checks --watch`), merge `--no-ff`, close the
issue, and publish every non-empty review detail beneath the primary worktree's
`.superpowers/issue-delivery/` home before cleanup. Publication failure must keep
the worktree and report `unpublished`. With `issueTracker.kind=none`, merge
locally and clean up under the same detail rule.
