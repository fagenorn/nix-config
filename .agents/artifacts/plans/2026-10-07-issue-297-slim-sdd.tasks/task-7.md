# Task 7: Measure the slice and record acceptance evidence

**Files:**
- Create: `.agents/artifacts/plans/2026-10-07-issue-297-slim-sdd.acceptance.md`
- Modify: `home/common/agent-skills/instruction-load.json` (by `tighten` only, and only if it changes anything)
- Modify (only when `CLAUDE_CODE_OAUTH_TOKEN` is non-empty): `home/common/agent-skills/evals/results/results.jsonl`

**Interfaces:**
- Consumes: Task 5's tree: all eight sdd documents cut, no `skills/sdd/` debt key, ceilings tightened.
- Produces: the acceptance record that sdd's final review grades (`skills/sdd/final-review.md` § Acceptance record). This task writes `Observed`, `Commit` and `Conditions`; `Verdict` is `—` on every row for the controller.

**Invariants:**
- No document, test or model edit beyond a `tighten` re-run (per D2, D12).
- No eval result is written, estimated or copied when the token is absent (per D14).
- No forge or tracker write, and no label.

- [ ] **Step 1: Measure the L2 line limit (AC2, per D19)**

```bash
PYTHONPATH=python python3 - <<'EOF'
from pathlib import Path
from agent_tools import skill_lint
text = Path("home/common/agent-skills/skills/sdd/SKILL.md").read_text(encoding="utf-8")
lines = skill_lint.reflowed_lines(skill_lint.parse_frontmatter(text)[1])
print(lines)
raise SystemExit(0 if lines <= 500 else 1)
EOF
```

Expected: a number ≤ 500 (plan target ≤ 230) and exit 0; `skill-lint check` (L2) passes with no allowlist entry for the scoped files. At the base it prints 433, which already meets the amended line; the plan target is the cut the content allows without moving a cited anchor (per D19).

- [ ] **Step 2: Measure the sdd share (AC3, per D1)**

Save as `<launch scratch root>/share.py`:

```python
import json, sys
d = json.load(sys.stdin)
docs = {e["member"]: e["head"]["bytes"] for e in d["documents"]}
ids = ("orchestrated-issue-owner", "implementation-owner")
share = whole = 0
for p in d["profiles"]:
    if p["id"] not in ids:
        continue
    for side in p["hosts"].values():
        for kind in ("hot", "conditional"):
            whole += side[kind]["head"]["bytes"]
            share += sum(docs[m] for m in side[kind]["members"] if m.startswith("sdd/"))
print(json.dumps({"sdd_share": share, "whole_profiles": whole}))
```

Run it once per revision; `report` reads the model at `--head`, so each revision passes itself as both (timeout 300 s each):

```bash
PYTHONPATH=python python3 -m agent_tools.instruction_load report --base baac2897f15daab46a4f25ec625b40d384d3573c --head baac2897f15daab46a4f25ec625b40d384d3573c --format json | python3 <scratch>/share.py
SYNCED=$(git merge-base HEAD origin/main)
PYTHONPATH=python python3 -m agent_tools.instruction_load report --base "$SYNCED" --head "$SYNCED" --format json | python3 <scratch>/share.py
PYTHONPATH=python python3 -m agent_tools.instruction_load report --base HEAD --head HEAD --format json | python3 <scratch>/share.py
```

