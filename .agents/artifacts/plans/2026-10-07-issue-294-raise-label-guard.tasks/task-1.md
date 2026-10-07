# Task 1: The guard refuses adding the raise label

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Test: `tests/test_claude_permission_guard.py`

**Interfaces:**
- Consumes: the existing `split_segments(command) -> list[str] | None`, `tokenize_segment(segment) -> list[tuple[str, bool]] | None` (value, is_operator; operators are `(`, `)`, `{`, `}`, `` ` ``), `command_position_flags(tokens)`, `SHELL_EVALUATORS`, `guarded_operations(command) -> list[tuple[str, str, str | None]]`, `block(reason) -> 2`, and the test helpers `run_guard(command, cwd=None)` / `invoke_command_in(command, cwd)` / `make_repo(origin)`.
- Produces (module-level, in `lifecycle_guard.py`):
  - `RAISE_LABEL = "instruction-budget-raise"`
  - `RAISE_LABEL_REFUSAL = "only the user applies this label (Instruction Budget raise control)"`
  - `OPERATION_LABELS["label"] = "instruction-budget-raise label edit"`
  - `mentions_raise_label(texts) -> bool` — `texts` is an iterable of strings; true when any lower-cased text contains `RAISE_LABEL`.
  - `adds_raise_label(tokens) -> bool`
  - `unvalidatable(segment, reason, mentions_label=False)` — unchanged result for the four verbs, plus `("label", segment, reason)` appended when `mentions_label` is true.
  - `guarded_operations` may now also yield `("label", segment, <non-None problem>)`; a `label` finding never has `problem is None`.

**Invariants:**
- A segment whose token values (or raw text, when it cannot be split or tokenised) do not mention `RAISE_LABEL` case-insensitively yields no `label` finding (D1).
- In a mentioning segment: unsplittable command, untokenisable segment, or a command-position evaluator (`eval`, `sh`, `bash`, …) → `label` finding with that case's existing reason string; otherwise a `label` finding with `RAISE_LABEL_REFUSAL` exactly when `adds_raise_label(tokens)` (D1).
- `main()` refuses on the first `label` finding before adjudicating any other finding and before building `Context`; it never needs `cwd` (D2, D7).
- Every refusal of the operation is exit 2 with stderr `lifecycle guard: unsafe instruction-budget-raise label edit: <reason>`.
- Findings for `merge`, `pr-create`, `branch`, `push` are byte-identical to today for every command (D1, D5).

- [ ] **Step 1: Write the failing tests**

Add these methods to `ClaudePermissionGuardTest`, after `test_shell_equivalent_spellings_are_adjudicated` in the adversarial-table section:

```python
    LABEL_REFUSAL_PREFIX = (
        "lifecycle guard: unsafe instruction-budget-raise label edit:")
    DIRECT_ADD_REASON = (
        "only the user applies this label (Instruction Budget raise control)")
    EVALUATOR_REASON = "shell source passed to an evaluator cannot be validated"
    # The unterminated-quote row's existing fail-closed reason: pin the exact string the
    # live guard yields for it — "the command could not be parsed" when split_segments
    # returns None, else "the segment could not be tokenised" (check once, then pin).
    UNPARSED_REASON = "the command could not be parsed"

    def test_raise_label_additions_are_refused_in_every_spelling(self):
        # Every command here adds the instruction-budget-raise label, so exit 0
        # would mean the guard failed to see it. No cwd: the rule is global.
        for command in (
            "gh pr edit 1 --add-label instruction-budget-raise",
            "gh issue edit 23 --add-label instruction-budget-raise",
            "gh pr edit 1 --add-label=instruction-budget-raise",
            "gh pr edit 1 --add-label bug,instruction-budget-raise",
            'gh pr edit 1 --add-label "bug, instruction-budget-raise"',
            "gh pr edit 1 --add-label 'instruction-budget-raise'",
            "gh pr edit 1 --add-label '\"bug\",\"instruction-budget-raise\"'",
            "gh pr edit 1 --add-label INSTRUCTION-BUDGET-RAISE",
            "gh pr edit 1 --add-label bug --add-label instruction-budget-raise",
            "gh pr edit 1 --add-label instruction\\-budget\\-raise",
            '"gh" pr edit 1 --add-label instruction-budget-raise',
            "gh  pr edit 1 --add-label instruction-budget-raise",
            "gh pr\tedit 1 --add-label instruction-budget-raise",
            "(gh pr edit 1 --add-label instruction-budget-raise)",
            "{ gh pr edit 1 --add-label instruction-budget-raise; }",
            "x=$(gh pr edit 1 --add-label instruction-budget-raise)",
            "`gh pr edit 1 --add-label instruction-budget-raise`",
            "true && gh pr edit 1 --add-label instruction-budget-raise",
            "if true; then gh pr edit 1 --add-label instruction-budget-raise; fi",
            "command gh pr edit 1 --add-label instruction-budget-raise",
            "env -i gh pr edit 1 --add-label instruction-budget-raise",
            "env FOO=bar gh pr edit 1 --add-label instruction-budget-raise",
            "sudo -u anis gh pr edit 1 --add-label instruction-budget-raise",
            "GH_REPO=fagenorn/nix-config gh pr edit 1 --add-label instruction-budget-raise",
            "gh pr -R fagenorn/nix-config edit 1 --add-label instruction-budget-raise",
            "gh issue --repo=a/b edit 1 --add-label instruction-budget-raise",
            "/opt/homebrew/bin/gh pr edit 1 --add-label instruction-budget-raise",
            "xargs gh pr edit 1 --add-label instruction-budget-raise",
            "timeout 5 gh pr edit 1 --add-label instruction-budget-raise",
            "eval 'gh pr edit 1 --add-label instruction-budget-raise'",
            "sh -c 'gh pr edit 1 --add-label instruction-budget-raise'",
            "gh pr edit 1 --add-label 'instruction-budget-raise",  # unterminated
        ):
            # Every row except the three fail-closed rows names the direct-add reason.
            reason = {
                "eval 'gh pr edit 1 --add-label instruction-budget-raise'": self.EVALUATOR_REASON,
                "sh -c 'gh pr edit 1 --add-label instruction-budget-raise'": self.EVALUATOR_REASON,
                "gh pr edit 1 --add-label 'instruction-budget-raise": self.UNPARSED_REASON,
            }.get(command, self.DIRECT_ADD_REASON)
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn(f"{self.LABEL_REFUSAL_PREFIX} {reason}", result.stderr)
        elsewhere = self.make_repo("https://github.com/someoneelse/tool.git")
        result = self.invoke_command_in(
            "gh pr edit 1 --add-label instruction-budget-raise", elsewhere)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(f"{self.LABEL_REFUSAL_PREFIX} {self.DIRECT_ADD_REASON}", result.stderr)

    def test_raise_label_refusal_precedes_every_other_verb(self):
        # The push alone would be refused as a push; the label wins, so the
        # label rule is judged before any repository-bound verb.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        result = self.run_guard(
            "git push origin main; gh pr edit 1 --add-label instruction-budget-raise",
            cwd=repo)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(f"{self.LABEL_REFUSAL_PREFIX} {self.DIRECT_ADD_REASON}", result.stderr)
        self.assertNotIn("unsafe push", result.stderr)

    def test_other_label_edits_and_mentions_pass(self):
        for command in (
            "gh pr edit 1 --add-label bug",
            'gh issue edit 23 34 --add-label "bug,help wanted"',
            "gh pr edit 1 --remove-label instruction-budget-raise",
            "gh pr edit 1 --body 'the user may add instruction-budget-raise'",
            "xargs gh pr edit 1 --add-label bug",
            "sh -c 'gh pr edit 1 --add-label bug'",
            'echo "gh pr edit 1 --add-label instruction-budget-raise"',
            "cat > notes.md <<'EOF'\ngh pr edit 1 --add-label instruction-budget-raise\nEOF\n",
            "git commit -m 'docs: explain the instruction-budget-raise label'",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(0, result.returncode, (command, result.stderr))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (Global Constraints' D6 command, `<selection>` = `-k raise_label -k other_label_edits`, timeout 1800 s):
`just build >/dev/null && CLAUDE_SETTINGS_PATH="$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')" python3 -m unittest -k raise_label -k other_label_edits tests/test_claude_permission_guard.py`
Expected: FAIL — `test_raise_label_additions_are_refused_in_every_spelling` sees exit 0 for `gh pr edit 1 --add-label instruction-budget-raise`; `test_raise_label_refusal_precedes_every_other_verb` sees `unsafe push`. `test_other_label_edits_and_mentions_pass` already passes (regression pin).

- [ ] **Step 3: Write the minimal implementation**

In `lifecycle_guard.py`:

1. Add `RAISE_LABEL`, `RAISE_LABEL_REFUSAL` (with a comment: the label is the user's Instruction Budget raise decision, a mistake-catcher not enforcement, see #294) and the `"label"` entry of `OPERATION_LABELS`. Do not touch `GUARDED_LITERALS` / `GUARDED_TOKEN_LITERALS` (D1).
2. `mentions_raise_label(texts)`: `any(RAISE_LABEL in text.lower() for text in texts)`.
3. `adds_raise_label(tokens)` — decision-bearing algorithm, exactly:
   - For each non-operator token whose `os.path.basename(value) == "gh"`, at any position (command position or not, D1):
     - its words are the following tokens up to, not including, the next operator token;
     - each label value is the word after a word equal to `--add-label` (when one exists), and the remainder of each word starting with `--add-label=`;
     - return `True` when any label value's lower-cased form contains `RAISE_LABEL`.
   - Otherwise return `False`. No subcommand parsing, no comma splitting (D1).
4. `unvalidatable(segment, reason, mentions_label=False)`: the existing list, then append `("label", segment, reason)` when `mentions_label`.
5. In `guarded_operations`:
   - unsplittable: `unvalidatable(command, "the command could not be parsed", mentions_raise_label([command]))`;
   - untokenisable: `unvalidatable(segment, "the segment could not be tokenised", mentions_raise_label([segment]))`;
   - after tokenising, compute `mentions = mentions_raise_label(values)`; the evaluator branch passes `mentions`;
   - on the normal path, after the existing verb loop for that segment, `if mentions and adds_raise_label(tokens): found.append(("label", segment, RAISE_LABEL_REFUSAL))`.
   - Extend the docstring: the `label` operation is mention-gated, considered only in a segment mentioning the raise label, always carries a problem, and is refused for any `gh` invocation in any position whose `--add-label` value contains it.
6. In `main()`, bind `operations = guarded_operations(command)`; before the existing loop, `for operation, _segment, problem in operations: if operation == "label": return block(f"unsafe {OPERATION_LABELS[operation]}: {problem}")`; the existing loop then iterates `operations` unchanged (D7).

- [ ] **Step 4: Verify**

Run the Step 2 command. Expected: OK, 3 tests.
Then the whole guard file (D6 command with empty `<selection>`, timeout 1800 s): `CLAUDE_SETTINGS_PATH="$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')" python3 -m unittest tests/test_claude_permission_guard.py` — Expected: `OK`; any existing test failing means a verb's behavior changed (violates D5).
Scope check: `git diff --stat origin/main -- home/common/claude-code/ tests/test_claude_permission_guard.py` lists only the two files above (no `default.nix` change).

- [ ] **Step 5: Commit**

Commit both files through the lifecycle commit command your brief names (`launch-commit … -- <git commit args>`), subject `feat(claude-code): refuse agent-applied instruction-budget-raise labels (#294)`, with the brief's trailers.
