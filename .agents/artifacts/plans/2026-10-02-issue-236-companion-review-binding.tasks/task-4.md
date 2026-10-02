# Task 4: Evals describe both shapes; final gate

**Files:**
- Modify: `home/common/claude-code/skills/codex-collaboration/evals/evals.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the SKILL.md wording from Task 2 (binding shape, companion tail, payload validation) and `cls.codex_collaboration_evals`, which the test class already loads but no test reads yet.
- Produces: nothing for other tasks.

**Invariants:**
- Eval 1 is the plan review on the companion binding, and it never names the exec tail.
- Evals 2 and 3 carry both shapes' tails verbatim, and the binding shape error.
- `test_live_evals_grade_strict_policy_and_direct_review` stays green. Its corpus still needs `gpt-6-astra`, `model_reasoning_effort="xhigh"`, `selected model` and `last-message`, which evals 2 and 3 keep.
- Eval ids, names, `mode` and `files` are unchanged. `evals.json` stays valid JSON.

- [ ] **Step 1: Write the failing test** in `WorkflowSkillContractsTest`:

```python
    def test_codex_collaboration_evals_describe_both_binding_shapes(self):
        evals = {item["id"]: item for item in self.codex_collaboration_evals["evals"]}
        exec_tail = (
            'exec --sandbox read-only --model gpt-6-astra -c model_reasoning_effort="xhigh" '
            "--json --output-last-message <absolute-last-message> --ephemeral "
            "-C <absolute-worktree> -"
        )
        companion_tail = "--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json"
        first = evals[1]
        self.assertIn(
            '["codex-companion","task","--fresh","--reviewer","plan-review"]',
            first["prompt"],
        )
        for fragment in (
            companion_tail, "no positional argument", "runtime.model",
            "runtime.reasoningEffort", "rawOutput", "touchedFiles",
            "no JSONL or last-message candidate", "binding shape error",
            "establish Codex",
        ):
            with self.subTest(eval=1, fragment=fragment):
                self.assertIn(fragment, first["expected_output"])
        self.assertNotIn("--output-last-message", first["expected_output"])
        for eval_id in (2, 3):
            expected = evals[eval_id]["expected_output"]
            for fragment in (exec_tail, companion_tail, "no positional argument",
                             "runtime.reasoningEffort", "binding shape error"):
                with self.subTest(eval=eval_id, fragment=fragment):
                    self.assertIn(fragment, expected)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k binding_shapes 2>&1 | tail -5`
Expected: FAIL. Eval 1's prompt has no companion argv.

- [ ] **Step 3: Edit `evals.json`** (JSON string escaping applies: `\"` inside values).

Eval 1 `prompt`, written as the decoded value:
`At from-issue Phase 5, plan-review is ready, capabilities.review.plan is available, and bindings.commands[review_id].argv is ["codex-companion","task","--fresh","--reviewer","plan-review"]. Plan-only: explain selection, binding shape, direct invocation, validation, failure handling, and disposition.`

Eval 1 `expected_output`, decoded value:
`Resolve once into a retained ResolvedProject. Select bindings.workflow.review.plan, capabilities.review.plan, and bindings.commands[review_id]; a refusal is fatal. blocked stops with its reason and repair ID; unsupported takes the documented native route. For available, classify the authored argv: basename codex-companion, subcommand task, --reviewer plan-review matching the running operation, optional --fresh and no other token make it the companion shape; an unrecognised executable, another subcommand, a missing or mismatched --reviewer or an unsupported token would be a binding shape error that stops with no Codex call, no retry and no native fallback. Preserve base argv/cwd/env and append `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json`, sending the complete packet on stdin with no positional argument, in the foreground; no JSONL or last-message candidate is created. Require exit 0 and exactly one JSON object with status 0, empty touchedFiles, runtime.model gpt-6-astra, runtime.reasoningEffort xhigh, and a non-empty rawOutput, the single terminal agent message, before Blocking / Should fix / Discussion establish Codex. A daemon, slot, or capacity rejection stops verbatim with no retry and no native fallback. A completed non-capacity runtime, payload, output, or schema failure takes exactly one native fallback with the same packet. The parent verifies and dispositions findings without storing the raw transcript.`

Eval 2 `expected_output`: replace exactly the sentence that starts `Invoke base argv/cwd/env plus` and ends `then Critical / Important / Minor.` with:
`Classify the authored argv. For the exec shape (basename codex) invoke base argv/cwd/env plus `exec --sandbox read-only --model gpt-6-astra -c model_reasoning_effort=\"xhigh\" --json --output-last-message <absolute-last-message> --ephemeral -C <absolute-worktree> -` and validate all JSONL, selected model/effort, exactly one terminal agent-message and non-empty last-message byte equality. For the companion shape (codex-companion task --reviewer diff-review, optional --fresh) append `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json`, send the packet on stdin with no positional argument, and require one JSON object with status 0, empty touchedFiles, runtime.model gpt-6-astra, runtime.reasoningEffort xhigh and a non-empty rawOutput. Any other argv is a binding shape error that stops with no Codex call, retry or native fallback. Then validate Critical / Important / Minor.`

Eval 3 `expected_output`: replace exactly the sentence that starts `Invoke the base command plus exact D7 argv augmentation` and ends `and Critical/Important/Minor.` with:
`Classify the authored argv. The exec shape invokes the base command plus `exec --sandbox read-only --model gpt-6-astra -c model_reasoning_effort=\"xhigh\" --json --output-last-message <absolute-last-message> --ephemeral -C <absolute-worktree> -` and validates JSONL selected model/effort, one terminal message and last-message bytes. The companion shape appends `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json` with the packet on stdin and no positional argument, and validates one JSON object's status 0, empty touchedFiles, runtime.model, runtime.reasoningEffort xhigh and non-empty rawOutput. Any other argv is a binding shape error with no Codex call, retry or native fallback. Then validate Critical/Important/Minor.`

(The `\"` above is the JSON-encoded form of the quote in `model_reasoning_effort="xhigh"`, the same encoding the file uses today.)

- [ ] **Step 4: Verify (final gate for the whole plan)**

Run, from the worktree:

```bash
python3 -c 'import json,sys; json.load(open("home/common/claude-code/skills/codex-collaboration/evals/evals.json"))'
PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3
just agent-workflow-tests 2>&1 | tail -3
just build 2>&1 | tail -3
```

Expected: the JSON loads; both unittest runs end `OK`; `just build` succeeds and leaves `./result`. Then confirm that the installed skill text is the edited source:

```bash
nix-store -qR result | while read -r p; do
  f="$p/codex-collaboration/SKILL.md"; [ -f "$f" ] && echo "$f"
done | xargs grep -l 'review binding shape'
```

Expected: at least one path. If none is found at that depth, run `find <closure path> -maxdepth 4 -path '*codex-collaboration/SKILL.md'` on the skills store path to locate the file, then grep it the same way. At the base commit, the new eval test fails and no built `SKILL.md` contains `review binding shape`, so this gate can fail.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/codex-collaboration/evals/evals.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "test(codex-collaboration): evals describe both review binding shapes (#236)"
```
