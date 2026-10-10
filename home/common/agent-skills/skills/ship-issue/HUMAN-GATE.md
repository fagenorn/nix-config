# Consolidated operator gate

## When to enter

Enter only when SKILL.md's `## Standing authorization` finds no repository policy or explicit
user grant covering the concrete action and target. Enter the gate *instead of* attempting the
verb. There are up to two gates on the successful path — one before the first push, one before the merge — and
only those whose actions lack existing authorization are entered. The gate makes the remaining
external effects reviewable; it does not grant them itself, and the host's actual automatic
approval decision still governs execution.

## In --auto

In `--auto`, present the gate's block and then pause through whoever owns the
ledger. A fresh ship owner launched per `from-issue/ship-handoff.md` writes no
workflow state beyond the `checkpoint-delivery` cycles of SKILL.md's
`## Delivery loop` — it never suspends or finishes its custody — so
it presents the block and returns the truthful `stopped` ship summary naming the
human gate, validated through
`artifact-budget validate-report --boundary ship-summary` like every other ship
return, keeping the worktree and claiming no merge success; its parent, the
`from-issue` owner, is what suspends `blocked_on: human_gate` and prints the
canonical re-entry line. A `from-issue` owner running this path itself, with no
fresh ship owner in between, follows `from-issue/SKILL.md`'s existing suspension
procedure directly — suspending `blocked_on: human_gate` and printing that same
line. This file defines no new suspension shape and no new `blocked_on` value.

## Gate 1 — before the first push (Phase 4)

Present Phase 4's push and `gh pr create` commands, in that order, as literal text the
operator can read and repeat in their own message.

Present the body fully rendered — the resolved bindings substituted, the `## Acceptance` section
filled from Phase 0's effective acceptance state, and the `Closes #<num>` trailer present on the
close branch and absent on a hold.

Gate 1 also names the second, final gate that follows CI and what it covers.

## Gate 2 — after CI, before the merge (Phase 7)

Present the merge command exactly as Phase 7 renders it.

The same grant covers the rest of the chain, in this order:

- `gh issue close <num>`, when the issue is still open;
- on a hold instead, Phase 8 step 1's hold branch: `gh issue reopen <num>` when
  the merge closed it, `gh label create needs-verification` when the label is
  missing, `gh issue edit <num> --add-label needs-verification` and
  `gh issue comment <num>`;
- `git push origin --delete <branch>` (`## gh hygiene`), only when
  `git ls-remote --heads origin <branch>` is non-empty;
- `git worktree remove <worktree-path>`, run from the main repo root;
- `git branch -d <branch>` (`## gh hygiene`).

After this grant nothing further is asked on the successful path: the same
session resumes in place and runs the chain to issue close or hold and cleanup. A
transient execution failure does not erase the grant; retry only after
diagnosing it and re-validating the same required checks.

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
  the base branch's required status check.

## Never route around a denial

A denial creates exactly the pressure to be creative, so the ban is stated as a
closed list.

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
