# Task 7: Reconcile profile notes, measure the slice and record acceptance evidence

**Files:**
- Modify: `home/common/agent-skills/instruction-load.json` (the `note` of `from-issue-controller`, `orchestrated-issue-owner` and `implementation-owner`, then `tighten`)
- Create: `.agents/artifacts/plans/2026-10-07-issue-295-slim-from-issue.acceptance.md`
- Modify (only when `CLAUDE_CODE_OAUTH_TOKEN` is non-empty): `home/common/agent-skills/evals/results/results.jsonl`

**Interfaces:**
- Consumes: Task 6's tree, which holds every route and phase file and a hub `SKILL.md`, with no from-issue debt keys left.
- Produces: the acceptance record that sdd's final review grades (`home/common/agent-skills/skills/sdd/final-review.md` § Acceptance record). This task writes its `Observed`, `Commit` and `Conditions` columns. `Verdict` holds `—` for the controller to fill in.

**Invariants:**
- Of the three notes, only these clauses change:
  - Delete each note's clause that says from-issue's acquisition routes or `AUTO.md`'s rollover are carried, and whose route-scoping is deferred (#155 D6).
  - Append one sentence naming #295 and what the profile now reads (texts below).
  - Every other clause, the ceiling-history sentences included, stays.
- No membership, `unread` or ceiling value changes by hand. `tighten` may lower ceilings.
- No eval result is written, estimated or copied when the token is absent (per D6).
- No forge write and no label (per D5).

- [ ] **Step 1: Notes, then tighten**

Append these sentences:
- `from-issue-controller`: "From #295 it reads the direct route and the rollover hot and the interactive and durable routes and the resume pack conditionally; the dispatcher route and the delegated owner are unread."
- `orchestrated-issue-owner`: "From #295 it reads the dispatcher route hot and the resume pack conditionally; the other acquisition routes, the rollover and the delegated owner are unread."
- `implementation-owner`: "From #295 it reads the delegated owner hot and the dispatcher envelope and the resume pack conditionally; the other acquisition routes and the rollover are unread."

