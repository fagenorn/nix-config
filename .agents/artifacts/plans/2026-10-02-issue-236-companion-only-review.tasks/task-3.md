# Task 3: Evals describe the companion invocation only

**Files:**
- Modify: `home/common/claude-code/skills/codex-collaboration/evals/evals.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes, from Task 1: the module constant `RETIRED_EXEC_REVIEW_TOKENS` (`"exec --sandbox"`, `"--output-last-message"`, `"terminal agent-message"`, `"model_reasoning_effort"`, `"JSONL"`, `"Exec shape"`, `"exec shape"`). Also `cls.codex_collaboration_evals`, which the test class already loads, and `test_live_evals_grade_strict_policy_and_direct_review`.
- Produces: nothing for other tasks.

**Invariants:**
- Evals 1–3 describe the companion tail, stdin delivery, the payload validation and the binding shape error with its expected form, and contain none of `RETIRED_EXEC_REVIEW_TOKENS` (per D12, D15, D17).
- Eval ids, names, `mode`, `files` and every sentence not named below are unchanged. `evals.json` stays valid JSON.

- [ ] **Step 1: Write the failing tests.** In `test_live_evals_grade_strict_policy_and_direct_review`, replace the `required` tuple's last line set `"bindings.commands", "gpt-6-astra", 'model_reasoning_effort="xhigh"', "selected model", "last-message",` with `"bindings.commands", "gpt-6-astra", "--effort xhigh", "runtime.reasoningEffort", "rawOutput",`. Then add to `WorkflowSkillContractsTest`:

```python
    def test_codex_collaboration_evals_describe_only_the_companion_shape(self):
        evals = {item["id"]: item for item in self.codex_collaboration_evals["evals"]}
        companion_tail = "--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json"
        self.assertIn(
            '["codex-companion","task","--fresh","--reviewer","plan-review"]',
            evals[1]["prompt"],
        )
        for eval_id in (1, 2, 3):
            expected = evals[eval_id]["expected_output"]
            for fragment in (
                companion_tail, "no positional argument", "touchedFiles",
                "runtime.model gpt-6-astra", "runtime.reasoningEffort xhigh",
                "rawOutput", "binding shape error",
                "codex-companion task [--fresh] --reviewer <op>",
            ):
                with self.subTest(eval=eval_id, fragment=fragment):
                    self.assertIn(fragment, expected)
            for retired in RETIRED_EXEC_REVIEW_TOKENS:
                with self.subTest(eval=eval_id, retired=retired):
                    self.assertNotIn(retired, evals[eval_id]["prompt"] + expected)
```

- [ ] **Step 2: Run and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k evals 2>&1 | tail -5`
Expected: FAIL — eval 1's prompt names no argv, and the corpus lacks `runtime.reasoningEffort`.

- [ ] **Step 3: Edit `evals.json`.** Values below are decoded; write them with JSON escaping (`\"` for each `"` inside a value). Edit with a JSON-aware tool (for example a short `python3` script that loads, assigns and dumps with `indent=2, ensure_ascii=False` plus a trailing newline), then confirm `git diff` touches only these four values.

Eval 1 `prompt`:
`At from-issue Phase 5, plan-review is ready, capabilities.review.plan is available, and bindings.commands[review_id].argv is ["codex-companion","task","--fresh","--reviewer","plan-review"]. Plan-only: explain selection, binding shape, direct invocation, validation, failure handling, and disposition.`

Eval 1 `expected_output`:
`Resolve once into a retained ResolvedProject. Select bindings.workflow.review.plan, capabilities.review.plan, and bindings.commands[review_id]; a refusal is fatal. blocked stops with its reason and repair ID; unsupported takes the documented native route. For available, classify the authored argv: basename codex-companion, subcommand task, --reviewer plan-review matching the running operation, optional --fresh and no other token make it the one supported shape. Any other argv, bare ["codex"] included, is a binding shape error naming the expected form codex-companion task [--fresh] --reviewer <op> and its cause, and stops with no Codex call, no retry and no native fallback. Preserve base argv/cwd/env and append `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json`, sending the complete packet on stdin with no positional argument, in the foreground. Require exit 0 and exactly one JSON object with status 0, empty touchedFiles, runtime.model gpt-6-astra, runtime.reasoningEffort xhigh, and a non-empty rawOutput, the last captured agent message, before Blocking / Should fix / Discussion establish Codex. A daemon, slot, or capacity rejection stops verbatim with no retry and no native fallback. A completed non-capacity runtime, payload, output, or schema failure takes exactly one native fallback with the same packet. The parent verifies and dispositions findings without storing the raw transcript.`

Eval 2 `expected_output`: replace exactly the sentence that starts `Invoke base argv/cwd/env plus` and ends `then Critical / Important / Minor.` with:
`Check the authored argv is codex-companion task --reviewer diff-review with optional --fresh; any other argv, bare ["codex"] included, is a binding shape error naming the expected form codex-companion task [--fresh] --reviewer <op> and stops with no Codex call, retry or native fallback. Invoke base argv/cwd/env plus `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json`, send the packet on stdin with no positional argument, and require one JSON object with status 0, empty touchedFiles, runtime.model gpt-6-astra, runtime.reasoningEffort xhigh and a non-empty rawOutput, then Critical / Important / Minor.`

Eval 3 `expected_output`: replace exactly the sentence that starts `Invoke the base command plus exact D7 argv augmentation` and ends `and Critical/Important/Minor.` with:
`Only codex-companion task --reviewer diff-review with optional --fresh is driven; any other argv is a binding shape error naming the expected form codex-companion task [--fresh] --reviewer <op>, with no Codex call, retry or native fallback. Invoke the base command plus `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json` with the packet on stdin and no positional argument, and validate one JSON object's status 0, empty touchedFiles, runtime.model gpt-6-astra, runtime.reasoningEffort xhigh and non-empty rawOutput, then Critical/Important/Minor.`

- [ ] **Step 4: Verify**

Run: `python3 -c 'import json; json.load(open("home/common/claude-code/skills/codex-collaboration/evals/evals.json"))' && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3`
Expected: the JSON loads and the run ends `OK`.
Run: `if grep -nE 'output-last-message|JSONL|model_reasoning_effort' home/common/claude-code/skills/codex-collaboration/evals/evals.json; then exit 1; fi`
Expected: no output, exit 0. At the start commit lines 10, 18 and 26 match, so this gate can fail.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/codex-collaboration/evals/evals.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "test(codex-collaboration): evals describe the companion review binding only (#236)"
```
