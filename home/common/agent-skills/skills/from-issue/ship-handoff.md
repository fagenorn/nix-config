# Phase 7 detail — ship handoff and inline fallback

Loaded from `SKILL.md` at Phase 7.

## Ship-owner subagent prompt

The handoff goes in the prompt, not a file — the subagent's starting context *is* the prompt:

```
You are running ship-issue for issue #<num> in <autonomous|interactive> mode. Use
"autonomous" only when the from-issue invocation included `--auto`; otherwise use
"interactive".

Handoff from from-issue:
  ledger_repo_root: <immutable ledger root from the lifecycle envelope>
  run_id:            <run id from the lifecycle envelope>
  attempt:           <attempt from the lifecycle envelope>
  owner:             <owner from the lifecycle envelope>
  owner_worktree:    <separate owner worktree from the lifecycle envelope>
  issue_number:   <num>
  branch:         <branch-name>
  worktree_path:  <absolute-worktree-path>
  spec_path:      <relative-from-repo-root>
  plan_path:      <relative-from-repo-root>
  head_sha:       <SHA at end of Phase 6 execute>
  review_state:   <clean | residuals | unknown — from sdd's report>
  auto:           true|false  (from --auto flag)
  summary:        <one paragraph: what shipped, key deltas the PR reviewer subagent
                   should weight heavily, anything non-obvious about scope>

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

Return to me, as your final message, exactly this report — details live in the
PR and the worktree, not the report:
  issue:            <num>
  state:            merged | stopped | failed
  pr_url:           <url>
  merge_sha:        <sha on the integration branch>
  issue_closed:     true | false
  discussion_items: <reviewer's Discussion/Minor items, verbatim, labeled by axis
                     when the two-axis path ran; [] if none>
  notes:            <≤500 chars: anything that needed manual intervention>
```

## Inline fallback (no ship-issue skill)

Deliver inline: push the branch, open a PR against `<integration-branch>`, then use the same full-review tier over the diff:

<!-- agent-dispatch: id=from-issue-inline-ship-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") launches a fresh first-pass reviewer over the shipping diff.

Then wait for CI (`<tracker-cli> pr checks --watch`), merge `--no-ff`, close the issue, and clean up the worktree + branch. With `issueTracker.kind=none`, merge locally and clean up.
