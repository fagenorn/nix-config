# Task 3: Cut the Claude orchestrate-issues SKILL.md and delete its prose pins

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/skill-lint-debt.json`, `home/common/agent-skills/instruction-load.json` (via `tighten` only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 2's tree. The Codex stub is untouched here (Task 4 owns it).
- Produces: a `SKILL.md` of ≤ 24,000 B and ≤ 430 reflowed body lines (500 is the hard limit) with the description below. The `L2 home/common/claude-code/skills/orchestrate-issues/SKILL.md` debt key is gone, and `test_workflow_skill_contracts.py` holds no prose pin on this file.

**Invariants:**
- Byte for byte, from base (the Step 6 script checks each):
  - frontmatter line `name: orchestrate-issues`;
  - the resolve paragraph, base lines 17–29, including its `build-delivery` sanctioned-exception sentence (per D12), with its line breaks;
  - the marker line, the `Agent(...)` line and the whole owner-prompt blockquote, base lines 349–387 (per D4; `test_dispatch_contracts` reads the blockquote as the carrier);
  - all six fenced blocks: the `host-route`, `init-run`, §3 control-request JSON (17 keys), `build-delivery`, `control` and owner-dispatch envelope fences;
  - every `ORCHESTRATE_MACHINE_TEXT` token (the focused suite checks them), the sentence holding `~/.agents/bin/workflow-state`, and every inline `workflow-state …` and `launch-scope reap …` argv span.
- Description is exactly: `Dispatches a set of tracker issues through from-issue --auto as independent background agents, tracking only a ledger. Use for "orchestrate issues X, Y, Z".` (per D8).
- Cited anchors keep their text (per D4): `## 1. Resolve issue set and bindings`, `## 2. Bootstrap and observe`, `## 3. Decide`, `## 4. Execute control actions`, `## 5. Final report`; `**Per-issue contract rule.**` and its rule; §4's `delivery_contract` rule ("This is the one rule for such an issue"); the owner-object projection sentence with its full member list; the `resume` / `resume-pack` step; `**Stop pass.**` ending in its `launch-scope reap … --sweep`.
- Closed sets and orders keep their members: the seven action kinds `spawn`, `resume`, `retry`, `delivery_remainder`, `delivery_contract`, `wait`, `finalize`; the notification classes (a), (b), (c); the worktree states `matching_issue_branch | absent | mismatch`; the forge-state normalization; the six `wait` rules in order; the `finalize` order (stop pass, clear `current_wait_id`, cancel, clear `current_wait_handle`); the §5 table columns and the per-summary reporting rules (lifecycle-only, delivered with stale custody, `held`, unable-to-resume, `admission.waiting`, **Stop failures**).
- Helper-enforced rules become one line each (per D6): `control` reserves slots and owns readiness, precedence, retryability, capacity, deadline and completion, so the adapter applies its envelopes and acts on its refusals; `build-delivery`'s resolution root and refusal shape are the builder's, so a refusal sends null and `[]` and the final report relays its stderr line verbatim.
- `launch_refused` keeps its rule (never retry; one control call carrying a `launch_refused` owner observation for that custody; execute that response) without the parking rationale. The `expired` paragraph keeps its reporting rules (consumes no attempt; usually `resumed` or `suspended`; at the bound its state is `stopped` and the issue is a finished `stopped(stalled)`; report a parked issue as paused; never `retried` or `retry_refused`) without the explanation.
- `## Notes` is deleted (the Claude-only rationale; `CLAUDE.md` holds it).

- [ ] **Step 1: Delete the prose pins on this file (per D10, D14)**

