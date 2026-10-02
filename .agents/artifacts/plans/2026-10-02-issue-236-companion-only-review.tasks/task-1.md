# Task 1: Skill — companion-only classifier, invocation, validation and shape error

**Files:**
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md` (section `## Direct configured review` only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: HEAD's two-shape text from commit 55e56aa (read `git show 55e56aa` first). The module constants `CODEX_SHAPE_CLASSIFIER_ANCHORS`, `CODEX_SHAPE_ERROR_ANCHORS`, `CODEX_COMPANION_INVOCATION_ANCHORS`, `CODEX_COMPANION_VALIDATION_ANCHORS`, `CAPACITY_SCOPE_ANCHORS`; helpers `normalized`, `assert_codex_operation_pair`, `self.section`, `self.direct_review_section`.
- Produces, for Tasks 2–3: the module constant `RETIRED_EXEC_REVIEW_TOKENS`, and `CODEX_COMPANION_INVOCATION_ANCHORS` / `CODEX_COMPANION_VALIDATION_ANCHORS` with exactly the values below. The SKILL.md phrases `one supported review binding shape`, `**Invocation.**`, `**Validation.**` and `malformed or mismatched payload`.

**Invariants:**
- `## Direct configured review` holds exactly one ```` ```text ```` block, the companion tail (per D4, D12).
- SKILL.md contains none of `RETIRED_EXEC_REVIEW_TOKENS` (per D12, D17).
- The shape-error paragraph names the expected form and offers no fallback; it precedes the capacity paragraph's `uses exactly one native fallback` (per D3, D13).
- The capacity paragraph keeps every failure class; only `metadata/output` becomes `payload` (per D6).
- Sections other than `## Direct configured review` are byte-identical.

- [ ] **Step 1: Write the failing tests.** In `test_workflow_skill_contracts.py`, replace the block that starts at the comment `# Issue 236: the closed set of review binding shapes and their routes (D1-D6).` and ends at the closing `)` of `CODEX_COMPANION_VALIDATION_ANCHORS` with:

```python
# Issue 236: the one review binding shape, its invocation and validation (D12-D15).
CODEX_SHAPE_CLASSIFIER_ANCHORS = (
    "one supported review binding shape",
    "basename of `argv[0]` is exactly `codex-companion`",
    "`argv[1]` is `task`",
    "`--reviewer <op>`",
    "optional `--fresh`",
    'bare `["codex"]` included',
    "binding shape error",
)
CODEX_SHAPE_ERROR_ANCHORS = (
    "binding shape error is a configuration error",
    "no Codex call", "no retry", "no native fallback",
    "`review_id`", "authored argv",
    "`codex-companion task [--fresh] --reviewer <op>`",
    "an executable other than `codex-companion`",
    "a companion subcommand other than `task`",
    "a missing or mismatched `--reviewer`",
    "an unsupported companion token",
    "no capability repair ID",
)
# In text order: the stdin sentence precedes the tail.
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
    "last captured agent message",
)
# Retired with the exec route (D12, D17): none may reappear in the skill, the
# two caller paragraphs or the evals.
RETIRED_EXEC_REVIEW_TOKENS = (
    "exec --sandbox", "--output-last-message", "terminal agent-message",
    "model_reasoning_effort", "JSONL", "Exec shape", "exec shape",
)
```

Replace the `case.assert_ordered(owner, ...)` call in `assert_codex_operation_pair` and add the retired-token loop right after it (the rest of the helper is unchanged):

```python
    case.assert_ordered(
        owner,
        review_field,
        *CODEX_SHAPE_CLASSIFIER_ANCHORS, *CODEX_SHAPE_ERROR_ANCHORS,
        CODEX_COMPANION_INVOCATION_ANCHORS[0],
        "bindings.commands[review_id].argv",
        *CODEX_COMPANION_INVOCATION_ANCHORS[1:],
        *CODEX_COMPANION_VALIDATION_ANCHORS,
        *CAPACITY_SCOPE_ANCHORS,
    )
    for retired in RETIRED_EXEC_REVIEW_TOKENS:
        case.assertNotIn(retired, owner)
```

Replace `test_codex_collaboration_dispatch_carries_operation_envelope`, `test_codex_collaboration_has_one_tail_per_binding_shape` and `test_codex_collaboration_shape_error_stops_before_any_fallback` with these three (keep `direct_review_section` as is):

