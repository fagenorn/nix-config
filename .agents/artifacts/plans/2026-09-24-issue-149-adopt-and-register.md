# Adopt and Register nix-config Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes. `sdd` runs only the
> Task index. The owner delivery steps are never `sdd` tasks.

**Goal:** Re-point the living references (Tasks 1–2). Then adopt nix-config with the
deployed `adopt-project`, land its one commit, and register it after the merge (B1–B9).

**Architecture:** One hand-authored task comes before any tool output (D3, D4). After
the loop, the issue owner runs B1–B7 in Phase 6 while the attempt is `active`. The ship
owner runs B8–B9 (D11). The adoption commit is the branch's last authored commit.

**Authority:** the spec `.claude/specs/2026-09-24-issue-149-adopt-and-register-design.md`,
with its Stage B and `## Decision ledger` (D1–D14). From B5 on, the spec and this plan
live where the migration map puts them (D7).

## Global Constraints

- Never run `just switch`, a force-push, `--acknowledge-deletions`, a second or
  incremental adoption, or `git verify-commit` (D1, D5, D9).
- Commits are signed, never `--no-gpg-sign`. Each authored commit ends with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01XJQu22Bg2fayzv7KNKKbaA`. The tool's
  commit carries the fixed #121 D28 message and no trailer.
- No commit message or PR body on this branch carries a closing keyword for #149 (D6).
- Never change `adopt-project`, its libraries, `resolve-project`, the classifier,
  `ship-issue`, `workflow-state` or the eval fixture contract. A gap becomes a new issue
  (#71). Point-in-time records and test fixtures are never rewritten.

## Test seams

These are the spec's seams: the installed CLIs run as subprocesses, git plumbing is the
review oracle, and GitHub's commit `verification` is the signature oracle. No test is
added.

## Delivery estimate and boundaries

These are estimates. Task 1 changes 8 lines in 4 files; Task 2 (D15), 1 line. The adoption commit has about 244
`R100`, 3 `A` and 2 `M`. It is never split (D9), and the work ships as one PR.

## Task index

Task 1 — Re-point the eight living references to the adopted paths — `CLAUDE.md`, `docs/standards/agent-helpers.md`, `home/common/agent-skills/README.md`, `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md` — full — [task-1.md](2026-09-24-issue-149-adopt-and-register.tasks/task-1.md)

Task 2 — Re-point the sibling-added reference — `docs/standards/agent-helpers.md` — full — [task-2.md](2026-09-24-issue-149-adopt-and-register.tasks/task-2.md)

## Decisions

Tasks 1–2 rest on D3 and D4 (Task 2 on D10, D15), and the owner steps on D1, D2, D5–D7 and D9–D14.

## Owner delivery steps (not sdd tasks)

Notation: `WT=/Users/anis/tmp/nix-config/.worktrees/worktree-issue-149-orchestrated`,
`P=/Users/anis/tmp/nix-config`, `A=$HOME/.agents/bin`, and a scratch dir
`D=$(mktemp -d "${TMPDIR:-/tmp}/i149-XXXXXX")`, created at B3 and removed after B7.
The values carried between steps are `D`, `M`, `BASE`, `PLAN_ID`, `DIGEST` (the id without `sha256:`), `BRANCH` and
`ADOPT`. Shell variables do not survive between separate tool calls, so each step prints
the values it records and later steps substitute them as literals. Snippets run under `bash`, and every command runs in `$WT` unless a step names
`$P`. A failed assertion stops the run with the issue open, unless the step names another
route. **Back to the loop (D13):** any route that returns to the `sdd` loop at or after B5
first runs `git reset --hard <BASE>` (local and pre-push only), then adds the new task
and restarts Stage B at B1. Task 1's three moves are these. The two specs
`.claude/specs/2026-09-20-issue-116-permission-guard-core-design.md` and
`.claude/specs/2026-09-24-agent-tools-package-design.md` each go to
`.agents/artifacts/specs/<same name>`. The rejection
`.out-of-scope/ungated-agent-merges.md` goes to
`.agents/knowledge/rejections/ungated-agent-merges.md`.

**B1 — Fresh base** (issue owner). Require `git status --porcelain` to be empty. Run
`git fetch origin && git merge --no-edit origin/main`, resolving any conflict under
ship-issue's `SYNC.md`. Then run `just build`, which must exit 0 and leaves the ignored
`./result`. Record `M=$(git merge-base HEAD origin/main)`. Re-run Task 1's check (1)
`git grep` on the synced head. A hit means a sibling added a living legacy reference, so
the owner goes back to the loop with a new re-pointing task (D10).

**B2 — Operator gate** (issue owner; D1, D12). Locate the built generation. Run
`set -- $(nix-store --query --requisites ./result | grep -- '-home-manager-files$')`,
require `$# -eq 1`, and set `H=$1`. For each of `bin/adopt-project`, `bin/resolve-project`,
`bin/conformance`, `bin/conformance-registry`, `bin/conformance-checks`,
`lib/python/agent_platform.py`, `lib/python/adopt_inspection.py`,
`lib/python/adopt_planning.py`, `lib/python/adopt_apply.py`, `lib/python/adopt_verify.py`
and `share/platform-manifest.json`:
- if `test -f "$H/.agents/$f"` fails, stop. That is a build defect, not a gate.
- if `cmp -s "$H/.agents/$f" "$HOME/.agents/$f"` fails, collect `.agents/$f`. Both
  sides follow their store symlinks, and a missing deployed file counts as a difference.

