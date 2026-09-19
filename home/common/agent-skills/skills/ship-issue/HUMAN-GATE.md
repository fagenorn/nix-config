# Consolidated operator gate

Read this only when SKILL.md's `## Standing authorization` finds no repository
policy or explicit user grant covering the concrete action and target. The gate

This included document receives the phase owner's retained `ResolvedProject`; it uses passed `bindings.tracker` and `bindings.vcs` values without resolving or inferring policy.
makes the remaining external effects reviewable; it does not grant them itself,
and the host's actual automatic approval decision still governs execution.

Enter the gate *instead of* attempting the verb — never attempt a shipping verb
and then react to the denial.

There are up to two planned gate locations on the successful path — one before
the first push, one before the merge — and only those whose actions lack existing
authorization are entered.

In `--auto`, present the gate's block and then pause through whoever owns the
ledger. A fresh ship owner launched per `from-issue/ship-handoff.md` writes no
workflow state — the read-only `check-launch` query is its one ledger call — so
it presents the block and returns the truthful `stopped` ship summary naming the
human gate, validated through
`artifact-budget validate-report --boundary ship-summary` like every other ship
return, keeping the worktree and claiming no merge success; its parent, the
`from-issue` owner, is what suspends `blocked_on: human_gate` and prints the
canonical re-entry line. A `from-issue` owner running this path itself, with no
fresh ship owner in between, follows `from-issue/SKILL.md`'s existing suspension
procedure directly — suspending `blocked_on: human_gate` and printing that same
line — exactly as `from-issue/AUTO.md`'s final paragraph already says. This file
defines no new suspension shape and no new `blocked_on` value.

## Gate 1 — before the first push (Phase 4)

Present both commands as literal text the operator can read and repeat in their
own message, in this order:

```
git push -u origin <branch>
```

```
gh pr create --base <integration-branch> --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-4 bullets of what shipped>

## Spec
<spec-path>

## Plan
<plan-path>

Closes #<num>
EOF
)"
```

Present the body fully rendered — the heredoc expanded, the resolved bindings
substituted, the `Closes #<num>` trailer present. Both commands are fully
determined at this moment, so neither needs a later correction.

Gate 1 also names that a second and final gate follows after CI and what it will
cover, so the operator sees the whole remaining chain once.

## Gate 2 — after CI, before the merge (Phase 7)

Present the merge command exactly as Phase 7 renders it. Its `<pr-num>` exists
only now, which is why this cannot be folded into Gate 1.

The same grant covers the rest of the chain, in this order:

- `gh issue close <num>`, when the issue is still open;
- `git push origin --delete <branch>`, taken only when
  `git ls-remote --heads origin <branch>` is non-empty;
- `git worktree remove <worktree-path>`, run from the main repo root;
- `git branch -d <branch>`.

Phase 6's CI wait has already bound before this gate is entered, and the grant
does not re-litigate it.

After this grant nothing further is asked on the successful path: the same
session resumes in place and runs the chain to issue closure and cleanup. A
transient execution failure does not erase the grant; retry only after
diagnosing the failure and re-validating the same required checks. An actual
permission denial stops the action and is never retried through another spelling.

## Grant semantics

These apply to both gates.

- A grant covers the concrete actions, targets, and external effects presented.
  It survives harmless quoting or spelling changes and transient failures; it
  does not expand to a different repository, branch, PR, or effect.
- Silence is not a grant. No reply → keep waiting (interactive) or stay
  suspended (`--auto`). A partial reply grants only the commands it names.
- An actual automatic approval denial stops the current attempt. Report the
  denied action and reason; do not change its spelling, delegate it, or switch
  hosts to obtain a different result. A later user message that supplies
  genuinely missing authority or material new evidence may resume through the
  normal approval review. Never infer that authority from a retry.
- The grant is additional to every check the Claude path performs, never a
  substitute: `check-launch` still runs before every pre-merge forge write,
  Phase 6's tip check and the CI wait still bind, and the merge still requires
  the base branch's required status check. Nothing here weakens
  `.out-of-scope/ungated-agent-merges.md`.

## Never route around a denial

A denial creates exactly the pressure to be creative, so the ban is stated as a
closed list. It restates for this path the ban Phase 1 already places on
rewriting the integration branch.

On this path the session must not:

- merge the feature branch into the passed `<integration-branch>` locally;
- push to the passed `<integration-branch>`;
- push to any remote other than `origin`;
- pass `--admin`, `--force`, `--force-with-lease`, or any hook-bypass flag;
- rewrite, reset or rebase any branch to change what a denied command would have
  done;
- re-attempt a denied command in a re-worded or re-quoted spelling;
- ask a subagent, another skill, or another host to run the command on its
  behalf.