Expected: the base prints `{"sdd_share": 279951, "whole_profiles": 929474}`; the synced base (per D18) is reported beside it (278,916 at 75784bed). The head must print `sdd_share` ≤ 223960 (0.80 × base, per D19). A head share above 223,960 is an unmet criterion: report it and do not alter the measurement. Also run `PYTHONPATH=python python3 -m agent_tools.instruction_load report --base origin/main --head HEAD` and keep its summary lines for the task report (the issue's demo).

- [ ] **Step 3: Gate and diff bound (AC1, per D2, D13)**

Run `git fetch origin` and `git merge-base --is-ancestor origin/main HEAD`; when it fails, `origin/main` has advanced (for example by #296), so stop and report BLOCKED with `needs sync` for the controller's sync and remeasurement before reading any budget line (per D20). Only on a synced branch run `just agent-instruction-load tighten` and `just agent-instruction-budget` (timeout 300 s each). Expected: exit 0, with no `lint:`, `raise:`, `ceiling:`, `tightness:` or `debt:` line. Any `raise:` line is a design defect (per D2): stop and report BLOCKED.
Run: `if grep -q 'skills/sdd/' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi`. Expected: exit 0.
Run the D13 diff-bound script. Expected: exit 0; put each sdd path's byte count in the task report.
If `tighten` changed `instruction-load.json`, commit it as `chore(instruction-load): re-tighten the sdd profiles (#297)`.

- [ ] **Step 4: Prose-pin inventory (AC5)**

List every remaining test method, across `home/common/agent-skills/tests/*.py`, whose body reads an sdd document: in `test_workflow_skill_contracts.py`, any method mentioning `SDD`, `SDD_DIR`, `self.sdd` or `SDD_MACHINE_TEXT`, plus any method iterating a module-level tuple, dict or helper that holds an sdd path (resolve `nested_workflow_documents`, `SKILL_ROOTS`-based corpora and similar by reading their definitions); in the other test files, any method reading `sdd/`. Print class, method and line, with one word per method: `machine` (asserts argv, markers, keys, placeholders, headings or closed values only) or `negative` (asserts absence only). Put the list in the task report so the reviewer can attest that no method asserts guidance prose on an sdd document. A method that does is a finding for the reviewer; do not edit it in this task.

- [ ] **Step 5: Evals (AC4, per D14)**

If `CLAUDE_CODE_OAUTH_TOKEN` is non-empty, run each in the foreground (timeout 3000 s each):

```text
EVAL_TREE=. EVAL_MODEL=sonnet just evals sdd 4
EVAL_TREE=. EVAL_MODEL=opus just evals sdd 4
```

Compare each new row's `passed` with 6, then commit `results.jsonl` as `test(evals): record sdd case 4 after the slimming (#297)`. If the token is empty, run neither and change no rows.

- [ ] **Step 6: Acceptance record**

Create the record in the schema `final-review.md` § Acceptance record gives: `# Acceptance record — issue #297`, then `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |` with rows AC1–AC5. `Criterion` is the issue line verbatim, without its checkbox, read once with `gh issue view 297 --repo fagenorn/nix-config --json body` (unsetting only the names `bindings.tracker.credential_env.unset_before_invocation` lists, none in this project). `Verdict` is `—` on every row.
- AC1, AC2, AC5 (`code`): `Observed` is `in final verification`; AC2 adds the Step 1 number; AC1 adds `just agent-instruction-budget exit 0, no raise:` from Step 3.
- AC3 (`evidence`): `Observed` is `base 279951 → head <n> (threshold ≤ 223960); synced base <s>; whole profiles 929474 → <m>`. `Commit` is the short SHA of the HEAD measured. `Conditions` is `report --base X --head X at each revision; O and I profiles, all hosts (D1)`.
- AC4 (`evidence`): with the token, the two `passed` values against 6 and the results commit. Without it, `Observed` is `not run — CLAUDE_CODE_OAUTH_TOKEN unset`, `Commit` is `—`, and `Conditions` lists the two Step 5 commands and `human_pending (D14)`.

Commit as `docs(plans): acceptance record for #297`.

- [ ] **Step 7: Verify**

Run the focused suite. Expected: OK.
Run `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run: `test -f .agents/artifacts/plans/2026-10-07-issue-297-slim-sdd.acceptance.md && grep -c '^| AC[1-5] |' .agents/artifacts/plans/2026-10-07-issue-297-slim-sdd.acceptance.md`. Expected: `5`. At Task 5's head it fails, because the record does not exist.