If anything was collected, first print this notice: "Operator gate (#149 D1): the deployed
agent runtime differs from `main` at `<M>` in: `<collected names>`. Fast-forward `main` in
`<P>` to `<M>` or later, run `just switch` there, then resume." Then run `workflow-state
suspend --repo-root <ledger_repo_root> --run-id <run> --now <utc> --issue 149 --attempt <k>
--blocked-on human_gate`. The last line printed is `Suspended (blocked_on=human_gate).
Resume: <reentry>`. On resume, restart at B1.

If nothing was collected, `just agent-workflow-tests` must exit 0 under the real `HOME`,
with the log on disk and only its tail read. If it fails and, after `git fetch origin`,
`origin/main` has moved past `M`, restart at B1. Otherwise stop. A red pre-adoption head is not the adoption's to fix.

**B3 — Plan** (issue owner; AC1). Run `$A/adopt-project plan --repo-root "$WT"` into
`$D/plan1.json` and again into `$D/plan2.json`. `cmp` must succeed. With `python3` over
`plan1.json`, assert every live value below. None of the probe's counts is asserted.
- `plan.state == "ready"`, `plan.outcome == "reconcile"`, `decisions.open == []`, and
  `plan.base_revision == $(git rev-parse HEAD)`;
- no `evidence[].action` is `needs-decision`, `archive-history` or
  `delete-exact-duplicate`;
- no `changes[]` entry has `op == "delete-file"` or `approval_class == "destructive"`;
- each `git-mv` has one source and one target. The set of sources equals the NUL-split
  output of `git ls-files -z -- .claude/specs .claude/plans .out-of-scope`;
- the `git-mv` target of each Task 1 old path equals Task 1's new path, for all three.

Record `PLAN_ID=plan.plan_id` and `BASE=plan.base_revision`. A contract or engine gap stops
the run (#71). **Benign re-plan (D13):** the inspection counts registered worktrees into
`evidence`, so a sibling adding or removing a worktree changes `plan_id`. If the `cmp`
differs, or B4 refuses with `adopt.plan.inputs_changed`, while HEAD is unchanged and the
tree clean, re-run B3 with no rebuild. Allow at most three re-plans, then stop.

**B4 — Apply** (issue owner; D2, D10). Run `$A/adopt-project apply --plan-id "$PLAN_ID" >
$D/apply.json` under the real `HOME`.
- On exit 0, record `BRANCH=.branch`, which must equal `adopt-${DIGEST:0:12}`, and
  `ADOPT=.commit`.
- On exit 2, read `error.code` and `error.repair_id`. A stale plan goes back to B1 (or to
  B3 under the benign re-plan rule), and a stale id is never re-run.
  `adopt.commit.failed` (signing) and `adopt.commit.unresolved_policy` are environment or
  contract failures: stop with the issue open, with no loop task. A failed commit gate retains
  `~/.agents/state/adopt/worktrees/$DIGEST`, and its `$DIGEST.failure.json` beside it
  names the gate. For `workflow-verification-commands`, rerun `just build` or
  `just agent-workflow-tests` in that worktree to see the output. Then apply D10: return
  to the loop with a new task, and restart Stage B at B1. Never delete the retained
  worktree.

**B5 — Land** (issue owner; D7). Run `git merge --ff-only "$BRANCH"`, require
`git rev-parse HEAD` to equal `$ADOPT`. Then, as a standalone command with no variable,
quoting or chaining (the `PreToolUse` guard refuses anything else), run
`git branch -d adopt-<first 12 hex of DIGEST>` with the value substituted by hand. From here on,
name the spec and plan only by the map's `new_path` for their old paths. Those are
`.agents/artifacts/specs/2026-09-24-issue-149-adopt-and-register-design.md` and
`.agents/artifacts/plans/2026-09-24-issue-149-adopt-and-register.md`, and B6 asserts that
both pairs are in the map.

**B6 — Typed-operation review** (issue owner; D9 checks 1–6). Write an uncommitted driver
at `$D/reconcile.py`. It reads the operations from
`~/.agents/state/adopt/plans/$DIGEST.json` `changes[]`, parses `-z` output into complete
sets, and hard-asserts:
1. `git rev-list --count $BASE..$ADOPT` is 1. The message after the header block of
   `git cat-file commit $ADOPT` is exactly
   `chore(adopt): adopt <plan.project_id> at plan <DIGEST[:12]>\n\npath migration map: <migration_map>\nadoption evidence record: <evidence_record>\n`,
   using `apply.json`'s values. The header block has a `gpgsig -----BEGIN SSH SIGNATURE-----` line.
2. `git diff-tree -r -M100% --name-status -z $BASE $ADOPT` has only `R100`, `A` and `M`.
   Its `R100` pairs equal the `git-mv` (source, target) pairs, which equal the map's
   `moves` (`old_path`, `new_path`) from `git show $ADOPT:<migration_map>`. `A` equals the
   `write-file` targets with a null `before`. `M` equals the `write-file` targets with a
   non-null `before`, plus the `regenerate-projection` targets whose blob id differs
   between `$BASE` and `$ADOPT`. No path appears twice.
3. For each `write-file`, `"sha256:" + sha256(git show $ADOPT:<target>)` equals `after`.
4. `git log --follow --format=%H $ADOPT -- <new_path>` prints at least 2 lines for every move.
5. `git ls-tree -r --name-only $ADOPT -- .claude/specs .claude/plans .out-of-scope` is
   empty. The same listing of `.agents/artifacts/evidence` is exactly
   `[evidence_record]`, and that record's `path_migration_map` equals `migration_map`.
   The map holds the B5 pairs for the spec and plan, and Task 1's three moves.

The issue owner then does the check-6 read-through. Read
`git show --format= -M100% --diff-filter=AM $ADOPT` against its operations: the contract
amendment, the `*\n` sentinel, `.gitignore`, the map and the record. Require
`git cat-file -e $ADOPT:<path>` for Task 1's three new paths. Require that this prints
nothing: `git grep -n -E '\.claude/(specs|plans)|\.out-of-scope' HEAD -- . ':!.agents/artifacts' ':!.agents/knowledge' ':!home/common/agent-skills/tests' ':!home/common/agent-skills/evals/fixture-repo' ':!home/common/agent-skills/scripts/adopt_inspection.py'`.
A driver failure is an engine defect: stop, and it becomes a new issue. A Task 1 defect,
or a check-6 `git grep` hit after a B7 sync, goes back to the loop by the D13 route (D10).

**B7 — Pre-push verification** (issue owner; D9 check 7, D5). At the head to be pushed:
- `just build` and `just agent-workflow-tests` exit 0.
- `$A/adopt-project verify --repo-root "$WT"` exits 0 with `result == "adopted"`,
  `adoption_commit == $ADOPT`, and the `projections-in-sync` check `passed`.
- Record the sha256 of every file under `~/.agents/state/fleet/`, or record that it is
  absent. Build a scratch home: `S=$(mktemp -d)`, then `mkdir -p $S/.agents/state`, and
  for each of `bin`, `lib` and `share` run `ln -s ~/.agents/$p $S/.agents/$p`. The command
  `HOME=$S $S/.agents/bin/adopt-project verify --repo-root "$WT" --register` must exit 2
  with `error.code == "not_integrated"`. Re-hash the fleet directory, which must match
  what was recorded, then remove `$S`.
- `$A/conformance run --purpose adoption --repo-root "$WT" --offline > $D/conf.json`
  must give `outcome.status == "passed"`, and `$A/conformance validate-report --input
  $D/conf.json` must exit 0.
- `$A/resolve-project platform-status --repo-root "$WT"` must give
  `compatibility.compatible == true`.
- **D5 stale check.** Run `git fetch origin`. The run is stale if `git log --format=
  --name-status --no-renames $ADOPT^..origin/main -- .claude/specs .claude/plans
  .out-of-scope` prints any line that starts with `A` or `D` followed by a tab.
  - Stale: run `git reset --hard $BASE` and restart at B1.
  - Not stale, but `git merge-base --is-ancestor origin/main HEAD` fails: run
    `git merge --no-edit origin/main`, then rerun B7 and the check-6 `git grep` on the
    merged head. A conflict in that merge counts as stale (D13): `git merge --abort`,
    `git reset --hard $BASE`, and restart at B1. Never resolve it by hand.
  - Engine drift (D13): if `git diff --name-only <M> origin/main --
    home/common/agent-skills/scripts home/common/agent-skills/default.nix lib/agent-tools.nix python`
    is non-empty, the deployed runtime may no longer match what B9 builds. Treat it as stale
    before push, and restart at B1, where B2 re-gates.

Then run `rm -rf "$D"`.

**B8 — Ship** (issue owner hands off; ship owner acts; D5–D7, D11). The handoff names
`spec_artifact` and `plan_artifact` by their relocated paths, re-measured there. Its
`notes` (at most 500 characters, kept near 380 so that a durable `report_path`, when
there is one, can be appended) read: "#149 (spec D5 D6 D11 D13 D14; plan B8-B9): PR body
`Part of https://github.com/fagenorn/nix-config/issues/149`, no closing keyword. D5 check
after sync and before merge; stale stops before merge. <ADOPT> needs verified=true. Fix
commits only per D14. After pr_merged, before close_tracker: B9 in
/Users/anis/tmp/nix-config, evidence comment, then close." The ship owner confirms
`gh api repos/fagenorn/nix-config/commits/<ADOPT> --jq .commit.verification.verified` is
`true` after the push (D9 check 1). It runs B7's stale check, including the D13 conflict
and engine-drift rules, at both D5 points. After a push nothing resets: stale there means
stop before merge with the issue open. After a non-stale sync it reruns B7's checks. A
ship-review fix commit may follow the adoption only under D14.

