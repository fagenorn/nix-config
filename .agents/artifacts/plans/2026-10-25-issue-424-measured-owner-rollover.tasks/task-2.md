# Task 2: One home for the phase budget, and skill text that stops restating it

Spec § Phase-budget defaults, § Skill text, test seams 2, 3 and 5; per D7, D11 and D15. The four phase-budget defaults move into a new package module, the context default drops from 150,000 to 120,000, and the from-issue skill stops restating the numbers and stops asking for context usage.

**Files:**
- Create: `python/agent_tools/phase_budget.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (the `progress` subparser's four defaults and one import)
- Modify: `home/common/agent-skills/tests/test_workflow_state.py` (the `progress` helper; a new `PhaseBudgetDefaultsTest`)
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/rollover.md`, `home/common/agent-skills/skills/from-issue/delegated-owner.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`test_owner_has_executable_phase_gate_and_action_semantics`)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `agent_tools.phase_budget` with exactly four module-level `int` constants, `TURN_CEILING = 120`, `TURN_HEADROOM = 2`, `CONTEXT_CEILING = 120000`, `CONTEXT_HEADROOM = 10000` (Task 3 computes its threshold as `CONTEXT_CEILING - CONTEXT_HEADROOM`).

**Invariants:**
- No file other than `phase_budget.py` holds these defaults; `workflow-state.py` imports the module as `from agent_tools import phase_budget` and its four `progress` options read `default=phase_budget.TURN_CEILING`, `phase_budget.CONTEXT_CEILING`, `phase_budget.TURN_HEADROOM`, `phase_budget.CONTEXT_HEADROOM`.
- `select_phase_action`, `validate_phase_inputs` and every other parser option are unchanged; explicit ceiling flags keep working, and every existing test that passes them is unedited apart from the helper.
- The from-issue skill keeps the turn-count clause (observed when available, never fabricated) and drops only the context-token request and the restated numbers (D11).

- [ ] **Step 1: Write the failing tests**

In `test_workflow_state.py`, change `LifecycleHarness.progress` so each of `turn_ceiling`, `context_ceiling`, `turn_headroom` and `context_headroom` emits its flag only when its value is not `None` (the defaults 120, 150000, 2, 10000 stay, so existing callers are unchanged): remove the four flag/value pairs from the `args` literal and, after it, add

```python
        for flag, value in (("--turn-ceiling", turn_ceiling), ("--context-ceiling", context_ceiling),
                            ("--turn-headroom", turn_headroom),
                            ("--context-headroom", context_headroom)):
            if value is not None:
                args.extend((flag, value))
```

Then add this class directly before `class PhaseGateReplyTest`:

```python
class PhaseBudgetDefaultsTest(LifecycleHarness, unittest.TestCase):
    """Issue 424: the phase-budget defaults live in agent_tools.phase_budget alone."""

    MINIMAL = ["progress", "--repo-root", "/ledger", "--run-id", "run-1", "--issue", "1",
               "--attempt", "1", "--phase", "0", "--next-needs-context", "true",
               "--artifacts-sufficient", "false", "--remainder-self-contained", "false"]
    BUDGET_FLAGS = ("--turn-ceiling", "--turn-headroom", "--context-ceiling",
                    "--context-headroom")

    def test_default_ceiling_hands_off_at_110000_and_continues_at_109999(self):
        self.init_run()
        self.spawn(issue=14, worktree=self.root / "wt-a")
        defaults = dict(turn_ceiling=None, context_ceiling=None, turn_headroom=None,
                        context_headroom=None)
        below = self.progress(issue=14, attempt=1, phase=1, now="2026-08-13T20:05:00Z",
                              turn_count=10, context_tokens=109999, **defaults)
        self.assertEqual(below["action"], "continue")
        at = self.progress(issue=14, attempt=1, phase=2, now="2026-08-13T20:10:00Z",
                           turn_count=10, context_tokens=110000, **defaults)
        self.assertEqual(at["action"], "handoff")

    def test_the_four_defaults_have_one_home(self):
        from agent_tools import phase_budget
        self.assertEqual((phase_budget.TURN_CEILING, phase_budget.TURN_HEADROOM,
                          phase_budget.CONTEXT_CEILING, phase_budget.CONTEXT_HEADROOM),
                         (120, 2, 120000, 10000))
        workflow = load_source_module(SCRIPT, "workflow_state_phase_budget_defaults")
        args = workflow.build_parser().parse_args(self.MINIMAL)
        self.assertEqual((args.turn_ceiling, args.turn_headroom, args.context_ceiling,
                          args.context_headroom), (120, 2, 120000, 10000))
        defaults = {}
        for node in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value in self.BUDGET_FLAGS):
                defaults[node.args[0].value] = [
                    ast.unparse(keyword.value) for keyword in node.keywords
                    if keyword.arg == "default"]
        self.assertEqual(defaults, {
            "--turn-ceiling": ["phase_budget.TURN_CEILING"],
            "--turn-headroom": ["phase_budget.TURN_HEADROOM"],
            "--context-ceiling": ["phase_budget.CONTEXT_CEILING"],
            "--context-headroom": ["phase_budget.CONTEXT_HEADROOM"]})

    def test_progress_reads_each_spelling_the_meter_removes_as_context_tokens(self):
        """The context meter drops every prefix of --context-tokens from --context-t on (D15)."""
        parser = load_source_module(
            SCRIPT, "workflow_state_context_tokens_spellings").build_parser()
        for spelling in ("--context-t", "--context-tok", "--context-tokens"):
            with self.subTest(spelling=spelling):
                self.assertEqual(parser.parse_args([*self.MINIMAL, spelling, "5"]).context_tokens, 5)
                self.assertEqual(parser.parse_args([*self.MINIMAL, f"{spelling}=7"]).context_tokens, 7)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([*self.MINIMAL, "--context-", "5"])