In `tests/test_workflow_skill_contracts.py`:
1. Delete `test_contract_builders_state_the_resolution_root_and_relay_refusals`. Then delete the `BUILD_ROOT_CLAUSE` and `BUILD_REFUSAL_RELAY` constants when `grep -n 'BUILD_ROOT_CLAUSE\|BUILD_REFUSAL_RELAY' home/common/agent-skills/tests/*.py` finds no other use.
2. In `test_delivery_interface_two_is_one_atomic_production_caller_contract`, remove `ORCHESTRATE` from the document tuple and delete the line `self.assertIn("workflow_bootstrap", normalized(self.orchestrate))` (`ORCHESTRATE_MACHINE_TEXT` holds that token). Every other assertion stays; at base every corpus phrase is still found without `ORCHESTRATE`. If a phrase fails after an integration sync only because orchestrate-issues held it, delete that phrase as a scoped prose pin.
3. In `test_lifecycle_calls_are_single_stdin_commands_on_interface_two`, keep the `INPUT_FLAG_RE` value check, the `--result-file` count and the `'"interface_version": 1'` absence for every `LIFECYCLE_DOCS` path, and apply the three English phrases only to paths outside this slice (per D14). Change the clause loop to `for path in (SHIP_ISSUE,):`. If a sync has already introduced a set of exempt scoped paths there, add `ORCHESTRATE` to that set instead. The resulting loop body:

```python
        for path in LIFECYCLE_DOCS:
            text = normalized(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertNotIn('"interface_version": 1', text)
                if path != ORCHESTRATE:
                    for forbidden in ("version-1", "temporary request file",
                                      "temporary `ship-summary/v2` file"):
                        self.assertNotIn(forbidden, text)
                for flag, value in INPUT_FLAG_RE.findall(text):
                    self.assertEqual(value.strip("`.,;"), "-", flag)
                self.assertLessEqual(text.count("--result-file"), 1)
        for path in (SHIP_ISSUE,):
            with self.subTest(clause=path.name):
                self.assertIn(STDIN_CLAUSE, normalized(path.read_text(encoding="utf-8")))
```

4. In `test_the_bound_is_described_as_progress_not_phase`, delete the `(ORCHESTRATE, "at the same phase too many times")` row and keep the `FROM_ISSUE` row.
5. Keep unchanged: `ORCHESTRATE_MACHINE_TEXT` and its test (both trees), `test_direct_and_control_requests_are_interface_two` (§3's 17 keys), `test_dispatcher_passes_immutable_ledger_root_separately_from_worktree`, `test_dispatcher_executes_the_closed_control_action_set`, `test_dispatcher_calls_no_retired_lifecycle_command`, `test_background_dispatch_flag_appears_only_in_orchestrate_issues`, `test_helper_binaries_resolve_from_bare_names`, `test_codex_orchestrate_stub_relays_the_unsupported_route`, `test_build_delivery_callers_name_the_sanctioned_resolution_exception` (per D12), the `CLAUDE_POLICY_ENTRIES` row, `InstalledOrchestrateRoutesTest` and the eval-corpus tests.

- [ ] **Step 2: Remove the L2 debt key and watch the gate fail**

Delete `"L2 home/common/claude-code/skills/orchestrate-issues/SKILL.md",` from `skill-lint-debt.json`.
Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check` (timeout 300 s)
Expected: non-zero exit with `L2 home/common/claude-code/skills/orchestrate-issues/SKILL.md: body is 510 reflowed lines, over 500`.

- [ ] **Step 3: Cut by content class (spec § Content classes)**

1. Frontmatter: replace only the description.
2. Preface: keep the adapter's limits (never read issue content, code, specs, plans, diffs or findings; no second ledger; no reconstructed policy), the `~/.agents/bin/workflow-state` sentence, the resolve paragraph unchanged, one sentence that every lifecycle call reads stdin through a quoted heredoc (`--request-file -` for `control`, `--input -` for `build-delivery`) and writes no request file, the validate-before-decoding rule with its `--boundary workflow-response` command, and the `resume-pack` exception in one sentence.
3. §1: keep both issue-set bullets with their `human_directed` values, cutting the authorization story; the two budget bullets as one; `ledger_repo_root` and the run-reuse pointer; the host-route fence; the `unsupported` stop; `host_route: "claude-code"`; then the D6 line for slots and `admission`.
4. §2: keep the run-reuse rule without "(per D13)"; the init-run fence; the bootstrap fields; the recorded-worktree states and rules; the candidate rules; the tracker and forge normalization; the notification correlation and its two `state` values; classes (a)–(c), each trimmed to its actions; the refresh rule; the restart rule in one sentence.
5. §3: keep the request sentence, the JSON fence, the `[]`/null rule, the per-issue contract rule, the builder fence and its bullets. In the `worktree` bullet keep "never build a recorded issue's contract from a candidate" and drop the builder's resolution-root sentence (per D6). The refusal bullet keeps "send null and `[]`, report the builder's stderr line verbatim in the final report". Keep the `control` fence, the one-line D6 ownership rule, and the accepted-response field list.
6. §4: keep everything named in Invariants. Trim explanations inside the stop pass (keep its steps, the unknown-`check-launch` rule and the non-blocking sweep). Cut the `launch_refused` parking rationale. Compress the `wait` bullets without reordering them.
7. §5: keep every reporting rule in Invariants; compress the `expired` paragraph to its rules.
8. Delete `## Notes`.

