# Task 1: Cut SKILL.md and give the review-package gate one home

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/sdd/SKILL.md`
- Modify: `instruction-load.json` (by `tighten` only)
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the branch synced with `origin/main` (Global Constraints, execution precondition; per D18). Its `SKILL.md` already carries #281's deadline-headroom paragraph in `### Lifecycle workers`. `fix-loop.md` and `final-review.md` still carry their own gate copies; Tasks 2 and 3 replace them.
- Produces: a new heading `### Review-package gate`, the one home of the gate (per D3, D15). Tasks 2 and 3 point at it by the exact text "`SKILL.md`'s `### Review-package gate`". `SKILL.md` ends ≤ 14,500 bytes and ≤ 230 reflowed body lines (hard line 300).

**Invariants:**
- Byte for byte (per D8): frontmatter; both dispatch markers with their `Agent(...)` call lines (`sdd-blocked-reasoning-escalation`, `sdd-lane-task-verification`); the leaf-clause blockquote, exactly once, inside `## Agent tiers`; every argv in `### Lifecycle workers` and the `Lifecycle worker:` line with its two following quoted sentences; the `launch fence refused: <reason>` token; `scripts/task-brief PLAN_FILE N`; `scripts/sdd-workspace PLAN_FILE`; the workspace literal `` `<primary-checkout>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/` ``; the three ledger formats `# SDD ledger — plan: <plan file path>`, `Task <N>: complete (commits <base7>..<head7>, review clean | <K> parked)`, `Task <N>: minor (deferred): <one-liner>` and `Task <N>: verified inline (mechanical)`; the eleven report keys and `review_state` values; `validate-report --boundary sdd`, `validate-detail-input`, `detail_state: "none"`, `report_path: null`, `detail_state: "unpublished"`.
- The opening paragraph stays a no-resolve rule and contains no `resolve-project resolve`.
- `### Review-package gate` states, once: record the full base and head SHAs before invoking the producer; run `review-package PLAN_FILE <base> <head>` and capture its stdout unchanged; pipe it through `artifact-budget validate-report --boundary producer --input -`; independently run `artifact-budget check --kind review-package` on its root and compare all four metrics (`root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`); the three exit routes — generator 0 + validator 0 + strict `complete` + agreement permits dispatch; generator exit 3 must validate as `decompose_required`, recorded and returned with no reviewer dispatched; generator or validator exit 2, malformed or unknown output, or any disagreement is `failed`, recorded and returned before dispatch through the failed SDD candidate (`detail_state: "none"`, `report_path: null`) validated by `artifact-budget validate-report --boundary sdd`. The argv `artifact-budget validate-report --boundary producer --input -` appears in `SKILL.md` exactly once, there.
- `### Cumulative delivery gate` keeps: integration branch from the bindings; `DELIVERY_BASE` pinned once to the full `git merge-base HEAD origin/<integration-branch>` SHA, never from a local integration branch; `DELIVERY_HEAD` pinned before the first implementer and after each completed task; `review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD`; "apply the review-package gate" by name; the existing-package reuse conditions (full `range.base`/`range.head` equal, retained report still validates, fresh check agrees, seven-character prefixes never establish identity); ledger the two SHAs and four metrics; a non-passing gate preserves work and names an independently deliverable split.
- §2's DONE route runs `review-package PLAN_FILE BASE HEAD` (BASE from step 1, never `HEAD~1`) and applies the gate. The manifest interface-version paragraphs (v2 EF designer evidence, v3 context sequence, `stable-first-fit-whole-file`, `member_count`, `aggregate_bytes`) leave the file (per D4). §2 keeps the four status routes and the BLOCKED escalation site.
- **Interim child results** stays one paragraph in §2, between `### 2. Handle the report` and `### 3. Review the task`, with every rule in spec § Cutting rules per document (per D10).
- §3 keeps the lane routing, the batching rule, the lane-verification site, the escalation rule, the full-lane dispatch inputs (plan root path and four metrics, brief and report paths, manifest root path and four metrics; never member lists, shard lists, artifact or diff contents) and the ⚠️ cannot-verify rule; what the reviewer reads goes (per D4).
- `## Agent tiers` keeps the five tier bullets, "Unsure between mechanic and implementer → pick implementer", the re-evaluation rule compressed per D6 (metric, baseline 84% over 153 reviews, floor ~10 issues and ≥ 30 reviews, < 74% reverts `sdd-nonmechanical-implementation` and `sdd-task-fix-redispatch` to the `implementer` role), and the leaf-clause paragraph.
- `### Lifecycle workers` keeps #281's deadline-headroom rule as exactly one paragraph containing `` `blocked_on=deadline` ``, in this order (per D18; `test_sdd_states_the_deadline_suspension_order` reads it): `` `deadline_at` ``, the `release-worker … --event stopped` argv, the `mark-progress` argv, the `check-launch` argv, `` `current: false` ``, `` `/from-issue <num> --auto` ``, `` `current: true` ``, `` `blocked_on=deadline` ``; its headroom definition (`remaining`, `longest`, the larger of 15 minutes and `longest`, checked before each dispatch and before the final review) and the expired-deadline route keep their meaning. The section also turns its refusal routing into a decision list (`current: false` or helper failure → superseded route, print `/from-issue <num> --auto` and stop; `current: true` → suspension with `blocked_on=transport`) and its `mark-progress` paragraph into two lines (run before the first task and after each `complete` line; a refusal never stops the loop).
- `## Finish` gains the `.superpowers/issue-delivery/` literal (the producer derives the delivery-detail destination beneath the primary checkout's `.superpowers/issue-delivery/` home; callers pass identity only), keeps the eleven fields, the three state derivations, both detail-publication routes, both terminal states and "Do not ship, merge, or open PRs"; it drops the ship-issue root contrast.
- Cut (spec § Content classes): every D-number trail, "Turn count beats token price…", "Subagents never inherit…", the plan-check metric-shape sentences beyond "run the check; exit 2 or 3 stops; require `within_budget` and the four metrics" (per D7), the compaction anecdote, and the why-not-cwd explanation.

- [ ] **Step 1: Write the falsifiable gate**

Save as `<launch scratch root>/task1_gate.py` (never in the worktree):

```python
import re, sys
from pathlib import Path
sys.path.insert(0, "python")
from agent_tools import skill_lint
path = Path("home/common/agent-skills/skills/sdd/SKILL.md")
text = path.read_text(encoding="utf-8")
flat = re.sub(r"\s+", " ", text)
low = flat.lower()
lines = skill_lint.reflowed_lines(skill_lint.parse_frontmatter(text)[1])
size = len(text.encode("utf-8"))
print(f"SKILL.md {size} bytes, {lines} reflowed body lines")
assert lines <= 300, "over the 300-line acceptance line"
if size > 14500 or lines > 230:
    print("over target: name it in the commit body")
assert text.count("### Review-package gate") == 1, "gate heading"
assert flat.count("artifact-budget validate-report --boundary producer --input -") == 1, "one gate home"
for gone in ("interface version 2", "interface version 3", "ef core", "member_count",
             "aggregate_bytes", "stable-first-fit-whole-file", "(d5, d6, d8)",
             "turn count beats token price", "subagents never inherit", "resolve-project resolve"):
    assert gone not in low, gone
finish = text[text.index("## Finish"):]
assert ".superpowers/issue-delivery/" in finish, "delivery literal in Finish"
two = text.index("### 2. Handle the report")
assert two < text.index("**Interim child results.**") < text.index("### 3. Review the task")
assert text.count("**Interim child results.**") == 1
```

- [ ] **Step 2: Watch it fail**

Run: `PYTHONPATH=python python3 <scratch>/task1_gate.py` (timeout 120 s).
Expected: AssertionError `over the 300-line acceptance line` (at `origin/main` 75784bed it prints 27494 bytes, 434 lines).

- [ ] **Step 3: Cut SKILL.md**

Work top to bottom by the Invariants and spec § Cutting rules per document (`SKILL.md`). Add `### Review-package gate` directly after `### Cumulative delivery gate`. Every new or kept fence is labeled; the file keeps zero unlabeled fences.

- [ ] **Step 4: Test edits (spec § Test changes items 1, 2, 3 and the SKILL.md part of 5)**

In `tests/test_workflow_skill_contracts.py`:

1. `SDD_MACHINE_TEXT[SDD]`: delete `WHOLE_FILE_POLICY`, `"member_count"` and `"aggregate_bytes"`; keep every other item (per D4).
2. `test_durable_review_detail_precedes_every_removable_cleanup`: remove `self.sdd` from the `report_path` / `keep the worktree` loop's tuple and leave its other members as the synced file has them; the two `.superpowers/issue-delivery/` assertions stay.
3. `test_fixture_producer_states_supplement_behavioral_cli_cases`: remove `self.sdd` from the `contract error` loop's tuple (leaving `self.from_issue` and its three assertions as they are), and the last loop becomes:

```python
        for value in ("complete", "within_budget"):
            self.assertIn(value, self.auto)
            self.assertIn(value, self.sdd)
```

4. `InterimChildResultContractsTest` (per D10): `OWNERS = (FROM_ISSUE, SHIP_ISSUE)`; in `test_the_paragraph_copies_stay_identical` iterate `(SHIP_ISSUE,)`; delete the `(SDD, "### 2. Handle the report", "### 3. Review the task")` row from `test_each_copy_sits_in_its_owner_section`. If a sync already removed `SHIP_ISSUE` from these (#296), keep both deletions (per D16).

- [ ] **Step 5: Models**

Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 6: Verify**

Run the Step 1 gate. Expected: exit 0.
Run the focused suite. Expected: OK.
Run the lint. Expected: exit 0.
Run `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`, no `raise:` line.
Run the D13 diff-bound script. Expected: exit 0.

- [ ] **Step 7: Commit**

Commit `skills/sdd/SKILL.md`, the test file and `instruction-load.json` as `refactor(sdd): cut SKILL.md and give the review-package gate one home (#297)`.