```

In `test_workflow_skill_contracts.py`, replace the body of `test_owner_has_executable_phase_gate_and_action_semantics` with:

```python
        self.assertIn("workflow-state progress", self.from_issue)
        self.assertIn("continue | fresh_start | handoff | delegate", self.from_issue)
        # Issue 424: the ceilings live in agent_tools.phase_budget and the context meter
        # supplies the count, so no from-issue document restates either.
        for document in sorted(FROM_ISSUE_DIR.glob("*.md")):
            text = document.read_text(encoding="utf-8")
            for argv in ("--turn-ceiling", "--turn-headroom", "--context-ceiling",
                         "--context-headroom", "--context-tokens"):
                with self.subTest(document=document.name, argv=argv):
                    self.assertNotIn(argv, text)
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k PhaseBudgetDefaultsTest 2>&1 | tail -4'
bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_owner_has_executable_phase_gate 2>&1 | tail -4'
```

(timeout 600 s each). Expected: the first `FAILED` — `continue != handoff` at 110000 and `No module named 'agent_tools.phase_budget'`; the spelling test passes already (it pins what argparse does today). The second `FAILED` — `--turn-ceiling`, `--context-ceiling`, `--turn-headroom`, `--context-headroom` and `--context-tokens` found in `SKILL.md`.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/phase_budget.py`: a module docstring saying it is the one home of the phase-budget defaults (issue 424) and that `workflow-state progress` takes its argparse defaults from it, then the four constants of **Interfaces** and nothing else.

`workflow-state.py`: add `from agent_tools import phase_budget` beside the other `agent_tools` imports, and change the four `progress.add_argument` lines to `default=phase_budget.TURN_CEILING`, `default=phase_budget.CONTEXT_CEILING`, `default=phase_budget.TURN_HEADROOM`, `default=phase_budget.CONTEXT_HEADROOM`.

`from-issue/SKILL.md`, in the **Executable phase gate** paragraph, replace

`the completed phase, the observed turn count and context tokens when available (omit an unavailable `--turn-count` or `--context-tokens`; never fabricate usage), and truthful booleans for next-phase context need, artifact sufficiency and remainder self-containment. Use the defaults `--turn-ceiling 120 --context-ceiling 150000 --turn-headroom 2 --context-headroom 10000`, and obey`

with

`the completed phase, the observed turn count when available (omit an unavailable `--turn-count`; never fabricate it), and truthful booleans for next-phase context need, artifact sufficiency and remainder self-containment, and obey`

and in the paragraph that starts `On the direct-autonomous route`, replace `with the 120-turn/150000-token ceilings and` with `with the default ceilings of `workflow-state progress` and`.

`rollover.md`: replace `for completed Phase 5 with truthful available usage and the exact gate values` with `for completed Phase 5 with the exact gate values`.

`delegated-owner.md`: replace `for completed Phase 6 with truthful available usage and `next_needs_context=false`` with `for completed Phase 6 with `next_needs_context=false``, and `use truthful available usage and the same three gate values` with `use the same three gate values`.

- [ ] **Step 4: Verify**

Rerun both Step 2 commands. Expected: `Ran 3 tests` and `OK`; `Ran 1 test` and `OK`. Then (timeout 3600 s each):

```bash
bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_attempt_custody.py home/common/agent-skills/tests/test_delivery_workflow.py 2>&1 | tail -4'
bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -6; echo "exit ${PIPESTATUS[0]}"'
if git grep -n -E '150000|120000|10000' -- home/common/agent-skills/skills/from-issue; then exit 1; fi
```

Expected: `OK` for the four modules (every existing fixture that passes explicit ceilings unchanged); the budget gate `exit 0` without `--raise-label` (AC7); the `git grep` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/phase_budget.py home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/test_workflow_state.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  home/common/agent-skills/skills/from-issue/SKILL.md \
  home/common/agent-skills/skills/from-issue/rollover.md \
  home/common/agent-skills/skills/from-issue/delegated-owner.md
launch-commit … -- -m "feat(workflow-state): one home for the phase budget, 120k context ceiling (issue 424)" -m "<session trailers>"
```

Verify: `git status --short -- python home/common/agent-skills` prints nothing.
