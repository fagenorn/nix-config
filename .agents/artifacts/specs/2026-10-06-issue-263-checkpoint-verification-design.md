# Full verification runs at checkpoints, not per task, issue 263

## Problem

Every plan task today names the project's whole declared verification
(`just build` and `just agent-workflow-tests` here), and the implementer
template tells each implementer to "run the full suite once before
committing". An eight-task plan therefore runs the 8 to 10 minute suite at
least eight times, more with fix rounds, and ship-issue then runs it again on
a head that sdd already verified. The per-task runs add no gate the final run
does not already give. They cost wall time, they make attempt budgets expire,
and they turn every implementer into a long-running command (the #261
cascade's raw material).

The fix keeps every quality gate. It moves the full declared verification
(`bindings.workflow.verification`, dereferenced through `bindings.commands`)
to two checkpoints: sdd's final gate, and ship. It proves the pass with a
recorded tree identity, not with prose, so ship can skip a rerun only when
the exact bytes it would verify already passed.

## Solution

Three changes, one per checkpoint ladder rung (per D1):

1. **Per task: focused tests.** The implementer, every fix round and the
   final-review fixer run the focused test commands their brief names, red
   then green, plus the brief's build check only when the task changes files
   the build evaluates. None of them runs the full declared verification.
   writing-plans makes each task brief name those focused commands, and the
   build check only where it applies (per D2).
2. **sdd's final gate: one full run, recorded.** After the final two-axis
   review's fix wave and scoped re-reviews, the controller runs every declared
   verification command once on the final head. On a pass it records the
   verified tree with a new helper, `verified-tree`, and writes the tree into
   the sdd ledger. `verification_state: passed` means exactly that recorded
   pass. A failing run gets one bounded repair round, then surfaces as a
   correctness residual (per D3, D4).
3. **Ship: run unless the tree already passed.** ship-issue's Phase 2 asks
   `verified-tree check` first. It skips the run only on `verified`, which
   means the worktree's current tree equals the recorded passing tree under
   the same declared verification list. Any other answer runs every command
   and records the new pass. REVIEW.md's apply/push step 2 and CI-MERGE.md's
   post-selection sync and amend re-runs use Phase 2's procedure, so they
   inherit the same skip rule (per D5).

## Decisions

### The `verified-tree` helper

A new `agent_tools` module with one command-table row, per the agent-helper
standard (thin shell over importable functions, strict JSON load through
`agent_tools.canonical`, tests driven from source). It runs in the current
directory's worktree and has two verbs (per D6):

- `verified-tree check --verification <id> [--verification <id> …]` computes
  the current tree and compares it with the record. It always prints one
  canonical JSON line `{"status": "verified" | "unverified", "tree": "<id>"}`
  and exits 0. It reports `verified` only when a record exists, its tree
  equals the current tree, and its verification list equals the given ids in
  order. A git failure, or a record that exists but fails strict parsing or
  its closed schema, exits 2 with one stderr line. Callers run verification
  on every answer except exit 0 `verified`.
- `verified-tree record --tree <id> --verification <id> […]` recomputes the
  current tree. If it differs from `--tree`, the tree changed while
  verification ran: it writes nothing, prints
  `{"recorded": false, "reason": "tree_changed", "tree": "<current>"}` and
  exits 3. Otherwise it atomically replaces the record and prints
  `{"recorded": true, "tree": "<id>"}`. A usage or git error exits 2.

The caller's protocol is fixed: `check`, keep its `tree`, run the declared
commands, and on a full pass `record --tree <that tree>`. A failing command
records nothing.

**What the tree is.** It is the git tree object of the working tree as
verification saw it: tracked files with their uncommitted edits plus
untracked files that are not ignored. The helper builds it with
`git add -A` and `git write-tree` against a temporary copy of the index, so
it never touches the real index. On a clean worktree it equals
`HEAD^{tree}`. That makes the record correct for REVIEW.md's step 2, which
verifies before it commits: once the commit stages everything, the committed
tree is the verified tree. A partial `git add` yields a different tree, and
the next `check` honestly answers `unverified` (per D7).

**Where the record lives.** One file, `verified-tree.json`, in the
worktree's own git directory (`git rev-parse --git-dir`). It sits outside
the working tree, so it cannot be committed, and it lives exactly as long as
the worktree. That is the precedent `GROUNDING.md` set. The file holds one
closed object, `{"schema": "verified-tree/v1", "tree": "<id>",
"verification": ["<id>", …]}`, and each pass replaces it. Only the latest
pass is kept (per D8).

**Invalidation.** Tree equality is the whole rule. A change to any file, a
test file included, makes the tree different and forces a rerun. That is
stricter than the issue's "any change to a non-test source file", and it
needs no classifier of test paths. The verification id list is bound too,
because the caller's retained bindings come from `resolve-project` and need
not match the tree's own contract (per D9).

**No launch fence.** `record` makes no commit and no forge write, and its
claim is content-addressed: a superseded writer can only record a tree that
really passed. So it is not routed through `launch-commit`, and it needs no
lifecycle identity. A standalone ship uses it the same way (per D8).

### Per-task test ladder

- **Implementer template.** Test Discipline replaces "run the full suite
  once before committing" with the rule: run the focused tests your brief
  names, red before green, and the brief's build check when your task
  changes files the build evaluates. Do not run the full declared
  verification. The final gate owns it. The report still carries the commands
  and output it ran.
- **Fix rounds and the final-review fixer.** fix-loop.md's "re-runs the
  covering tests" names the same ladder: the covering focused tests, and the
  build check when the fix changes build-evaluated files. The final-review
  fixer's dispatch text says the same, and says the final gate runs the full
  verification after it.
- **writing-plans.** The task template's Step 2 and Step 4 stay focused
  commands. A new rule beside "Every task carries at least one verification
  line that could fail" says each task names its focused test commands and
  includes the project's build verification command only when the task
  changes files that command evaluates. No task names the full declared
  verification as a per-task gate: sdd's final gate runs it once. The plan's
  Global Constraints may still name the verification commands with their
  timeouts (the #261 form), as the final gate's and ship's commands.
- **Skill text stays project-neutral.** The shared skills say "the build
  check" and "files the build evaluates". The plan supplies the concrete
  command. In this repository that is `just build` for any change to a file
  Nix evaluates. A planner unsure whether a task's files reach the build
  includes the build check (per D2, D11).

### sdd's final gate

final-review.md gains a **Final verification** step after the fix wave and
its scoped re-reviews, or right after the first pass when neither axis had
findings, and before the terminal state is chosen:

1. Run `verified-tree check` with the retained verification ids. On
   `verified` (a resumed controller, say), skip the run.
2. Otherwise run every declared verification command once, in the foreground
   with an explicit timeout above its duration (the #261 rule), its output
   in a log on disk and only the tail read back (writing-plans' payload
   discipline), then run `verified-tree record --tree <checked tree>`.
3. Append `Final verification: passed (head <full sha>, tree <tree id>)` to
   the ledger. That is the human-readable copy, while the record file is the
   machine-checked one.
4. A failing command, or a `record` refused for `tree_changed`, is not a
   pass. It gets one repair round, the final-review fixer dispatch carrying
   the failing command and its log path, or for `tree_changed` the
   `git status --porcelain` output. One scoped correctness re-review of
   that fix diff follows, then the verification runs once more. If it still
   fails, the failure becomes a load-bearing correctness finding in the
   retained detail, the terminal state is `residuals`, and the report carries
   `verification_state: failed` (per D4).

The terminal **Clean** state and `verification_state: passed` require step
3's recorded pass on the reported `head_sha`. SKILL.md's Finish names that
rule and points to the step. It does not restate the step.

### Ship

ship-issue Phase 2 becomes: `verified-tree check` with the retained
verification ids, then skip on `verified` (noting `verification reused: tree
<id>` in the PR body), else run every command and `record` the pass. The
existing failure and baselining rules apply only to an actual run. A
`record` refused for `tree_changed` there is a failing verification under
those rules, because the passing run no longer describes the worktree
(per D10). REVIEW.md
step 2 and CI-MERGE.md's "Run the Phase 2 verification commands" (both the
sync step and the after-amend rerun) now say "Run Phase 2's verification
step", so all three call sites share one procedure. A review fix or sync
merge changes the tree, so in practice they run. The skip pays off where the
Phase-1 sync was `Already up to date` and sdd's final gate recorded the head.

## Test seams

Two seams, both existing kinds.

- **Command tests from source** (new `tests/test_verified_tree.py`, added to
  `agent-workflow-tests`; the `test_launch_commit.py` precedent). These tests
  run `python -m agent_tools.verified_tree` in temporary git repositories and
  assert the printed JSON, the exit status and the record file's contents:
  a pass is recorded; `check` is `verified` on the same tree; `check` is
  `unverified` after an edit to a source file, after an edit to a test file,
  after a new untracked file, and with a different verification list;
  `record` with a mismatched `--tree` is refused with exit 3 and leaves the
  previous record byte-identical; an uncommitted verified edit stays
  `verified` once committed; the real index is unchanged by either verb;
  a malformed record makes `check` exit 2. The command-table row is covered by
  the build's module import check.
- **Workflow skill contracts** (`test_workflow_skill_contracts.py`, the
  section/`normalized`/`assert_ordered` anchor style). These pin: the
  implementer template no longer contains the full-suite-per-task sentence
  and holds the focused-tests-plus-build-check rule; fix-loop.md and the
  final-review fixer name the same ladder; writing-plans holds the per-task
  verification rule; final-review.md's Final verification step follows the
  fix wave and holds check, run, record, ledger line and the
  repair-then-residual route in order; SKILL.md's Finish ties `passed` to
  it; ship-issue Phase 2 holds check, skip only on `verified`, run otherwise,
  then record; and REVIEW.md step 2 and both CI-MERGE.md reruns point to
  Phase 2's step. The #261 `own-commands` and interim-result anchors stay
  green unchanged.

Verification is `just build` and `just agent-workflow-tests`.

## Out of scope

- CI, the declared verification list, and `bindings.commands` entries.
- Host-contention scheduling, which stays deferred
  (`.agents/knowledge/rejections/host-contention-scheduling.md`).
- The SDD report and ship-handoff schemas. `verification_state` keeps its
  values and gains only a precise meaning, and ship reads the record itself.
- Retaining more than the latest pass, keying passes to run or attempt ids,
  and classifying paths as test or non-test.
- The per-task review rubric, which already forbids reviewers from re-running
  tests.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Three rungs: focused tests per task, one full run at sdd's final gate, ship reruns unless the recorded tree matches | Issue's stated decision: no gate removed, full suite at least once on the merging head | Keep a full run per task in "risky" tasks: reintroduces the cost with no gate the final run lacks |
| D2 | Shared skills say "the build check" and "files the build evaluates"; the plan names the concrete command (`just build` here) | Skills are a shared, project-neutral tree reaching Claude and Codex; bindings carry no build/test classification of verification ids | Hard-coding `just build` in skill text: wrong for every other project using these skills |
| D3 | The final gate runs after the fix wave and scoped re-reviews, and its recorded pass is what Clean and `verification_state: passed` mean | Issue: "after the fix wave and before the final two-axis review is accepted"; the SDD validator already ties complete+clean to `passed` | Run before the review: the fix wave would change the head and force a second run |
| D4 | A failing final verification gets one repair round (existing final fixer + scoped correctness re-review), then becomes a correctness finding → `residuals`, `verification_state: failed` | SDD validator: clean axes with failed verification is unrepresentable, residuals needs a finding axis; one-fix-wave precedent | Unlimited repair loop (unbounded) or no repair (one integration slip strands a whole plan) |
| D5 | One Phase 2 procedure (check → run unless `verified` → record); REVIEW.md step 2 and CI-MERGE.md's reruns point to it | Single-home precedent; issue names REVIEW step 2 as a rerun site | Separate skip logic per call site: copies drift |
| D6 | A packaged `verified-tree` command (check/record) rather than skill prose plus git commands | docs/standards/agent-helpers.md rule 1; "a recorded tree hash, not prose, proves it"; deterministic and testable | Prose `git rev-parse HEAD^{tree}` plus a hand-written file: untestable, and agents compose it differently |
| D7 | The tree is the working tree (temporary index, `git add -A`, `git write-tree`); `record` refuses when it differs from the tree checked before the run | REVIEW.md verifies before committing; the issue asks that a mismatched hash be refused | `HEAD^{tree}`: a pre-commit verification could never be recorded, and an uncommitted edit would pass as verified |
| D8 | The record is one latest-pass file in the worktree's git dir, unfenced, with no run/attempt binding | sdd deletes its ledger on Clean, and ship is a fresh agent; GROUNDING.md per-worktree precedent; content addressing makes a pass reusable by a retry that shares the worktree | The sdd ledger alone (deleted before ship) or a ship-handoff field (closed schema; standalone ship has none) |
| D9 | Invalidation is plain tree equality plus the verification id list; test-file edits invalidate too | Strictest reading of the issue; YAGNI on a test-path classifier; bindings resolve from the ledger root, not the tree | Test-path exemptions: needs a classifier and lets an edited test escape the run that proves it |
| D10 | Grill: `tree_changed` is never a pass; sdd sends it to the repair round with `git status --porcelain` as evidence, ship treats it as a failing verification | A verification command that dirties the tree, or a writer active during the run, means the pass does not describe the current bytes; this repo ignores `result` and caches, so a clean run never trips it | Record the checked tree anyway: certifies bytes that are no longer the worktree's |
| D11 | Grill: the planner includes the build check whenever unsure a task's files reach the build; the final gate's logs go to disk with only tails read | Nix here copies skills and import-checks the package, so "Nix-evaluated" is wide; the-bar Token economy and writing-plans payload discipline | Leave it to the implementer: briefs are the single source of task requirements |