**B9 — Registration** (ship owner; D6, AC4, AC5). After `pr_merged` and before
`close_tracker`, work in `$P`:
1. Require a clean tree on `main`, then run `git fetch origin && git merge --ff-only
   origin/main`. Never force.
2. Run `just build` in `$P`, then B2's comparison against that `./result`. A mismatch
   stops before `close_tracker` with the issue open. The ship summary is a truthful
   stop that names the drifted files. The follow-up owner is the operator: run
   `just switch` in `$P`, then re-run B9 (D13's pre-merge engine-drift check keeps this
   case rare).
3. The Task 8 steps. `git merge-base --is-ancestor <ADOPT> main` exits 0. Exactly one
   record exists under `.agents/artifacts/evidence`, and
   `git log --diff-filter=A --format=%H -- <record>` gives `<ADOPT>`. Save the registry
   bytes. `verify` reports `adopted` with `adoption_commit == <ADOPT>`. `verify
   --register` exits 0, its report has `registered == true`, and it adds
   `{"project_id": "fagenorn/nix-config", "root": "/Users/anis/tmp/nix-config"}`, keeping
   every earlier entry. A
   second `--register` leaves the registry bytes identical. The
   `platform-status --repo-root $P --fleet` row reads `compatible: true`,
   `reason_code: null` and `repair_id: null`. `$A/conformance run --purpose adoption
   --repo-root "$P" --offline` gives `outcome.status == "passed"`.
4. Post one issue comment under the `current-launch` fence. It carries each command's
   verbatim output, `<ADOPT>` and the merge commit. Only then run `close_tracker`.

---

## Standards review provenance

The reviewer was the Claude fallback, fresh and read-only, because Codex failed on a usage
limit. It reviewed base `2c368486` at plan commit `37e6b97`, with no focus. Accepted: 1
blocking finding (B5) and 5 should-fix findings. Decided: 4 discussion items (D13, D14,
and B4's stop route). Rejected: 0. Deferred: 0.
