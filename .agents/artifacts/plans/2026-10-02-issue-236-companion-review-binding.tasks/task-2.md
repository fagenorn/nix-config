# Task 2: Skill binding-shape classifier, companion invocation and validation

**Files:**
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md` (only the `## Direct configured review` section)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's `task --json` payload key `runtime: {model, reasoningEffort}`.
- Produces: four module-level tuples in the test file: `CODEX_SHAPE_CLASSIFIER_ANCHORS`, `CODEX_SHAPE_ERROR_ANCHORS`, `CODEX_COMPANION_INVOCATION_ANCHORS` and `CODEX_COMPANION_VALIDATION_ANCHORS`. Task 3 reuses the last two verbatim, so keep their names and their order.

**Invariants:**
- The section heading `## Direct configured review` and the next heading `## Disposition` are unchanged. The existing read-only-rules test sections the file on them.
- The exec-shape tail code block is byte-identical to today's (per D1).
- The section holds exactly two ```` ```text ```` code blocks: the exec tail first, then the companion tail. The companion block contains no `exec` and does not end in ` -`.
- The shape error comes before the capacity and fallback paragraph, and the shape-error text never offers a fallback (per D3).
- The failure-class paragraph (capacity rejection, routing error, one native fallback) stays one shared paragraph that applies to both shapes. Its sentences are unchanged, so `DIFF-REVIEW.md`'s "closed list of three" stays true (per D8).

- [ ] **Step 1: Write the failing tests.** Add the constants after `CAPACITY_SCOPE_ANCHORS` and replace `assert_codex_operation_pair` with the version below.

```python
# Issue 236: the closed set of review binding shapes and their routes (D1-D6).
CODEX_SHAPE_CLASSIFIER_ANCHORS = (
    "review binding shape",
    "basename of `argv[0]` is exactly `codex`",
    "basename of `argv[0]` is exactly `codex-companion`",
    "`argv[1]` is `task`",
    "`--reviewer <op>`",
    "optional `--fresh`",
    "binding shape error",
)
CODEX_SHAPE_ERROR_ANCHORS = (
    "binding shape error is a configuration error",
    "no Codex call", "no retry", "no native fallback",
    "`review_id`", "authored argv",
    "unrecognised executable",
    "a companion subcommand other than `task`",
    "a missing or mismatched `--reviewer`",
    "an unsupported companion token",
    "no capability repair ID",
)
# In text order: the stdin sentence precedes the tail's code block.
CODEX_COMPANION_INVOCATION_ANCHORS = (
    "no positional argument",
    "--model gpt-6-astra --effort xhigh",
    "--cwd <absolute-worktree> --json",
)
CODEX_COMPANION_VALIDATION_ANCHORS = (
    "exactly one JSON object",
    "`status` is `0`",
    "`touchedFiles` is empty",
    "`runtime.model` is `gpt-6-astra`",
    "`runtime.reasoningEffort` is `xhigh`",
    "`rawOutput` is a non-empty string",
    "single terminal agent message",
    "No JSONL or last-message candidate",
)


def assert_codex_operation_pair(case, support, review_field, headings):
    owner = normalized(COLLABORATION.read_text(encoding="utf-8"))
    support_text = normalized(support.read_text(encoding="utf-8"))
    case.assert_ordered(
        owner,
        review_field,
        *CODEX_SHAPE_CLASSIFIER_ANCHORS, *CODEX_SHAPE_ERROR_ANCHORS,
        "bindings.commands[review_id].argv",
        "exec", "--sandbox read-only", "--model gpt-6-astra",
        'model_reasoning_effort="xhigh"', "--json",
        "--output-last-message", "--ephemeral",
        "selected model", "selected reasoning effort",
        "terminal agent-message", "last-message",
        *CODEX_COMPANION_INVOCATION_ANCHORS,
        *CODEX_COMPANION_VALIDATION_ANCHORS,
        *CAPACITY_SCOPE_ANCHORS,
    )
    case.assertIn("retained `ResolvedProject`", support_text)
    case.assertIn(review_field, support_text)
    for heading in headings:
        case.assertIn(heading, support_text)
    case.assertNotIn("resolve-project resolve", support_text)