Delete the deferred clauses: the controller's "The hot path keeps from-issue's top-level acquisition routes and AUTO.md's rollover, whose route-scoping is deferred (#155 D6).", the orchestrated owner's "It carries from-issue's top-level acquisition routes and AUTO.md's rollover, which its route never takes (#155 D6).", and the implementation owner's "It carries from-issue's top-level acquisition routes, whose route-scoping is deferred (#155 D6)."

Run `just agent-instruction-load tighten` (timeout 300 s). Commit as `chore(instruction-load): name #295 in the from-issue profile notes and re-tighten`.

- [ ] **Step 2: Measure the 300-line line (AC2, per D8)**

```bash
PYTHONPATH=python python3 - <<'EOF'
from pathlib import Path
from agent_tools import skill_lint
text = Path("home/common/agent-skills/skills/from-issue/SKILL.md").read_text(encoding="utf-8")
lines = skill_lint.reflowed_lines(skill_lint.parse_frontmatter(text)[1])
print(lines)
raise SystemExit(0 if lines <= 300 else 1)
EOF
```

Expected: a number ≤ 300 and exit 0. At the base it prints about 915 and exits 1.

- [ ] **Step 3: Measure the from-issue share (AC3, per D1)**

Save this script in the launch scratch root (never in the worktree) as `share.py`:

```python
import json, sys
d = json.load(sys.stdin)
docs = {e["member"]: e["head"]["bytes"] for e in d["documents"]}
ids = ("from-issue-controller", "orchestrated-issue-owner", "implementation-owner",
       "planning-owner", "plan-reviewer")
share = whole = 0
for p in d["profiles"]:
    if p["id"] not in ids:
        continue
    for side in p["hosts"].values():
        for kind in ("hot", "conditional"):
            whole += side[kind]["head"]["bytes"]
            share += sum(docs[m] for m in side[kind]["members"] if m.startswith("from-issue/"))
print(json.dumps({"from_issue_share": share, "whole_profiles": whole}))
```

Run it once per revision. `report` reads the model at `--head`, so the base and the head each pass themselves as both:

```bash
PYTHONPATH=python python3 -m agent_tools.instruction_load report --base a891b08cc4d1599c71e7802ba49ec5da07631132 --head a891b08cc4d1599c71e7802ba49ec5da07631132 --format json | python3 <scratch>/share.py
PYTHONPATH=python python3 -m agent_tools.instruction_load report --base HEAD --head HEAD --format json | python3 <scratch>/share.py
```

Expected: the base prints `{"from_issue_share": 539997, "whole_profiles": 1348691}`. The head must print `from_issue_share` ≤ 350998. A head share above 350,998 is an unmet acceptance criterion. Report it, and do not alter the measurement.

- [ ] **Step 4: Gate and audit (AC1, AC5)**

Run `git fetch origin` and then `just agent-instruction-budget` (timeout 300 s). Expected: exit 1, and its only failing line is `raise: home/common/agent-skills/instruction-load.json changes more than lowering a ceiling; …`. There is no `lint:`, `ceiling:`, `tightness:` or `debt:` line. Then run `just agent-instruction-budget --raise-label`. Expected: exit 0. This local run shows the human gate is the only blocker (per D5).

Run: `if grep -q 'skills/from-issue/' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi`. Expected: exit 0.

For the AC5 attestation, list every remaining test method that reads a scoped file, using the AST inventory: each method of `test_workflow_skill_contracts.py` whose body mentions `FROM_ISSUE`, `FROM_ISSUE_DIR`, `AUTO`, `ROLLOVER`, `DELEGATED_OWNER`, `ACQUIRE_`, `RESUME_PACK`, `SHIP_HANDOFF_DOC`, `PHASE_5_REVIEW_CONTRACT`, `self.from_issue`, `self.auto`, `self.standards_review`, `self.ship_handoff` or `self.investigate`. Also count indirect readers: any method that iterates `LIFECYCLE_DOCS` or another module-level tuple, list or alias holding a scoped path (find them by resolving each module-level name whose value mentions a scoped constant). Before the inventory, edit `test_lifecycle_calls_are_single_stdin_commands_on_interface_two`: keep its `INPUT_FLAG_RE` stdin-flag check, its `--result-file` count and its `'"interface_version": 1'` JSON check for every path, and keep its English forbidden phrases (`"version-1"`, `"temporary request file"`, `"temporary `ship-summary/v2` file"`) only for the paths outside this slice's scope, so no scoped file carries a prose pin (per D11). Print the class, method and line, and put the list in the task report so the reviewer can attest that each one asserts only machine-read text.

- [ ] **Step 5: Evals (AC4, per D6)**

If `CLAUDE_CODE_OAUTH_TOKEN` is non-empty, run each of these in the foreground (timeout 3000 s each):

```text
EVAL_TREE=. EVAL_MODEL=sonnet just evals from-issue 1
EVAL_TREE=. EVAL_MODEL=opus just evals from-issue 1
EVAL_TREE=. EVAL_MODEL=sonnet just evals from-issue 2
EVAL_TREE=. EVAL_MODEL=opus just evals from-issue 2
EVAL_TREE=. EVAL_MODEL=sonnet just evals from-issue 3
EVAL_TREE=. EVAL_MODEL=opus just evals from-issue 3
```

Compare each new row's `passed` with the threshold (case 1: 9 on both models; case 2: 4 on sonnet, 3 on opus; case 3: 5 on both), then commit `results.jsonl`. If the token is empty, run none of them and change no rows.

- [ ] **Step 6: Acceptance record**

Create the record in the schema `final-review.md` § Acceptance record gives: `# Acceptance record — issue #295`, then the table `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |` with rows AC1–AC5. Each `Criterion` is the issue line verbatim, without its checkbox. `Verdict` is `—` on every row.
- AC1, AC2 and AC5 (`code`): `Observed` is `in final verification` (AC2 adds the Step 2 number). For AC1, `Conditions` lists every `raise:` commit-body line from `git log --format=%b a891b08cc4d1599c71e7802ba49ec5da07631132..HEAD -- home/common/agent-skills/instruction-load.json`, followed by "`Instruction Budget` stays red on its `raise:` line until a human applies `instruction-budget-raise` (D5)".
- AC3 (`evidence`): `Observed` is `base 539997 → head <n> (threshold ≤ 350998); whole profiles 1348691 → <m>`. `Commit` is the Step 1 commit's short SHA. `Conditions` is `report --base X --head X at each revision; five profiles, all hosts (D1)`.
- AC4 (`evidence`): with the token, give the six `passed` values against their thresholds and the commit. Without it, `Observed` is `not run — CLAUDE_CODE_OAUTH_TOKEN unset`, `Commit` is `—`, and `Conditions` lists the six Step 5 commands (D6).

Commit as `docs(plans): acceptance record for #295`.

- [ ] **Step 7: Verify**

Run the focused suite. Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run: `if grep -q "top-level acquisition routes" home/common/agent-skills/instruction-load.json; then exit 1; fi`. Expected: exit 0. At Task 6's head it fails, because all three notes still carry that clause.