```python
    def test_codex_collaboration_dispatch_carries_operation_envelope(self):
        text = normalized(self.collaboration)
        self.assertIn("bindings.commands[review_id].argv", text)
        self.assertIn("--cwd <absolute-worktree> --json", text)
        self.assertIn("`rawOutput` is a non-empty string", text)

    def test_codex_collaboration_has_exactly_one_companion_tail(self):
        section = self.direct_review_section()
        blocks = re.findall(r"```text\n(.*?)```", section, re.S)
        self.assertEqual(blocks, [
            "bindings.commands[review_id].argv \\\n"
            "  --model gpt-6-astra --effort xhigh \\\n"
            "  --cwd <absolute-worktree> --json\n",
        ])
        for retired in RETIRED_EXEC_REVIEW_TOKENS:
            with self.subTest(retired=retired):
                self.assertNotIn(retired, self.collaboration)
        text = normalized(section)
        self.assertIn("malformed or mismatched payload", text)
        self.assertNotIn("metadata", text)

    def test_codex_collaboration_shape_error_stops_before_any_fallback(self):
        section = normalized(self.direct_review_section())
        error_at = section.index("binding shape error is a configuration error")
        fallback_at = section.index("uses exactly one native fallback")
        self.assertLess(error_at, fallback_at)
        error_paragraph = section[error_at:section.index("**Invocation.**", error_at)]
        self.assertIn("`codex-companion task [--fresh] --reviewer <op>`", error_paragraph)
        self.assertIn("(bare `codex` included)", error_paragraph)
        # The shape-error paragraph itself never offers the fallback.
        for offered in ("one native fallback", "same packet", "Claude fallback"):
            self.assertNotIn(offered, error_paragraph)
        # It is a pre-call stop, not a fourth failure class.
        self.assertNotIn("fourth failure class", section)
```

In `test_codex_collaboration_states_a_per_operation_wall_clock`, replace `self.assertIn('model_reasoning_effort="xhigh"', self.collaboration)` with `self.assertIn("--effort xhigh", self.collaboration)`.

- [ ] **Step 2: Run and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k codex 2>&1 | tail -5`
Expected: FAIL — the tail test finds two blocks, `RETIRED_EXEC_REVIEW_TOKENS` hits `exec --sandbox`, and `one supported review binding shape` is missing.

- [ ] **Step 3: Rewrite the section.** In SKILL.md, replace everything from `Build the operation packet from its support document.` through the companion paragraph's closing `establishes reviewer identity `Codex`.` with this text, verbatim (it is the skill's instruction, so it is its behavior):

````markdown
Build the operation packet from its support document. Before any invocation,
classify the selected command's authored argv. It has the one supported review
binding shape, the companion shape, only when all of these hold:

- the basename of `argv[0]` is exactly `codex-companion`;
- `argv[1]` is `task`;
- the remaining tokens are exactly `--reviewer <op>` plus an optional
  `--fresh`, in any order;
- `<op>` equals the running operation (`plan-review` or `diff-review`).

No other flag and no positional token may appear: this skill owns model,
effort, cwd and output, and a positional would displace the stdin packet. Any
other argv, bare `["codex"]` included, is a **binding shape error**.

A binding shape error is a configuration error. It makes no Codex call, no
retry and no native fallback, and stops the operation with one error. The error
names the operation, the `review_id`, the authored argv, the expected form
`codex-companion task [--fresh] --reviewer <op>`, and exactly one cause, the
first of these that fails, in this order: an
executable other than `codex-companion` (bare `codex` included), a companion
subcommand other than `task`, a missing or mismatched `--reviewer`, or an
unsupported companion token. It stops the way `blocked` does, but carries no
capability repair ID.

**Invocation.** Preserve the selected command object's base argv, cwd, and
declared env (unset only declared env names), append the exact tail, and send
the complete packet on stdin with no positional argument, in the foreground:

```text
bindings.commands[review_id].argv \
  --model gpt-6-astra --effort xhigh \
  --cwd <absolute-worktree> --json
```

The companion's reviewer mode forces a fresh, read-only, ephemeral thread and
applies its own wall-clock budget, so the tail passes none of these.

**Validation.** Require exit status 0 and stdout that parses as exactly one JSON
object in which `status` is `0`, `touchedFiles` is empty, `runtime.model` is
`gpt-6-astra`, `runtime.reasoningEffort` is `xhigh`, and `rawOutput` is a
non-empty string, the companion's last captured agent message; then validate the
operation headings. Only that success establishes reviewer identity `Codex`.
````

In the following capacity paragraph, change only the word `metadata/output` to `payload` in the phrase `malformed or mismatched metadata/output`, which is wrapped across two source lines (`malformed or` ends one line); keep the wrap.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3`
Expected: `OK`. (The caller helper still expects the two-shape caller text; Task 2 changes it.)
Run: `if grep -nE 'exec --sandbox|output-last-message|JSONL|metadata' home/common/claude-code/skills/codex-collaboration/SKILL.md; then exit 1; fi`
Expected: no output, exit 0. At the start commit it prints lines 66–109, so this gate can fail.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/codex-collaboration/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(codex-collaboration): support only the companion review binding shape (#236)"
```
