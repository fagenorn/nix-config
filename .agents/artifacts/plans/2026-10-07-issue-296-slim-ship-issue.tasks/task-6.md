# Task 6: Measure the slice and record acceptance evidence

**Files:**
- Modify: `home/common/agent-skills/instruction-load.json` (`tighten` only)
- Create: `.agents/artifacts/plans/2026-10-07-issue-296-slim-ship-issue.acceptance.md`
- Modify (only when `CLAUDE_CODE_OAUTH_TOKEN` is non-empty): `home/common/agent-skills/evals/results/results.jsonl`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (the Step 4 stdin-loop edit only)

**Interfaces:**
- Consumes: Task 5's tree, with a hub `SKILL.md`, all nine ship-issue documents and no ship-issue debt keys.
- Produces: the acceptance record that sdd's final review grades (`home/common/agent-skills/skills/sdd/final-review.md` § Acceptance record). This task writes its `Observed`, `Commit` and `Conditions` columns. `Verdict` holds `—` for the controller to fill in.

**Invariants:**
- No membership, `unread`, note or ceiling value changes by hand. `tighten` may lower ceilings (per D13, D14).
- No eval result is written, estimated or copied when the token is absent (per D15).
- No forge write and no label (per D2).

- [ ] **Step 1: Re-tighten**

Run `git fetch origin`, then `just agent-instruction-load tighten` (timeout 300 s). If it changes the file, commit as `chore(instruction-load): re-tighten the ship-issue profiles (#296)`.

- [ ] **Step 2: Measure the 300-line line (AC2)**

```bash
PYTHONPATH=python python3 - <<'EOF'
from pathlib import Path
from agent_tools import skill_lint
text = Path("home/common/agent-skills/skills/ship-issue/SKILL.md").read_text(encoding="utf-8")
lines = skill_lint.reflowed_lines(skill_lint.parse_frontmatter(text)[1])
print(lines)
raise SystemExit(0 if lines <= 300 else 1)
EOF
```

Expected: a number ≤ 300 and exit 0. At the base it prints 841 and exits 1.

- [ ] **Step 3: Measure the ship-issue share (AC3, per D1)**

Save this script in the launch scratch root (never in the worktree) as `share.py`:

```python
import json, sys
d = json.load(sys.stdin)
docs = {e["member"]: e["head"]["bytes"] for e in d["documents"]}
ids = ("ship-owner", "orchestrated-issue-owner", "implementation-owner")
share = whole = 0
for p in d["profiles"]:
    if p["id"] not in ids:
        continue
    for side in p["hosts"].values():
        for kind in ("hot", "conditional"):
            whole += side[kind]["head"]["bytes"]
            share += sum(docs[m] for m in side[kind]["members"] if m.startswith("ship-issue/"))
print(json.dumps({"ship_issue_share": share, "whole_profiles": whole}))
```

`report` reads the model at `--head`, so each revision passes itself as both:

```bash
PYTHONPATH=python python3 -m agent_tools.instruction_load report --base baac2897f15daab46a4f25ec625b40d384d3573c --head baac2897f15daab46a4f25ec625b40d384d3573c --format json | python3 <scratch>/share.py
PYTHONPATH=python python3 -m agent_tools.instruction_load report --base HEAD --head HEAD --format json | python3 <scratch>/share.py
```

Expected: the base prints `{"ship_issue_share": 434345, "whole_profiles": 1140613}`. The head must print `ship_issue_share` ≤ 282324. A head share above 282,324 is an unmet acceptance criterion. Report it, and do not alter the measurement.

- [ ] **Step 4: Gate and audit (AC1, AC5)**

Run `just agent-instruction-budget` (timeout 300 s). Expected: exit 1, and the only failing line is `raise: home/common/agent-skills/instruction-load.json changes more than lowering a ceiling; …`. There is no `lint:`, `ceiling:`, `tightness:` or `debt:` line. Then run `just agent-instruction-budget --raise-label`. Expected: exit 0. This local run shows that the human gate is the only blocker (per D2).

Run: `if grep -q 'skills/ship-issue/' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi`. Expected: exit 0.

Before the inventory, edit `test_lifecycle_calls_are_single_stdin_commands_on_interface_two`. For every path, keep its `INPUT_FLAG_RE` stdin-flag check, its `--result-file` count and its `'"interface_version": 1'` check. Keep its English forbidden phrases (`"version-1"`, `"temporary request file"`, `` "temporary `ship-summary/v2` file" ``) only for paths outside `skills/ship-issue/` (per D11, #295 D13).

For the AC5 attestation, list every remaining test method that reads a scoped file, using an AST pass over `test_workflow_skill_contracts.py`. A direct reader is a method whose body mentions `SHIP_ISSUE` (any `SHIP_ISSUE*` constant), `self.ship_issue`, `self.ship_review` or `self.ship_human_gate`. An indirect reader is a method that iterates `LIFECYCLE_DOCS`, `SHIP_ISSUE_MACHINE_TEXT`, `RETAINED_SUPPORT_CONTRACTS`, `SHARED_POLICY_ENTRIES` or another module-level name whose value mentions a scoped constant or `ship-issue/`. Print the class, method and line, and put the list in the task report so that the reviewer can attest that each one asserts only machine-read text.

- [ ] **Step 5: Evals (AC4, per D15)**

If `CLAUDE_CODE_OAUTH_TOKEN` is non-empty, run each of these in the foreground (timeout 3000 s each):

```text
EVAL_TREE=. EVAL_MODEL=sonnet just evals ship-issue 5
EVAL_TREE=. EVAL_MODEL=opus just evals ship-issue 5
```

Compare each new row's `passed` with its threshold (sonnet ≥ 5, opus ≥ 6). Its failed assertions may include only "the run names the push it would run next". Then commit `results.jsonl` as `test(evals): ship-issue case 5 on the slimmed tree (#296)`. If the token is empty, run neither and change no rows.

- [ ] **Step 6: Acceptance record**

Create the record in the schema that `final-review.md` § Acceptance record gives: `# Acceptance record — issue #296`, then the table `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |` with rows AC1–AC5. Each `Criterion` is the issue line verbatim, without its checkbox. `Verdict` is `—` on every row.
- AC1, AC2 and AC5 (`code`): `Observed` is `in final verification` (AC2 adds the Step 2 number). For AC1, `Conditions` lists every `raise:` commit-body line from `git log --format=%b baac2897f15daab46a4f25ec625b40d384d3573c..HEAD -- home/common/agent-skills/instruction-load.json`, followed by "`Instruction Budget` stays red on its `raise:` line until a human applies `instruction-budget-raise` (D2)".
- AC3 (`evidence`): `Observed` is `base 434345 → head <n> (threshold ≤ 282324); whole profiles 1140613 → <m>`. `Commit` is the measured head's short SHA. `Conditions` is `report --base X --head X at each revision; three profiles, all hosts (D1)`.
- AC4 (`evidence`): with the token, give both `passed` values against their thresholds, any failed assertion names, and the commit. Without it, `Observed` is `human_pending — CLAUDE_CODE_OAUTH_TOKEN unset`, `Commit` is `—`, and `Conditions` lists the two Step 5 commands (D15).

Commit the record and the Step 4 test edit as `docs(plans): acceptance record for #296`.

- [ ] **Step 7: Verify**

Run the focused suite. Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run: `test -f .agents/artifacts/plans/2026-10-07-issue-296-slim-ship-issue.acceptance.md && grep -q '^| AC5 |' .agents/artifacts/plans/2026-10-07-issue-296-slim-ship-issue.acceptance.md`. Expected: exit 0. At Task 5's head it fails, because the record is absent.
