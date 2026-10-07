# Task 4: Skill text drops hand-built timestamps

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/final-review.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`
- Modify: `CLAUDE.md` (the `mark-progress` example)
- Modify: `home/common/agent-skills/instruction-load.json`, only if the gate asks for it (Step 4)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Test: `home/common/agent-skills/tests/test_shell_example_contracts.py`

**Interfaces:**
- Consumes: the Task 1–3 behavior. Every ledger-writing command, `control`, `direct-owner` and the contract builder accept an omitted time. No code symbol is consumed.
- Produces: `HandBuiltTimeContractsTest` in `test_workflow_skill_contracts.py`. Task 5 cites it in the acceptance map and does not touch it.

**Invariants:**
- No `.md` file under `home/common/agent-skills/skills`, `home/common/claude-code/skills` or `home/common/codex/skills` contains a `--now` token or a `"now":` JSON key (D9).
- Every other argv token and JSON key in the edited examples is unchanged. Only the time goes.
- The pins stay structural: argv strings, key sets and token scans. No English phrase is pinned (agent-helpers rule 6).
- `CHECKPOINT_CALL` stays byte-identical to ship-issue's Delivery-loop checkpoint call, so the shell-example classification cases keep testing the documented call.

- [ ] **Step 1: Write the failing test and update the pins**

In `test_workflow_skill_contracts.py`, after `CODEX_MODULE`, add:

```python
SKILL_TREES = (REPO_ROOT / "home/common/agent-skills/skills",
               REPO_ROOT / "home/common/claude-code/skills",
               REPO_ROOT / "home/common/codex/skills")
NOW_FLAG = re.compile(r"(?<![\w-])--now(?![\w-])")
NOW_KEY = re.compile(r'"now"\s*:')
```

and append:

```python
class HandBuiltTimeContractsTest(unittest.TestCase):
    """#309 D9: no skill document hands workflow-state a time; the helper reads its clock."""

    def documents(self):
        for tree in SKILL_TREES:
            self.assertTrue(tree.is_dir(), tree)
            yield from sorted(path for path in tree.rglob("*.md") if path.is_file())

    def test_no_skill_document_passes_now(self):
        checked = 0
        for path in self.documents():
            text = path.read_text(encoding="utf-8")
            checked += 1
            with self.subTest(document=str(path.relative_to(REPO_ROOT))):
                self.assertIsNone(NOW_FLAG.search(text))
                self.assertIsNone(NOW_KEY.search(text))
        self.assertGreater(checked, 20)
```

Update the existing pins:
- Remove `"now"` from `V2_DIRECT_REQUEST_KEYS` and from `V2_CONTROL_REQUEST_KEYS`. `V3_CONTROL_REQUEST_KEYS` follows from the latter.
- In the six argv pins (the two `suspend` strings in the Suspension-procedure tests, `LaunchFencedWorkerContractsTest.REGISTER` / `RELEASE`, `ProgressMarkerContractsTest.MARK`, and the `RELEASE` beside the `launch-scope reap` `REAP` constant), delete the `--now <utc> ` token pair and change nothing else.

In `test_shell_example_contracts.py`:
- In `CHECKPOINT_CALL` and `PATH_NAMED_CALL`, delete `--now <utc> `.
- In `LIFECYCLE_VARIANTS`, re-anchor the two argument cases on `--run-id <run-id>`. Change `("substitution argument", "--now <utc>", '--now "$(date -u +%FT%TZ)"', ...)` to `("substitution argument", "--run-id <run-id>", '--run-id "$(cat run-id)"', ("pipe", "heredoc"))`. Change ``("backtick argument", "--now <utc>", "--now `date -u`", ...)`` to ``("backtick argument", "--run-id <run-id>", "--run-id `cat run-id`", ("pipe", "heredoc"))``. Each `old` value must occur exactly once in `CHECKPOINT_CALL`, which the existing `assertEqual(CHECKPOINT_CALL.count(old), 1, name)` enforces.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -15`
Expected: FAIL. `test_no_skill_document_passes_now` names the documents that still pass `--now` or `"now":`. The updated argv pins and key sets no longer match the unedited skills.

- [ ] **Step 3: Edit the skill text**

Delete only the time. Keep each line's other tokens and reflow only where a sentence was removed.
- `from-issue/SKILL.md`:
  - In `### Direct autonomous acquisition`, delete the sentence `Resolve a fresh current RFC3339 UTC instant for every request, including before the first call.`.
  - Delete the `"now": "2026-09-24T10:00:00Z",` line of the interface_version 2 JSON example.
  - In the `delivery_contract` builder input, delete `, "now": "<RFC3339-now>"`.
  - In "orchestrate-issues' exact 18-key shape", write `17-key`.
  - Delete `--now <utc> ` from the `register-worker`, `finish`, `suspend` and `mark-progress` commands.
- `from-issue/AUTO.md`: delete ` --now <utc>` from the bookkeeper's `workflow-state finish --summary-file - …` command.
- `from-issue/ship-handoff.md`: delete `--now <utc> ` from the `release-worker` command.
- `ship-issue/SKILL.md`: delete `--now <utc> ` from the `checkpoint-delivery`, `release-worker` and `finish` commands.
- `sdd/SKILL.md`: delete `--now <utc> ` from the two `register-worker` / `release-worker` commands and from both `mark-progress` commands (in `### Lifecycle workers` and in the task-complete paragraph).
- `sdd/final-review.md`: delete `--now <utc> ` from the `register-worker` and `release-worker` commands.
- `orchestrate-issues/SKILL.md`: delete ` --now <RFC3339-now>` from the `init-run` command, the `"now": "2026-09-24T10:00:00Z",` line of the control-request example, and `, "now": "<RFC3339-now>"` from the builder input.
- `orchestrate-issues/evals/evals.json`: in the first eval's `expected_output`, change `Send the exact 18-key interface_version 3 control request` to `Send the exact 17-key interface_version 3 control request`. The file must still parse as JSON.
- `CLAUDE.md`: in the anti-zombie bullet, delete `--now <utc> ` from the `workflow-state mark-progress …` example.

Run: `grep -rnE -- '--now|"now"[[:space:]]*:|RFC3339-now|18-key' home/common/agent-skills/skills home/common/claude-code/skills home/common/codex/skills CLAUDE.md || true`
Expected: no output.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py 2>&1 | tail -5` (timeout 900 s)
Expected: `OK`.

Run: `just agent-instruction-budget 2>&1 | tail -15` (timeout 600 s)
Expected: `check: pass`. This task only removes text, so a ceiling can only be loose. If the gate prints a `tightness:` line, run `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load tighten`, then re-run the gate until it reads `check: pass`, and add `home/common/agent-skills/instruction-load.json` to the commit.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/sdd/final-review.md home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/claude-code/skills/orchestrate-issues/evals/evals.json CLAUDE.md home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py
git add home/common/agent-skills/instruction-load.json  # only if Step 4 tightened it
git commit -m "docs(skills): stop handing workflow-state a time (#309)"
```