```

Add these methods to `WorkflowSkillContractsTest`, beside `test_codex_collaboration_dispatch_carries_operation_envelope`:

```python
    def direct_review_section(self):
        return self.section(
            self.collaboration, "## Direct configured review", "## Disposition")

    def test_codex_collaboration_has_one_tail_per_binding_shape(self):
        blocks = re.findall(r"```text\n(.*?)```", self.direct_review_section(), re.S)
        self.assertEqual(len(blocks), 2, blocks)
        exec_tail, companion_tail = blocks
        self.assertEqual(
            exec_tail,
            "bindings.commands[review_id].argv \\\n"
            "  exec --sandbox read-only --model gpt-6-astra \\\n"
            '  -c model_reasoning_effort="xhigh" --json \\\n'
            "  --output-last-message <absolute-last-message> --ephemeral \\\n"
            "  -C <absolute-worktree> -\n",
        )
        self.assertEqual(
            companion_tail,
            "bindings.commands[review_id].argv \\\n"
            "  --model gpt-6-astra --effort xhigh \\\n"
            "  --cwd <absolute-worktree> --json\n",
        )

    def test_codex_collaboration_shape_error_stops_before_any_fallback(self):
        section = normalized(self.direct_review_section())
        error_at = section.index("binding shape error is a configuration error")
        fallback_at = section.index("uses exactly one native fallback")
        self.assertLess(error_at, fallback_at)
        # The shape-error paragraph itself never offers the fallback.
        error_paragraph = section[error_at:section.index("**Exec shape.**", error_at)]
        for offered in ("one native fallback", "same packet", "Claude fallback"):
            self.assertNotIn(offered, error_paragraph)
        # It is a pre-call stop, not a fourth failure class.
        self.assertNotIn("fourth failure class", section)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k codex 2>&1 | tail -5`
Expected: FAIL. The base text has no `review binding shape`, so the `missing anchor` assertion fails, and there is only one `text` code block.

- [ ] **Step 3: Rewrite `## Direct configured review`.** Keep this order, and use each anchor phrase above literally:

1. Keep today's opening sentence: "Build the operation packet from its support document."
2. **Classifier** (per D1, D2). Before any invocation, classify the selected command's authored argv into one **review binding shape**, as a three-item list. Exec shape: the basename of `argv[0]` is exactly `codex`. Companion shape: the basename of `argv[0]` is exactly `codex-companion`, `argv[1]` is `task`, and the remaining tokens are exactly `--reviewer <op>` plus an optional `--fresh`, in any order. `<op>` equals the running operation. No other flag and no positional token may appear, because the skill owns model, effort, cwd and output, and a positional would displace the stdin packet. Anything else is a **binding shape error**.
3. **Shape error** paragraph (per D3, D8), starting "A binding shape error is a configuration error". It makes no Codex call, no retry and no native fallback, and stops the operation with one error. The error names the operation, the `review_id`, the authored argv, and exactly one cause: unrecognised executable, a companion subcommand other than `task`, a missing or mismatched `--reviewer`, or an unsupported companion token. It stops the way `blocked` does but carries no capability repair ID. Do not use the words "fallback with the same packet" here.
4. `**Exec shape.**` Today's candidate and cleanup sentences, the exact tail code block, and today's validation paragraph, unchanged.
5. `**Companion shape.**` (per D4, D6) Preserve the base argv, cwd and declared env (unset only declared env names). Append the exact tail and send the complete packet on stdin with no positional argument, in the foreground:

   ```text
   bindings.commands[review_id].argv \
     --model gpt-6-astra --effort xhigh \
     --cwd <absolute-worktree> --json
   ```

   Then the validation, as one sentence or a short list. Require exit status 0 and stdout that parses as exactly one JSON object; `status` is `0`; `touchedFiles` is empty; `runtime.model` is `gpt-6-astra` and `runtime.reasoningEffort` is `xhigh`; `rawOutput` is a non-empty string, the turn's single terminal agent message. Then validate the operation headings. Say: "No JSONL or last-message candidate is created on this route." Only that success establishes reviewer identity `Codex`. It is true to add that the companion's reviewer mode forces a fresh, read-only, ephemeral thread and applies its own wall-clock budget, so the tail passes none of these.
6. Keep today's failure-class paragraph unchanged as the section's last paragraph. It starts "On the `available` route, a daemon, slot, or capacity rejection" and covers both shapes.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3`
Expected: `OK`. That includes the unchanged `test_codex_collaboration_never_reports_sandbox_limits_as_findings`, `test_codex_collaboration_dispatch_carries_operation_envelope` and `test_codex_plan_review_owner_and_support_are_complete` / `..._diff_review_...`.
Also run `git diff --quiet -- home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md`. Expected: exit 0, since both are out of scope.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/codex-collaboration/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(codex-collaboration): classify review binding shapes and drive the companion task (#236)"
```