- [ ] **Step 4: Models**

Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 5: Run the focused suite**

Run the focused suite (Global Constraints). Expected: OK.

- [ ] **Step 6: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check`. Expected: exit 0.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run:

```bash
set -euo pipefail
PYTHONPATH=python python3 - <<'EOF'
import subprocess
from pathlib import Path
from agent_tools import skill_lint
BASE = "75784bed116805ee948d6e2f7f45a6d0ad3b4212"
PATH = "home/common/claude-code/skills/orchestrate-issues/SKILL.md"
base = subprocess.run(["git", "show", f"{BASE}:{PATH}"], capture_output=True, text=True, check=True).stdout
text = Path(PATH).read_text(encoding="utf-8")
def fences(t):
    out, cur = [], None
    for line in t.splitlines(keepends=True):
        if cur is None:
            if line.startswith("```"):
                cur = [line]
        else:
            cur.append(line)
            if line.startswith("```"):
                out.append("".join(cur)); cur = None
    return out
blocks = fences(base)
assert len(blocks) == 6, len(blocks)
for block in blocks:
    assert block in text, "fence changed: " + block.splitlines()[1]
lines = base.splitlines(keepends=True)
for lo, hi in ((2, 2), (17, 29), (349, 387)):
    assert "".join(lines[lo - 1:hi]) in text, f"base lines {lo}-{hi} changed"
front, body = skill_lint.parse_frontmatter(text)
assert front["description"] == ("Dispatches a set of tracker issues through from-issue --auto as "
    "independent background agents, tracking only a ledger. "
    'Use for "orchestrate issues X, Y, Z".'), "description"
for anchor in ("## 1. Resolve issue set and bindings", "## 2. Bootstrap and observe", "## 3. Decide",
               "## 4. Execute control actions", "## 5. Final report", "**Per-issue contract rule.**",
               "**Stop pass.**", "This is the one rule for such an issue"):
    assert anchor in text, anchor
for gone in ("## Notes", "Claude-only skill: it depends on background agents",
             "The runtime parks the refused owner", "(per D13)"):
    assert gone not in text, gone
assert text.count("Agent(") == 1, "unmarked Agent( line"
reflowed = skill_lint.reflowed_lines(body)
size = len(text.encode("utf-8"))
print(f"SKILL.md body {reflowed} reflowed lines, {size} bytes")
assert reflowed <= 500, "over the L2 limit"
if reflowed > 430 or size > 24000:
    print("over target (name it in the commit body)")
EOF
if grep -q '"L2 home/common/claude-code/skills/orchestrate-issues/SKILL.md"' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
if grep -q 'BUILD_ROOT_CLAUSE, decide\|at the same phase too many times' home/common/agent-skills/tests/test_workflow_skill_contracts.py; then exit 1; fi
```

Expected: exit 0. At Task 2's head it fails first on `description`, and then on `## Notes` and the two test pins.

- [ ] **Step 7: Commit**

Commit `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `tests/test_workflow_skill_contracts.py`, `skill-lint-debt.json` and `instruction-load.json` as `refactor(orchestrate-issues): cut the Claude adapter and delete its prose pins (#298)`.
